"""Local asset and evidence checks before any remote mutation."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .state import safe_local


def _evidence(filename, images, checks):
    if not filename:
        raise ValueError('release evidence diperlukan sebelum deployment ini dapat diterapkan.')
    path = safe_local(filename)
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('Evidence terlalu besar.')
        data = json.loads(path.read_text())
        expiry = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError('Release evidence kedaluwarsa atau tanpa timezone.')
        if not isinstance(data.get('approved_by'), str) or not data['approved_by'].strip():
            raise ValueError('Evidence harus mencatat pemilik penerimaan.')
        if not isinstance(data.get('approved_images'), list) or not set(images) <= set(data['approved_images']):
            raise ValueError('Digest image belum diterima pada evidence.')
        for check in checks:
            if data.get('checks', {}).get(check) is not True:
                raise ValueError(f'Release evidence belum membuktikan {check}.')
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('File release evidence hilang atau formatnya tidak valid.') from exc


def _openssl(args):
    try:
        result = subprocess.run(['openssl', *args], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('OpenSSL diperlukan untuk memvalidasi TLS asset.') from exc
    if result.returncode:
        raise ValueError('Validasi sertifikat/key TLS gagal; periksa nama, masa berlaku, dan pasangan key.')
    return result.stdout


def _tls(config):
    for service in config['services']:
        if not service.get('enabled', True):
            continue
        cfg = service.get('config', {})
        if not cfg.get('tls_cert'):
            continue
        cert, key = str(safe_local(cfg['tls_cert'])), str(safe_local(cfg['tls_key']))
        _openssl(['x509', '-in', cert, '-noout', '-checkend', '86400'])
        cert_public = _openssl(['x509', '-in', cert, '-pubkey', '-noout'])
        key_public = _openssl(['pkey', '-in', key, '-pubout', '-passin', 'pass:'])
        if cert_public.strip() != key_public.strip():
            raise ValueError('Sertifikat dan private key bukan pasangan yang sama.')
        domains = {cfg[name] for name in ('domain', 's3_domain', 'console_domain', 'server_name') if cfg.get(name)}
        domains.update(route['domain'] for route in cfg.get('routes', []))
        for domain in sorted(domains):
            _openssl(['x509', '-in', cert, '-noout', '-checkhost', domain])
        if cfg.get('tls_ca'):
            _openssl(['verify', '-CAfile', str(safe_local(cfg['tls_ca'])), cert])


def local_preflight(config, bundles):
    for name, host in config['hosts'].items():
        if host.get('connection', 'ssh-key') == 'ssh-key':
            key = safe_local(host['private_key_file'])
            if not key.is_file() or key.stat().st_mode & 0o077:
                raise ValueError(f'SSH private key untuk {name} harus tersedia dan berizin 0600.')
    for bundle in bundles.values():
        for source in bundle.get('asset_files', {}).values():
            path = safe_local(source)
            if not path.is_file() or not 0 < path.stat().st_size <= 16 * 1024 * 1024:
                raise ValueError(f'Asset hilang, kosong, atau terlalu besar: {path}')
    images = [s['image'] for s in config['services'] if s.get('enabled', True)]
    for image in images:
        digest = image.rsplit('sha256:', 1)[-1]
        if len(set(digest)) < 4:
            raise ValueError('Digest fixture/placeholder tidak boleh diterapkan pada server.')
    _tls(config)
    for service in config['services']:
        if service.get('enabled', True) and service['kind'] == 'minio':
            _evidence(service.get('config', {}).get('release_evidence_file'), [service['image']],
                      ['runtime_verified', 'network_verified', 'minio_gui_verified', 'minio_s3_verified'])
    if config['environment'] == 'production':
        production = config.get('production', {})
        _evidence(production.get('release_evidence_file'), images, ['runtime_verified', 'network_verified'])
        _evidence(production.get('restore_evidence_file'), images, ['restore_verified'])
    return {'ok': True, 'checks': ['private-assets', 'image-references', 'tls', 'required-release-evidence']}
