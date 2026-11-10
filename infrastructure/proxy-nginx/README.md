# Nginx reverse proxy

Base Compose exposes host ports 8080 and 8443 behind a TLS load balancer (ALB).
Restrict host ingress to the load balancer security group; staging deliberately
forwards `X-Forwarded-Proto: https` and port 443. Do not expose this origin directly
to the internet.

Active vhost files live in `sites-enabled/`; source files can live in
`sites-available/`. Review every enabled domain before deployment. ELRT staging
uses Apache; retain the Nginx `staging.conf` only as a reference and do not enable
it while Apache owns the staging domain. The current
`.localhost` entries are suitable only for a trusted development host; replace
them with real domains or remove their enabled file before exposing this proxy.
`staging.conf` preserves the `/elrt/` path and ALB HTTP routing.
Docker DNS resolves upstreams dynamically, allowing the proxy to start when an
application is absent; requests to an unavailable application return 502.
`sites-available/minio.conf` is a disabled template for AIStor. It requires
separate S3 and Console hostnames before being enabled.

```bash
docker network create shared-network # once, if absent
docker compose config --quiet
docker compose up -d
```

For local experiments, combine the base file with `docker-compose.local.yml`; it
binds ports 8080 and 8443 to `127.0.0.1`. Port 8443 maps to the container's port
443, but no TLS virtual host is included; it becomes usable only after a matching
`listen 443 ssl` server is added to an enabled site and its certificate/key are
supplied under `ssl/`.

Health checks use a container-only HTTP listener on 127.0.0.1:8081 and test proxy
liveness, not backend readiness. Logs go to stdout/stderr and Docker uses its
daemon default logging policy. The service uses `nginx:1.27-alpine`.
