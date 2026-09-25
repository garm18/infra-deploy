import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dynamic_deployment import wizard


class WizardHelperTests(unittest.TestCase):
    def test_input_helpers_and_image_resolution(self):
        with patch('builtins.input', return_value=''):
            self.assertEqual(wizard.ask('name', 'default'), 'default')
        with patch('builtins.input', return_value='batal'):
            with self.assertRaises(KeyboardInterrupt):
                wizard.ask('name')
        with patch('builtins.input', return_value='ya'):
            self.assertTrue(wizard.yes('continue'))
        with patch('dynamic_deployment.wizard.ask', return_value='postgres:16.8'), \
             patch('dynamic_deployment.wizard.resolve_image', return_value='postgres:16.8@sha256:' + 'a' * 64):
            self.assertIn('@sha256:', wizard._image('postgres'))

    def test_reference_and_database_profiles(self):
        services = [{'id': 'db', 'kind': 'postgres', 'host': 'one', 'enabled': True},
                    {'id': 'redis', 'kind': 'redis', 'host': 'two', 'enabled': True}]
        with patch('dynamic_deployment.wizard.ask', return_value='db'):
            self.assertEqual(wizard._reference(services, 'one', {'postgres'}, 'DB', True), 'db')
        answers = iter(['application', 'appuser'])
        with patch('dynamic_deployment.wizard.ask', side_effect=lambda *_: next(answers)):
            item = wizard._configure({'id': 'pg-one', 'kind': 'postgres', 'host': 'one', 'image': 'x'}, services)
        self.assertEqual(item['config']['database'], 'application')
        self.assertIn('root_password', item['secrets'])

    def test_redis_phpmyadmin_and_worker_profiles(self):
        services = [{'id': 'db', 'kind': 'mariadb', 'host': 'one', 'enabled': True},
                    {'id': 'php', 'kind': 'laravel-php', 'host': 'one', 'enabled': True,
                     'image': 'app:1@sha256:' + 'a' * 64,
                     'config': {'release_id': 'r1', 'session_driver': 'file'}, 'secrets': {'app_key': 'KEY'}}]
        with patch('dynamic_deployment.wizard.ask', return_value='128mb'):
            redis = wizard._configure({'id': 'redis-one', 'kind': 'redis', 'host': 'one', 'image': 'x'}, services)
        self.assertEqual(redis['config']['maxmemory'], '128mb')
        with patch('dynamic_deployment.wizard.ask', return_value='db'):
            admin = wizard._configure({'id': 'admin', 'kind': 'phpmyadmin', 'host': 'one', 'image': 'x'}, services)
        self.assertEqual(admin['config']['database_service'], 'db')
        with patch('dynamic_deployment.wizard.ask', return_value='critical'):
            worker = wizard._configure({'id': 'worker', 'kind': 'laravel-worker', 'host': 'one', 'image': ''}, services)
        self.assertEqual(worker['image'], services[1]['image'])
        self.assertEqual(worker['config']['queue'], 'critical')

    def test_laravel_php_with_dependencies(self):
        services = [{'id': 'pg', 'kind': 'postgres', 'host': 'one', 'enabled': True},
                    {'id': 'cache', 'kind': 'redis', 'host': 'one', 'enabled': True},
                    {'id': 's3', 'kind': 'minio', 'host': 'one', 'enabled': True}]
        answers = iter(['release1', '8.3', 'https://app.internal', 'file', 'pg', 'cache', 's3', 'uploads'])
        with patch('dynamic_deployment.wizard.ask', side_effect=lambda *_: next(answers)):
            result = wizard._configure({'id': 'php', 'kind': 'laravel-php', 'host': 'one', 'image': 'app'}, services)
        self.assertEqual(result['config']['storage_service'], 's3')
        self.assertIn('storage_secret_key', result['secrets'])

    def test_file_path_expands_absolute(self):
        with tempfile.TemporaryDirectory() as directory, patch('dynamic_deployment.wizard.ask', return_value=directory):
            self.assertEqual(wizard.file_path('test'), str(Path(directory).absolute()))

    def test_minio_and_web_profiles_collect_required_assets(self):
        paths = iter(['/tmp/cert', '/tmp/key', '/tmp/license', '/tmp/evidence'])
        answers = iter(['s3.internal', 'console.internal'])
        with patch('dynamic_deployment.wizard.file_path', side_effect=lambda *_: next(paths)), \
             patch('dynamic_deployment.wizard.ask', side_effect=lambda *_: next(answers)):
            minio = wizard._configure({'id': 's3', 'kind': 'minio', 'host': 'one', 'image': 'x'}, [])
        self.assertEqual(minio['config']['console_domain'], 'console.internal')
        self.assertIn('root_user', minio['secrets'])
        php = {'id': 'php', 'kind': 'laravel-php', 'host': 'one', 'enabled': True,
               'config': {'release_id': 'r1'}}
        paths = iter(['/tmp/cert', '/tmp/key'])
        answers = iter(['php', 'app.internal', 'r1', '8443'])
        with patch('dynamic_deployment.wizard.file_path', side_effect=lambda *_: next(paths)), \
             patch('dynamic_deployment.wizard.ask', side_effect=lambda *_: next(answers)):
            web = wizard._configure({'id': 'web', 'kind': 'laravel-web', 'host': 'one', 'image': 'x'}, [php])
        self.assertEqual(web['config']['php_service'], 'php')
