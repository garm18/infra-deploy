import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import os
import io
from contextlib import redirect_stdout, redirect_stderr

SPEC = importlib.util.spec_from_file_location('preflight', Path(__file__).resolve().parents[1] / 'scripts/preflight.py')
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)
# Tests must also run from a read-only source checkout.
TEMP_ROOT = None
TEST_DIRECTORY = Path(__file__).resolve().parent

class PreflightTests(unittest.TestCase):
    def test_secrets(self):
        for value in ('', 'short', 'CHANGE_ME_123456789', 'your_password_here', 'minioadmin'):
            self.assertFalse(preflight.valid_secret(value))
        self.assertTrue(preflight.valid_secret('8acb5802a946df719e15ca78'))

    def test_dotenv(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / '.env'
            path.write_text("PASSWORD='abc # xyz'\nNAME=service # comment\nDOUBLE=\"hello world\"\n")
            env = preflight.read_env(path, {'NAME': 'override'})
            self.assertEqual(env['PASSWORD'], 'abc # xyz')
            self.assertEqual(env['NAME'], 'override')
            self.assertEqual(env['DOUBLE'], 'hello world')

    def test_unsupported_dotenv_never_leaks(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / '.env'
            path.write_text('PASSWORD="${SUPER_SECRET}"\n')
            with self.assertRaises(ValueError) as caught:
                preflight.read_env(path, {})
            self.assertNotIn('SUPER_SECRET', str(caught.exception))

    def test_minio_requires_existing_data_directory(self):
        errors = preflight.minio_assets({'MINIO_DATA_DIR': '/nonexistent/minio'})
        self.assertTrue(any('MINIO_DATA_DIR' in error for error in errors))

    def test_minio_valid_assets(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            self.assertEqual(preflight.minio_assets({
                'MINIO_DATA_DIR': directory,
            }), [])

    def test_missing_compose_executable(self):
        result = preflight.compose_check(TEST_DIRECTORY, {'COMPOSE_BIN': '/nonexistent/compose'}, 'production')
        self.assertIn('absolute executable', result)

    def test_compose_errors_do_not_leak_subprocess_secrets(self):
        with patch.object(preflight.shutil, 'which', return_value='/usr/bin/docker'), patch.object(preflight.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stdout='secret-value', stderr='secret-value')):
            result = preflight.compose_check(TEST_DIRECTORY, {}, 'production')
        self.assertNotIn('secret-value', result)
        self.assertIn('failed', result)

    def test_redis_rejects_inputs_before_writing_config(self):
        script = Path(__file__).absolute().parents[1] / 'redis/start-redis.sh'
        for override in ({'REDIS_PASSWORD': ''}, {'REDIS_PASSWORD': 'secret\ninjection'}, {'REDIS_PASSWORD': 'secret\rinjection'}, {'REDIS_MAXMEMORY': '256mb\nrequirepass hacked'}, {'REDIS_MAXMEMORY_POLICY': 'invalid'}):
            env = {**os.environ, 'REDIS_PASSWORD': 'long-enough-test-password', **override}
            result = subprocess.run(['sh', str(script)], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('injection', result.stderr)
            self.assertNotIn('hacked', result.stderr)

    def test_cli_static_success_and_missing_files(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(preflight.main(['--static']), 0)
        self.assertIn('no runtime validation', output.getvalue())
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, patch.object(preflight, 'ROOT', Path(directory)), redirect_stdout(io.StringIO()):
            self.assertEqual(preflight.main(['--static', 'redis']), 1)

    def test_cli_deployment_success_and_failures(self):
        with patch.object(preflight, 'read_env', return_value={'REDIS_PASSWORD': 'a-secure-fixture-secret'}), patch.object(preflight, 'compose_check', return_value=None), redirect_stdout(io.StringIO()):
            self.assertEqual(preflight.main(['--mode', 'local', 'redis']), 0)
        output = io.StringIO()
        with patch.object(preflight, 'read_env', return_value={}), patch.object(preflight, 'compose_check', return_value='Compose unavailable'), redirect_stdout(output):
            self.assertEqual(preflight.main(['redis']), 1)
        self.assertIn('REDIS_PASSWORD', output.getvalue())
        with patch.object(preflight, 'read_env', side_effect=ValueError('hidden-secret')), redirect_stdout(output):
            self.assertEqual(preflight.main(['redis']), 1)
        self.assertNotIn('hidden-secret', output.getvalue())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            preflight.main(['unknown-service'])
        self.assertEqual(caught.exception.code, 2)

    def test_mariadb_required_identity_and_production_storage(self):
        errors = preflight.deployment_errors('mariadb', {}, 'production')
        for key in ('MARIADB_ROOT_PASSWORD', 'MARIADB_PASSWORD', 'MARIADB_USER', 'MARIADB_DATABASE'):
            self.assertTrue(any(key in error for error in errors))
        self.assertEqual(preflight.deployment_errors('postgres', {
            'POSTGRES_PASSWORD': 'a-secure-fixture-secret',
        }, 'local'), [])
        self.assertTrue(preflight.deployment_errors('minio', {}, 'local'))

    def test_compose_local_success_and_unavailable(self):
        with patch.object(preflight.shutil, 'which', return_value='/usr/bin/docker'), patch.object(preflight.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertIsNone(preflight.compose_check(TEST_DIRECTORY, {}, 'local'))
            self.assertIn(str(TEST_DIRECTORY / 'docker-compose.local.yml'), run.call_args.args[0])
            self.assertEqual(run.call_args.args[0][-2:], ['config', '--quiet'])
        with patch.object(preflight.shutil, 'which', return_value=None):
            self.assertIn('unavailable', preflight.compose_check(TEST_DIRECTORY, {}, 'production'))
        with patch.object(preflight.shutil, 'which', return_value='/usr/bin/docker'), patch.object(preflight.subprocess, 'run', side_effect=subprocess.TimeoutExpired('docker', 45)):
            self.assertIn('could not complete', preflight.compose_check(TEST_DIRECTORY, {}, 'production'))

    def test_dotenv_invalid_forms_and_empty_data_directory(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / '.env'
            for content in ('invalid secret', "KEY='unterminated", 'KEY=hello world', 'KEY=one\nKEY=two'):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    preflight.read_env(path, {})
            path.write_text('# comment\n\nexport KEY=value\n')
            self.assertEqual(preflight.read_env(path, {}), {'KEY': 'value'})
            path.write_text('')
            self.assertTrue(any('MINIO_DATA_DIR' in error for error in preflight.minio_assets({'MINIO_DATA_DIR': str(path)})))

    def test_bad_directory(self):
        for value in ('relative/data', '/nonexistent/data'):
            self.assertIsNotNone(preflight.directory_error(value, 'DATA_DIR'))

if __name__ == '__main__':
    unittest.main()
