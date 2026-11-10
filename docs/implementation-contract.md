# Kontrak internal controller dan Ansible

[Beranda](../README.md) · [Indeks dokumentasi](README.md)

This document coordinates the Python controller and Ansible executor. User instructions are in README.md. No live host credentials or fabricated image digests are shipped as deployable examples.

Python package: `src/dynamic_deployment`; Python >=3.12; PyYAML 6.0.3. Use standard-library unittest (test files `tests/test_*.py`). Modules accept/return plain JSON-compatible dictionaries; never mutate caller input. `errors.py` provides `ValidationError(ValueError)` and `OperationError(RuntimeError)`.

## Configuration v1

Top-level keys: `schema_version: 1`, `environment: development|staging|production`, `deployment: slug`, `hosts: mapping`, `services: list`, optional `secrets_file: local Vault path`, `production: mapping`.

Host keys: `address` private IPv4, `user` safe identifier, `port` (22 default), `private_key_file` absolute local path, `runtime_root` (/opt/dynamic-deployment default), `data_root` (/srv/dynamic-deployment default), `expected_mount` absolute remote path, `bootstrap` bool false default, `allowed_cidrs` nonempty list of private CIDRs for published ports, `firewall_check` absolute remote executable path (required when ingress/egress/remote connections exist; must be operator supplied, root-owned non-writable by group/other). Deployment paths append environment/deployment. No caller-controlled shell snippets. SSH host key checking stays enabled.

Service keys: `id: slug`, `kind` one of postgres,mariadb,redis,minio,nginx,apache,phpmyadmin,laravel-web,laravel-php,laravel-worker,laravel-scheduler; `host: host ID`, `image: repository:version@sha256:<64hex>` (no latest; fixture digests must be flagged as unverified), `enabled: bool` default true; `depends_on: [service IDs]`; `config: mapping`; `secrets: {name: Vault variable name}` (values never literals); `resources: {cpus: number, memory: string e.g. 512m, pids: integer}` defaults 1,512m,256. No arbitrary compose override/command/environment/volumes fields.

Allowed config keys per kind (all strings except named types): postgres/mariadb: database,username,uid(integer),gid(integer),publish_port(integer optional),tls_ca,tls_cert,tls_key,server_name. redis: maxmemory,uid,gid,publish_port,tls_ca,tls_cert,tls_key,server_name. minio: s3_domain,console_domain,license_file,tls_ca,tls_cert,tls_key,server_name,uid,gid,publish_port,console_port (optional integer; only private),release_evidence_file. nginx/apache: routes (list objects {domain,target,port(optional integer),protocol:http|https(default http),tls_ca(optional local path)}),tls_cert,tls_key,https_port(integer default 443),role:admin(default)|application. phpmyadmin: database_service (ID). laravel-web: php_service(ID),tls_cert,tls_key,https_port,domain,release_id,upload_path(optional relative subpath). laravel-php/worker/scheduler: database_service,redis_service,storage_service,release_id,health_path(default /up),queue(optional safe string),stop_grace_seconds(integer),upload_path(optional relative subpath),egress(list objects {host,port}),uid,gid,php_version,session_driver:database|redis|file,app_url. PHP app secrets `app_key` required; postgres/mariadb secrets `password` and mariadb `root_password`; redis `password`; minio `root_user`,`root_password`; others optional. All PHP processes must use same image digest/release and dependency values on same application profile. PHP frontend/worker cardinality follows one role per host/deployment; laravel-web and PHP same host. TLS/license paths refer to local files copied as protected assets, excluded from plan content except path/fingerprint.

Production keys: owner,rpo_minutes,rto_minutes,backup_destination,backup_schedule,backup_retention_days,release_evidence_file,restore_evidence_file. Production apply requires external evidence and secrets; local checks never certify production readiness. Images supplied by operator and actual evidence must be validated before deployment; no fake latest fallback.

## Core interfaces

`config.load_config(path: Path|str) -> dict`: safe JSON/YAML, reject duplicate keys/unknown fields, normalize defaults; validates configuration without requiring actual local assets (that is preflight). `config.validate_config(value: dict) -> dict`: same normalization, frozen-by-copy contract.

`config.service_order(config: dict) -> list[str]`: enabled services dependency topological order. Explicit/inferred dependency errors and cycles rejected. Disabled providers cannot have enabled consumers. Local connection topology rejected on unsupported combinations rather than falling back to plaintext.

`render.render_host(config: dict, host_id: str) -> dict`: returns `{compose: dict, files: {relative_path: text}, secret_files: {relative_path: vault_key}, asset_files: {relative_path: local_path}, directories: [relative_data_subdir], endpoints: [{service,url}], warnings: [str]}`. `render.render_all(config) -> {host_id: bundle}`. Compose bind paths use <runtime_root>/<env>/<deployment>/ for files/secrets/assets and <data_root>/<env>/<deployment>/ for data. Each compose service key is service ID, no container_name. One private data network per dependency, web/backend separate, management separate, uplinks per role. No placeholder plaintext secret or shell interpolation of config. Service commands fixed by kind; files generated with safe escaped validated fields. Ansible receives these bundles unchanged.

## Kontrak CLI aktual

Jalankan `./setup.sh --help` dari root repository untuk daftar opsi yang berlaku.

| Operasi | Argumen utama |
| --- | --- |
| wizard | `--output PATH` |
| validate, plan | `CONFIG` sebagai argumen posisi |
| secrets-init | `--config PATH`, opsional `--vault-password-file PATH` |
| apply | `--plan PATH --environment NAME --deployment NAME` |
| preflight, status, logs | `--config PATH`, opsional `--host ID --service ID` |
| stop | `--config PATH --host ID --service ID --yes` |
| backup | `--config PATH --host ID --service ID --backup-id ID --destination PATH --recipient AGE` |
| restore | `--config PATH --host ID --service ID --archive PATH --identity-file PATH` |

`--state-dir PATH` adalah opsi global sebelum nama operasi. State default memakai
direktori privat user; lihat `state.py` untuk lokasi aktual. Plan mencatat identitas
konfigurasi dan fingerprint asset, lalu diverifikasi ulang sebelum apply. Jangan
menambahkan `plan --config`, `--check-hosts` atau `apply --yes`: opsi tersebut tidak
tersedia. Preflight remote menjadi bagian apply, bukan opsi untuk melewatinya.

## Ansible interface

Root executor writes temporary inventory JSON and vars JSON (mode0600) then uses subprocess argv, no shell. `ansible/preflight.yml`, `ansible/operate.yml` entrypoints, `ansible/ansible.cfg`, requirements pinned collection. Vars: `dd_environment`, `dd_deployment`, `dd_operation` (apply,status,logs,stop,backup,restore), `dd_run_id` safe slug, `dd_hosts` config hosts, `dd_bundles` rendered per-host, `dd_services` normalized services, `dd_secrets` decrypted Vault mapping, `dd_selected_services` list IDs (empty=all), `dd_backup` optional operation settings. Host inventory_hostname equals host ID. Inventory connection vars supplied by root. Runtime/data roots derived on target. preflight must not mutate host; localhost temp/cache okay. Validate Ubuntu24 amd64 SSH/sudo paths disk mount, capabilities and firewall provider. operate must lock target before any mutation; shared host lock protects overlapping deployments and bootstrap, release only owned locks. Reconcile stale locks, never delete by age. No down-v/prune; no destructive restore active data; no arbitrary remote command from input. Status/logs capture and return markers or fetched result path safe to parse; failed/unreachable -> nonzero.

## Integrasi infrastructure existing

`infrastructure/scripts/manage.py` merupakan sumber operasi stack shared.
`make infra-*` mendelegasikan ke Makefile infrastructure; playbook
`ansible/infrastructure.yml` memanggil manager yang sama pada checkout target.
Kontrak `dd_*` di atas hanya untuk controller dynamic. Jangan meneruskan vars
`infra_*` ke operate.yml atau menganggap stack shared memiliki gate dynamic.

Referensi implementasi: `src/dynamic_deployment/cli.py`, `executor.py`, `state.py`
dan `ansible/files/guard.py`. Perubahan kontrak harus disertai perubahan tes yang
memeriksa perilaku terkait.
