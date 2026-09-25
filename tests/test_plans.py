import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dynamic_deployment.plans import _code_fingerprint, create_plan, fingerprint, verify_plan
from dynamic_deployment.state import StateStore


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'deployment.json'
        self.config = {'environment': 'development', 'deployment': 'demo', 'hosts': {'one': {}},
                       'services': [{'id': 'db', 'kind': 'postgres', 'host': 'one', 'image': 'image'}]}
        self.source.write_text(json.dumps(self.config))
        self.store = StateStore(self.root / 'state')
        self.bundle = {'one': {'compose': {'services': {}}, 'files': {}, 'asset_files': {}, 'endpoints': []}}
        self.addCleanup(patch.stopall)
        patch('dynamic_deployment.plans._load_config', side_effect=lambda p: json.loads(Path(p).read_text())).start()
        patch('dynamic_deployment.plans._render_all', return_value=self.bundle).start()

    def test_sign_and_verify(self):
        path, payload = create_plan(self.source, self.store)
        verified, config, bundles = verify_plan(path, self.store, 'development', 'demo')
        self.assertEqual(verified['run_id'], payload['run_id'])
        self.assertEqual(config, self.config)
        self.assertEqual(bundles, self.bundle)

    def test_tamper_and_wrong_target_rejected(self):
        path, _ = create_plan(self.source, self.store)
        with self.assertRaises(ValueError):
            verify_plan(path, self.store, 'production', 'demo')
        content = json.loads(path.read_text())
        content['payload']['deployment'] = 'evil'
        path.write_text(json.dumps(content))
        with self.assertRaises(ValueError):
            verify_plan(path, self.store, 'development', 'evil')

    def test_changed_source_or_asset_requires_new_plan(self):
        asset = self.root / 'certificate.pem'
        asset.write_text('certificate-one')
        self.bundle['one']['asset_files'] = {'assets/cert': str(asset)}
        path, _ = create_plan(self.source, self.store)
        asset.write_text('certificate-two')
        with self.assertRaisesRegex(ValueError, 'berubah'):
            verify_plan(path, self.store, 'development', 'demo')
        path, _ = create_plan(self.source, self.store)
        self.config['services'][0]['image'] = 'new-image'
        self.source.write_text(json.dumps(self.config))
        with self.assertRaises(ValueError):
            verify_plan(path, self.store, 'development', 'demo')

    def test_code_fingerprint_covers_controller_and_ansible_sources(self):
        project = Path(__file__).resolve().parents[1]
        files = sorted((project / 'src' / 'dynamic_deployment').glob('*.py'))
        files += sorted((project / 'ansible').rglob('*.yml'))
        files += sorted((project / 'ansible' / 'files').glob('*.py'))
        expected = fingerprint({str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
        self.assertGreater(len(files), 10)
        self.assertNotEqual(expected, fingerprint({}))
        self.assertEqual(_code_fingerprint(), expected)

    def test_removed_service_is_stop_not_delete(self):
        self.store.write_json('deployments/development/demo.json',
                              {'config': {**self.config, 'services': self.config['services'] + [{'id': 'old', 'host': 'one'}]}})
        _, plan = create_plan(self.source, self.store)
        self.assertIn({'service': 'old', 'host': 'one', 'action': 'stop-preserve-data'}, plan['changes'])
