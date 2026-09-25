"""Authenticated S3 write/read/delete proof via container curl, credentials only on stdin."""
import datetime
import hmac
import uuid


def s3_request(payload, service, method, path, body=b''):
    config = service['config']
    secrets = payload['secrets']
    access = secrets[service['secrets']['root_user']]
    password = secrets[service['secrets']['root_password']]
    if any(c in str(access) + str(password) for c in '\r\n'):
        raise ValueError('Invalid S3 credentials')
    tls = bool(config.get('tls_cert'))
    hostname = config['server_name'] if tls else '127.0.0.1'
    authority = hostname + ':9000'
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp, date = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
    digest = hashlib.sha256(body).hexdigest()
    headers = f'host:{authority}\nx-amz-content-sha256:{digest}\nx-amz-date:{timestamp}\n'
    signed = 'host;x-amz-content-sha256;x-amz-date'
    canonical = '\n'.join([method, path, '', headers, signed, digest])
    scope = date + '/us-east-1/s3/aws4_request'
    message = 'AWS4-HMAC-SHA256\n' + timestamp + '\n' + scope + '\n' + hashlib.sha256(canonical.encode()).hexdigest()
    key = ('AWS4' + str(password)).encode()
    for value in (date, 'us-east-1', 's3', 'aws4_request'):
        key = hmac.new(key, value.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    authorization = f'AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={signed}, Signature={signature}'
    # curl config strings use JSON-compatible quoted ASCII, no shell or secret argv.
    options = {'url': ('https' if tls else 'http') + '://' + authority + path,
               'request': method, 'max-time': '30'}
    lines = ['silent', 'show-error', 'fail']
    lines.extend(k + ' = ' + json.dumps(v) for k, v in options.items())
    lines.extend('header = ' + json.dumps(v) for v in (
        'Authorization: ' + authorization, 'x-amz-content-sha256: ' + digest,
        'x-amz-date: ' + timestamp))
    if body:
        lines.append('data-binary = ' + json.dumps(body.decode('ascii')))
    if tls:
        lines += ['cacert = "/etc/minio/certs/CAs/ca.crt"',
                  'resolve = ' + json.dumps(authority + ':127.0.0.1')]
    return compose(payload, ['exec', '-T', service['id'], 'curl', '--config', '-'],
                   input_data=('\n'.join(lines) + '\n').encode(), timeout=45).stdout


def minio_verify(payload):
    results = {}
    selected = services(payload)
    for service in payload['services']:
        if service['id'] not in selected or service['kind'] != 'minio':
            continue
        bucket = '/dd-verification-' + uuid.uuid4().hex
        path, data = bucket + '/proof', uuid.uuid4().hex.encode()
        created = False
        try:
            s3_request(payload, service, 'PUT', bucket)
            created = True
            s3_request(payload, service, 'PUT', path, data)
            if s3_request(payload, service, 'GET', path) != data:
                raise ValueError('MinIO S3 round-trip checksum failed')
        finally:
            if created:
                s3_request(payload, service, 'DELETE', path)
                s3_request(payload, service, 'DELETE', bucket)
        results[service['id']] = {'s3_write_read_delete': True,
            'gui_license': 'operator release evidence required; not certified by runtime probe'}
    return results
