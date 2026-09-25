import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('guard', Path(__file__).parents[1] / 'files' / 'guard.py')
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def test_reject_traversal(self):
        for value in ('../escape', '/etc/passwd', 'a/../../b', '.'):
            with self.assertRaises(ValueError):
                guard.child(Path('/opt/demo'), value)

    def test_reject_symlink_ancestor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'link').symlink_to('/tmp', target_is_directory=True)
            with self.assertRaises(ValueError):
                guard.secure_path(root / 'link' / 'missing')

    def test_lock_exclusive_and_owned_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'lock'
            guard.acquire(lock, 'run-a')
            with self.assertRaises(FileExistsError):
                guard.acquire(lock, 'run-b')
            with self.assertRaises(ValueError):
                guard.release(lock, 'run-b')
            self.assertTrue(lock.exists())
            guard.release(lock, 'run-a')
            self.assertFalse(lock.exists())

    def test_secret_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'secret'
            guard.write_protected(target, b'first', immutable=True)
            guard.write_protected(target, b'first', immutable=True)
            with self.assertRaises(ValueError):
                guard.write_protected(target, b'second', immutable=True)
            self.assertEqual(target.read_bytes(), b'first')

    def test_redaction(self):
        self.assertEqual(guard.redact('password=abc123', {'p':'abc123'}), 'password=[REDACTED]')


if __name__ == '__main__':
    unittest.main()
