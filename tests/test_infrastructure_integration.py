"""Check the integration boundary without Docker or remote access."""
import os
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class InfrastructureIntegration(unittest.TestCase):
    def test_make_delegates_selection_without_executing_it(self):
        result = subprocess.run(['make', '-n', 'infra-up', 'ENV=staging', 'SERVICES=redis'],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('scripts/manage.py up', result.stdout)

    def test_unknown_service_fails_before_docker(self):
        result = subprocess.run(['python3', 'infrastructure/scripts/manage.py', 'up'],
                                cwd=ROOT, env={**os.environ, 'ENV': 'staging', 'SERVICES': '../postgres'},
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('known service directories', result.stderr)

    def test_ansible_uses_shared_manager_without_secret_copy(self):
        play = yaml.safe_load((ROOT / 'ansible/infrastructure.yml').read_text())[0]
        task = next(t for t in play['tasks'] if 'ansible.builtin.command' in t)
        self.assertIn('/scripts/manage.py', task['ansible.builtin.command']['argv'][1])
        self.assertTrue(task['no_log'])
        self.assertEqual(task['when'], 'not ansible_check_mode')
        self.assertFalse(any('ansible.builtin.copy' in t for t in play['tasks']))
