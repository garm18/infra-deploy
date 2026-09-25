import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from dynamic_deployment.images import resolve_image


class Response:
    def __init__(self, data=b'', headers=None):
        self.data = data
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size=-1):
        return self.data[:size] if size >= 0 else self.data


class ImageTests(unittest.TestCase):
    digest = 'sha256:' + 'a' * 64

    def test_invalid_references(self):
        for ref in ['ubuntu:latest', 'evil.org/x:1', 'php', 'php:latest',
                    'quay.io/other/minio:1', 'docker.io/attacker/php:1',
                    'php:8.4\n', 'https://docker.io/library/php:8.4']:
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                resolve_image(ref)

    @patch('dynamic_deployment.images._open')
    def test_public_manifest(self, request):
        request.return_value = Response(headers={'Docker-Content-Digest': self.digest})
        self.assertEqual(resolve_image('php:8.4-fpm'),
                         'docker.io/library/php:8.4-fpm@' + self.digest)
        self.assertEqual(request.call_args.args[0].method, 'HEAD')

    @patch('dynamic_deployment.images._open')
    def test_bearer_auth(self, request):
        headers = {'WWW-Authenticate': 'Bearer realm="https://auth.docker.io/token",service="registry.docker.io",scope="repository:library/php:pull"'}
        request.side_effect = [HTTPError('url', 401, 'Unauthorized', headers, io.BytesIO()),
                               Response(json.dumps({'token': 'example-token'}).encode()),
                               Response(headers={'Docker-Content-Digest': self.digest})]
        self.assertTrue(resolve_image('docker.io/library/php:8.4-fpm').endswith(self.digest))
        self.assertEqual(request.call_args.args[0].get_header('Authorization'), 'Bearer example-token')

    @patch('dynamic_deployment.images._open')
    def test_token_endpoint_not_trusted(self, request):
        headers = {'WWW-Authenticate': 'Bearer realm="https://evil.org/token",service="registry.docker.io"'}
        request.side_effect = HTTPError('url', 401, 'Unauthorized', headers, io.BytesIO())
        with self.assertRaises(ValueError):
            resolve_image('php:8.4-fpm')
        self.assertEqual(request.call_count, 1)

    @patch('dynamic_deployment.images._open')
    def test_bad_digest(self, request):
        request.return_value = Response(headers={'Docker-Content-Digest': 'oops'})
        with self.assertRaises(ValueError):
            resolve_image('quay.io/minio/aistor/minio:RELEASE.2025-01-01')

    @patch('dynamic_deployment.images._open')
    def test_network_failure(self, request):
        request.side_effect = OSError('offline')
        with self.assertRaises(ValueError):
            resolve_image('redis:7.4')
