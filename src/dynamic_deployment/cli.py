"""Small, guarded command line interface for Dynamic Deployment."""

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import load_config, service_order
from .executor import run_operation
from .plans import create_plan, verify_plan
from .preflight import local_preflight
from .render import render_all
from .state import StateStore, safe_local
from .vault import initialize_secrets, load_secrets, redact


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE = Path.home() / '.local' / 'state' / 'dynamic-deployment'


def _json(value):
    print(json.dumps(redact(value), ensure_ascii=False, indent=2, sort_keys=True))


def _store(args):
    return StateStore(args.state_dir)


def _config_and_bundles(filename):
    config = load_config(filename)
    return config, render_all(config)


def _target(args, payload):
    if args.environment != payload['environment'] or args.deployment != payload['deployment']:
        raise ValueError('Target environment/deployment harus persis sama dengan plan.')


def _state_name(config):
    return f"deployments/{config['environment']}/{config['deployment']}.json"


def _assert_safe_evolution(config, previous):
    old = {s['id']: s for s in previous.get('config', {}).get('services', []) if s.get('enabled', True)}
    new = {s['id']: s for s in config['services'] if s.get('enabled', True)}
    stateful = {'postgres', 'mariadb', 'redis', 'minio'}
    for name in old.keys() & new.keys():
        before, after = old[name], new[name]
        if before['kind'] in stateful and any(before.get(k) != after.get(k) for k in ('kind', 'host', 'image')):
            raise ValueError(f'Layanan data {name} berubah host/kind/image. Gunakan deployment baru dan isolated restore.')


def _assert_stop_safe(config, selected):
    selected = set(selected)
    consumers = []
    for service in config['services']:
        if not service.get('enabled', True) or service['id'] in selected:
            continue
        dependencies = set(service.get('depends_on', []))
        dependencies.update(service.get('config', {}).get(key) for key in
                            ('database_service', 'redis_service', 'storage_service', 'php_service')
                            if service.get('config', {}).get(key))
        dependencies.update(route['target'] for route in service.get('config', {}).get('routes', []))
        if dependencies & selected:
            consumers.append(service['id'])
    if consumers:
        raise ValueError('Tidak boleh menghentikan provider saat consumer masih aktif: ' + ', '.join(sorted(consumers)))


def _apply(args):
    store = _store(args)
    payload, config, bundles = verify_plan(args.plan, store, args.environment, args.deployment)
    _target(args, payload)
    local_preflight(config, bundles)
    secrets = load_secrets(config, args.vault_password_file)
    previous = store.read_json(_state_name(config), {})
    _assert_safe_evolution(config, previous)
    order = service_order(config)
    outcomes = []
    with store.lock(f"{config['environment']}-{config['deployment']}"):
        # All hosts must pass non-mutating remote checks before the first compose change.
        check = run_operation(config, bundles, 'preflight', payload['run_id'], secrets_values=secrets)
        outcomes.append(check)
        if not check['ok']:
            return {'ok': False, 'phase': 'remote-preflight', 'runs': outcomes}
        for service_id in order:
            service = next(s for s in config['services'] if s['id'] == service_id)
            result = run_operation(config, bundles, 'apply', payload['run_id'], secrets_values=secrets,
                                   selected=[service_id], host=service['host'])
            outcomes.append(result)
            if not result['ok']:
                return {'ok': False, 'phase': 'apply', 'runs': outcomes}
        store.write_json(_state_name(config), {'config': config, 'run_id': payload['run_id'],
                                               'applied_at': payload['created_at']})
    return {'ok': True, 'run_id': payload['run_id'], 'runs': outcomes}


def _read_config_operation(args, operation):
    config, bundles = _config_and_bundles(args.config)
    secrets = load_secrets(config, args.vault_password_file) if operation != 'status' else {}
    selected = args.service or []
    backup = getattr(args, 'backup', None)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12]
    return run_operation(config, bundles, operation, run_id, secrets_values=secrets,
                         selected=selected, host=args.host, backup=backup)


def build_parser():
    parser = argparse.ArgumentParser(prog='dynamic-deployment', description='Deployment Docker Compose terjaga melalui Ansible SSH.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--state-dir', default=str(DEFAULT_STATE), help='Direktori state privat controller.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Periksa kebutuhan controller.')
    commands.add_parser('catalog', help='Tampilkan katalog layanan yang didukung.')
    validate = commands.add_parser('validate', help='Validasi konfigurasi dan render lokal.')
    validate.add_argument('config')
    plan = commands.add_parser('plan', help='Buat plan bertanda tangan; belum mengubah server.')
    plan.add_argument('config')
    apply = commands.add_parser('apply', help='Terapkan plan yang masih identik.')
    apply.add_argument('--plan', required=True)
    apply.add_argument('--environment', required=True)
    apply.add_argument('--deployment', required=True)
    apply.add_argument('--vault-password-file')
    for name in ('preflight', 'status', 'logs'):
        item = commands.add_parser(name, help=f'Jalankan {name} pada server melalui SSH.')
        item.add_argument('--config', required=True)
        item.add_argument('--host')
        item.add_argument('--service', action='append')
        item.add_argument('--vault-password-file')
    stop = commands.add_parser('stop', help='Hentikan layanan terpilih sambil mempertahankan data.')
    stop.add_argument('--config', required=True)
    stop.add_argument('--host', required=True)
    stop.add_argument('--service', action='append', required=True)
    stop.add_argument('--yes', action='store_true', help='Konfirmasi bahwa layanan akan dihentikan.')
    stop.add_argument('--vault-password-file')
    for name in ('backup', 'restore'):
        item = commands.add_parser(name, help=('Buat backup terenkripsi pada mount eksternal.' if name == 'backup' else 'Restore hanya ke deployment baru yang terisolasi.'))
        item.add_argument('--config', required=True)
        item.add_argument('--host', required=True)
        item.add_argument('--service', required=True)
        item.add_argument('--vault-password-file')
        if name == 'backup':
            item.add_argument('--backup-id', required=True)
            item.add_argument('--destination', required=True)
            item.add_argument('--recipient', required=True)
        else:
            item.add_argument('--archive', required=True)
            item.add_argument('--identity-file', required=True)
    vault = commands.add_parser('secrets-init', help='Buat Ansible Vault sekali; tidak merotasi secret yang ada.')
    vault.add_argument('--config', required=True)
    vault.add_argument('--vault-password-file')
    wizard = commands.add_parser('wizard', help='Buat konfigurasi melalui pertanyaan terminal.')
    wizard.add_argument('--output', required=True)
    wizard.add_argument('--force', action='store_true')
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            result = {'ok': all(shutil.which(x) for x in ('python3', 'ansible-playbook', 'ansible-vault', 'openssl')),
                      'commands': {x: bool(shutil.which(x)) for x in ('python3', 'ansible-playbook', 'ansible-vault', 'openssl', 'docker')},
                      'project_root': str(PROJECT_ROOT)}
        elif args.command == 'catalog':
            result = json.loads((PROJECT_ROOT / 'catalog' / 'services.json').read_text())
        elif args.command == 'validate':
            config, bundles = _config_and_bundles(args.config)
            result = {'ok': True, 'environment': config['environment'], 'deployment': config['deployment'],
                      'service_order': service_order(config), 'hosts': sorted(bundles),
                      'endpoints': [entry for b in bundles.values() for entry in b.get('endpoints', [])]}
        elif args.command == 'plan':
            plan_path, payload = create_plan(args.config, _store(args))
            result = {'ok': True, 'plan': str(plan_path), 'run_id': payload['run_id'],
                      'changes': payload['changes'], 'warnings': payload['warnings']}
        elif args.command == 'apply':
            result = _apply(args)
        elif args.command in {'preflight', 'status', 'logs'}:
            result = _read_config_operation(args, args.command)
        elif args.command == 'stop':
            if not args.yes:
                raise ValueError('Stop dibatalkan: ulangi dengan --yes setelah memastikan tidak ada consumer aktif.')
            stop_config = load_config(args.config)
            _assert_stop_safe(stop_config, args.service)
            result = _read_config_operation(args, 'stop')
        elif args.command == 'backup':
            args.service = [args.service]
            args.backup = {'id': args.backup_id, 'destination': args.destination, 'recipient': args.recipient}
            result = _read_config_operation(args, 'backup')
        elif args.command == 'restore':
            args.service = [args.service]
            args.backup = {'archive': args.archive, 'identity_file': args.identity_file}
            result = _read_config_operation(args, 'restore')
        elif args.command == 'secrets-init':
            config = load_config(args.config)
            result = initialize_secrets(config, args.vault_password_file)
        else:
            from .wizard import configure
            output = safe_local(args.output)
            if output.exists() and not args.force:
                raise ValueError('File konfigurasi sudah ada; gunakan --force setelah meninjau isinya.')
            config = configure(load_config(output) if output.exists() else None)
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            output.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            output.chmod(0o600)
            result = {'ok': True, 'config': str(output), 'next': 'Jalankan validate, lalu secrets-init dan plan.'}
        _json(result)
        return 0 if result.get('ok', True) else 1
    except KeyboardInterrupt:
        print('Dibatalkan.', file=sys.stderr)
        return 130
    except (ValueError, OSError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
