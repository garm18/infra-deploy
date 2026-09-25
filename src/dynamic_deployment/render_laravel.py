"""Laravel image contract: /var/www/html, PHP CLI/FPM, cgi-fcgi, immutable vendor."""
import json


def laravel(ctx, s, out):
    from .render_services import health
    cfg = s.get('config', {})
    uid, gid = cfg.get('uid', 1000), cfg.get('gid', 1000)
    out['user'] = f'{uid}:{gid}'
    out['working_dir'] = '/var/www/html'
    env = {'APP_ENV': ctx.config['environment'], 'APP_DEBUG': 'false', 'LOG_CHANNEL': 'stderr',
           'APP_URL': cfg.get('app_url', ''), 'APP_CONFIG_CACHE': '/tmp/laravel/config.php',
           'VIEW_COMPILED_PATH': '/tmp/laravel/views', 'SESSION_DRIVER': cfg.get('session_driver', 'file')}
    secret_env = {'APP_KEY': ctx.secret(s, out, 'app_key')}
    for key, prefix in [('database_service', 'DB'), ('redis_service', 'REDIS'), ('storage_service', 'AWS')]:
        if not cfg.get(key):
            continue
        target = ctx.services[cfg[key]]
        host, port, remote = ctx.connect(s, out, target['id'])
        tc = target.get('config', {})
        if prefix == 'DB':
            encrypted = remote or bool(tc.get('tls_cert'))
            if encrypted and not remote:
                host = tc['server_name']
                ctx.asset(s, out, target['id'] + '-ca', tc['tls_ca'], '/run/assets/' + target['id'] + '-ca')
            env.update(DB_CONNECTION='pgsql' if target['kind'] == 'postgres' else 'mysql',
                       DB_HOST=host, DB_PORT=str(port), DB_DATABASE=tc.get('database', 'app'),
                       DB_USERNAME=tc.get('username', 'app'))
            secret_env['DB_PASSWORD'] = ctx.secret(s, out, 'database_password', target['secrets']['password'])
            if encrypted:
                if target['kind'] == 'mariadb':
                    raise ValueError('Remote Laravel MariaDB requires application PDO TLS verification adapter; unsupported v1')
                env.update(PGSSLMODE='verify-full', PGSSLROOTCERT='/run/assets/' + target['id'] + '-ca',
                           DB_SSLMODE='verify-full')
        elif prefix == 'REDIS':
            if remote or tc.get('tls_cert'):
                raise ValueError('TLS Laravel Redis requires application TLS context adapter; unsupported v1')
            env.update(REDIS_HOST=host, REDIS_PORT=str(port))
            secret_env['REDIS_PASSWORD'] = ctx.secret(s, out, 'redis_password', target['secrets']['password'])
        else:
            encrypted = remote or bool(tc.get('tls_cert'))
            if encrypted and not remote:
                host = tc['server_name']
                ctx.asset(s, out, target['id'] + '-ca', tc['tls_ca'], '/run/assets/' + target['id'] + '-ca')
            env.update(AWS_ENDPOINT=('https' if encrypted else 'http') + f'://{host}:{port}',
                       AWS_USE_PATH_STYLE_ENDPOINT='true', AWS_DEFAULT_REGION='us-east-1',
                       AWS_BUCKET=cfg['storage_bucket'])
            secret_env['AWS_ACCESS_KEY_ID'] = ctx.secret(s, out, 'storage_access_key')
            secret_env['AWS_SECRET_ACCESS_KEY'] = ctx.secret(s, out, 'storage_secret_key')
            if encrypted:
                env['AWS_CA_BUNDLE'] = '/run/assets/' + target['id'] + '-ca'
    out['environment'] = env
    php = next((v for v in ctx.services.values() if v['host'] == s['host'] and v['kind'] == 'laravel-php'), s)
    ctx.persistent(s, out, 'uploads', '/var/www/html/storage/app/public', owner=php['id'])
    if cfg.get('session_driver', 'file') == 'file':
        ctx.persistent(s, out, 'sessions', '/var/www/html/storage/framework/sessions', owner=php['id'])
    out['tmpfs'] += [f'/var/www/html/bootstrap/cache:rw,nosuid,size=32m,uid={uid},gid={gid}',
                    f'/var/www/html/storage/framework/views:rw,nosuid,size=32m,uid={uid},gid={gid}',
                    f'/var/www/html/storage/framework/cache:rw,nosuid,size=32m,uid={uid},gid={gid}']
    if cfg.get('egress'):
        ctx.network(out, 'egress-' + s['id'], False)
    role = s['kind'].removeprefix('laravel-')
    commands = {'php': ['php-fpm', '--nodaemonize', '--fpm-config', '/run/dd/fpm.conf'],
                'worker': ['php', 'artisan', 'queue:work', '--sleep=3', '--tries=3', '--timeout=60',
                           '--queue=' + cfg.get('queue', 'default')],
                'scheduler': ['php', 'artisan', 'schedule:work']}
    # PHP reads secrets as data; proc_open argv avoids shell expansion and preserves signals via pcntl_exec.
    start = '<?php\ndeclare(strict_types=1);\numask(0027);\n'
    for key, path in secret_env.items():
        start += '$v=file_get_contents(' + json.dumps(path) + '); if($v===false){exit(1);} putenv(' + json.dumps(key + '=') + '.$v);\n'
    start += "if(!is_dir('/tmp/laravel/views') && !mkdir('/tmp/laravel/views',0700,true)){exit(1); }\n"
    start += "if(!is_dir('/var/www/html/storage/framework/cache/data') && !mkdir('/var/www/html/storage/framework/cache/data',0700,true)){exit(1); }\n"
    start += "umask(0077); $p=proc_open(['php','artisan','config:cache'],[STDIN,STDOUT,STDERR],$pipes); if(!is_resource($p)||proc_close($p)!==0){exit(1);}\n"
    start += "umask(0027);\n"
    command = commands[role]
    start += 'pcntl_exec(' + json.dumps('/usr/local/bin/' + command[0] if command[0] == 'php' else '/usr/local/sbin/php-fpm') + ',' + json.dumps(command[1:]) + '); exit(1);\n'
    ctx.file(s, out, 'start.php', start, '/run/dd/start.php')
    out['entrypoint'] = ['php', '/run/dd/start.php']
    out['stop_grace_period'] = str(cfg.get('stop_grace_seconds', 90)) + 's'
    if role == 'php':
        ctx.network(out, 'backend')
        ctx.file(s, out, 'fpm.conf', '[global]\ndaemonize = no\nerror_log = /proc/self/fd/2\n[www]\nlisten = 0.0.0.0:9000\npm = dynamic\npm.max_children = 10\npm.start_servers = 2\npm.min_spare_servers = 1\npm.max_spare_servers = 3\nclear_env = no\ncatch_workers_output = yes\n', '/run/dd/fpm.conf')
        # Dedicated PHP parser requires an actual HTTP status (implicit CGI 200 permitted only without Status).
        probe = '#!/bin/sh\nset -eu\nexport SCRIPT_FILENAME=/var/www/html/public/index.php REQUEST_METHOD=GET REQUEST_URI=' + cfg.get('health_path', '/up') + '\n' + "cgi-fcgi -bind -connect 127.0.0.1:9000 > /tmp/health.out\nphp /run/dd/health.php\n"
        ctx.file(s, out, 'health.sh', probe, '/run/dd/health.sh')
        ctx.file(s, out, 'health.php', '<?php $s=file_get_contents("/tmp/health.out"); if(!$s || !str_contains($s,"\\r\\n\\r\\n")){exit(1);} $h=explode("\\r\\n\\r\\n",$s,2)[0]; exit(preg_match("/^Status:\\s*(\\d+)/mi",$h,$m) && (int)$m[1]!==200 ? 1 : 0);', '/run/dd/health.php')
        health(out, ['CMD', 'sh', '/run/dd/health.sh'])
    else:
        # Process readiness does not certify jobs; acceptance evidence must run a fixture job/schedule.
        health(out, ['CMD', 'php', '-r', '$ok=false; foreach(glob("/proc/[0-9]*/cmdline") as $f){if($f==="/proc/".getmypid()."/cmdline")continue; $c=@file_get_contents($f); if($c!==false && str_contains($c,"artisan\\0' + ('queue:work' if role == 'worker' else 'schedule:work') + '")){$ok=true;}} exit($ok?0:1);'])
        ctx.bundle['warnings'].append(s['id'] + ': lifecycle probe only; queue/schedule functional acceptance required in release evidence.')
