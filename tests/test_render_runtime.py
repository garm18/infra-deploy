"""Regression checks for adapter runtime contracts; no Docker runtime claims."""
from pathlib import Path
import unittest
import test_render
from test_render import fixture
from dynamic_deployment.render import render_host

ROOT = Path(__file__).resolve().parents[1]

class RuntimeTests(unittest.TestCase):
    def test_nginx_readonly_temp_paths_and_php_upload_denial(self):
        helper = test_render.ProfileTests()
        config = fixture([helper.database(), helper.php(), {'id':'web','kind':'laravel-web',
            'config':{'php_service':'php','domain':'app.test','tls_cert':'/tmp/c','tls_key':'/tmp/k'}}])
        bundle = render_host(config, 'one')
        text = bundle['files']['files/web/nginx.conf']
        self.assertIn('uwsgi_temp_path /tmp/', text)
        self.assertIn('scgi_temp_path /tmp/', text)
        self.assertIn('location ~* \\.php(?:/|$)', text)
        dockerfile = (ROOT/'templates/laravel/Dockerfile').read_text()
        self.assertIn('/usr/share/nginx/html', dockerfile)
        self.assertIn('USER 1000:1000', dockerfile)

    def test_postgres_bootstrap_password_stays_out_of_argv(self):
        result = render_host(fixture([test_render.ProfileTests().database()]), 'one')
        text = result['files']['files/db/10-app.sh']
        self.assertNotIn('--set=password', text)
        self.assertIn('\\getenv password DD_APP_PASSWORD', text)
        self.assertIn("PASSWORD :'password' NOSUPERUSER", text)

    def test_local_postgres_tls_uses_hostname_verification(self):
        helper = test_render.ProfileTests()
        db = helper.database()
        db['config'].update(tls_ca='/tmp/ca',tls_cert='/tmp/c',tls_key='/tmp/k',server_name='db.test')
        result = render_host(fixture([db,helper.php()]), 'one')
        env = result['compose']['services']['php']['environment']
        self.assertEqual(env['DB_HOST'], 'db.test')
        self.assertEqual(env['PGSSLMODE'], 'verify-full')

    def test_mariadb_tls_probe_uses_socket(self):
        result = render_host(fixture([{'id':'db','kind':'mariadb',
            'config':{'tls_ca':'/tmp/ca','tls_cert':'/tmp/c','tls_key':'/tmp/k','server_name':'db.test'},
            'secrets':{'password':'pw','root_password':'rp'}}]), 'one')
        self.assertIn('--protocol=SOCKET', result['files']['files/db/health.sh'])

    def test_nginx_minio_proxy_allows_large_unbuffered_uploads(self):
        result = render_host(fixture([{'id':'obj','kind':'minio','config':{
            'license_file':'/tmp/license','console_domain':'console.test','s3_domain':'s3.test'},
            'secrets':{'root_user':'u','root_password':'p'}},
            {'id':'proxy','kind':'nginx','config':{'tls_cert':'/tmp/c','tls_key':'/tmp/k',
            'routes':[{'domain':'s3.test','target':'obj','port':9000}]}}]),'one')
        text = result['files']['files/proxy/nginx.conf']
        self.assertIn('client_max_body_size 0;', text)
        self.assertIn('proxy_request_buffering off;', text)
        self.assertIn('proxy_set_header Host $http_host;', text)
