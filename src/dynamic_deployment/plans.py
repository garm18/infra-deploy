"""Reproducible signed plans bind configuration, assets and rendering code."""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .state import safe_local


def _load_config(path):
    from .config import load_config
    return load_config(path)


def _render_all(config):
    from .render import render_all
    return render_all(config)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def asset_fingerprints(config, bundles):
    paths = {source for bundle in bundles.values() for source in bundle.get('asset_files', {}).values()}
    if config.get('secrets_file'):
        paths.add(config['secrets_file'])
    for key in ('release_evidence_file', 'restore_evidence_file'):
        if config.get('production', {}).get(key):
            paths.add(config['production'][key])
    for service in config['services']:
        if service.get('config', {}).get('release_evidence_file'):
            paths.add(service['config']['release_evidence_file'])
    result = {}
    for name in sorted(paths):
        path = safe_local(name)
        if not path.is_file():
            result[str(path)] = 'missing'
        elif path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError(f'Asset melebihi 16 MiB: {path}')
        else:
            result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _code_fingerprint():
    project = Path(__file__).resolve().parents[2]
    files = sorted((project / 'src' / 'dynamic_deployment').glob('*.py'))
    files += sorted((project / 'ansible').rglob('*.yml'))
    files += sorted((project / 'ansible' / 'files').glob('*.py'))
    return fingerprint({str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def _changes(config, previous):
    old = {s['id']: s for s in previous.get('services', []) if s.get('enabled', True)}
    new = {s['id']: s for s in config['services'] if s.get('enabled', True)}
    result = []
    for name, service in sorted(new.items()):
        action = 'create' if name not in old else ('unchanged' if service == old[name] else 'update')
        result.append({'service': name, 'host': service['host'], 'action': action})
    result.extend({'service': name, 'host': service['host'], 'action': 'stop-preserve-data'}
                  for name, service in sorted(old.items()) if name not in new)
    return result


def create_plan(config_path, store):
    path = safe_local(config_path)
    config = _load_config(path)
    bundles = _render_all(config)
    current = store.read_json(f"deployments/{config['environment']}/{config['deployment']}.json", {})
    assets = asset_fingerprints(config, bundles)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12]
    payload = {
        'schema_version': 1, 'run_id': run_id, 'created_at': datetime.now(timezone.utc).isoformat(),
        'environment': config['environment'], 'deployment': config['deployment'],
        'config_path': str(path), 'config_hash': fingerprint(config),
        'render_hash': fingerprint(bundles), 'assets': assets,
        'code_hash': _code_fingerprint(), 'previous_hash': fingerprint(current),
        'changes': _changes(config, current.get('config', {})),
        'hosts': sorted(config['hosts']), 'remote_preflight': 'pending',
        'endpoints': [item for bundle in bundles.values() for item in bundle.get('endpoints', [])],
        'warnings': [f'Asset belum tersedia: {name}' for name, digest in assets.items() if digest == 'missing']
                    + ['Plan lokal bukan bukti kesehatan server. Apply wajib mengulang preflight remote.'],
    }
    signature = hmac.new(store.key(), canonical(payload), hashlib.sha256).hexdigest()
    target = store.write_json(f'plans/{run_id}.json', {'payload': payload, 'signature': signature})
    return target, payload


def verify_plan(path, store, environment, deployment):
    path = safe_local(path)
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Plan tidak ditemukan atau terlalu besar.')
    try:
        envelope = json.loads(path.read_text())
        payload = envelope['payload']
        expected = hmac.new(store.key(), canonical(payload), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, envelope['signature']):
            raise ValueError('Tanda tangan plan tidak valid. Buat plan baru.')
        if payload['environment'] != environment or payload['deployment'] != deployment:
            raise ValueError('Environment/deployment tidak sama dengan target plan.')
        if payload['schema_version'] != 1:
            raise ValueError('Versi plan tidak didukung.')
        config = _load_config(safe_local(payload['config_path']))
        bundles = _render_all(config)
        current = store.read_json(f'deployments/{environment}/{deployment}.json', {})
        checks = (payload['config_hash'] == fingerprint(config),
                  payload['render_hash'] == fingerprint(bundles),
                  payload['assets'] == asset_fingerprints(config, bundles),
                  payload['code_hash'] == _code_fingerprint(),
                  payload['previous_hash'] == fingerprint(current))
        if not all(checks):
            raise ValueError('Konfigurasi, asset, kode, atau state berubah. Jalankan plan kembali.')
        return payload, config, bundles
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Format plan tidak valid.') from exc
