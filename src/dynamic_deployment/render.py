"""Deterministic Compose bundles; accepts validated configuration, never secret values."""
from copy import deepcopy
from .render_services import configure

PORTS = {'postgres': 5432, 'mariadb': 3306, 'redis': 6379, 'minio': 9000,
         'phpmyadmin': 80, 'laravel-php': 9000}
DATA = {'postgres', 'mariadb', 'redis', 'minio'}


def dependencies(service):
    conf = service.get('config', {})
    refs = [conf[k] for k in ('database_service', 'redis_service', 'storage_service', 'php_service') if conf.get(k)]
    refs += [r['target'] for r in conf.get('routes', [])]
    return sorted(set(service.get('depends_on', []) + refs))


class Context:
    def __init__(self, config, host_id):
        self.config = config
        self.host_id = host_id
        self.host = config['hosts'][host_id]
        suffix = '/' + config['environment'] + '/' + config['deployment']
        self.runtime = self.host.get('runtime_root', '/opt/dynamic-deployment') + suffix
        self.data = self.host.get('data_root', '/srv/dynamic-deployment') + suffix
        self.services = {s['id']: s for s in config['services'] if s.get('enabled', True)}
        self.bundle = {'compose': {'name': config['environment'] + '-' + config['deployment'],
                                  'services': {}, 'networks': {}}, 'files': {}, 'secret_files': {},
                       'asset_files': {}, 'directories': [], 'endpoints': [], 'warnings': []}

    def network(self, out, name, internal=True):
        self.bundle['compose']['networks'][name] = {'internal': internal}
        if name not in out['networks']:
            if isinstance(out['networks'], dict):
                out['networks'][name] = {}
            else:
                out['networks'].append(name)

    def mount(self, out, source, target, readonly=True):
        out['volumes'].append({'type': 'bind', 'source': source, 'target': target,
                               'read_only': readonly, 'bind': {'create_host_path': False}})

    def file(self, service, out, name, content, target):
        path = 'files/' + service['id'] + '/' + name
        self.bundle['files'][path] = content
        self.mount(out, self.runtime + '/' + path, target)

    def asset(self, service, out, name, source, target):
        path = 'assets/' + service['id'] + '/' + name
        self.bundle['asset_files'][path] = source
        self.mount(out, self.runtime + '/' + path, target)

    def secret(self, service, out, name, vault_key=None):
        path = 'secrets/' + service['id'] + '/' + name
        self.bundle['secret_files'][path] = vault_key or service.get('secrets', {})[name]
        target = '/run/secrets/' + name
        self.mount(out, self.runtime + '/' + path, target)
        return target

    def persistent(self, service, out, suffix, target, readonly=False, owner=None):
        path = (owner or service['id']) + '/' + suffix
        if path not in self.bundle['directories']:
            self.bundle['directories'].append(path)
        self.mount(out, self.data + '/' + path, target, readonly)

    def endpoint(self, service, out, port, target, domain=None):
        out.setdefault('ports', []).append({'host_ip': self.host['address'],
                                            'published': str(port), 'target': target, 'protocol': 'tcp'})
        self.network(out, 'uplink-' + service['id'], False)
        if domain:
            self.bundle['endpoints'].append({'service': service['id'],
                'url': 'https://' + domain + (':' + str(port) if port != 443 else '')})

    def connect(self, service, out, target_id):
        target = self.services[target_id]
        if target['host'] == service['host']:
            name = 'data-' + target_id if target['kind'] in DATA else (
                'backend' if target['kind'] == 'laravel-php' else 'management')
            self.network(out, name)
            out.setdefault('depends_on', {})[target_id] = {'condition': 'service_healthy'}
            return target_id, PORTS.get(target['kind'], 80), False
        cfg = target.get('config', {})
        if not all(cfg.get(k) for k in ('tls_ca', 'tls_cert', 'tls_key', 'server_name', 'publish_port')):
            raise ValueError('Remote dependency requires published private TLS endpoint: ' + target_id)
        self.network(out, 'uplink-' + service['id'], False)
        out.setdefault('extra_hosts', []).append(cfg['server_name'] + ':' + self.config['hosts'][target['host']]['address'])
        self.asset(service, out, target_id + '-ca', cfg['tls_ca'], '/run/assets/' + target_id + '-ca')
        return cfg['server_name'], cfg['publish_port'], True


def render_host(config, host_id):
    ctx = Context(deepcopy(config), host_id)
    for service in ctx.services.values():
        if service['host'] != host_id:
            continue
        resources = service.get('resources', {})
        out = {'image': service['image'], 'restart': 'unless-stopped', 'init': True,
               'read_only': True, 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
               'cpus': resources.get('cpus', 1), 'mem_limit': resources.get('memory', '512m'),
               'pids_limit': resources.get('pids', 256), 'networks': [], 'volumes': [],
               'tmpfs': ['/tmp:rw,noexec,nosuid,size=64m'],
               'logging': {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '3'}},
               'labels': {'io.dynamic-deployment.service': service['id']}}
        configure(ctx, service, out)
        if not out['networks']:
            ctx.network(out, 'isolated-' + service['id'])
        ctx.bundle['compose']['services'][service['id']] = out
    ctx.bundle['compose'] = escape_compose(ctx.bundle['compose'])
    return ctx.bundle


def escape_compose(value):
    if isinstance(value, str):
        return value.replace('$', '$$')
    if isinstance(value, list):
        return [escape_compose(item) for item in value]
    if isinstance(value, dict):
        return {key: escape_compose(item) for key, item in value.items()}
    return value


def render_all(config):
    return {host: render_host(config, host) for host in config['hosts']}
