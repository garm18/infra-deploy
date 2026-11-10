# Apache reverse proxy

HTTP origin behind a TLS proxy/load balancer, using `httpd:2.4.68-alpine`.
Active virtual hosts live in `sites-enabled/`; source files can live in
`sites-available/`. Set the `ServerName` in every enabled vhost before deployment.
The ELRT staging vhost forwards `/elrt/` to `e-lrt-app:80`; every backend must
join the external `shared-network`. Unknown hostnames are denied. Restrict origin
ingress to your proxy/load balancer.

```bash
docker network create shared-network # once, if absent
docker compose config --quiet
docker compose up -d
```

The service exposes host port 8081 to container port 80. The sample virtual host
forwards `X-Forwarded-Proto: https` and port 443 because TLS terminates at a
trusted upstream load balancer. The local override keeps the same port on
`127.0.0.1`:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

Health uses a static endpoint on container loopback port 8083, independent of the
application. Logs go to stdout/stderr and Docker uses its daemon default logging
policy. Validate changes with `docker compose exec proxy-apache httpd -t` before
restarting. The `ssl/` directory is reserved; this configuration does not enable
direct HTTPS.
