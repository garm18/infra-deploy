"""Strict scalar and schema validation for deployment data."""
import ipaddress
import re
from pathlib import PurePosixPath
from .errors import ValidationError

SLUG = re.compile(r'[a-z][a-z0-9-]{0,39}\Z')
IDENT = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]{0,62}\Z')
DOMAIN = re.compile(r'(?=.{1,253}\Z)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\Z')
IMAGE = re.compile(r'(?:[a-z0-9.-]+(?::[0-9]+)?/)?[a-z0-9_./-]+:([a-zA-Z0-9_][a-zA-Z0-9_.-]*)@sha256:[a-f0-9]{64}\Z')
PRIVATE = tuple(ipaddress.ip_network(x) for x in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
TLS = {'tls_ca', 'tls_cert', 'tls_key', 'server_name'}
DATA = {'uid', 'gid', 'publish_port'} | TLS
PHP = {'database_service', 'redis_service', 'storage_service', 'release_id', 'health_path', 'queue', 'stop_grace_seconds', 'upload_path', 'egress', 'uid', 'gid', 'php_version', 'session_driver', 'app_url', 'storage_bucket'}
CONFIG_KEYS = {
    'postgres': DATA | {'database', 'username'},
    'mariadb': DATA | {'database', 'username'},
    'redis': DATA | {'maxmemory'},
    'minio': DATA | {'s3_domain', 'console_domain', 'license_file', 'console_port', 'release_evidence_file'},
    'nginx': {'routes', 'tls_cert', 'tls_key', 'https_port', 'role'},
    'apache': {'routes', 'tls_cert', 'tls_key', 'https_port', 'role'},
    'phpmyadmin': {'database_service'},
    'laravel-web': {'php_service', 'tls_cert', 'tls_key', 'https_port', 'domain', 'release_id', 'upload_path'},
    'laravel-php': PHP, 'laravel-worker': PHP, 'laravel-scheduler': PHP,
}
REQUIRED_SECRETS = {'postgres': {'password', 'root_password'}, 'mariadb': {'password', 'root_password'},
                    'redis': {'password'}, 'minio': {'root_user', 'root_password'},
                    'laravel-php': {'app_key'}, 'laravel-worker': {'app_key'}, 'laravel-scheduler': {'app_key'}}


def fail(where, reason):
    raise ValidationError(f'{where}: {reason}')


def mapping(value, allowed, where, required=()):
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        fail(where, 'expected mapping with string keys')
    if set(value) - set(allowed):
        fail(where, 'unknown field(s): ' + ', '.join(sorted(set(value) - set(allowed))))
    if set(required) - set(value):
        fail(where, 'missing field(s): ' + ', '.join(sorted(set(required) - set(value))))


def match(value, pattern, where):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        fail(where, 'invalid format')


def integer(value, where, minimum=1, maximum=65535):
    if type(value) is not int or not minimum <= value <= maximum:
        fail(where, f'expected integer between {minimum} and {maximum}')


def boolean(value, where):
    if type(value) is not bool:
        fail(where, 'expected boolean')


def path(value, where, relative=False):
    if not isinstance(value, str) or not value or not re.fullmatch(r'[a-zA-Z0-9_./-]+', value):
        fail(where, 'expected safe path without substitutions')
    p = PurePosixPath(value)
    if '..' in value.split('/') or '.' in value.split('/') or '//' in value or p.is_absolute() == relative or str(p) == '/':
        fail(where, 'path must be normalized and confined')


def address(value, where):
    if not isinstance(value, str):
        fail(where, 'expected private IPv4 string')
    try:
        ip = ipaddress.IPv4Address(value)
    except (ValueError, TypeError):
        fail(where, 'expected private IPv4 address')
    if not any(ip in net for net in PRIVATE):
        fail(where, 'only RFC1918 private IPv4 addresses accepted')


def cidrs(value, where):
    if not isinstance(value, list):
        fail(where, 'expected list of private CIDRs')
    for entry in value:
        if not isinstance(entry, str) or '/' not in entry:
            fail(where, 'expected canonical RFC1918 CIDRs')
        try:
            net = ipaddress.ip_network(entry, strict=True)
            valid = net.version == 4 and any(net.subnet_of(parent) for parent in PRIVATE)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            fail(where, 'expected canonical RFC1918 CIDRs')


def strings(value, where):
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value) or len(set(value)) != len(value):
        fail(where, 'expected unique string list')
