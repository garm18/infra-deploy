"""Fixed image adapters. Release evidence must verify each image's declared tools."""
from .render_web import web
from .render_laravel import laravel


def health(out, command):
    out['healthcheck'] = {'test': command, 'interval': '15s', 'timeout': '5s', 'retries': 5,
                          'start_period': '60s'}


def script(ctx, service, out, name, body, target='/run/dd'):
    ctx.file(service, out, name, '#!/bin/sh\nset -eu\n' + body + '\n', target + '/' + name)
    return target + '/' + name


def tls(ctx, s, out):
    cfg = s.get('config', {})
    for key in ('tls_ca', 'tls_cert', 'tls_key'):
        if cfg.get(key):
            ctx.asset(s, out, key, cfg[key], '/run/assets/' + key)
    return bool(cfg.get('tls_cert'))


def postgres(ctx, s, out):
    cfg = s.get('config', {})
    user, database = cfg.get('username', 'app'), cfg.get('database', 'app')
    out['user'] = str(cfg.get('uid', 999)) + ':' + str(cfg.get('gid', 999))
    out['environment'] = {'POSTGRES_USER': 'postgres', 'POSTGRES_DB': database,
        'POSTGRES_PASSWORD_FILE': ctx.secret(s, out, 'root_password'), 'PGDATA': '/var/lib/postgresql/data/pgdata',
        'DD_DB_USER': user, 'DD_DB_NAME': database}
    ctx.secret(s, out, 'password')
    ctx.persistent(s, out, 'data', '/var/lib/postgresql/data')
    out['tmpfs'].append('/var/run/postgresql:rw,nosuid,size=16m,uid=' + str(cfg.get('uid', 999)))
    script(ctx, s, out, '10-app.sh', '''export DD_APP_PASSWORD="$(cat /run/secrets/password)"
psql -v ON_ERROR_STOP=1 --username postgres --dbname "$POSTGRES_DB" --set=user="$DD_DB_USER" <<'SQL'
\\getenv password DD_APP_PASSWORD
CREATE ROLE :"user" LOGIN PASSWORD :'password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
GRANT CONNECT ON DATABASE :"DBNAME" TO :"user";
GRANT USAGE, CREATE ON SCHEMA public TO :"user";
SQL''', '/docker-entrypoint-initdb.d')
    probe = script(ctx, s, out, 'health.sh', '''export PGPASSWORD="$(cat /run/secrets/password)"
exec psql -h 127.0.0.1 -U "$DD_DB_USER" -d "$DD_DB_NAME" -v ON_ERROR_STOP=1 -tAc 'SELECT 1' ''')
    health(out, ['CMD', 'sh', probe])
    if tls(ctx, s, out):
        out['command'] = ['postgres', '-c', 'ssl=on', '-c', 'ssl_cert_file=/run/assets/tls_cert',
                          '-c', 'ssl_key_file=/run/assets/tls_key', '-c', 'hba_file=/run/dd/pg_hba.conf']
        ctx.file(s, out, 'pg_hba.conf', 'local all all trust\nhost all all 127.0.0.1/32 scram-sha-256\nhostssl all all 0.0.0.0/0 scram-sha-256\n', '/run/dd/pg_hba.conf')


def mariadb(ctx, s, out):
    cfg = s.get('config', {})
    out['user'] = str(cfg.get('uid', 999)) + ':' + str(cfg.get('gid', 999))
    out['environment'] = {'MARIADB_DATABASE': cfg.get('database', 'app'), 'MARIADB_USER': cfg.get('username', 'app'),
        'MARIADB_PASSWORD_FILE': ctx.secret(s, out, 'password'),
        'MARIADB_ROOT_PASSWORD_FILE': ctx.secret(s, out, 'root_password')}
    ctx.persistent(s, out, 'data', '/var/lib/mysql')
    out['tmpfs'].append('/run/mysqld:rw,nosuid,size=16m,uid=' + str(cfg.get('uid', 999)))
    probe = script(ctx, s, out, 'health.sh', '''export MYSQL_PWD="$(cat /run/secrets/password)"
exec mariadb --protocol=SOCKET --socket=/run/mysqld/mysqld.sock --user="$MARIADB_USER" --database="$MARIADB_DATABASE" --batch --execute='SELECT 1' ''')
    health(out, ['CMD', 'sh', probe])
    if tls(ctx, s, out):
        out['command'] = ['mariadbd', '--require-secure-transport=ON', '--ssl-ca=/run/assets/tls_ca',
                          '--ssl-cert=/run/assets/tls_cert', '--ssl-key=/run/assets/tls_key']


def redis(ctx, s, out):
    cfg = s.get('config', {})
    out['user'] = str(cfg.get('uid', 999)) + ':' + str(cfg.get('gid', 999))
    ctx.secret(s, out, 'password')
    ctx.persistent(s, out, 'data', '/data')
    enabled_tls = tls(ctx, s, out)
    settings = ('dir /data\nappendonly yes\nmaxmemory ' + cfg.get('maxmemory', '256mb') +
                '\nmaxmemory-policy noeviction\nprotected-mode yes\n')
    if enabled_tls:
        settings += 'port 0\ntls-port 6379\ntls-auth-clients no\ntls-cert-file /run/assets/tls_cert\ntls-key-file /run/assets/tls_key\ntls-ca-cert-file /run/assets/tls_ca\n'
    ctx.file(s, out, 'redis.conf', settings, '/run/dd/redis.conf')
    start = script(ctx, s, out, 'start.sh', '''umask 077
password=$(cat /run/secrets/password)
hash=$(printf '%s' "$password" | sha256sum)
hash=${hash%% *}
cat /run/dd/redis.conf > /tmp/redis.conf
printf '\\nuser default on #%s ~* &* +@all\\n' "$hash" >> /tmp/redis.conf
exec redis-server /tmp/redis.conf''')
    out['entrypoint'] = ['sh', start]
    args = ' --tls --cacert /run/assets/tls_ca --sni ' + cfg.get('server_name', s['id']) if enabled_tls else ''
    probe = script(ctx, s, out, 'health.sh', 'export REDISCLI_AUTH="$(cat /run/secrets/password)"\n' +
                   'test "$(redis-cli' + args + ' ping)" = PONG')
    health(out, ['CMD', 'sh', probe])


def minio(ctx, s, out):
    cfg = s.get('config', {})
    out['user'] = str(cfg.get('uid', 1000)) + ':' + str(cfg.get('gid', 1000))
    out['environment'] = {'MINIO_ROOT_USER_FILE': ctx.secret(s, out, 'root_user'),
        'MINIO_ROOT_PASSWORD_FILE': ctx.secret(s, out, 'root_password'),
        'MINIO_BROWSER_REDIRECT_URL': 'https://' + cfg['console_domain']}
    ctx.asset(s, out, 'license', cfg['license_file'], '/run/assets/license')
    ctx.persistent(s, out, 'data', '/data')
    out['command'] = ['minio', 'server', '/data', '--license', '/run/assets/license', '--console-address', ':9001',
                      '--certs-dir', '/etc/minio/certs']
    if cfg.get('tls_cert'):
        for name, target in [('tls_cert', 'public.crt'), ('tls_key', 'private.key'), ('tls_ca', 'CAs/ca.crt')]:
            ctx.asset(s, out, name, cfg[name], '/etc/minio/certs/' + target)
        probe = ['CMD', 'curl', '--fail', '--silent', '--cacert', '/etc/minio/certs/CAs/ca.crt',
                 '--resolve', cfg['server_name'] + ':9000:127.0.0.1', 'https://' + cfg['server_name'] + ':9000/minio/health/ready']
    else:
        probe = ['CMD', 'curl', '--fail', '--silent', 'http://127.0.0.1:9000/minio/health/ready']
    health(out, probe)
    ctx.network(out, 'management')
    if cfg.get('console_port'):
        ctx.endpoint(s, out, cfg['console_port'], 9001, cfg['console_domain'])
    ctx.bundle['warnings'].append(s['id'] + ': readiness HTTP is not license/IAM/S3 acceptance; release evidence must prove GUI and scoped S3 access.')


def configure(ctx, s, out):
    kind = s['kind']
    if kind in ('postgres', 'mariadb', 'redis', 'minio'):
        {'postgres': postgres, 'mariadb': mariadb, 'redis': redis, 'minio': minio}[kind](ctx, s, out)
        ctx.network(out, 'data-' + s['id'])
        if s.get('config', {}).get('server_name'):
            out['networks'] = {name: ({'aliases': [s['config']['server_name']]} if name in ('data-' + s['id'], 'management') else {}) for name in out['networks']}
        if s.get('config', {}).get('publish_port'):
            from .render import PORTS
            ctx.endpoint(s, out, s['config']['publish_port'], PORTS[kind])
    elif kind.startswith('laravel-') and kind != 'laravel-web':
        laravel(ctx, s, out)
    else:
        web(ctx, s, out)
