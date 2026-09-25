import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dynamic_deployment.cli import main


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_doctor_and_catalog_do_not_require_server(self):
        self.assertEqual(main(['--state-dir', self.tmp.name, 'doctor']), 0)
        self.assertEqual(main(['--state-dir', self.tmp.name, 'catalog']), 0)

    def test_validate_uses_config_and_render(self):
        with patch('dynamic_deployment.cli._config_and_bundles', return_value=(
                {'environment': 'development', 'deployment': 'demo', 'services': []}, {})), \
             patch('dynamic_deployment.cli.service_order', return_value=[]):
            self.assertEqual(main(['--state-dir', self.tmp.name, 'validate', '/tmp/config.yml']), 0)

    def test_apply_requires_verified_plan_target(self):
        with patch('dynamic_deployment.cli.verify_plan', return_value=({'environment': 'development', 'deployment': 'demo'}, {}, {})):
            self.assertEqual(main(['--state-dir', self.tmp.name, 'apply', '--plan', '/tmp/p', '--environment', 'production', '--deployment', 'demo']), 2)

    def test_plan_returns_path_without_remote_execution(self):
        output = Path(self.tmp.name) / 'signed.json'
        with patch('dynamic_deployment.cli.create_plan', return_value=(output, {'run_id': 'r', 'changes': [], 'warnings': []})):
            self.assertEqual(main(['--state-dir', self.tmp.name, 'plan', '/tmp/config.yml']), 0)

    def test_module_entrypoint_delegates_to_cli(self):
        with patch('dynamic_deployment.cli.main', return_value=0):
            import runpy
            with self.assertRaises(SystemExit) as exit_value:
                runpy.run_module('dynamic_deployment.__main__', run_name='__main__')
        self.assertEqual(exit_value.exception.code, 0)

    def test_stop_backup_and_restore_route_scoped_requests(self):
        with patch('dynamic_deployment.cli.load_config', return_value={'services': []}), \
             patch('dynamic_deployment.cli._read_config_operation', return_value={'ok': True}) as operation:
            self.assertEqual(main(['--state-dir', self.tmp.name, 'stop', '--config', '/tmp/c', '--host', 'one', '--service', 'php', '--yes']), 0)
            self.assertEqual(operation.call_args.args[1], 'stop')
            self.assertEqual(main(['--state-dir', self.tmp.name, 'backup', '--config', '/tmp/c', '--host', 'one', '--service', 'db', '--backup-id', 'run1', '--destination', '/mnt/backups', '--recipient', 'age1abcdefghijklmnopqrst']), 0)
            self.assertEqual(operation.call_args.args[1], 'backup')
            self.assertEqual(operation.call_args.args[0].backup['id'], 'run1')
            self.assertEqual(main(['--state-dir', self.tmp.name, 'restore', '--config', '/tmp/c', '--host', 'one', '--service', 'db', '--archive', '/mnt/backups/a.tar.age', '--identity-file', '/root/age.key']), 0)
            self.assertEqual(operation.call_args.args[1], 'restore')

    def test_stop_without_confirmation_is_rejected(self):
        self.assertEqual(main(['--state-dir', self.tmp.name, 'stop', '--config', '/tmp/c', '--host', 'one', '--service', 'php']), 2)

    def test_stop_rejects_active_consumer(self):
        config = {'services': [{'id': 'db', 'enabled': True, 'config': {}},
                               {'id': 'php', 'enabled': True, 'config': {'database_service': 'db'}}]}
        with patch('dynamic_deployment.cli.load_config', return_value=config), \
             patch('dynamic_deployment.cli._read_config_operation') as operation:
            self.assertEqual(main(['--state-dir', self.tmp.name, 'stop', '--config', '/tmp/c', '--host', 'one', '--service', 'db', '--yes']), 2)
            operation.assert_not_called()

    def test_apply_runs_preflight_then_dependency_order_and_saves_state(self):
        config = {'environment': 'development', 'deployment': 'demo', 'services': [
            {'id': 'db', 'kind': 'postgres', 'host': 'one', 'enabled': True},
            {'id': 'php', 'kind': 'laravel-php', 'host': 'one', 'enabled': True}]}
        payload = {'environment': 'development', 'deployment': 'demo', 'run_id': 'run-1', 'created_at': 'now'}
        calls = []
        def operation(_config, _bundles, name, *_args, **kwargs):
            calls.append((name, kwargs.get('selected'), kwargs.get('host')))
            return {'ok': True, 'operation': name}
        with patch('dynamic_deployment.cli.verify_plan', return_value=(payload, config, {'one': {}})), \
             patch('dynamic_deployment.cli.local_preflight'), \
             patch('dynamic_deployment.cli.load_secrets', return_value={'p': 'secret'}), \
             patch('dynamic_deployment.cli.service_order', return_value=['db', 'php']), \
             patch('dynamic_deployment.cli.run_operation', side_effect=operation):
            self.assertEqual(main(['--state-dir', self.tmp.name, 'apply', '--plan', '/tmp/p', '--environment', 'development', '--deployment', 'demo']), 0)
        self.assertEqual(calls, [('preflight', None, None), ('apply', ['db'], 'one'), ('apply', ['php'], 'one')])
        saved = json.loads((Path(self.tmp.name) / 'deployments/development/demo.json').read_text())
        self.assertEqual(saved['run_id'], 'run-1')

    def test_apply_stops_when_remote_preflight_or_data_change_fails(self):
        config = {'environment': 'development', 'deployment': 'demo', 'services': [
            {'id': 'db', 'kind': 'postgres', 'host': 'one', 'enabled': True, 'image': 'new'}]}
        payload = {'environment': 'development', 'deployment': 'demo', 'run_id': 'run-1', 'created_at': 'now'}
        with patch('dynamic_deployment.cli.verify_plan', return_value=(payload, config, {})), \
             patch('dynamic_deployment.cli.local_preflight'), patch('dynamic_deployment.cli.load_secrets', return_value={}), \
             patch('dynamic_deployment.cli.service_order', return_value=['db']), \
             patch('dynamic_deployment.cli.run_operation', return_value={'ok': False}):
            self.assertEqual(main(['--state-dir', self.tmp.name, 'apply', '--plan', '/tmp/p', '--environment', 'development', '--deployment', 'demo']), 1)
        state = Path(self.tmp.name) / 'deployments/development/demo.json'
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({'config': {'services': [{'id': 'db', 'kind': 'postgres', 'host': 'one', 'image': 'old', 'enabled': True}]}}))
        with patch('dynamic_deployment.cli.verify_plan', return_value=(payload, config, {})), \
             patch('dynamic_deployment.cli.local_preflight'), patch('dynamic_deployment.cli.load_secrets', return_value={}), \
             patch('dynamic_deployment.cli.service_order', return_value=['db']):
            self.assertEqual(main(['--state-dir', self.tmp.name, 'apply', '--plan', '/tmp/p', '--environment', 'development', '--deployment', 'demo']), 2)
