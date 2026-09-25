"""Loaded after guard.py by the trusted playbook. Encrypted backups, isolated restore."""


def backup_service(payload):
    request = payload['backup']
    slug(request['id'])
    target = request['service']
    matches = [s for s in payload['services'] if s['id'] == target and s.get('enabled', True)]
    if len(matches) != 1 or target not in payload['bundle']['compose']['services']:
        raise ValueError('Backup requires exactly one service on the selected host')
    service = matches[0]
    if service['kind'] not in ('postgres', 'mariadb', 'redis', 'minio'):
        raise ValueError('Only PostgreSQL, MariaDB, Redis and MinIO support data backup')
    return service


def external_directory(value):
    path = secure_path(value, trusted=True)
    if not path.is_dir():
        raise ValueError('Backup destination must be an existing protected external mount directory')
    mounts = json.loads(run(['findmnt', '--json', '--target', str(path), '-o', 'TARGET,FSTYPE']).stdout)
    entry = mounts['filesystems'][0]
    if entry['fstype'] not in ('nfs', 'nfs4', 'cifs'):
        raise ValueError('External backup destination must use NFS or CIFS; local disks are not off-host backups')
    return path


def command_in_service(payload, service, command, *, output=None, input_data=None, input_file=None):
    return compose(payload, ['exec', '-T', service['id'], *command], timeout=3600,
                   stdout=output, input_data=input_data, input_file=input_file)


def pg_command(binary, args, root=False):
    secret = '/run/secrets/root_password' if root else '/run/secrets/password'
    # Fixed script; database/user names are positional argv, never interpolated into shell.
    return ['sh', '-c', f'export PGPASSWORD="$(cat {secret})"; exec "$@"', 'dd', binary, *args]


def mysql_command(binary, args):
    return ['sh', '-c', 'export MYSQL_PWD="$(cat /run/secrets/root_password)"; exec "$@"',
            'dd', binary, '--user=root', *args]


def snapshot_database(payload, service, staging):
    config = service['config']
    if service['kind'] == 'postgres':
        roles = command_in_service(payload, service, pg_command('psql', ['-U', 'postgres', '-Atc',
                   "SELECT rolname FROM pg_roles WHERE rolname NOT LIKE 'pg_%';"], root=True)).stdout.decode().splitlines()
        if set(roles) != {'postgres', config['username']}:
            raise ValueError('Additional PostgreSQL roles require reviewed custom restore workflow')
        with (staging / 'database.dump').open('wb') as output:
            command_in_service(payload, service, pg_command('pg_dump', ['-U', config['username'],
                '-d', config['database'], '--format=custom', '--no-owner', '--no-acl']), output=output)
        # Two roles are re-created by the target bootstrap, never import password hashes.
        (staging / 'roles.json').write_text(json.dumps(sorted(roles)))
    else:
        with (staging / 'database.sql').open('wb') as output:
            command_in_service(payload, service, mysql_command('mariadb-dump',
                ['--all-databases', '--lock-all-tables', '--routines', '--events', '--triggers', '--hex-blob']), output=output)


def running_services(payload):
    value = compose(payload, ['ps', '--status', 'running', '--services']).stdout.decode()
    return [slug(line) for line in value.splitlines() if line]


def snapshot_storage(payload, service, staging):
    # Stop every local writer, and reject uncoordinated cross-host writers.
    for candidate in payload['services']:
        config = candidate.get('config', {})
        dependencies = set(candidate.get('depends_on', [])) | {config.get('storage_service'), config.get('redis_service')}
        if service['id'] in dependencies and candidate['host'] != service['host'] and candidate.get('enabled', True):
            raise ValueError('Cross-host storage backup requires coordinated maintenance; unsupported by this executor')
    _, data = context(payload)
    source = child(data, service['id'] + '/data')
    if not source.is_dir():
        raise ValueError('Source data directory is missing')
    previously_running = running_services(payload)
    try:
        if previously_running:
            compose(payload, ['stop', '--timeout', '120', *previously_running], timeout=300)
        with tarfile.open(staging / 'data.tar', 'w') as archive:
            archive.add(source, arcname='data', recursive=True, filter=safe_tar_member)
    finally:
        if previously_running:
            compose(payload, ['up', '-d', '--wait', '--wait-timeout', '180', *previously_running], timeout=300)


def safe_tar_member(member):
    path = PurePosixPath(member.name)
    if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
        raise ValueError('Backup archive cannot contain links, devices or traversal')
    return member


def extract_safe(archive, target):
    with tarfile.open(archive, 'r') as handle:
        names = set()
        for member in handle.getmembers():
            safe_tar_member(member)
            path = child(target, member.name)
            if path in names:
                raise ValueError('Duplicate archive paths are prohibited')
            names.add(path)
        handle.extractall(target, filter='data')



def file_sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def verify_manifest_files(manifest, content):
    required = {'postgres': {'database.dump', 'roles.json'}, 'mariadb': {'database.sql'},
                'redis': {'data.tar'}, 'minio': {'data.tar'}}.get(manifest.get('kind'))
    files = manifest.get('files')
    if not required or not isinstance(files, dict) or set(files) != required:
        raise ValueError('Backup manifest file set mismatch')
    if {p.name for p in content.iterdir()} != required | {'manifest.json'}:
        raise ValueError('Unexpected archive contents')
    for filename, expected in files.items():
        path = child(content, filename)
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected) or not path.is_file():
            raise ValueError('Invalid backup checksum or missing file')
        if file_sha256(path) != expected:
            raise ValueError('Backup content checksum mismatch')


def backup_run(payload):
    service = backup_service(payload)
    request = payload['backup']
    destination = external_directory(request['destination'])
    recipient = request.get('recipient', '')
    if not re.fullmatch(r'age1[0-9a-z]{20,100}', recipient):
        raise ValueError('An age X25519 encryption recipient is required')
    if not shutil.which('age'):
        raise ValueError('Install age on the target before backup/restore')
    output = child(destination, request['id'] + '.tar.age')
    if output.exists():
        raise ValueError('Backup ID already exists; refusing overwrite')
    runtime, _ = context(payload)
    with tempfile.TemporaryDirectory(prefix='dd-backup-', dir=runtime) as temporary:
        staging = Path(temporary)
        if service['kind'] in ('postgres', 'mariadb'):
            snapshot_database(payload, service, staging)
        else:
            snapshot_storage(payload, service, staging)
        manifest = {'schema_version': 1, 'service': service['id'], 'kind': service['kind'],
                    'image': service['image'], 'database': service.get('config', {}).get('database'),
                    'username': service.get('config', {}).get('username'), 'id': request['id'],
                    'files': {p.name: file_sha256(p) for p in staging.iterdir()}}
        (staging / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        plain = staging / 'backup.tar'
        with tarfile.open(plain, 'w') as archive:
            for item in sorted(staging.iterdir()):
                if item != plain:
                    archive.add(item, arcname=item.name, filter=safe_tar_member)
        partial = child(destination, '.' + request['id'] + '.partial')
        partial_owned = False
        try:
            descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            partial_owned = True
            with os.fdopen(descriptor, 'wb') as encrypted:
                run(['age', '--encrypt', '--recipient', recipient, str(plain)], stdout=encrypted, timeout=3600)
                encrypted.flush()
                os.fsync(encrypted.fileno())
            os.link(partial, output)  # Atomic publish without replacing another backup.
        finally:
            if partial_owned:
                partial.unlink(missing_ok=True)
    return {'archive': str(output), 'sha256': file_sha256(output), 'service': service['id']}


def restore_database(payload, service, staging):
    # Only this service starts. Application writers remain absent during import.
    compose(payload, ['up', '-d', '--wait', '--wait-timeout', '180', service['id']], timeout=300)
    if service['kind'] == 'postgres':
        with (staging / 'database.dump').open('rb') as source:
            command_in_service(payload, service, pg_command('pg_restore', ['-U', service['config']['username'],
                '-d', service['config']['database'], '--no-owner', '--no-acl', '--exit-on-error']), input_file=source)
        command_in_service(payload, service, pg_command('psql', ['-U', service['config']['username'],
            '-d', service['config']['database'], '-v', 'ON_ERROR_STOP=1', '-c', 'SELECT 1']))
    else:
        with (staging / 'database.sql').open('rb') as source:
            command_in_service(payload, service, mysql_command('mariadb', []), input_file=source)
        # Imported users overwrite authentication. Target secret must match backup source.
        command_in_service(payload, service, mysql_command('mariadb', ['-e', 'SELECT 1']))


def restore_run(payload):
    service = backup_service(payload)
    request = payload['backup']
    runtime, data = context(payload)
    if runtime.exists() or data.exists():
        raise ValueError('Restore requires a brand new isolated deployment target')
    archive = secure_path(request['archive'], trusted=True)
    external_directory(str(archive.parent))
    identity = secure_path(request['identity_file'], trusted=True)
    if not identity.is_file() or identity.stat().st_mode & 0o077:
        raise ValueError('Age identity must be root-owned mode 0600')
    if not archive.is_file() or archive.stat().st_mode & 0o077:
        raise ValueError('Encrypted archive must be a protected regular file')
    with tempfile.TemporaryDirectory(prefix='dd-restore-') as temporary:
        staging = Path(temporary)
        decrypted = staging / 'backup.tar'
        with decrypted.open('wb') as output:
            run(['age', '--decrypt', '--identity', str(identity), str(archive)], stdout=output, timeout=3600)
        extract_safe(decrypted, staging / 'content')
        content = staging / 'content'
        manifest = json.loads((content / 'manifest.json').read_text())
        if manifest.get('schema_version') != 1:
            raise ValueError('Unsupported backup schema')
        for key in ('kind', 'image'):
            if manifest.get(key) != service[key]:
                raise ValueError('Restore engine and exact image digest must match source backup')
        for key in ('database', 'username'):
            if manifest.get(key) != service.get('config', {}).get(key):
                raise ValueError('Restore database and username must match source')
        verify_manifest_files(manifest, content)
        if service['kind'] == 'postgres' and set(json.loads((content / 'roles.json').read_text())) != {'postgres', service['config']['username']}:
            raise ValueError('Backup PostgreSQL role contract mismatch')
        prepare(payload)
        if service['kind'] in ('postgres', 'mariadb'):
            restore_database(payload, service, content)
        else:
            source_root = child(data, service['id'])
            extract_safe(content / 'data.tar', source_root)
            uid, gid = owner_for(payload, service['id'] + '/data')
            for item in (source_root / 'data', *(source_root / 'data').rglob('*')):
                os.chown(item, uid, gid)
            compose(payload, ['up', '-d', '--wait', '--wait-timeout', '180', service['id']], timeout=300)
        result = report({**payload, 'operation': 'status', 'selected': [service['id']]})
        if not result['healthy']:
            raise ValueError('Restored service failed health check; isolated target retained for diagnosis')
        if service['kind'] == 'minio':
            minio_verify({**payload, 'selected': [service['id']]})
        return {'restored': True, 'service': service['id'], 'isolated_target': str(data),
                'verification': 'engine readiness; operator must verify business data and permissions before cutover'}


if __name__ == '__main__':
    try:
        request_payload = json.load(sys.stdin)
        if request_payload['operation'] == 'backup':
            print(json.dumps(backup_run(request_payload)))
        elif request_payload['operation'] == 'restore':
            print(json.dumps(restore_run(request_payload)))
        else:
            raise ValueError('Unsupported backup operation')
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        sys.exit(1)
