"""Resolve approved public OCI image tags; no credentials or registry writes."""

import json
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

APPROVED = {
    'docker.io': {'library/php', 'library/composer', 'library/node', 'library/nginx',
                  'library/httpd', 'library/postgres', 'library/mariadb', 'library/redis',
                  'library/phpmyadmin', 'phpmyadmin/phpmyadmin'},
    'quay.io': {'minio/aistor/minio'},
}
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Registry redirects are not permitted')


def _open(request):
    return build_opener(NoRedirect()).open(request, timeout=20)


def _manifest(url, token=None):
    headers = {'Accept': ', '.join([
        'application/vnd.oci.image.index.v1+json',
        'application/vnd.oci.image.manifest.v1+json',
        'application/vnd.docker.distribution.manifest.list.v2+json',
        'application/vnd.docker.distribution.manifest.v2+json'])}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with _open(Request(url, headers=headers, method='HEAD')) as response:
        return response.headers.get('Docker-Content-Digest', '')


def _token(challenge, host, repository):
    if not challenge.startswith('Bearer '):
        raise ValueError('Registry requires unsupported authentication')
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm, service = ({'docker.io': ('https://auth.docker.io/token', 'registry.docker.io'),
                       'quay.io': ('https://quay.io/v2/auth', 'quay.io')})[host]
    if fields.get('realm') != realm or fields.get('service') != service:
        raise ValueError('Untrusted registry authentication endpoint')
    url = realm + '?' + urlencode({'service': service, 'scope': 'repository:' + repository + ':pull'})
    with _open(Request(url)) as response:
        payload = response.read(65537)
    if len(payload) > 65536:
        raise ValueError('Registry token response too large')
    data = json.loads(payload)
    token = data.get('token', data.get('access_token')) if isinstance(data, dict) else None
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=-]{1,16384}', token):
        raise ValueError('Registry returned an invalid token')
    return token


def resolve_image(reference: str) -> str:
    """Return canonical tag@digest. Pinning platform compatibility is a later gate."""
    if not isinstance(reference, str) or not re.fullmatch(r'[a-z0-9./_-]+:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', reference):
        raise ValueError('Use an approved image with an explicit version tag')
    name, tag = reference.rsplit(':', 1)
    if tag.lower() == 'latest':
        raise ValueError('Floating latest tag is forbidden')
    parts = name.split('/')
    host = parts.pop(0) if '.' in parts[0] else 'docker.io'
    repository = '/'.join(parts)
    if host == 'docker.io' and '/' not in repository:
        repository = 'library/' + repository
    if repository not in APPROVED.get(host, set()):
        raise ValueError('Image publisher is not approved')
    endpoint = 'registry-1.docker.io' if host == 'docker.io' else host
    url = 'https://' + endpoint + '/v2/' + repository + '/manifests/' + tag
    try:
        try:
            digest = _manifest(url)
        except HTTPError as error:
            if error.code != 401:
                raise
            token = _token(error.headers.get('WWW-Authenticate', ''), host, repository)
            digest = _manifest(url, token)
        if not DIGEST.fullmatch(digest):
            raise ValueError('Registry did not return a valid immutable digest')
        return host + '/' + repository + ':' + tag + '@' + digest
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError('Image resolution failed; verify version and registry connectivity') from error
