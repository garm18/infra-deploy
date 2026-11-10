#!/usr/bin/env python3
"""Run bounded Compose operations on the current Docker host."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import preflight

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = {'init', 'check', 'config', 'network', 'build', 'pull', 'up', 'deploy', 'ps', 'logs', 'stop', 'down'}


def run(argv, cwd=ROOT):
    subprocess.run(argv, cwd=cwd, check=True)


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    mode = os.environ.get('ENV', 'local')
    services = os.environ.get('SERVICES', 'postgres mariadb redis minio').split()
    if action not in ACTIONS or mode not in ('local', 'staging', 'production'):
        raise ValueError('Invalid action or ENV (local, staging, production)')
    if not services or len(set(services)) != len(services) or any(s not in preflight.SERVICES for s in services):
        raise ValueError('SERVICES must contain unique known service directories')
    if action == 'init':
        for service in services:
            source = ROOT / service / '.env.example'
            target = source.with_name('.env')
            if source.exists() and not target.exists():
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(source.read_bytes())
                print(f'{service}: .env created; edit credentials before up')
        return
    docker = shutil.which('docker')
    if not docker:
        raise ValueError('Docker CLI unavailable')
    if action in ('check', 'up', 'deploy'):
        result = preflight.main(['--mode', 'local' if mode == 'local' else 'production', *services])
        if result:
            raise ValueError('Preflight failed; no deployment started')
        if action == 'check':
            return
    if action in ('network', 'up', 'deploy'):
        inspected = subprocess.run([docker, 'network', 'inspect', 'shared-network'], capture_output=True)
        if inspected.returncode:
            run([docker, 'network', 'create', 'shared-network'])
        if action == 'network':
            return
    for service in services:
        command = [docker, 'compose', '-f', 'docker-compose.yml']
        if mode == 'local':
            command += ['-f', 'docker-compose.local.yml']
        commands = {
            'config': [['config', '--quiet']], 'build': [['build']],
            'pull': [['pull', '--ignore-buildable']],
            'up': [['up', '-d', '--wait', '--wait-timeout', '180']],
            'deploy': [['pull', '--ignore-buildable'], ['build', '--pull'], ['up', '-d', '--wait', '--wait-timeout', '180']],
            'ps': [['ps']], 'logs': [['logs', '--tail', '100']],
            'stop': [['stop']], 'down': [['down']],
        }
        print(f'{mode}: {action} {service}', flush=True)
        for args in commands[action]:
            run(command + args, ROOT / service)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
