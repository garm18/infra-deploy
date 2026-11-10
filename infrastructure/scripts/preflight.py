#!/usr/bin/env python3
"""Read-only deployment checks. Never prints environment values or Compose output."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).absolute().parents[1]
SERVICES = ('mariadb', 'postgres', 'redis', 'minio', 'apache', 'proxy-nginx')
PASSWORDS = {'mariadb': ('MARIADB_ROOT_PASSWORD', 'MARIADB_PASSWORD'),
             'postgres': ('POSTGRES_PASSWORD',), 'redis': ('REDIS_PASSWORD',),
             'minio': ('MINIO_ROOT_PASSWORD',)}
DATA = {'mariadb': '/mnt/data/mariadb'}


def valid_secret(value):
    normalized = re.sub(r'[^a-z0-9]', '', value.lower())
    return (len(value) >= 16 and '\n' not in value and '\r' not in value
            and not any(word in normalized for word in
                        ('changeme', 'changethis', 'yourpassword', 'minioadmin', 'placeholder')))


def read_env(path, process):
    """Parse a deliberately small dotenv subset; reject interpolation/escape ambiguity."""
    values = {}
    if path.exists():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = re.fullmatch(r'(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)', line)
            if not match:
                raise ValueError(f'.env line {number}: unsupported syntax')
            key, raw = match.groups()
            if raw.startswith(("'", '"')):
                quote = raw[0]
                end = raw.find(quote, 1)
                if end < 0 or (raw[end + 1:].strip() and not raw[end + 1:].strip().startswith('#')):
                    raise ValueError(f'.env line {number}: unsupported quoting')
                value = raw[1:end]
                if quote == '"' and ('$' in value or '\\' in value):
                    raise ValueError(f'.env line {number}: use literal single quotes')
            else:
                value = re.split(r'\s+#', raw, maxsplit=1)[0].strip()
                if '$' in value or '\\' in value or any(char.isspace() for char in value):
                    raise ValueError(f'.env line {number}: use literal single quotes')
            if key in values:
                raise ValueError(f'.env line {number}: duplicate key')
            values[key] = value
    return {**values, **process}


def directory_error(value, key):
    path = Path(value)
    if not value or not path.is_absolute() or not path.is_dir():
        return f'{key}: requires an existing absolute data directory'
    return None


def minio_assets(env, require_data=True):
    errors = []
    data = env.get('MINIO_DATA_DIR', '/mnt/data/minio')
    if require_data:
        error = directory_error(data, 'MINIO_DATA_DIR')
        if error:
            errors.append(error)
    return errors


def deployment_errors(service, env, mode):
    errors = []
    for key in PASSWORDS.get(service, ()):
        if not valid_secret(env.get(key, '')):
            errors.append(f'{key}: requires at least 16 characters and no placeholder or newline')
    for key in {'mariadb': ('MARIADB_USER', 'MARIADB_DATABASE'), 'minio': ('MINIO_ROOT_USER',)}.get(service, ()):
        if not env.get(key, '').strip() or env.get(key, '').lower() == 'minioadmin':
            errors.append(f'{key}: requires a non-default value')
    if service == 'minio':
        errors.extend(minio_assets(env, require_data=mode == 'production'))
    if mode == 'production' and service in DATA:
        error = directory_error(DATA[service], f'{service} data')
        if error:
            errors.append(error)
    return errors


def compose_check(directory, env, mode, local_override=True):
    standalone = env.get('COMPOSE_BIN')
    docker = shutil.which('docker')
    if standalone and (not Path(standalone).is_absolute() or not os.access(standalone, os.X_OK)):
        return 'COMPOSE_BIN must be an absolute executable path'
    if not standalone and not docker:
        return 'Docker unavailable; Compose validation was not run'
    command = ([standalone] if standalone else [docker, 'compose']) + ['-f', str(directory / 'docker-compose.yml')]
    if mode == 'local' and local_override:
        command += ['-f', str(directory / 'docker-compose.local.yml')]
    try:
        result = subprocess.run(command + ['config', '--quiet'], cwd=directory,
                                env=env, capture_output=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 'Docker Compose validation could not complete'
    if result.returncode:
        return 'Docker Compose validation failed; inspect configuration privately on deployment host'
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('production', 'local'), default='production')
    parser.add_argument('--static', action='store_true', help='Check repository files only; skips deployment credentials/assets and Docker')
    parser.add_argument('services', nargs='*', metavar='SERVICE')
    args = parser.parse_args(argv)
    services = args.services or SERVICES
    if any(service not in SERVICES for service in services):
        parser.error('SERVICE must be one of: ' + ', '.join(SERVICES))
    failures = 0
    for service in services:
        directory = ROOT / service
        errors = []
        files = ['docker-compose.yml']
        if service not in ('proxy-nginx', 'apache'):
            files.append('.env.example')
        files.append('docker-compose.local.yml')
        for name in files:
            if not (directory / name).is_file():
                errors.append(f'{name}: missing')
        if not args.static:
            try:
                env = read_env(directory / '.env', os.environ)
                errors.extend(deployment_errors(service, env, args.mode))
                error = compose_check(directory, env, args.mode,
                                      local_override=True)
                if error:
                    errors.append(error)
            except (ValueError, OSError):
                errors.append('.env: unreadable or unsupported syntax; use simple KEY=value or single quoted literals')
        for error in errors:
            print(f'FAIL {service}: {error}')
        if not errors:
            print(f'OK {service}: ' + ('repository files present (no runtime validation)' if args.static else 'preflight passed (not a runtime smoke test)'))
        failures += bool(errors)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
