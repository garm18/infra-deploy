import json
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dynamic_deployment.preflight import local_preflight


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = self.root / 'key'
        self.key.write_text('test-key')
        self.key.chmod(0o600)
        self.config = {'environment': 'development', 'hosts': {'one': {'private_key_file': str(self.key)}},
                       'services': [{'id': 'db', 'kind': 'postgres', 'image': 'postgres:16@sha256:' + hashlib.sha256(b'test-only').hexdigest(),
                                     'config': {}, 'enabled': True}]}

    def test_missing_asset_and_unsafe_key_permissions(self):
        bundles = {'one': {'asset_files': {'a': str(self.root / 'missing')}}}
        with self.assertRaisesRegex(ValueError, 'Asset'):
            local_preflight(self.config, bundles)
        self.key.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'SSH'):
            local_preflight(self.config, {'one': {'asset_files': {}}})

    def test_minio_requires_real_evidence(self):
        self.config['services'][0]['kind'] = 'minio'
        with self.assertRaisesRegex(ValueError, 'evidence'):
            local_preflight(self.config, {'one': {'asset_files': {}}})

    def test_production_evidence_must_be_current_and_verified(self):
        self.config['environment'] = 'production'
        evidence = self.root / 'evidence.json'
        data = {'approved_by': 'test-operator', 'approved_images': [self.config['services'][0]['image']],
                'expires_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                'checks': {'runtime_verified': True, 'network_verified': True, 'restore_verified': True}}
        evidence.write_text(json.dumps(data))
        self.config['production'] = {'release_evidence_file': str(evidence), 'restore_evidence_file': str(evidence)}
        local_preflight(self.config, {'one': {'asset_files': {}}})
        data['checks']['restore_verified'] = False
        evidence.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'restore_verified'):
            local_preflight(self.config, {'one': {'asset_files': {}}})
