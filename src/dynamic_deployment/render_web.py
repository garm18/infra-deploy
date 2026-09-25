"""TLS reverse proxy adapters with fixed routing and protected Laravel front controller."""


def nginx_config(blocks):
    return 'pid /tmp/nginx.pid;\nerror_log /dev/stderr warn;\nevents {}\nhttp {\ninclude /etc/nginx/mime.types;\naccess_log /dev/stdout;\nclient_body_temp_path /tmp/client;\nproxy_temp_path /tmp/proxy;\nfastcgi_temp_path /tmp/fastcgi;\nuwsgi_temp_path /tmp/uwsgi;\nscgi_temp_path /tmp/scgi;\nmap $http_upgrade $connection_upgrade { default upgrade; "" close; }\n' + '\n'.join(blocks) + '\n}\n'


def server(domain, body):
    return ('server { listen 8443 ssl; server_name ' + domain + ';\n'
            'ssl_certificate /run/assets/tls_cert; ssl_certificate_key /run/assets/tls_key;\n'
            'ssl_protocols TLSv1.2 TLSv1.3;\n' + body + '\n}')


def web(ctx, s, out):
    from .render_services import health, tls
    cfg, kind = s.get('config', {}), s['kind']
    if kind == 'phpmyadmin':
        host, port, remote = ctx.connect(s, out, cfg['database_service'])
        if remote or ctx.services[cfg['database_service']].get('config', {}).get('tls_cert'):
            raise ValueError('phpMyAdmin TLS hostname verification adapter unsupported v1')
        out['read_only'] = False
        out['cap_add'] = ['CHOWN', 'SETUID', 'SETGID', 'NET_BIND_SERVICE']
        out['environment'] = {'PMA_HOST': host, 'PMA_PORT': str(port), 'PMA_ARBITRARY': '0'}
        ctx.network(out, 'management')
        health(out, ['CMD', 'php', '-r', '$s=@file_get_contents("http://127.0.0.1/");exit($s===false?1:0);'])
        ctx.bundle['warnings'].append(s['id'] + ': official Apache phpMyAdmin entrypoint requires writable rootfs/root bootstrap; no automatic DB login.')
        return
    tls(ctx, s, out)
    out['user'] = '101:101' if kind != 'apache' else '82:82'
    ctx.network(out, 'frontend' if kind == 'laravel-web' or cfg.get('role') == 'application' else 'admin-entry', False)
    blocks = []
    if kind == 'laravel-web':
        target, _, _ = ctx.connect(s, out, cfg['php_service'])
        out['group_add'] = [str(ctx.services[cfg['php_service']].get('config', {}).get('gid', 1000))]
        domain = cfg['domain']
        body = ('root /usr/share/nginx/html;\nindex index.php;\n'
            'location ~ /\\. { deny all; }\nlocation ~* ^/storage/.*\\.php$ { deny all; }\n'
            'location / { try_files $uri $uri/ /index.php?$query_string; }\n'
            'location = /index.php { include /etc/nginx/fastcgi_params; fastcgi_param SCRIPT_FILENAME /var/www/html/public/index.php; '
            'fastcgi_param HTTPS on; fastcgi_pass ' + target + ':9000; }\n'
            'location ~* \\.php(?:/|$) { return 404; }')
        blocks.append(server(domain, body))
        ctx.persistent(s, out, 'uploads', '/usr/share/nginx/html/storage', True, cfg['php_service'])
    else:
        for route in cfg.get('routes', []):
            target, port, remote = ctx.connect(s, out, route['target'])
            domain = route['domain']
            protocol = route.get('protocol', 'https' if remote else 'http')
            port = route.get('port', 9001 if ctx.services[route['target']]['kind'] == 'minio' else port)
            if remote and ctx.services[route['target']]['kind'] == 'minio':
                port = ctx.services[route['target']]['config']['console_port' if port == 9001 else 'publish_port']
            provider = ctx.services[route['target']].get('config', {})
            if protocol == 'https' and not remote:
                target = provider.get('server_name', target)
            verify = ''
            if protocol == 'https':
                ca = route.get('tls_ca') or ctx.services[route['target']].get('config', {}).get('tls_ca')
                if not ca:
                    raise ValueError('HTTPS route requires trusted CA')
                ctx.asset(s, out, route['target'] + '-proxy-ca', ca, '/run/assets/' + route['target'] + '-proxy-ca')
                verify = 'proxy_ssl_verify on; proxy_ssl_server_name on; proxy_ssl_trusted_certificate /run/assets/' + route['target'] + '-proxy-ca;'
            body = 'client_max_body_size 0;\nlocation / { proxy_request_buffering off; proxy_buffering off; proxy_read_timeout 300s; proxy_pass ' + protocol + '://' + target + ':' + str(port) + '; proxy_set_header Host $http_host; proxy_set_header X-Forwarded-Proto https; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection $connection_upgrade; ' + verify + ' }'
            blocks.append(server(domain, body))
        if not blocks:
            raise ValueError('Proxy requires at least one route')
    if kind == 'apache':
        apache(ctx, s, out)
    else:
        ctx.file(s, out, 'nginx.conf', nginx_config(blocks), '/etc/nginx/nginx.conf')
        out['entrypoint'] = ['nginx', '-g', 'daemon off;']
        health(out, ['CMD', 'nginx', '-t'])
    domains = [cfg['domain']] if kind == 'laravel-web' else [r['domain'] for r in cfg['routes']]
    ctx.endpoint(s, out, cfg.get('https_port', 443), 8443, domains[0])
    for domain in domains[1:]:
        port = cfg.get('https_port', 443)
        ctx.bundle['endpoints'].append({'service': s['id'], 'url': 'https://' + domain + (':' + str(port) if port != 443 else '')})
    ctx.bundle['warnings'].append(s['id'] + ': syntax probe is not route acceptance; runtime HTTPS request evidence required.')


def apache(ctx, s, out):
    from .render_services import health
    cfg = s['config']
    conf = 'ServerRoot "/usr/local/apache2"\nListen 8443\nPidFile /tmp/httpd.pid\nServerName localhost\n'
    modules = ['mpm_event', 'authz_core', 'unixd', 'log_config', 'ssl', 'socache_shmcb', 'proxy', 'proxy_http', 'headers']
    conf += ''.join('LoadModule ' + m + '_module modules/mod_' + m + '.so\n' for m in modules)
    conf += 'User daemon\nGroup daemon\nErrorLog /proc/self/fd/2\nLogFormat "%h %l %u %t \\"%r\\" %>s %b" common\nCustomLog /proc/self/fd/1 common\nSSLSessionCache none\nDefaultRuntimeDir /tmp\nMutex file:/tmp default\n'
    for route in cfg['routes']:
        target = ctx.services[route['target']]
        if target['host'] != s['host'] or route.get('protocol', 'http') != 'http':
            raise ValueError('Apache remote/TLS upstream unsupported v1; use Nginx')
        from .render import PORTS
        port = route.get('port', PORTS.get(target['kind'], 80))
        upstream = 'http://' + target['id'] + ':' + str(port) + '/'
        conf += '<VirtualHost *:8443>\nServerName ' + route['domain'] + '\nSSLEngine on\nSSLCertificateFile /run/assets/tls_cert\nSSLCertificateKeyFile /run/assets/tls_key\nSSLProtocol -all +TLSv1.2 +TLSv1.3\nProxyPreserveHost On\nRequestHeader set X-Forwarded-Proto "https"\nProxyPass / ' + upstream + '\nProxyPassReverse / ' + upstream + '\n</VirtualHost>\n'
    ctx.file(s, out, 'httpd.conf', conf, '/usr/local/apache2/conf/httpd.conf')
    out['entrypoint'] = ['httpd', '-DFOREGROUND']
    health(out, ['CMD', 'httpd', '-t'])
