import copy
import unittest
from dynamic_deployment.config import validate_config, service_order
from dynamic_deployment.errors import ValidationError
from test_config import fixture


def app_fixture():
    data = fixture()
    data['hosts']['db'].update({'allowed_cidrs': ['10.0.0.0/24'], 'firewall_check': '/usr/local/bin/firewall-check'})
    php = {'id': 'php', 'kind': 'laravel-php', 'host': 'db',
           'image': 'myapp/php:1.0@sha256:' + 'c' * 64,
           'config': {'database_service': 'db', 'release_id': 'r1'},
           'secrets': {'app_key': 'app_key'}}
    web = {'id': 'web', 'kind': 'laravel-web', 'host': 'db',
           'image': 'myapp/web:1.0@sha256:' + 'd' * 64,
           'config': {'php_service': 'php', 'release_id': 'r1', 'domain': 'app.internal',
                      'tls_cert': '/tmp/cert', 'tls_key': '/tmp/key'}}
    data['services'] = [web, php, data['services'][0]]
    return data


class TopologyTests(unittest.TestCase):
    def test_inferred_order(self):
        result = validate_config(app_fixture())
        self.assertEqual(service_order(result), ['db', 'php', 'web'])
        self.assertEqual(result['services'][0]['depends_on'], ['php'])

    def test_bad_profile_and_session(self):
        for change in ({'release_id': 'r2'}, {'session_driver': 'redis'}, {'health_path': 1}, {'upload_path': '../escape'}):
            value = app_fixture()
            value['services'][1]['config'].update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                validate_config(value)

    def test_disabled_provider(self):
        value = app_fixture()
        value['services'][-1]['enabled'] = False
        with self.assertRaises(ValidationError):
            validate_config(value)

    def test_cross_host_tls(self):
        value = app_fixture()
        value['hosts']['remote'] = {**value['hosts']['db'], 'address': '10.0.0.3'}
        db = value['services'][-1]
        db['host'] = 'remote'
        with self.assertRaises(ValidationError):
            validate_config(value)
        db['config'].update({'publish_port': 5432, 'tls_ca': '/tmp/ca', 'tls_cert': '/tmp/cert', 'tls_key': '/tmp/key', 'server_name': 'db.internal'})
        self.assertEqual(service_order(validate_config(value)), ['db', 'php', 'web'])
        value['hosts']['remote']['allowed_cidrs'] = ['10.0.1.0/24']
        with self.assertRaises(ValidationError):
            validate_config(value)

    def test_ports_and_roles(self):
        value = app_fixture()
        value['services'][-1]['config']['publish_port'] = 443
        with self.assertRaises(ValidationError):
            validate_config(value)
        value = fixture()
        duplicate = {**value['services'][0], 'id': 'db2'}
        value['services'].append(duplicate)
        with self.assertRaises(ValidationError):
            validate_config(value)

    def test_worker_profile_consistency(self):
        value = app_fixture()
        worker = copy.deepcopy(value['services'][1])
        worker.update({'id': 'worker', 'kind': 'laravel-worker'})
        value['services'].append(worker)
        validate_config(value)
        worker['image'] = 'myapp/php:1.1@sha256:' + 'e' * 64
        with self.assertRaises(ValidationError):
            validate_config(value)

    def test_cyclic_yaml_and_untyped_values(self):
        value = fixture()
        value['services'][0]['config']['database'] = value
        with self.assertRaises(ValidationError):
            validate_config(value)

    def test_minio_requires_gui_and_scoped_s3_credentials(self):
        value = app_fixture()
        value['services'].append({'id': 's3', 'kind': 'minio', 'host': 'db',
                                 'image': 'quay.io/minio/aistor/minio:1.0@sha256:' + 'e' * 64,
                                 'secrets': {'root_user': 's3_root_user', 'root_password': 's3_root_password'},
                                 'config': {'license_file': '/tmp/license', 's3_domain': 's3.internal',
                                            'console_domain': 'console.internal', 'tls_cert': '/tmp/cert', 'tls_key': '/tmp/key'}})
        with self.assertRaises(ValidationError):
            validate_config(value)
        value['services'].append({'id': 'admin', 'kind': 'nginx', 'host': 'db',
                                 'image': 'nginx:1.27@sha256:' + 'f' * 64,
                                 'config': {'https_port': 8443, 'tls_cert': '/tmp/cert', 'tls_key': '/tmp/key',
                                            'routes': [{'domain': 'console.internal', 'target': 's3', 'protocol': 'https', 'tls_ca': '/tmp/ca'}]}})
        validate_config(value)
        php = value['services'][1]
        php['config']['storage_service'] = 's3'
        with self.assertRaises(ValidationError):
            validate_config(value)
        php['config']['storage_bucket'] = 'uploads'
        php['secrets'].update({'storage_access_key': 's3_app_user', 'storage_secret_key': 's3_app_password'})
        validate_config(value)

    def test_remote_unsupported_driver_fails_before_render(self):
        value = app_fixture()
        value['hosts']['remote'] = {**value['hosts']['db'], 'address': '10.0.0.3'}
        db = value['services'][-1]
        db['host'] = 'remote'
        db['kind'] = 'mariadb'
        db['config'].update({'publish_port': 3306, 'tls_ca': '/tmp/ca', 'tls_cert': '/tmp/cert', 'tls_key': '/tmp/key', 'server_name': 'db.internal'})
        with self.assertRaises(ValidationError):
            validate_config(value)

    def test_worker_identity_mismatch(self):
        value = app_fixture()
        worker = copy.deepcopy(value['services'][1])
        worker.update({'id': 'worker', 'kind': 'laravel-worker'})
        worker['config']['uid'] = 2000
        value['services'].append(worker)
        with self.assertRaises(ValidationError):
            validate_config(value)

    def test_local_tls_driver_and_unimplemented_upload_path_rejected(self):
        value = app_fixture()
        value['services'][-1]['kind'] = 'mariadb'
        value['services'][-1]['config'].update({'tls_cert': '/tmp/cert', 'tls_key': '/tmp/key'})
        with self.assertRaises(ValidationError):
            validate_config(value)

    def test_local_connection_allows_loopback_development_proxy_without_firewall_script(self):
        value = app_fixture()
        value['hosts']['db'].pop('private_key_file')
        value['hosts']['db'].update({'connection': 'local', 'address': '127.0.0.1',
                                     'expected_mount': '/', 'data_root': '/tmp/data', 'runtime_root': '/tmp/runtime'})
        value['hosts']['db'].pop('firewall_check')
        value['hosts']['db']['allowed_cidrs'] = []
        self.assertEqual(validate_config(value)['hosts']['db']['connection'], 'local')
        value = app_fixture()
        value['services'][1]['config']['upload_path'] = 'uploads'
        with self.assertRaises(ValidationError):
            validate_config(value)
