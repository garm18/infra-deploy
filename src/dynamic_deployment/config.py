"""Parse and normalize the deliberately closed deployment schema."""
import copy
import json
import math
import re
from pathlib import Path
import yaml
from .config_rules import (SLUG, IDENT, DOMAIN, IMAGE, CONFIG_KEYS, REQUIRED_SECRETS,
                           fail, mapping, match, integer, boolean, path, address, cidrs, strings)
from .config_topology import check_topology, service_order
from .errors import ValidationError


class UniqueLoader(yaml.SafeLoader):
    """Safe YAML loader rejecting duplicate keys, including merge overrides."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            fail('configuration', 'duplicate or non-string mapping key')
        result[key] = value
    return result


def _yaml_mapping(loader, node):
    loader.flatten_mapping(node)
    return _unique((loader.construct_object(k), loader.construct_object(v)) for k, v in node.value)


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def load_config(filename):
    try:
        raw = Path(filename).read_text(encoding='utf-8')
        if len(raw) > 1024 * 1024:
            fail('configuration', 'file exceeds 1 MiB')
        value = json.loads(raw, object_pairs_hook=_unique) if Path(filename).suffix == '.json' else yaml.load(raw, Loader=UniqueLoader)
        return validate_config(value)
    except ValidationError:
        raise
    except (OSError, UnicodeError, ValueError, yaml.YAMLError, RecursionError) as exc:
        raise ValidationError('configuration: cannot read or parse input') from exc


def _host(value, where):
    allowed = {'address', 'user', 'port', 'connection', 'private_key_file', 'ssh_password_ref',
               'runtime_root', 'data_root', 'expected_mount', 'bootstrap', 'allowed_cidrs', 'firewall_check'}
    mapping(value, allowed, where, {'address', 'user', 'expected_mount'})
    defaults = {'port': 22, 'connection': 'ssh-key', 'runtime_root': '/opt/dynamic-deployment',
                'data_root': '/srv/dynamic-deployment', 'bootstrap': False, 'allowed_cidrs': []}
    h = {**defaults, **value}
    if h['connection'] not in ('local', 'ssh-key', 'ssh-password', 'ssh-agent'):
        fail(where + '.connection', 'must be local, ssh-key, ssh-password, or ssh-agent')
    if h['connection'] == 'local':
        if h['address'] != '127.0.0.1':
            fail(where + '.address', 'local connection must use 127.0.0.1')
    else:
        address(h['address'], where + '.address')
    match(h['user'], re.compile(r'[a-z_][a-z0-9_-]{0,31}\Z'), where + '.user')
    integer(h['port'], where + '.port')
    boolean(h['bootstrap'], where + '.bootstrap')
    cidrs(h['allowed_cidrs'], where + '.allowed_cidrs')
    if h['connection'] == 'ssh-key' and 'private_key_file' not in h:
        fail(where, 'private_key_file required for ssh-key connection')
    if h['connection'] == 'ssh-password':
        match(h.get('ssh_password_ref'), IDENT, where + '.ssh_password_ref')
    elif 'ssh_password_ref' in h:
        fail(where, 'ssh_password_ref only allowed for ssh-password connection')
    if h['connection'] != 'ssh-key' and 'private_key_file' in h:
        fail(where, 'private_key_file only allowed for ssh-key connection')
    for key in ('private_key_file', 'runtime_root', 'data_root', 'firewall_check'):
        if key in h:
            path(h[key], where + '.' + key)
    if h['expected_mount'] != '/':
        path(h['expected_mount'], where + '.expected_mount')
    runtime, data, mount = (Path(h[k]) for k in ('runtime_root', 'data_root', 'expected_mount'))
    if runtime == data or runtime in data.parents or data in runtime.parents:
        fail(where, 'runtime_root and data_root must not overlap')
    if mount != data and mount not in data.parents:
        fail(where, 'data_root must lie within expected_mount')
    return h


def _routes(routes, where):
    if not isinstance(routes, list) or not routes:
        fail(where, 'at least one route required')
    domains = set()
    for route in routes:
        mapping(route, {'domain', 'target', 'port', 'protocol', 'tls_ca'}, where, {'domain', 'target'})
        match(route['domain'], DOMAIN, where + '.domain')
        match(route['target'], SLUG, where + '.target')
        if route['domain'] in domains:
            fail(where, 'duplicate route domain')
        domains.add(route['domain'])
        route.setdefault('protocol', 'http')
        if route['protocol'] not in ('http', 'https'):
            fail(where, 'unsupported upstream protocol')
        if 'port' in route:
            integer(route['port'], where + '.port')
        if 'tls_ca' in route:
            path(route['tls_ca'], where + '.tls_ca')


def _service_config(kind, value, where):
    mapping(value, CONFIG_KEYS[kind], where)
    cfg = copy.deepcopy(value)
    if kind in ('postgres', 'mariadb'):
        for key in ('database', 'username'):
            match(cfg.get(key), IDENT, where + '.' + key)
    if kind == 'redis':
        cfg.setdefault('maxmemory', '256mb')
    if kind in ('nginx', 'apache'):
        cfg.setdefault('role', 'admin')
        if cfg['role'] not in ('admin', 'application'):
            fail(where, 'invalid proxy role')
        _routes(cfg.get('routes'), where + '.routes')
    if kind in ('nginx', 'apache', 'laravel-web'):
        cfg.setdefault('https_port', 443)
        for key in ('tls_cert', 'tls_key'):
            path(cfg.get(key), where + '.' + key)
    if kind == 'minio':
        for key in ('s3_domain', 'console_domain'):
            match(cfg.get(key), DOMAIN, where + '.' + key)
        if cfg['s3_domain'] == cfg['console_domain']:
            fail(where, 'S3 and console domains must differ')
        path(cfg.get('license_file'), where + '.license_file')
        for key in ('tls_cert', 'tls_key'):
            path(cfg.get(key), where + '.' + key)
    if kind.startswith('laravel-'):
        match(cfg.get('release_id'), SLUG, where + '.release_id')
        if kind == 'laravel-web':
            match(cfg.get('php_service'), SLUG, where + '.php_service')
            match(cfg.get('domain'), DOMAIN, where + '.domain')
        else:
            cfg.setdefault('health_path', '/up')
            cfg.setdefault('session_driver', 'file')
            cfg.setdefault('stop_grace_seconds', 60)
            cfg.setdefault('egress', [])
            if cfg['session_driver'] not in ('database', 'redis', 'file'):
                fail(where, 'unsupported session driver')
            if not isinstance(cfg['health_path'], str) or not re.fullmatch(r'/[a-zA-Z0-9_/-]*', cfg['health_path']):
                fail(where, 'invalid health path')
            if 'app_url' in cfg and (not isinstance(cfg['app_url'], str) or not re.fullmatch(r'https://[a-zA-Z0-9.-]+(?::[0-9]{1,5})?', cfg['app_url'])):
                fail(where, 'app_url must be an HTTPS origin')
            if not isinstance(cfg['egress'], list):
                fail(where, 'egress must be a list')
            for entry in cfg['egress']:
                mapping(entry, {'host', 'port'}, where + '.egress', {'host', 'port'})
                match(entry['host'], DOMAIN, where + '.egress.host')
                integer(entry['port'], where + '.egress.port')
        if cfg.get('upload_path') not in (None, 'storage/app/public'):
            fail(where + '.upload_path', 'currently only storage/app/public is supported')
    if kind == 'phpmyadmin':
        match(cfg.get('database_service'), SLUG, where + '.database_service')
    for key, value in cfg.items():
        _config_scalar(key, value, where)
    if bool(cfg.get('tls_cert')) != bool(cfg.get('tls_key')):
        fail(where, 'TLS certificate and key must be provided together')
    return cfg


def _config_scalar(key, value, where):
    w = where + '.' + key
    if key in ('uid', 'gid'):
        integer(value, w, 1, 2147483647)
    elif key in ('publish_port', 'console_port', 'https_port', 'stop_grace_seconds'):
        integer(value, w)
    elif key in ('tls_ca', 'tls_cert', 'tls_key', 'license_file', 'release_evidence_file'):
        path(value, w)
    elif key == 'upload_path':
        path(value, w, relative=True)
    elif key.endswith('_service'):
        match(value, SLUG, w)
    elif key in ('server_name', 'domain', 's3_domain', 'console_domain'):
        match(value, DOMAIN, w)
    elif key == 'queue':
        match(value, re.compile(r'[a-zA-Z0-9_-]+(?:,[a-zA-Z0-9_-]+)*\Z'), w)
    elif key == 'php_version':
        match(value, re.compile(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?\Z'), w)
    elif key == 'storage_bucket':
        match(value, re.compile(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\Z'), w)
    elif key == 'maxmemory':
        match(value, re.compile(r'[1-9][0-9]*(?:kb|mb|gb)\Z'), w)
    elif key not in ('routes', 'egress') and not isinstance(value, str):
        fail(w, 'expected string')


def _service(value, hosts):
    mapping(value, {'id', 'kind', 'host', 'image', 'enabled', 'depends_on', 'config', 'secrets', 'resources'}, 'service', {'id', 'kind', 'host', 'image'})
    s = {'enabled': True, 'depends_on': [], 'config': {}, 'secrets': {}, 'resources': {}, **value}
    match(s['id'], SLUG, 'service.id')
    w = 'service.' + s['id']
    if not isinstance(s['kind'], str) or s['kind'] not in CONFIG_KEYS:
        fail(w, 'unsupported service kind')
    if not isinstance(s['host'], str) or s['host'] not in hosts:
        fail(w, 'unknown host')
    match(s['image'], IMAGE, w + '.image')
    if IMAGE.fullmatch(s['image']).group(1).lower() == 'latest':
        fail(w, 'latest image tags forbidden')
    boolean(s['enabled'], w + '.enabled')
    strings(s['depends_on'], w + '.depends_on')
    for dep in s['depends_on']:
        match(dep, SLUG, w + '.depends_on')
    if not isinstance(s['secrets'], dict):
        fail(w, 'secrets must be Vault references mapping')
    for name, ref in s['secrets'].items():
        match(name, IDENT, w + '.secrets.name')
        match(ref, IDENT, w + '.secrets.reference')
    if REQUIRED_SECRETS.get(s['kind'], set()) - set(s['secrets']):
        fail(w, 'required secret references missing')
    mapping(s['resources'], {'cpus', 'memory', 'pids'}, w + '.resources')
    s['resources'] = {'cpus': 1, 'memory': '512m', 'pids': 256, **s['resources']}
    cpu = s['resources']['cpus']
    if type(cpu) not in (int, float) or not math.isfinite(cpu) or not 0 < cpu <= 1024:
        fail(w, 'invalid CPU limit')
    match(s['resources']['memory'], re.compile(r'[1-9][0-9]*[kmg]\Z'), w + '.memory')
    integer(s['resources']['pids'], w + '.pids', 16, 1048576)
    s['config'] = _service_config(s['kind'], s['config'], w + '.config')
    return s


def validate_config(value):
    mapping(value, {'schema_version', 'environment', 'deployment', 'hosts', 'services', 'secrets_file', 'production'}, 'configuration', {'schema_version', 'environment', 'deployment', 'hosts', 'services'})
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        fail('schema_version', 'only version 1 supported')
    if value['environment'] not in ('development', 'staging', 'production'):
        fail('environment', 'must be development, staging, or production')
    match(value['deployment'], SLUG, 'deployment')
    if not isinstance(value['hosts'], dict) or not value['hosts']:
        fail('hosts', 'at least one host required')
    result = copy.deepcopy(value)
    hosts = {}
    addresses = set()
    for name, host in result['hosts'].items():
        match(name, SLUG, 'host.id')
        hosts[name] = _host(host, 'host.' + name)
        if hosts[name]['address'] in addresses:
            fail('hosts', 'duplicate host address; use one canonical host ID')
        addresses.add(hosts[name]['address'])
    if not isinstance(result['services'], list) or not result['services']:
        fail('services', 'at least one service required')
    services = [_service(s, hosts) for s in result['services']]
    if len({s['id'] for s in services}) != len(services):
        fail('services', 'duplicate service ID')
    if 'secrets_file' in result:
        path(result['secrets_file'], 'secrets_file')
    production = result.get('production', {})
    mapping(production, {'owner', 'rpo_minutes', 'rto_minutes', 'backup_destination', 'backup_schedule', 'backup_retention_days', 'release_evidence_file', 'restore_evidence_file'}, 'production')
    for key, item in production.items():
        if key in ('rpo_minutes', 'rto_minutes', 'backup_retention_days'):
            integer(item, 'production.' + key, 1, 5256000)
        elif key.endswith('_file'):
            path(item, 'production.' + key)
        elif not isinstance(item, str) or not item.strip() or any(ord(c) < 32 for c in item):
            fail('production.' + key, 'expected nonempty printable string')
    result = {**result, 'hosts': hosts, 'services': services, 'production': production}
    return check_topology(result)
