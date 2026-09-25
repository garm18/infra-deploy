import unittest
from pathlib import Path
from unittest.mock import Mock
from test_guard import guard

ns = {k: v for k, v in vars(guard).items() if not k.startswith('__')}
source = Path(__file__).parents[1] / 'files/minio_probe.py'
exec(compile(source.read_text(), str(source), 'exec'), ns)


class MinioProbeTests(unittest.TestCase):
    def test_signing_credentials_never_in_command_arguments(self):
        stub = Mock(return_value=Mock(stdout=b'ok'))
        old = ns['compose']
        ns['compose'] = stub
        try:
            service = {'id': 'store', 'config': {}, 'secrets': {'root_user': 'user', 'root_password': 'password'}}
            ns['s3_request']({'secrets': {'user': 'EXAMPLEACCESS', 'password': 'example-secret'}}, service, 'PUT', '/test', b'fixture')
            args = stub.call_args.args[1]
            self.assertEqual(args, ['exec', '-T', 'store', 'curl', '--config', '-'])
            stdin = stub.call_args.kwargs['input_data']
            self.assertIn(b'AWS4-HMAC-SHA256', stdin)
            self.assertNotIn(b'example-secret', stdin)
        finally:
            ns['compose'] = old

    def test_roundtrip_proves_write_and_cleans_only_own_fixture(self):
        calls=[]
        contents={}
        def request(payload, service, method, path, body=b''):
            calls.append((method,path))
            if method == 'PUT': contents[path]=body
            if method == 'GET': return contents[path]
            if method == 'DELETE': contents.pop(path,None)
            return b''
        payload={'services':[{'id':'store','kind':'minio'}], 'bundle':{'compose':{'services':{'store':{}}}}}
        old=ns['s3_request']
        ns['s3_request']=request
        try:
            self.assertTrue(ns['minio_verify'](payload)['store']['s3_write_read_delete'])
            self.assertEqual([c[0] for c in calls],['PUT','PUT','GET','DELETE','DELETE'])
            self.assertFalse(contents)
            self.assertTrue(all(c[1].startswith('/dd-verification-') for c in calls))
        finally:
            ns['s3_request']=old
