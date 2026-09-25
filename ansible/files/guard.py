"""Privileged, typed remote executor. Only fixed argv commands; never shell input."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile

SLUG = re.compile(r'[a-z0-9][a-z0-9-]{0,62}\Z')
LOCK = Path('/run/lock/dynamic-deployment.lock')


def slug(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ValueError('Invalid operation identifier')
    return value


def secure_path(path, trusted=False):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Absolute normalized path required')
    for part in reversed((path, *path.parents)):
        if part.is_symlink():
            raise ValueError('Symlink path is prohibited')
        if trusted and part.exists():
            info = part.stat()
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('Path must be root-owned and not group/world writable')
    return path


def child(root, relative):
    item = PurePosixPath(relative)
    if item.is_absolute() or '..' in item.parts or not item.parts or str(item) == '.':
        raise ValueError('Unsafe bundle path')
    return secure_path(Path(root) / item)


def acquire(path, token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,95}', token):
        raise ValueError('Invalid run identifier')
    secure_path(path)
    path.mkdir(mode=0o700)
    try:
        (path / 'owner').write_text(token, encoding='utf-8')
        (path / 'owner').chmod(0o600)
    except BaseException:
        (path / 'owner').unlink(missing_ok=True)
        path.rmdir()
        raise


def release(path, token):
    secure_path(path)
    if (path / 'owner').read_text(encoding='utf-8') != token:
        raise ValueError('Refusing to release another operation lock')
    (path / 'owner').unlink()
    path.rmdir()


def write_protected(path, data, immutable=False, uid=0, gid=0, mode=0o600):
    secure_path(path)
    if path.exists() and immutable and path.read_bytes() != data:
        raise ValueError('Existing credentials differ; explicit rotation is required')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
            if os.geteuid() == 0:
                os.fchown(handle.fileno(), uid, gid)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def redact(text, secrets):
    for value in sorted((str(v) for v in secrets.values() if v), key=len, reverse=True):
        text = text.replace(value, '[REDACTED]')
    return re.sub(r'(?i)(password|token|secret|authorization)([=: ]+)[^\s,;]+', r'\1\2[REDACTED]', text)


def run(argv, *, input_data=None, input_file=None, timeout=120, check=True, stdout=None):
    result = subprocess.run(argv, input=input_data, stdin=input_file, stdout=stdout or subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False)
    if check and result.returncode:
        # Command output may contain credentials. Never include it in exceptions.
        raise RuntimeError(f'Command failed ({Path(argv[0]).name}, exit {result.returncode})')
    return result


def context(payload):
    host = payload['host']
    environment, deployment = slug(payload['environment']), slug(payload['deployment'])
    roots = [secure_path(host[key], trusted=True) for key in ('runtime_root', 'data_root')]
    for root in roots:
        if len(root.parts) < 3 or str(root) in ('/etc/ssl', '/var/lib', '/usr/local'):
            raise ValueError('Dedicated runtime/data root required')
    if roots[0] == roots[1] or roots[0] in roots[1].parents or roots[1] in roots[0].parents:
        raise ValueError('Runtime and data roots must not overlap')
    return tuple(root / environment / deployment for root in roots)


def compose(payload, args, **kwargs):
    runtime, _ = context(payload)
    return run(['docker', 'compose', '--project-directory', str(runtime), '-f',
                str(runtime / 'compose.json'), *args], **kwargs)


def services(payload):
    selected = payload.get('selected', [])
    available = payload['bundle']['compose'].get('services', {})
    if not isinstance(selected, list) or any(item not in available for item in selected):
        raise ValueError('Unknown selected service')
    return selected or list(available)


def preflight(payload):
    runtime, data = context(payload)
    host = payload['host']
    os_release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if os_release.get('ID', '').strip('"') != 'ubuntu' or os_release.get('VERSION_ID', '').strip('"') != '24.04':
        raise ValueError('Only Ubuntu Server 24.04 LTS is supported')
    if os.uname().machine != 'x86_64' or os.geteuid() != 0:
        raise ValueError('amd64 host and sudo root privileges required')
    mount = secure_path(host['expected_mount'], trusted=True)
    if not os.path.ismount(mount) or mount not in (data, *data.parents):
        raise ValueError('Expected data mount is missing or does not contain data root')
    existing = next(p for p in (data, *data.parents) if p.exists())
    if shutil.disk_usage(existing).free < 2 * 1024**3:
        raise ValueError('At least 2 GiB free data space required')
    docker = shutil.which('docker')
    needs_bootstrap = not docker
    if docker:
        version = run(['docker', 'compose', 'version', '--short'], check=False)
        needs_bootstrap = version.returncode != 0
        if not needs_bootstrap:
            match = re.match(r'v?(\d+)\.(\d+)\.(\d+)', version.stdout.decode().strip())
            if not match or tuple(map(int, match.groups())) < (2, 18, 0):
                raise ValueError('Docker Compose >=2.18.0 required')
            run(['docker', 'info', '--format', '{{json .ServerVersion}}'])
    if needs_bootstrap and not host.get('bootstrap', False):
        raise ValueError('Docker/Compose missing; plan must explicitly authorize bootstrap')
    for category in ('files', 'secret_files', 'asset_files'):
        for relative in payload['bundle'].get(category, {}):
            child(runtime, relative)
    for relative in payload['bundle'].get('directories', []):
        child(data, relative)
    check_firewall(payload)
    check_ports(payload, docker and not needs_bootstrap)
    return {'bootstrap_required': needs_bootstrap, 'free_bytes': shutil.disk_usage(existing).free}


def check_firewall(payload):
    host, bundle = payload['host'], payload['bundle']
    needs = any(s.get('ports') for s in bundle['compose'].get('services', {}).values())
    needs = needs or any(s.get('config', {}).get('egress') for s in payload.get('services', []))
    if not needs and not host.get('firewall_check'):
        return
    if not host.get('firewall_check'):
        raise ValueError('Trusted firewall validator is required')
    path = secure_path(host['firewall_check'], trusted=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Firewall validator must be executable regular file')
    request = {'environment': payload['environment'], 'deployment': payload['deployment'],
               'host': host, 'compose': bundle['compose']}
    run([str(path), '--check'], input_data=json.dumps(request).encode())


def check_ports(payload, docker_ready):
    # Existing deployment owns its ports; never exempt unrelated containers/listeners.
    owned = set()
    if docker_ready:
        project = payload['bundle']['compose'].get('name')
        if project:
            ids = run(['docker', 'ps', '-q', '--filter', f'label=com.docker.compose.project={project}']).stdout.split()
            if ids:
                entries = json.loads(run(['docker', 'inspect', *[x.decode() for x in ids]]).stdout)
                for entry in entries:
                    for bindings in entry.get('NetworkSettings', {}).get('Ports', {}).values():
                        for binding in bindings or []:
                            owned.add((binding['HostIp'], int(binding['HostPort'])))
    for service in payload['bundle']['compose'].get('services', {}).values():
        for port in service.get('ports', []):
            if isinstance(port, str):
                address, number, _ = port.split(':')
            else:
                address, number = port.get('host_ip', '0.0.0.0'), port['published']
            if address in ('0.0.0.0', '::'):
                raise ValueError('Wildcard published ports are prohibited')
            if (address, int(number)) not in owned:
                with socket.socket() as sock:
                    try:
                        sock.bind((address, int(number)))
                    except OSError as exc:
                        raise ValueError('Published address unavailable or port occupied') from exc


def owner_for(payload, relative):
    parts = PurePosixPath(relative).parts
    service_id = parts[1] if parts[0] in ('files', 'assets', 'secrets') else parts[0]
    service = payload['bundle']['compose']['services'].get(service_id, {})
    user = str(service.get('user', '0:0'))
    if not re.fullmatch(r'[0-9]+:[0-9]+', user):
        raise ValueError('Rendered service must use numeric uid:gid')
    return tuple(map(int, user.split(':')))


def data_identity(payload):
    available = payload['bundle']['compose']['services']
    return {'environment': payload.get('environment'), 'deployment': payload.get('deployment'),
            'services': {s['id']: {'kind': s['kind'], 'image': s['image']}
                         for s in payload.get('services', []) if s['id'] in available}}


def check_data_identity(payload, data):
    marker = child(data, '.managed.json')
    identity = data_identity(payload)
    if marker.exists():
        previous = json.loads(marker.read_text())
        if any(previous.get(k) != identity[k] for k in ('environment', 'deployment')):
            raise ValueError('Persistent data belongs to another deployment')
        for relative in payload['bundle'].get('directories', []):
            owner = PurePosixPath(relative).parts[0]
            target = child(data, relative)
            if owner not in previous.get('services', {}) and target.exists() and any(target.iterdir()):
                raise ValueError('Unmanaged service data cannot be adopted')
        for name, value in identity['services'].items():
            old = previous.get('services', {}).get(name)
            if old and old != value:
                raise ValueError('Engine or image change requires isolated restore')
    elif data.exists() and any(data.iterdir()):
        raise ValueError('Unmanaged existing data cannot be adopted; use isolated restore')
    return identity


def prepare_inputs(payload, runtime, data):
    bundle = payload['bundle']
    writes = []
    for relative, text in bundle.get('files', {}).items():
        writes.append((relative, text.encode(), False))
    for relative, key in bundle.get('secret_files', {}).items():
        if key not in payload.get('secrets', {}):
            raise ValueError('Required Vault secret missing')
        writes.append((relative, str(payload['secrets'][key]).encode(), True))
    assets = payload.get('assets', {})
    if set(assets) != set(bundle.get('asset_files', {})):
        raise ValueError('Required asset payload mismatch')
    writes.extend((relative, base64.b64decode(content, validate=True), False)
                  for relative, content in assets.items())
    for relative, content, immutable in writes:
        target = child(runtime, relative)
        owner_for(payload, relative)
        if target.exists() and (not target.is_file() or
                               (immutable and target.read_bytes() != content)):
            raise ValueError('Existing credentials differ or file type invalid; rotation required')
    for relative in bundle.get('directories', []):
        target = child(data, relative)
        owner_for(payload, relative)
        if target.exists() and not target.is_dir():
            raise ValueError('Persistent data path is not a directory')
    return writes


def stop_removed(payload, runtime):
    removed = payload.get('removed_services', [])
    if not removed:
        return
    if not isinstance(removed, list) or any(not SLUG.fullmatch(s) for s in removed):
        raise ValueError('Invalid removed service selection')
    active = runtime / 'compose.json'
    if not active.is_file():
        raise ValueError('Cannot stop removed services without active Compose')
    old = json.loads(active.read_text())['services']
    if any(s not in old or s in payload['bundle']['compose']['services'] for s in removed):
        raise ValueError('Removed services must exist only in previous Compose')
    compose(payload, ['stop', '--timeout', '120', *removed], timeout=300)


def prepare(payload):
    runtime, data = context(payload)
    if payload.get('operation') == 'restore' and (runtime.exists() or data.exists()):
        raise ValueError('Restore target must have no existing runtime or data directory')
    identity = check_data_identity(payload, data)
    writes = prepare_inputs(payload, runtime, data)
    # Validate candidate before touching the active configuration or persistent data.
    with tempfile.TemporaryDirectory(prefix='dd-compose-') as directory:
        candidate = Path(directory) / 'compose.json'
        candidate.write_text(json.dumps(payload['bundle']['compose']))
        run(['docker', 'compose', '--project-directory', str(runtime), '-f', str(candidate),
             'config', '--quiet'])
    stop_removed(payload, runtime)
    runtime.mkdir(parents=True, mode=0o700, exist_ok=True)
    data.mkdir(parents=True, mode=0o700, exist_ok=True)
    for relative in payload['bundle'].get('directories', []):
        target = child(data, relative)
        mode = 0o750 if PurePosixPath(relative).name == 'uploads' else 0o700
        target.mkdir(parents=True, mode=mode, exist_ok=True)
        target.chmod(mode)
        os.chown(target, *owner_for(payload, relative))
    for relative, content, immutable in writes:
        uid, gid = owner_for(payload, relative)
        write_protected(child(runtime, relative), content, immutable=immutable, uid=uid, gid=gid)
    previous_marker = data / '.managed.json'
    if previous_marker.exists():
        previous = json.loads(previous_marker.read_text())
        identity = {**identity, 'services': {**previous.get('services', {}), **identity['services']}}
    write_protected(previous_marker, json.dumps(identity).encode())
    write_protected(runtime / 'compose.json', json.dumps(payload['bundle']['compose'], indent=2).encode())
    return {'prepared': True}


def report(payload):
    operation = payload['operation']
    if operation == 'logs':
        output = compose(payload, ['logs', '--no-color', '--tail', '200', *services(payload)]).stdout.decode(errors='replace')
        return {'logs': redact(output, payload.get('secrets', {}))}
    result = compose(payload, ['ps', '--all', '--format', 'json', *services(payload)])
    raw = result.stdout.decode().strip()
    records = json.loads(raw) if raw.startswith('[') else [json.loads(line) for line in raw.splitlines() if line]
    states = {row.get('Service'): {'state': row.get('State'), 'health': row.get('Health')} for row in records}
    healthy = all(states.get(s, {}).get('state') == 'running' and states.get(s, {}).get('health') == 'healthy' for s in services(payload))
    return {'services': states, 'healthy': healthy, 'endpoints': payload['bundle'].get('endpoints', [])}


def main():
    payload = json.load(sys.stdin)
    action = sys.argv[1]
    result = {}
    if action == 'preflight':
        result = preflight(payload)
    elif action == 'acquire':
        acquire(LOCK, payload['run_id'])
    elif action == 'release':
        release(LOCK, payload['run_id'])
    elif action == 'prepare':
        result = prepare(payload)
    elif action == 'report':
        result = report(payload)
    elif action in ('backup', 'restore'):
        # The companion source is shipped by the controller, never configuration input.
        raise ValueError('Backup helper must be invoked through the backup playbook tasks')
    else:
        raise ValueError('Unsupported executor action')
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': str(exc)}))
        sys.exit(1)
