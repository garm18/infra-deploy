import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_guard import guard
import test_prepare


class OperationTests(unittest.TestCase):
    def payload(self):
        return {**test_prepare.PrepareTests().payload(), 'environment': 'development', 'deployment': 'demo',
                'services': [{'id': 'db', 'kind': 'postgres', 'image': 'postgres:pinned'}]}

    def test_successful_prepare_owns_files_and_preserves_marker(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, data = Path(root) / 'runtime', Path(root) / 'data'
            with patch.object(guard, 'context', return_value=(runtime, data)), patch.object(guard, 'run') as run, patch.object(guard.os, 'chown') as chown, patch.object(guard.os, 'fchown'):
                guard.prepare(self.payload())
                guard.prepare(self.payload())
            self.assertEqual((runtime / 'files/db/start.sh').read_text(), 'echo ready')
            self.assertEqual((runtime / 'secrets/db/password').stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((data / '.managed.json').read_text())['services']['db']['kind'], 'postgres')
            chown.assert_called_with(data / 'db/data', 999, 999)
            self.assertEqual(run.call_count, 2)

    def test_existing_data_engine_change_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            identity = guard.data_identity(self.payload())
            (data / '.managed.json').write_text(json.dumps(identity))
            changed = self.payload()
            changed['services'][0]['image'] = 'postgres:other'
            with self.assertRaises(ValueError):
                guard.check_data_identity(changed, data)

    def test_stop_only_previous_services(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = Path(root)
            (runtime / 'compose.json').write_text(json.dumps({'services': {'old': {}, 'db': {}}}))
            with patch.object(guard, 'compose') as command:
                guard.stop_removed({**self.payload(), 'removed_services': ['old']}, runtime)
                command.assert_called_once()
                self.assertIn('old', command.call_args.args[1])
            for removed in (['db'], ['unknown'], ['../escape']):
                with self.assertRaises(ValueError):
                    guard.stop_removed({**self.payload(), 'removed_services': removed}, runtime)

    def test_report_does_not_accept_missing_or_unhealthy_service(self):
        for rows, expected in [([], False), ([{'Service':'db','State':'running','Health':'unhealthy'}], False), ([{'Service':'db','State':'running','Health':'healthy'}], True)]:
            with patch.object(guard, 'compose', return_value=SimpleNamespace(stdout=json.dumps(rows).encode())):
                self.assertEqual(guard.report(self.payload())['healthy'], expected)

    def test_logs_redact_known_secret(self):
        with patch.object(guard, 'compose', return_value=SimpleNamespace(stdout=b'failed password=new')):
            result = guard.report({**self.payload(), 'operation': 'logs'})
        self.assertNotIn('new', result['logs'])

    def test_firewall_provider_is_required_and_never_shell(self):
        payload = self.payload()
        payload['host'] = {}
        payload['bundle']['compose']['services']['db']['ports'] = [{'published': '5432'}]
        with self.assertRaises(ValueError):
            guard.check_firewall(payload)
        with tempfile.TemporaryDirectory() as root:
            validator = Path(root) / 'firewall'
            validator.write_text('test')
            validator.chmod(0o700)
            payload['host']['firewall_check'] = str(validator)
            with patch.object(guard, 'secure_path', return_value=validator), patch.object(guard, 'run') as run:
                guard.check_firewall(payload)
            self.assertEqual(run.call_args.args[0], [str(validator), '--check'])

    def test_preflight_supported_host_and_mount(self):
        payload = self.payload()
        payload['host'] = {'expected_mount': '/srv'}
        with patch.object(guard, 'context', return_value=(Path('/opt/dd'), Path('/srv/dd'))), patch.object(guard, 'secure_path', side_effect=lambda value, **kwargs: Path(value)), patch.object(Path, 'read_text', return_value='ID=ubuntu\nVERSION_ID="24.04"'), patch.object(guard.os, 'uname', return_value=SimpleNamespace(machine='x86_64')), patch.object(guard.os, 'geteuid', return_value=0), patch.object(guard.os.path, 'ismount', return_value=True), patch.object(guard.shutil, 'disk_usage', return_value=SimpleNamespace(free=4*1024**3)), patch.object(guard.shutil, 'which', return_value='/usr/bin/docker'), patch.object(guard, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'2.24.0')), patch.object(guard, 'check_firewall'), patch.object(guard, 'check_ports'):
            self.assertFalse(guard.preflight(payload)['bootstrap_required'])
            with patch.object(guard.os.path, 'ismount', return_value=False):
                with self.assertRaises(ValueError):
                    guard.preflight(payload)

    def test_run_hides_command_stderr(self):
        with patch.object(guard.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr=b'secret')):
            with self.assertRaises(RuntimeError) as error:
                guard.run(['docker', 'test'])
        self.assertNotIn('secret', str(error.exception))
