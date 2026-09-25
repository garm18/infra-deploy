"""Invoke only project-owned Ansible playbooks with structured private inputs."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .vault import redact


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = {'preflight', 'apply', 'status', 'logs', 'stop', 'backup', 'restore'}


def parse_results(output):
    try:
        tree = json.loads(output)
    except (ValueError, TypeError):
        return []
    results = []

    def walk(value):
        if isinstance(value, dict):
            msg = value.get('msg')
            if isinstance(msg, str) and msg.startswith('DD_RESULT='):
                try:
                    item = json.loads(msg[len('DD_RESULT='):])
                except ValueError:
                    return
                if isinstance(item, dict) and {'host', 'operation', 'result'} <= item.keys():
                    results.append(item)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(tree)
    return results


def _inventory(config, hosts, secrets_values):
    inventory = {}
    for name in hosts:
        host = config['hosts'][name]
        item = {'ansible_user': host['user'], 'ansible_python_interpreter': '/usr/bin/python3',
                'ansible_become_flags': '-n'}
        connection = host.get('connection', 'ssh-key')
        if connection == 'local':
            item['ansible_connection'] = 'local'
        else:
            item.update(ansible_host=host['address'], ansible_port=host.get('port', 22),
                        ansible_ssh_common_args='-o StrictHostKeyChecking=yes -o BatchMode=yes')
            if connection == 'ssh-key':
                item['ansible_ssh_private_key_file'] = host['private_key_file']
            elif connection == 'ssh-password':
                item['ansible_password'] = secrets_values[host['ssh_password_ref']]
        inventory[name] = item
    return {'all': {'hosts': inventory}}


def _private_json(directory, name, value):
    target = Path(directory) / name
    with target.open('x', encoding='utf-8') as handle:
        target.chmod(0o600)
        json.dump(value, handle)
    return target


def run_operation(config, bundles, operation, run_id, *, secrets_values=None,
                  selected=None, host=None, backup=None, removed=None):
    if operation not in OPERATIONS or (host is not None and host not in config['hosts']):
        raise ValueError('Operasi atau host tidak valid.')
    hosts = [host] if host else sorted(config['hosts'])
    secrets_values = secrets_values or {}
    selected = selected or []
    available = {s['id'] for s in config['services'] if s.get('enabled', True) and s['host'] in hosts}
    if any(name not in available for name in selected):
        raise ValueError('Pilihan layanan tidak berada pada host yang diminta.')
    variables = {
        'dd_environment': config['environment'], 'dd_deployment': config['deployment'],
        'dd_hosts': config['hosts'], 'dd_bundles': bundles, 'dd_services': config['services'],
        'dd_operation': operation, 'dd_run_id': run_id, 'dd_secrets': secrets_values,
        'dd_selected_services': selected, 'dd_backup': backup or {}, 'dd_removed_services': removed or [],
    }
    env = {**os.environ, 'ANSIBLE_CONFIG': str(PROJECT_ROOT / 'ansible' / 'ansible.cfg'),
           'ANSIBLE_STDOUT_CALLBACK': 'ansible.posix.json', 'ANSIBLE_HOST_KEY_CHECKING': 'True',
           'ANSIBLE_PIPELINING': 'True', 'ANSIBLE_KEEP_REMOTE_FILES': 'False',
           'ANSIBLE_DISPLAY_ARGS_TO_STDOUT': 'False', 'ANSIBLE_NOCOLOR': 'True'}
    with tempfile.TemporaryDirectory(prefix='dynamic-deployment-') as directory:
        os.chmod(directory, 0o700)
        env['ANSIBLE_LOCAL_TEMP'] = str(Path(directory) / 'ansible-tmp')
        inventory = _private_json(directory, 'inventory.json', _inventory(config, hosts, secrets_values))
        parameters = _private_json(directory, 'vars.json', variables)
        playbook = PROJECT_ROOT / 'ansible' / ('preflight.yml' if operation == 'preflight' else 'operate.yml')
        args = ['ansible-playbook', '-i', str(inventory), str(playbook), '--extra-vars', '@' + str(parameters)]
        try:
            result = subprocess.run(args, capture_output=True, text=True, env=env,
                                    cwd=PROJECT_ROOT, timeout=7200 if operation in {'backup', 'restore'} else 900)
        except FileNotFoundError:
            return {'ok': False, 'status': 'failed', 'operation': operation,
                    'hosts': hosts, 'error': 'ansible-playbook tidak tersedia; jalankan doctor.', 'results': []}
        except subprocess.TimeoutExpired:
            return {'ok': False, 'status': 'unknown', 'operation': operation, 'hosts': hosts,
                    'error': 'Timeout. Periksa status dan lock remote sebelum mencoba ulang.', 'results': []}
    parsed = parse_results(result.stdout)
    valid = [entry for entry in parsed if entry['host'] in hosts and entry['operation'] == operation]
    observed = {entry['host'] for entry in valid}
    ok = result.returncode == 0 and observed == set(hosts)
    summary = {'ok': ok, 'status': 'completed' if ok else 'failed-or-unknown',
               'operation': operation, 'hosts': hosts, 'results': valid, 'exit_code': result.returncode}
    if not ok:
        summary['error'] = ('Operasi Ansible tidak selesai pada seluruh target. Periksa koneksi SSH/sudo, '
                            'prasyarat, dan status remote; output mentah disembunyikan untuk melindungi secrets.')
    return redact(summary, secrets_values.values())
