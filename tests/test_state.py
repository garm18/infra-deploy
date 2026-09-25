import tempfile
import unittest
from pathlib import Path

from dynamic_deployment.state import StateStore


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = StateStore(Path(self.tmp.name) / "state")

    def test_roundtrip_and_private_permissions(self):
        self.store.write_json("runs/one.json", {"status": "failed"})
        self.assertEqual(self.store.read_json("runs/one.json"), {"status": "failed"})
        self.assertEqual((self.store.root / "runs/one.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.key(), self.store.key())

    def test_traversal_and_symlink_rejected(self):
        for path in ("../escape", "/tmp/escape", "runs/../../escape"):
            with self.assertRaises(ValueError):
                self.store.write_json(path, {})
        (self.store.root / "evil").symlink_to(self.tmp.name)
        with self.assertRaises(ValueError):
            self.store.write_json("evil/escape", {})

    def test_lock_rejects_concurrent_operation(self):
        with self.store.lock("development-demo"):
            with self.assertRaises(RuntimeError):
                with self.store.lock("development-demo"):
                    self.fail("A second owner acquired the lock")
        with self.store.lock("development-demo"):
            pass

    def test_key_symlink_rejected(self):
        other = Path(self.tmp.name) / "other"
        other.write_text("x" * 32)
        (self.store.root / "signing.key").symlink_to(other)
        with self.assertRaises(ValueError):
            self.store.key()
