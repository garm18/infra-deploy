import copy
import tempfile
import unittest
from pathlib import Path

from dynamic_deployment.config import load_config, validate_config, service_order
from dynamic_deployment.errors import ValidationError


def fixture():
    return {'schema_version': 1, 'environment': 'development', 'deployment': 'demo',
            'hosts': {'db': {'address': '10.0.0.2', 'user': 'deploy',
                             'private_key_file': '/tmp/key', 'expected_mount': '/srv'}},
            'services': [{'id': 'db', 'kind': 'postgres', 'host': 'db',
                          'image': 'postgres:16.8@sha256:' + 'a' * 64,
                          'config': {'database': 'app', 'username': 'app'},
                          'secrets': {'password': 'db_password', 'root_password': 'db_root_password'}}]}


class ConfigTests(unittest.TestCase):
    def test_normalize_without_mutation(self):
        original = fixture()
        before = copy.deepcopy(original)
        normalized = validate_config(original)
        self.assertEqual(before, original)
        self.assertEqual(normalized['hosts']['db']['port'], 22)
        normalized['services'][0]['resources']['pids'] = 1
        self.assertEqual(validate_config(original)['services'][0]['resources']['pids'], 256)

    def test_bad_boundaries(self):
        for key, value in [('deployment', '../escape'), ('environment', 'prod'),
                           ('schema_version', True), ('command', 'echo hi')]:
            with self.subTest(key=key):
                data = fixture()
                data[key] = value
                with self.assertRaises(ValidationError):
                    validate_config(data)

    def test_unsafe_hosts(self):
        for key, value in [('address', '8.8.8.8'), ('address', '127.0.0.1'), ('address', 167772162),
                           ('user', 'root;id'), ('data_root', '/srv/../etc'),
                           ('port', True), ('bootstrap', 'yes')]:
            with self.subTest(key=key, value=value):
                data = fixture()
                data['hosts']['db'][key] = value
                with self.assertRaises(ValidationError):
                    validate_config(data)

    def test_image_and_secret(self):
        for key, value in [('image', 'postgres:latest'), ('secrets', {'password': 'p@ssword!'}),
                           ('config', {'command': 'id'}), ('depends_on', ['missing'])]:
            data = fixture()
            data['services'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                validate_config(data)

    def test_duplicates(self):
        for suffix, content in [('.json', '{"schema_version":1,"schema_version":1}'),
                                ('.yaml', 'schema_version: 1\nschema_version: 1\n')]:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / ('config' + suffix)
                path.write_text(content)
                with self.assertRaises(ValidationError):
                    load_config(path)

    def test_graph_cycle_disabled_provider(self):
        data = fixture()
        data['services'][0]['depends_on'] = ['db']
        with self.assertRaises(ValidationError):
            validate_config(data)
        data = fixture()
        data['services'].append({'id': 'admin', 'kind': 'phpmyadmin', 'host': 'db',
                                 'image': 'phpmyadmin:5.2@sha256:' + 'b' * 64,
                                 'config': {'database_service': 'db'}})
        with self.assertRaises(ValidationError):
            validate_config(data)

    def test_publish_requires_firewall(self):
        data = fixture()
        data['services'][0]['config']['publish_port'] = 5432
        with self.assertRaises(ValidationError):
            validate_config(data)

    def test_order(self):
        self.assertEqual(service_order(validate_config(fixture())), ['db'])

    def test_local_and_password_authentication_are_supported_without_key(self):
        data = fixture()
        data['hosts']['db'].pop('private_key_file')
        data['hosts']['db'].update({'connection': 'local', 'address': '127.0.0.1',
                                    'expected_mount': '/', 'data_root': '/tmp/dd-data',
                                    'runtime_root': '/tmp/dd-runtime'})
        self.assertEqual(validate_config(data)['hosts']['db']['connection'], 'local')
        data = fixture()
        data['hosts']['db'].pop('private_key_file')
        data['hosts']['db'].update({'connection': 'ssh-password', 'ssh_password_ref': 'SERVER_PASSWORD'})
        self.assertEqual(validate_config(data)['hosts']['db']['ssh_password_ref'], 'SERVER_PASSWORD')

    def test_authentication_requirements_are_closed(self):
        data = fixture()
        data['hosts']['db'].pop('private_key_file')
        with self.assertRaises(ValidationError):
            validate_config(data)
        data = fixture()
        data['hosts']['db']['connection'] = 'ssh-password'
        with self.assertRaises(ValidationError):
            validate_config(data)


if __name__ == '__main__':
    unittest.main()
