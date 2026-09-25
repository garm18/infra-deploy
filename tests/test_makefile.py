"""Exercise the public Make targets without contacting deployment hosts."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MakefileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='make wrapper ')
        self.addCleanup(self.directory.cleanup)
        self.capture = Path(self.directory.name) / 'arguments.json'
        self.calls = Path(self.directory.name) / 'calls.jsonl'
        self.python = Path(self.directory.name) / 'python stub'
        self.python.write_text(
            '#!/usr/bin/env python3\nimport json, os, sys\n'
            'from pathlib import Path\n'
            'Path(os.environ["CAPTURE"]).write_text(json.dumps(sys.argv[1:]))\n'
            'with Path(os.environ["CALLS"]).open("a") as calls:\n'
            '    calls.write(json.dumps(sys.argv[1:]) + "\\n")\n'
            'sys.exit(int(os.environ.get("STUB_EXIT", "0")))\n'
        )
        self.python.chmod(0o755)

    def run_make(self, *arguments, **variables):
        env = {**os.environ, 'DD_PYTHON': str(self.python), 'CAPTURE': str(self.capture),
               'CALLS': str(self.calls),
               **variables}
        return subprocess.run(['make', '--no-print-directory', *arguments], cwd=ROOT,
                              env=env, text=True, capture_output=True, check=False)

    def assert_arguments(self, expected):
        self.assertEqual(json.loads(self.capture.read_text()), ['-m', 'dynamic_deployment', *expected])

    def test_default_is_help_without_running_cli(self):
        result = self.run_make()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('make wizard', result.stdout)
        self.assertFalse(self.capture.exists())

    def test_config_commands_preserve_paths_and_shell_characters(self):
        config = 'configs/my app; echo unexpected.yml'
        for target, args in [('wizard', ['--output']), ('validate', []), ('plan', []),
                             ('secrets-init', ['--config'])]:
            with self.subTest(target=target):
                result = self.run_make(target, CONFIG=config)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_arguments([target, *args, config])

    def test_apply_requires_explicit_target_and_forwards_optional_paths(self):
        result = self.run_make('apply', PLAN='plans/my plan.json', ENVIRONMENT='staging',
                               DEPLOYMENT='demo', STATE_DIR='state directory',
                               VAULT_PASSWORD_FILE='private/password file')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_arguments(['--state-dir', 'state directory', 'apply', '--plan',
                               'plans/my plan.json', '--environment', 'staging', '--deployment',
                               'demo', '--vault-password-file', 'private/password file'])

    def test_operations_with_optional_selection(self):
        for target in ('preflight', 'status', 'logs'):
            with self.subTest(target=target):
                result = self.run_make(target, CONFIG='config.yml', HOST='app', SERVICE='web')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_arguments([target, '--config', 'config.yml', '--host', 'app', '--service', 'web'])
                result = self.run_make(target, CONFIG='config.yml')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_arguments([target, '--config', 'config.yml'])

    def test_missing_values_prevent_execution(self):
        for target, variables, missing in [
            ('wizard', {}, 'CONFIG'), ('validate', {}, 'CONFIG'), ('plan', {}, 'CONFIG'),
            ('secrets-init', {}, 'CONFIG'), ('status', {}, 'CONFIG'),
            ('apply', {}, 'PLAN'), ('apply', {'PLAN': 'p'}, 'ENVIRONMENT'),
            ('apply', {'PLAN': 'p', 'ENVIRONMENT': 'test'}, 'DEPLOYMENT'),
            ('stop', {'CONFIG': 'c'}, 'HOST'),
            ('stop', {'CONFIG': 'c', 'HOST': 'h'}, 'SERVICE'),
            ('stop', {'CONFIG': 'c', 'HOST': 'h', 'SERVICE': 's'}, 'CONFIRM=yes'),
        ]:
            with self.subTest(target=target, missing=missing):
                result = self.run_make(target, **variables)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(missing, result.stderr)
                self.assertFalse(self.capture.exists())

    def test_confirmed_stop(self):
        result = self.run_make('stop', CONFIG='c', HOST='h', SERVICE='s', CONFIRM='yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_arguments(['stop', '--config', 'c', '--host', 'h', '--service', 's', '--yes'])

    def test_failure_is_not_swallowed(self):
        result = self.run_make('doctor', STUB_EXIT='17')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('17', result.stderr)

    def test_catalog(self):
        result = self.run_make('catalog')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_arguments(['catalog'])

    def test_command_line_assignment_preserves_spaces(self):
        result = self.run_make('validate', 'CONFIG=configs/my app.yml')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_arguments(['validate', 'configs/my app.yml'])

    def test_local_verification_targets(self):
        for target, expected in [
            ('test', ['-m', 'unittest', 'discover', '-s', 'ansible/tests', '-v']),
            ('coverage', ['scripts/measure_coverage.py', '--minimum', '80']),
        ]:
            with self.subTest(target=target):
                result = self.run_make(target)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(self.capture.read_text()), expected)

    def test_test_runs_both_local_suites(self):
        result = self.run_make('test')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([json.loads(line) for line in self.calls.read_text().splitlines()], [
            ['-m', 'unittest', 'discover', '-s', 'tests', '-v'],
            ['-m', 'unittest', 'discover', '-s', 'ansible/tests', '-v'],
        ])

    def test_test_stops_when_first_suite_fails(self):
        result = self.run_make('test', STUB_EXIT='17')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
