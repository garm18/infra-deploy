import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_guard import guard


class PrepareTests(unittest.TestCase):
    def payload(self):
        return {'operation': 'apply', 'bundle': {'compose': {'services': {'db': {'user': '999:999'}}},
                'files': {'files/db/start.sh': 'echo ready'}, 'directories': ['db/data'],
                'secret_files': {'secrets/db/password': 'password'}, 'asset_files': {}},
                'secrets': {'password': 'new'}}

    def test_unmanaged_data_never_adopted(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, data = Path(root) / 'runtime', Path(root) / 'data'
            (data / 'db/data').mkdir(parents=True)
            (data / 'db/data/existing').write_text('legacy')
            with patch.object(guard, 'context', return_value=(runtime, data)):
                with self.assertRaises(ValueError):
                    guard.prepare(self.payload())
            self.assertFalse(runtime.exists())

    def test_timestamp_run_lock(self):
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / 'lock'
            guard.acquire(lock, '20260912T130001Z-ab12')
            guard.release(lock, '20260912T130001Z-ab12')
        with self.assertRaises(ValueError):
            guard.acquire(Path('/tmp/unused'), '../../x')

    def test_owner_uses_rendered_user(self):
        self.assertEqual(guard.owner_for(self.payload(), 'files/db/start.sh'), (999, 999))

    def test_missing_secret_has_no_mutations(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, data = Path(root) / 'runtime', Path(root) / 'data'
            payload = self.payload()
            payload['secrets'] = {}
            with patch.object(guard, 'context', return_value=(runtime, data)):
                with self.assertRaises(ValueError):
                    guard.prepare(payload)
            self.assertFalse(runtime.exists())
            self.assertFalse(data.exists())

    def test_invalid_compose_preserves_active_files(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, data = Path(root) / 'runtime', Path(root) / 'data'
            runtime.mkdir()
            (runtime / 'compose.json').write_text('old')
            with patch.object(guard, 'context', return_value=(runtime, data)), patch.object(guard, 'run', side_effect=RuntimeError('invalid')):
                with self.assertRaises(RuntimeError):
                    guard.prepare(self.payload())
            self.assertEqual((runtime / 'compose.json').read_text(), 'old')
            self.assertFalse((runtime / 'files').exists())
            self.assertFalse(data.exists())

    def test_secret_conflict_precedes_any_rewrite(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, data = Path(root) / 'runtime', Path(root) / 'data'
            (runtime / 'secrets/db').mkdir(parents=True)
            (runtime / 'secrets/db/password').write_text('old')
            with patch.object(guard, 'context', return_value=(runtime, data)):
                with self.assertRaises(ValueError):
                    guard.prepare(self.payload())
            self.assertFalse((runtime / 'files').exists())
            self.assertFalse(data.exists())
