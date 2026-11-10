# MinIO Community

This service uses the Quay image
`quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z`. It is pinned to keep the
legacy full Console GUI for bucket, user, access-key, and policy administration.
The Console listens on internal port 9001; the S3 API listens on internal port
9000.

## Configure

Copy `.env.example` to `.env` and set a unique root user and password. Keep
`MINIO_DATA_DIR` on persistent host storage. Set `MINIO_BROWSER_REDIRECT_URL` to
the external Console URL when using HTTPS through `proxy-nginx`.

```bash
docker network create shared-network # once, if absent
docker compose config --quiet
docker compose up -d --wait
```

## Console and S3 access

MinIO has no published host ports. Enable the template at
`../proxy-nginx/sites-available/minio.conf` after replacing its two example
domains:

- S3 API hostname routes to `minio-storage:9000`.
- Console hostname routes to `minio-storage:9001`.

Set `MINIO_BROWSER_REDIRECT_URL` to the final Console hostname. The proxy template
preserves S3 request semantics, disables upload buffering, and forwards Console
WebSocket connections.

This release is intentionally frozen for GUI compatibility. Test upgrades and
migration before changing the image tag. Use scoped access keys for applications;
reserve root credentials for administration and recovery.

## Local experiment

Combine the base file with `docker-compose.local.yml` to use a disposable named
volume and expose the S3 API and Console only on `127.0.0.1:9000` and
`127.0.0.1:9001`:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```
