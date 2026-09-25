import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'scripts/check_release.py'

def module():
    spec = importlib.util.spec_from_file_location('release_tool', PATH)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tool = module()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'evidence.json'
        self.evidence = {'approved_images': ['postgres:16@sha256:' + 'a' * 64],
                         'approved_by': 'release-team', 'expires_at': '2099-01-01T00:00:00+00:00',
                         'checks': {'runtime_verified': True}}

    def validate(self):
        self.path.write_text(json.dumps(self.evidence))
        return self.tool.validate_evidence(self.path, self.evidence.get('approved_images', []), ['runtime_verified'])

    def test_valid_and_missing_image(self):
        self.assertEqual(self.validate(), [])
        self.assertTrue(self.tool.validate_evidence(self.path, ['other:1']))

    def test_expired_naive_or_malformed(self):
        for timestamp in ['2001-01-01T00:00:00Z', '2099-01-01', 'tomorrow', 42]:
            self.evidence['expires_at'] = timestamp
            self.assertTrue(self.validate())

    def test_structural_validation_and_false_checks(self):
        for key, value in [('approved_images', 'image'), ('approved_images', []),
                           ('approved_images', ['postgres:latest']), ('approved_by', ''),
                           ('checks', []), ('checks', {'runtime_verified': 'true'}),
                           ('checks', {'runtime_verified': False})]:
            original = dict(self.evidence)
            self.evidence[key] = value
            with self.subTest(key=key, value=value):
                self.assertTrue(self.validate())
            self.evidence = original

    def test_invalid_json_and_nonobject(self):
        for content in ['{', '[]', '{"checks":{},"checks":{}}']:
            self.path.write_text(content)
            self.assertTrue(self.tool.validate_evidence(self.path, []))
        self.assertTrue(self.tool.validate_evidence(self.path.parent / 'missing', []))

    def test_scanner_missing_or_failing_never_approves(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        image = self.evidence['approved_images'][0]
        with patch.object(self.tool.shutil, 'which', return_value=None):
            self.assertEqual(self.tool.main(['--scan', image]), 2)
        with patch.object(self.tool.shutil, 'which', return_value='/usr/bin/trivy'), \
                patch.object(self.tool.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=1, stdout='', stderr='scanner failed')) as run:
            self.assertEqual(self.tool.scan_image(image, self.path.parent), 1)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-1], image)
            self.assertEqual((self.path.parent / 'scan.log').read_text(), 'scanner failed')
