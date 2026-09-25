import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from dynamic_deployment.executor import run_operation, parse_results


def fixture():
    return {'environment': 'development', 'deployment': 'demo',
            'hosts': {'one': {'address': '10.0.0.2', 'user': 'deploy', 'port': 22,
                              'private_key_file': '/tmp/test-key'}},
            'services': [{'id': 'db', 'host': 'one', 'enabled': True}]}


class ExecutorTests(unittest.TestCase):
    def test_parse_only_expected_markers(self):
        body = {'plays': [{'tasks': [{'hosts': {'one': {'msg': 'DD_RESULT=' + json.dumps(
            {'host': 'one', 'operation': 'status', 'result': {'healthy': True}})}}}]}]}
        self.assertEqual(parse_results(json.dumps(body))[0]['host'], 'one')
        self.assertEqual(parse_results('not-json'), [])

    def test_argv_and_inventory_are_scoped_and_secret_output_redacted(self):
        def run(args, **kwargs):
            self.assertNotIn('shell', kwargs)
            inventory = json.loads(Path(args[args.index('-i') + 1]).read_text())
            self.assertEqual(set(inventory['all']['hosts']), {'one'})
            self.assertIn('StrictHostKeyChecking=yes', inventory['all']['hosts']['one']['ansible_ssh_common_args'])
            variables = json.loads(Path(args[args.index('--extra-vars') + 1][1:]).read_text())
            self.assertEqual(variables['dd_secrets'], {'p': 'very-private'})
            return subprocess.CompletedProcess(args, 0, json.dumps({'msg': 'DD_RESULT=' + json.dumps(
                {'host': 'one', 'operation': 'status', 'result': {'note': 'very-private'}})}), '')
        with patch('dynamic_deployment.executor.subprocess.run', side_effect=run):
            result = run_operation(fixture(), {'one': {}}, 'status', 'run-1', secrets_values={'p': 'very-private'})
        self.assertNotIn('very-private', json.dumps(result))

    def test_nonzero_and_missing_result_never_succeed(self):
        for code in (0, 2):
            with patch('dynamic_deployment.executor.subprocess.run', return_value=subprocess.CompletedProcess([], code, '{}', 'private error')):
                result = run_operation(fixture(), {'one': {}}, 'status', 'run-1')
            self.assertFalse(result['ok'])
            self.assertNotIn('private error', json.dumps(result))

    def test_invalid_operation_or_host_rejected_before_subprocess(self):
        for operation, host in [('purge', None), ('status', 'other')]:
            with patch('dynamic_deployment.executor.subprocess.run') as run:
                with self.assertRaises(ValueError):
                    run_operation(fixture(), {'one': {}}, operation, 'run-1', host=host)
                run.assert_not_called()

    def test_timeout_becomes_unknown_not_success(self):
        with patch('dynamic_deployment.executor.subprocess.run', side_effect=subprocess.TimeoutExpired('ansible', 20)):
            result = run_operation(fixture(), {'one': {}}, 'apply', 'run-1')
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'unknown')

    def test_inventory_supports_local_and_vault_password_ssh(self):
        from dynamic_deployment.executor import _inventory
        config = fixture()
        config['hosts']['one'] = {'connection': 'local', 'address': '127.0.0.1', 'user': 'deploy'}
        local = _inventory(config, ['one'], {})['all']['hosts']['one']
        self.assertEqual(local['ansible_connection'], 'local')
        self.assertNotIn('ansible_ssh_private_key_file', local)
        config['hosts']['one'] = {'connection': 'ssh-password', 'address': '10.0.0.2', 'user': 'deploy',
                                  'ssh_password_ref': 'SSH_PASSWORD'}
        password = _inventory(config, ['one'], {'SSH_PASSWORD': 'not-printed'})['all']['hosts']['one']
        self.assertEqual(password['ansible_password'], 'not-printed')
