import copy
import unittest

from dynamic_deployment.render import render_host, render_all


def fixture(services):
    return {'environment': 'development', 'deployment': 'demo', 'hosts': {
        'one': {'address': '10.0.0.2'}, 'two': {'address': '10.0.0.3'}},
        'services': [{'host': 'one', 'image': 'example/service:1@sha256:' + 'a'*64,
                     **s} for s in services]}


class RenderTests(unittest.TestCase):
    def test_database_secret_persistence_and_immutable(self):
        config = fixture([{'id': 'db', 'kind': 'postgres', 'config': {
            'database': 'app', 'username': 'app'}, 'secrets': {'password': 'db_password', 'root_password': 'db_root_password'}}])
        original = copy.deepcopy(config)
        bundle = render_host(config, 'one')
        db = bundle['compose']['services']['db']
        self.assertEqual(config, original)
        self.assertNotIn('ports', db)
        self.assertEqual(bundle['secret_files']['secrets/db/password'], 'db_password')
        self.assertIn('SELECT 1', str(bundle['files']))
        self.assertTrue(bundle['compose']['networks']['data-db']['internal'])
        self.assertEqual(bundle['directories'], ['db/data'])
        self.assertIn('/srv/dynamic-deployment/development/demo/db/data', str(db))

    def test_dependencies_are_separate(self):
        config = fixture([
            {'id': 'db', 'kind': 'mariadb', 'config': {'database': 'app', 'username': 'app'},
             'secrets': {'password': 'pw', 'root_password': 'rootpw'}},
            {'id': 'cache', 'kind': 'redis', 'secrets': {'password': 'rpw'}},
        ])
        b = render_host(config, 'one')['compose']
        self.assertNotEqual(b['services']['db']['networks'], b['services']['cache']['networks'])
        self.assertNotIn('default', b['networks'])

    def test_minio_license(self):
        config = fixture([{'id': 'objects', 'kind': 'minio', 'config': {
            'license_file': '/tmp/license', 'console_domain': 'console.example.test',
            's3_domain': 's3.example.test'},
            'secrets': {'root_user': 'mu', 'root_password': 'mp'}}])
        bundle = render_host(config, 'one')
        self.assertIn('/run/assets/license', bundle['compose']['services']['objects']['command'])
        self.assertEqual(bundle['asset_files']['assets/objects/license'], '/tmp/license')

    def test_disabled_and_all(self):
        config = fixture([{'id': 'gone', 'kind': 'redis', 'enabled': False}])
        self.assertEqual(render_host(config, 'one')['compose']['services'], {})
        self.assertEqual(set(render_all(config)), {'one', 'two'})

    def test_remote_without_tls_rejected(self):
        config = fixture([
            {'id': 'db', 'kind': 'mariadb', 'host': 'two', 'config': {}, 'secrets': {}},
            {'id': 'admin', 'kind': 'phpmyadmin', 'config': {'database_service': 'db'}}])
        with self.assertRaises(ValueError):
            render_host(config, 'one')


if __name__ == '__main__':
    unittest.main()

class ProfileTests(unittest.TestCase):
    def database(self):
        return {'id': 'db', 'kind': 'postgres', 'config': {'database': 'app', 'username': 'app'},
                'secrets': {'password': 'dp', 'root_password': 'dr'}}

    def php(self, role='php'):
        return {'id': role, 'kind': 'laravel-' + role, 'config': {
            'database_service': 'db', 'release_id': 'r1', 'app_url': 'https://app.example.test'},
            'secrets': {'app_key': 'ak'}}

    def test_laravel_network_and_mount_boundaries(self):
        services = [self.database(), self.php(), self.php('worker'), self.php('scheduler'),
                    {'id': 'web', 'kind': 'laravel-web', 'config': {'php_service': 'php',
                     'domain': 'app.example.test', 'tls_cert': '/tmp/cert', 'tls_key': '/tmp/key'}}]
        cfg = fixture(services)
        bundle = render_host(cfg, 'one')
        all_services = bundle['compose']['services']
        self.assertNotIn('data-db', all_services['web']['networks'])
        self.assertNotIn('backend', all_services['worker']['networks'])
        self.assertNotIn('ports', all_services['php'])
        self.assertIn('data-db', all_services['php']['networks'])
        self.assertIn('php/uploads', bundle['directories'])
        self.assertNotIn('worker/uploads', bundle['directories'])
        text = bundle['files']['files/web/nginx.conf']
        self.assertIn('location = /index.php', text)
        self.assertIn('return 404', text)
        self.assertIn('pcntl_exec', bundle['files']['files/worker/start.php'])
        self.assertIn('$$ok', str(all_services['worker']['healthcheck']))

    def test_admin_proxy_is_separate(self):
        cfg = fixture([
            {'id': 'db', 'kind': 'mariadb', 'secrets': {'password': 'pw', 'root_password': 'rp'}},
            {'id': 'pma', 'kind': 'phpmyadmin', 'config': {'database_service': 'db'}},
            {'id': 'proxy', 'kind': 'nginx', 'config': {'tls_cert': '/tmp/c', 'tls_key': '/tmp/k',
              'routes': [{'domain': 'db.example.test', 'target': 'pma'}]}},
        ])
        b = render_host(cfg, 'one')
        self.assertIn('management', b['compose']['services']['proxy']['networks'])
        self.assertNotIn('data-db', b['compose']['services']['proxy']['networks'])
        self.assertIn('data-db', b['compose']['services']['pma']['networks'])
        self.assertNotIn('PMA_PASSWORD', b['compose']['services']['pma']['environment'])

    def test_redis_secret_not_commandline_and_auth_health(self):
        b = render_host(fixture([{'id': 'r', 'kind': 'redis', 'secrets': {'password': 'redis_pw'}}]), 'one')
        self.assertIn('sha256sum', b['files']['files/r/start.sh'])
        self.assertIn('REDISCLI_AUTH', b['files']['files/r/health.sh'])
        self.assertNotIn('redis_pw', str(b['compose']))
        self.assertIn('appendonly yes', b['files']['files/r/redis.conf'])

    def test_remote_postgres_verified_tls(self):
        db = self.database()
        db['host'] = 'two'
        db['config'].update(publish_port=5432, tls_ca='/tmp/ca', tls_cert='/tmp/cert',
                            tls_key='/tmp/key', server_name='db.example.test')
        cfg = fixture([db, self.php()])
        b = render_host(cfg, 'one')
        p = b['compose']['services']['php']
        self.assertEqual(p['environment']['PGSSLMODE'], 'verify-full')
        self.assertIn('uplink-php', p['networks'])
        self.assertNotIn('data-db', p['networks'])
        self.assertNotIn('depends_on', p)
        provider = render_host(cfg, 'two')['compose']['services']['db']
        self.assertEqual(provider['ports'][0]['host_ip'], '10.0.0.3')
        self.assertIn('ssl=on', provider['command'])

    def test_apache_config(self):
        cfg = fixture([{'id': 'pma', 'kind': 'phpmyadmin', 'config': {'database_service': 'db'}},
                       {'id': 'db', 'kind': 'mariadb', 'secrets': {'password': 'p', 'root_password': 'r'}},
                       {'id': 'proxy', 'kind': 'apache', 'config': {'tls_cert': '/tmp/c', 'tls_key': '/tmp/k',
                        'routes': [{'target': 'pma', 'domain': 'admin.example.test'}]}}])
        b = render_host(cfg, 'one')
        self.assertIn('ProxyPass / http://pma:80/', b['files']['files/proxy/httpd.conf'])
        self.assertEqual(b['compose']['services']['proxy']['entrypoint'], ['httpd', '-DFOREGROUND'])

    def test_minio_tls_and_scoped_app_credentials(self):
        obj = {'id': 'obj', 'kind': 'minio', 'config': {'license_file': '/tmp/license',
            'console_domain': 'console.example.test', 's3_domain': 's3.example.test',
            'server_name': 's3.example.test', 'tls_ca': '/tmp/ca', 'tls_cert': '/tmp/c', 'tls_key': '/tmp/k'},
            'secrets': {'root_user': 'mu', 'root_password': 'mp'}}
        php = self.php()
        php['config']['storage_service'] = 'obj'
        php['config']['storage_bucket'] = 'uploads'
        php['secrets'].update(storage_access_key='sak', storage_secret_key='ssk')
        b = render_host(fixture([self.database(), obj, php]), 'one')
        self.assertEqual(b['compose']['services']['php']['environment']['AWS_ENDPOINT'], 'https://s3.example.test:9000')
        self.assertNotIn('mp', [v for k, v in b['secret_files'].items() if '/php/' in k])
        self.assertIn('management', b['compose']['services']['obj']['networks'])
