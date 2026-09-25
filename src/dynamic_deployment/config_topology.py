"""Dependency inference and explicit private-network constraints."""
import copy
import ipaddress
from .config_rules import fail

PHP_KINDS = ('laravel-php', 'laravel-worker', 'laravel-scheduler')
DATA_KINDS = ('postgres', 'mariadb', 'redis', 'minio')


def _infer(service):
    cfg = service['config']
    refs = [cfg[key] for key in ('database_service', 'redis_service', 'storage_service', 'php_service') if key in cfg]
    refs.extend(route['target'] for route in cfg.get('routes', []))
    return list(dict.fromkeys(service.get('depends_on', []) + refs))


def service_order(config):
    services = {s['id']: s for s in config['services']}
    ordered, visiting, visited = [], set(), set()

    def visit(name):
        if name in visiting:
            fail('services', 'dependency cycle detected')
        if name in visited:
            return
        visiting.add(name)
        service = services[name]
        for dep in _infer(service):
            if dep not in services:
                fail('service.' + name, 'unknown dependency ' + dep)
            if service['enabled'] and not services[dep]['enabled']:
                fail('service.' + name, 'dependency is disabled: ' + dep)
            visit(dep)
        visiting.remove(name)
        visited.add(name)
        if service['enabled']:
            ordered.append(name)

    for name in services:
        visit(name)
    return ordered


def _firewall(host, where, publish=False):
    if host.get('connection') == 'local':
        # Local mode always renders loopback bindings and has no remote firewall boundary.
        return
    if not host.get('firewall_check'):
        fail(where, 'operator firewall_check executable required')
    if publish and not host['allowed_cidrs']:
        fail(where, 'published ports require private source allowed_cidrs')


def _remote(consumer, provider, hosts):
    if consumer['kind'] == 'phpmyadmin' or (consumer['kind'] in PHP_KINDS and provider['kind'] in ('mariadb', 'redis')):
        fail('connection.' + consumer['id'], 'remote TLS adapter unavailable for this application driver; use same-host provider')
    source, target = hosts[consumer['host']], hosts[provider['host']]
    where = 'connection.' + consumer['id'] + '.' + provider['id']
    _firewall(source, where)
    _firewall(target, where, publish=True)
    cfg = provider['config']
    if provider['kind'] not in DATA_KINDS:
        fail(where, 'remote connection only supports TLS data providers')
    if not cfg.get('publish_port') or not all(cfg.get(k) for k in ('tls_ca', 'tls_cert', 'tls_key', 'server_name')):
        fail(where, 'remote provider requires publish_port and verified TLS CA/certificate/key/server_name')
    if not any(ipaddress.ip_address(source['address']) in ipaddress.ip_network(cidr) for cidr in target['allowed_cidrs']):
        fail(where, 'provider allowlist does not include consumer private address')


def _dependencies(service, services, hosts):
    cfg, kind = service['config'], service['kind']
    types = {'database_service': ('mariadb',) if kind == 'phpmyadmin' else ('postgres', 'mariadb'),
             'redis_service': ('redis',), 'storage_service': ('minio',), 'php_service': ('laravel-php',)}
    for key, kinds in types.items():
        if key not in cfg:
            continue
        provider = services[cfg[key]]
        if provider['kind'] not in kinds:
            fail('service.' + service['id'], key + ' has incompatible provider kind')
        if key == 'php_service' and provider['host'] != service['host']:
            fail('service.' + service['id'], 'Laravel web and PHP must share host')
        if provider['host'] != service['host']:
            _remote(service, provider, hosts)
        elif provider['kind'] in ('mariadb', 'redis') and provider['config'].get('tls_cert'):
            fail('connection.' + service['id'], 'local Laravel/phpMyAdmin driver does not support configured TLS; remove local TLS or use the supported remote adapter')
    for route in cfg.get('routes', []):
        provider = services[route['target']]
        if kind == 'apache' and (route['protocol'] == 'https' or provider['host'] != service['host']):
            fail('service.' + service['id'], 'Apache TLS upstream adapter unavailable; use Nginx')
        admin_target = provider['kind'] in ('minio', 'phpmyadmin')
        if cfg.get('role') == 'application' and admin_target:
            fail('service.' + service['id'], 'application proxy cannot route administration GUI')
        if cfg.get('role') == 'admin' and not admin_target:
            fail('service.' + service['id'], 'admin proxy supports only MinIO/phpMyAdmin')
        if provider['kind'] not in ('minio', 'phpmyadmin', 'laravel-web'):
            fail('service.' + service['id'], 'route target does not speak supported HTTP protocol')
        if provider['kind'] == 'minio' and route.get('port', 9001) not in (9000, 9001):
            fail('service.' + service['id'], 'MinIO route port must be 9000 or 9001')
        if provider['host'] != service['host']:
            _remote(service, provider, hosts)
            if route['protocol'] != 'https' or not route.get('tls_ca'):
                fail('service.' + service['id'], 'remote GUI requires HTTPS and CA')
            if route.get('port', 9001) == 9001 and not provider['config'].get('console_port'):
                fail('service.' + service['id'], 'remote console requires explicit private console_port')
        if provider['kind'] == 'minio' and route['protocol'] != 'https':
            fail('service.' + service['id'], 'TLS MinIO upstream requires HTTPS route')
        if route['protocol'] == 'https' and not route.get('tls_ca'):
            fail('service.' + service['id'], 'HTTPS upstream requires CA file')
    if kind in PHP_KINDS:
        for driver in ('database', 'redis'):
            if cfg['session_driver'] == driver and driver + '_service' not in cfg:
                fail('service.' + service['id'], 'session driver dependency missing')
        if 'storage_service' in cfg:
            if not cfg.get('storage_bucket') or not {'storage_access_key', 'storage_secret_key'} <= set(service['secrets']):
                fail('service.' + service['id'], 'S3 requires bucket and scoped access key secret references')


def _profiles(enabled):
    for service in enabled:
        kind, cfg = service['kind'], service['config']
        if kind == 'laravel-web':
            php = next(s for s in enabled if s['id'] == cfg['php_service'])
            for key in ('release_id', 'upload_path'):
                if cfg.get(key) != php['config'].get(key):
                    fail('service.' + service['id'], 'web/PHP release and upload paths must match')
        if kind in ('laravel-worker', 'laravel-scheduler'):
            candidates = [s for s in enabled if s['kind'] == 'laravel-php' and s['host'] == service['host']]
            if len(candidates) != 1:
                fail('service.' + service['id'], 'worker/scheduler requires same-host PHP profile')
            php = candidates[0]
            keys = ('release_id', 'database_service', 'redis_service', 'storage_service', 'storage_bucket', 'upload_path', 'session_driver', 'app_url', 'php_version')
            if any(cfg.get(key, 1000) != php['config'].get(key, 1000) for key in ('uid', 'gid')):
                fail('service.' + service['id'], 'PHP profile UID and GID must match')
            if service['image'] != php['image'] or any(cfg.get(k) != php['config'].get(k) for k in keys) or service['secrets'] != php['secrets']:
                fail('service.' + service['id'], 'PHP profile images, dependencies, and secrets must match')
        if kind in ('phpmyadmin', 'minio'):
            proxies = [s for s in enabled if s['kind'] in ('nginx', 'apache') and s['config']['role'] == 'admin' and any(r['target'] == service['id'] for r in s['config']['routes'])]
            if not proxies:
                fail('service.' + service['id'], 'GUI requires an administration HTTPS proxy route')


def check_topology(config):
    result = copy.deepcopy(config)
    services = {s['id']: s for s in result['services']}
    for s in result['services']:
        s['depends_on'] = _infer(s)
    service_order(result)
    enabled = [s for s in result['services'] if s['enabled']]
    ports, roles = set(), set()
    for service in enabled:
        host = result['hosts'][service['host']]
        cfg = service['config']
        role = (service['host'], service['kind'], cfg.get('role', ''))
        if role in roles:
            fail('service.' + service['id'], 'only one instance per host and role supported')
        roles.add(role)
        for key in ('publish_port', 'console_port', 'https_port'):
            if key in cfg:
                _firewall(host, 'service.' + service['id'], publish=True)
                binding = (host['address'], cfg[key])
                if binding in ports or cfg[key] == host['port']:
                    fail('service.' + service['id'], 'published port conflicts with another service or SSH')
                ports.add(binding)
        if cfg.get('egress'):
            _firewall(host, 'service.' + service['id'])
        _dependencies(service, services, result['hosts'])
    _profiles(enabled)
    return result
