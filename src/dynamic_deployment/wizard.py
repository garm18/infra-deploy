"""Plain terminal onboarding; existing values remain unless explicitly edited."""

from copy import deepcopy
import getpass
from pathlib import Path

from .config import validate_config
from .images import resolve_image

KINDS = ['postgres', 'mariadb', 'redis', 'minio', 'phpmyadmin', 'nginx', 'apache',
         'laravel-php', 'laravel-web', 'laravel-worker', 'laravel-scheduler']
REPOSITORIES = {'postgres': 'postgres', 'mariadb': 'mariadb', 'redis': 'redis',
                'minio': 'quay.io/minio/aistor/minio', 'phpmyadmin': 'phpmyadmin',
                'nginx': 'nginx', 'apache': 'httpd'}


def ask(prompt, default=None):
    suffix = f' [{default}]' if default not in (None, '') else ''
    answer = input(prompt + suffix + ': ').strip()
    if answer.lower() in {'batal', 'cancel'}:
        raise KeyboardInterrupt
    return answer if answer else (default if default is not None else '')


def yes(prompt, default=False):
    return str(ask(prompt + ' (y/n)', 'y' if default else 'n')).lower() in {'y', 'yes', 'ya'}


def file_path(prompt, default=None):
    value = ask(prompt, default)
    if not value:
        raise ValueError('A file path is required; type cancel to exit.')
    return str(Path(value).expanduser().absolute())


def _image(kind, current=None):
    hint = ('nama:versi; Enter = nilai tersimpan atau lanjut isi versi'
            if kind in REPOSITORIES else 'nama:versi@sha256:digest dari hasil build')
    value = ask(f'Image {kind} ({hint})', current)
    if '@sha256:' in value:
        return value
    if not value:
        repo = REPOSITORIES.get(kind)
        if repo:
            version = ask(f'Versi {repo} yang sudah diuji (isi tag saja, bukan nama image; wajib diisi, bukan latest)')
            value = repo + ':' + version
        else:
            raise ValueError('Laravel requires a team-built image with a fixed digest.')
    return resolve_image(value)


def _reference(services, host, kinds, prompt, required=False):
    choices = [s['id'] for s in services if s.get('enabled', True) and s['kind'] in kinds]
    local = [s['id'] for s in services if s['id'] in choices and s['host'] == host]
    if not choices:
        if required:
            raise ValueError(prompt + ': select that dependency first.')
        return None
    default = local[0] if required and local else (choices[0] if required else '')
    answer = ask(prompt + ' (' + ', '.join(choices) + '; blank=not used)', default)
    if answer and answer not in choices:
        raise ValueError('Unknown dependency: ' + answer)
    return answer or None


def _tls(cfg):
    return {**cfg, 'tls_cert': file_path('TLS certificate PEM file', cfg.get('tls_cert')),
            'tls_key': file_path('TLS private-key PEM file', cfg.get('tls_key'))}


def _configure(service, services):
    kind, host = service['kind'], service['host']
    cfg, refs = deepcopy(service.get('config', {})), deepcopy(service.get('secrets', {}))
    prefix = service['id'].replace('-', '_').upper()
    if kind in {'postgres', 'mariadb'}:
        cfg.update(database=ask('Application database name', cfg.get('database', 'app')),
                   username=ask('Application user (not admin)', cfg.get('username', 'app')))
        refs.setdefault('password', prefix + '_PASSWORD')
        refs.setdefault('root_password', prefix + '_ROOT_PASSWORD')
    elif kind == 'redis':
        cfg['maxmemory'] = ask('Redis memory limit', cfg.get('maxmemory', '256mb'))
        refs.setdefault('password', prefix + '_PASSWORD')
    elif kind == 'minio':
        cfg = _tls(cfg)
        cfg.update(s3_domain=ask('Internal S3 DNS name', cfg.get('s3_domain')),
                   console_domain=ask('Internal console DNS name', cfg.get('console_domain')),
                   license_file=file_path('AIStor Free license file', cfg.get('license_file')),
                   release_evidence_file=file_path('MinIO GUI/S3 evidence file', cfg.get('release_evidence_file')))
        refs.setdefault('root_user', prefix + '_ROOT_USER')
        refs.setdefault('root_password', prefix + '_ROOT_PASSWORD')
    elif kind == 'phpmyadmin':
        cfg['database_service'] = _reference(services, host, {'mariadb'}, 'Target MariaDB service', True)
    elif kind in {'nginx', 'apache'}:
        cfg = _tls(cfg)
        cfg.update(role='admin', https_port=int(ask('Private HTTPS port for admin proxy', cfg.get('https_port', 443))))
        targets = [s for s in services if s.get('enabled', True) and s['kind'] in {'minio', 'phpmyadmin'}]
        routes = []
        for target in targets:
            if target['kind'] == 'minio':
                ca = file_path('Trusted CA file for proxy-to-MinIO connection')
                for key, port in [('s3_domain', 9000), ('console_domain', 9001)]:
                    routes.append({'domain': target['config'][key], 'target': target['id'],
                                   'port': port, 'protocol': 'https', 'tls_ca': ca})
            else:
                routes.append({'domain': ask('Internal phpMyAdmin DNS name'), 'target': target['id']})
        if not routes:
            raise ValueError('Admin proxy requires MinIO/phpMyAdmin; Laravel web uses laravel-web.')
        cfg['routes'] = routes
    elif kind == 'laravel-web':
        cfg = _tls(cfg)
        cfg.update(php_service=_reference(services, host, {'laravel-php'}, 'Target PHP-FPM service', True),
                   domain=ask('Internal application DNS name', cfg.get('domain')),
                   release_id=ask('Release ID matching the PHP image', cfg.get('release_id')),
                   https_port=int(ask('Private HTTPS port for web (different from admin proxy)', cfg.get('https_port', 8443))))
    elif kind == 'laravel-php':
        cfg.update(release_id=ask('Application image release ID', cfg.get('release_id')),
                   php_version=ask('PHP version from composer.lock', cfg.get('php_version')),
                   app_url=ask('HTTPS application URL', cfg.get('app_url')),
                   session_driver=ask('Session driver: file/database/redis', cfg.get('session_driver', 'file')))
        for name, kinds in [('database', {'postgres', 'mariadb'}), ('redis', {'redis'}), ('storage', {'minio'})]:
            dep = _reference(services, host, kinds, 'Dependency ' + name)
            if dep:
                cfg[name + '_service'] = dep
        refs.setdefault('app_key', prefix + '_APP_KEY')
        if cfg.get('storage_service'):
            cfg['storage_bucket'] = ask('Pre-provisioned application S3 bucket', cfg.get('storage_bucket'))
            refs.setdefault('storage_access_key', prefix + '_S3_ACCESS_KEY')
            refs.setdefault('storage_secret_key', prefix + '_S3_SECRET_KEY')
    elif kind in {'laravel-worker', 'laravel-scheduler'}:
        php = next((s for s in services if s['kind'] == 'laravel-php' and s['host'] == host and s.get('enabled', True)), None)
        if not php:
            raise ValueError('Worker/scheduler requires PHP on the same host.')
        cfg, refs = deepcopy(php['config']), deepcopy(php['secrets'])
        service = {**service, 'image': php['image']}
        if kind == 'laravel-worker':
            cfg['queue'] = ask('Queue name (connection follows image contract)', 'default')
    return {**service, 'config': cfg, 'secrets': refs}


def configure(existing=None):
    print('Dynamic Deployment — type cancel at any prompt to exit.')
    current = deepcopy(existing or {})
    environment = ask('Environment: development/staging/production', current.get('environment', 'development'))
    deployment = ask('Deployment name', current.get('deployment', 'team-app'))
    hosts = deepcopy(current.get('hosts', {}))
    if not hosts or yes('Add or edit a host inventory entry'):
        while True:
            name = ask('Host ID', next(iter(hosts), 'local'))
            host = hosts.get(name, {})
            mode = ask('Connection mode: local / ssh-password / ssh-key / ssh-agent', host.get('connection', 'local'))
            if mode == 'local':
                hosts[name] = {**host, 'connection': 'local', 'address': '127.0.0.1',
                               'user': ask('Local user with passwordless sudo', host.get('user', getpass.getuser())),
                               'port': 22, 'expected_mount': ask('Existing data mount', host.get('expected_mount', '/')),
                               'data_root': ask('Local persistent data root', host.get('data_root', '/tmp/dynamic-deployment-data')),
                               'runtime_root': ask('Local runtime root', host.get('runtime_root', '/tmp/dynamic-deployment-runtime')),
                               'bootstrap': False, 'allowed_cidrs': []}
                hosts[name].pop('private_key_file', None)
                hosts[name].pop('ssh_password_ref', None)
            else:
                item = {**host, 'connection': mode, 'address': ask('Private IPv4 host address', host.get('address')),
                        'user': ask('SSH user with passwordless sudo', host.get('user', 'deploy')),
                        'port': int(ask('SSH port', host.get('port', 22))),
                        'expected_mount': ask('Existing server data mount', host.get('expected_mount', '/srv')),
                        'data_root': ask('Persistent data root on that mount', host.get('data_root', '/srv/dynamic-deployment')),
                        'runtime_root': ask('Separate runtime root', host.get('runtime_root', '/opt/dynamic-deployment')),
                        'bootstrap': yes('Allow Docker installation if absent', host.get('bootstrap', False)),
                        'allowed_cidrs': host.get('allowed_cidrs', [])}
                if mode == 'ssh-key':
                    item['private_key_file'] = file_path('Local SSH private-key file', host.get('private_key_file'))
                    item.pop('ssh_password_ref', None)
                elif mode == 'ssh-password':
                    item['ssh_password_ref'] = ask('Vault reference for existing SSH password', host.get('ssh_password_ref', name.upper().replace('-', '_') + '_SSH_PASSWORD'))
                    item.pop('private_key_file', None)
                elif mode == 'ssh-agent':
                    item.pop('private_key_file', None)
                    item.pop('ssh_password_ref', None)
                else:
                    raise ValueError('Connection mode must be local, ssh-password, ssh-key, or ssh-agent.')
                hosts[name] = item
            if not yes('Add or edit another host'):
                break
    services = deepcopy(current.get('services', []))
    for host in hosts:
        print(f'\nServices on {host}: ' + ', '.join(f'{i + 1}={kind}' for i, kind in enumerate(KINDS)))
        previous = [str(KINDS.index(s['kind']) + 1) for s in services if s['host'] == host and s.get('enabled', True)]
        choice = ask('Active service numbers separated by spaces; - disables all', ' '.join(previous))
        numbers = [] if choice == '-' else [int(n) for n in choice.split()]
        if any(n < 1 or n > len(KINDS) for n in numbers):
            raise ValueError('A selected service number is outside the catalog.')
        selected = {KINDS[n - 1] for n in numbers}
        if selected & {'minio', 'phpmyadmin'} and not selected & {'nginx', 'apache'}:
            print('GUI requires an HTTPS admin proxy; Nginx was added for review.')
            selected.add('nginx')
        old = {s['kind']: s for s in services if s['host'] == host}
        services = [s for s in services if s['host'] != host]
        services.extend({**s, 'enabled': False} for kind, s in old.items() if kind not in selected)
        for kind in KINDS:
            if kind not in selected:
                continue
            saved = old.get(kind)
            if saved and not yes('Edit parameters for ' + saved['id']):
                services.append({**saved, 'enabled': True})
                continue
            service = saved or {'id': f'{kind}-{host}', 'kind': kind, 'host': host, 'enabled': True}
            image = service.get('image')
            if kind not in {'laravel-worker', 'laravel-scheduler'}:
                image = _image(kind, image)
            service = _configure({**service, 'enabled': True, 'image': image or ''}, services)
            services.append(service)
    for name, host in list(hosts.items()):
        local = [s for s in services if s['host'] == name and s.get('enabled', True)]
        if any(s['kind'] in {'nginx', 'apache', 'laravel-web'} for s in local):
            if host.get('connection') != 'local':
                hosts[name] = {**host,
                              'allowed_cidrs': ask('Internal/VPN CIDRs for ' + name + ' (comma-separated)', ','.join(host.get('allowed_cidrs', []))).split(','),
                              'firewall_check': ask('Root-owned firewall validator executable on ' + name, host.get('firewall_check'))}
    value = {**current, 'schema_version': 1, 'environment': environment, 'deployment': deployment,
             'hosts': hosts, 'services': services,
             'secrets_file': file_path('Environment Ansible Vault path', current.get('secrets_file', f'deployments/{environment}/{deployment}/secrets.vault.yml'))}
    if environment == 'production':
        production = deepcopy(current.get('production', {}))
        for key in ['owner', 'backup_destination', 'backup_schedule', 'release_evidence_file', 'restore_evidence_file']:
            production[key] = ask('Production ' + key, production.get(key))
        for key in ['rpo_minutes', 'rto_minutes', 'backup_retention_days']:
            production[key] = int(ask('Production ' + key, production.get(key)))
        value['production'] = production
    return validate_config(value)
