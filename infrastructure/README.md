# Shared infrastructure — production runbook

[Beranda](../README.md) · [Indeks dokumentasi](../docs/README.md)

Konfigurasi single-host Docker Compose untuk PostgreSQL, MariaDB, Redis, MinIO,
Nginx, dan Apache. Semua layanan dikelola dari subfolder masing-masing. Ini bukan
cluster HA: kerusakan host/storage tetap menyebabkan downtime. Tidak ada deploy,
rotasi credential, atau migrasi data yang dijalankan saat file ini diperbarui.

## Persyaratan

- Linux + Docker Engine dengan Compose **>= 2.24.4** (`!override`).
- Python 3 untuk preflight; PyYAML hanya untuk tes kontrak MinIO.
- Disk `/mnt/data` sudah tersedia dan dimonitor. Production bind mount tidak
  membuat direktori data yang hilang secara otomatis.
- External network `shared-network` tersedia. Buat sekali dengan
  `docker network create shared-network` bila belum ada.
- Pilih proxy yang memang digunakan. Nginx port 8080 dan Apache port 8081 adalah
  HTTP origin di belakang TLS load balancer; firewall/security group harus
  membatasi origin ke load balancer. Jangan menganggap Docker published ports
  otomatis terlindungi oleh aturan UFW biasa.

## Konfigurasi sebelum deploy

1. Per layanan, salin `.env.example` ke `.env` **hanya jika belum ada**. Jika sudah
   ada, tambahkan key baru tanpa menimpa credential yang sedang digunakan.
   `.env` lama di workspace tidak diubah otomatis dan masih harus diperiksa.
2. Gunakan password acak unik minimal 16 karakter, misalnya hasil
   `openssl rand -hex 32`. Masukkan melalui editor/secret manager, bukan chat/log.
   Gunakan single quote untuk literal yang mengandung `$`, spasi, atau `#`.
   Batasi permission `.env` menjadi `0600` pada host Linux.
3. Pin image database dan proxy ke versi kompatibel yang sudah diuji, idealnya
   `tag@sha256:...`. Default
   PostgreSQL 16, MariaDB 11, Redis 7, dan Nginx 1.27 mempertahankan garis versi
   lama; tag tersebut masih mutable. Jangan menurunkan versi database existing
   hanya untuk mengikuti contoh. MinIO memakai release Quay yang dipin langsung
   di Compose agar Console GUI legacy tetap tersedia.
4. Siapkan direktori data berikut dan ownership sesuai image yang dipilih.
   Pastikan mount disk benar dengan `findmnt -T /mnt/data`, bukan sekadar ada
   folder bernama `/mnt/data`. Jangan menjalankan `chown -R` membabi buta pada
   database existing.

| Layanan | Host data directory | Port production |
|---|---|---|
| PostgreSQL | Docker volume `postgres-career-data` on Docker Desktop/WSL | Internal Docker 5432 |
| MariaDB | `/mnt/data/mariadb` | Internal Docker 3306 |
| Redis | Tidak ada; cache ephemeral | Internal Docker 6379 |
| MinIO | `/mnt/data/minio` | Internal Docker 9000/9001 |
| Nginx | Log ke Docker | HTTP 8080; HTTPS 8443 |
| Apache | Log ke Docker | HTTP 8081 |

5. Review domain/vhost di folder proxy. `*.localhost` merupakan konfigurasi
   pengembangan, bukan nama domain production. Tambahkan virtual host TLS dan
   certificate/key ke `ssl/` bila HTTPS di-terminate oleh Nginx; lihat
   [runbook Nginx](proxy-nginx/README.md).
6. Ikuti [runbook MinIO](minio/README.md) untuk Console GUI dan konfigurasi proxy.
7. Jalankan preflight dari folder `dynamic_deployment/infrastructure`:

```bash
python3 scripts/preflight.py --mode production postgres mariadb redis proxy-nginx
python3 scripts/preflight.py --mode production minio
```

Ganti `proxy-nginx` dengan `apache` bila itu proxy yang digunakan.

Preflight memeriksa credential placeholder, direktori bind mount, dan `docker compose config --quiet`. Ia tidak membuktikan konektivitas, IAM, backup, firewall, ataupun kondisi disk mount.
   Hindari membagikan output `docker compose config` tanpa `--quiet`: credential
   dapat tercetak. `--static` hanya memeriksa keberadaan file, bukan kesiapan deploy.

## Menjalankan layanan

Setelah preflight lulus, dari subfolder layanan:

```bash
docker compose config --quiet
docker compose pull
docker compose up -d --wait --wait-timeout 180
docker compose ps
```

Jalankan database/cache sebelum aplikasi. Proxy HTTP healthcheck hanya membuktikan
proxy hidup; uji URL aplikasi melalui domain sebenarnya secara terpisah.
`restart: unless-stopped` tidak otomatis me-restart container berstatus unhealthy
jika prosesnya masih berjalan: monitoring tetap wajib.

## Pengembangan lokal

Gunakan `.env` khusus workstation, jangan credential production. Setiap layanan
memiliki override `docker-compose.local.yml`. Dari subfolder layanan:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --wait
```

Semua port lokal bind `127.0.0.1`. Data memakai named volume terpisah. Nama
container/network masih sama untuk kompatibilitas aplikasi: production dan local
tidak ditujukan berjalan bersamaan di satu Docker daemon. Update credential
aplikasi secara terencana; file aplikasi tidak diubah oleh pekerjaan ini.

Override local membatasi published port ke `127.0.0.1`; data database dan MinIO
menggunakan named volume disposable. Jangan menggabungkan konfigurasi local dan
production pada Docker daemon yang sama.

## Upgrade deployment yang sudah berisi data

- Backup konsisten dan uji restore sebelum mengganti image/config.
- PostgreSQL/MariaDB menerapkan environment inisialisasi hanya pada data kosong.
  Mengedit `.env` tidak mengganti password user existing. Sinkronkan perubahan
  akun database dan credential aplikasi dengan prosedur administrasi database.
- PostgreSQL memakai named volume `postgres-career-data` ke
  `/var/lib/postgresql/data`. Cluster lama di
  `/mnt/data/postgres/pgdata` tidak dipindahkan atau dipakai otomatis. Untuk
  mempertahankan data lama, hentikan service, backup dan uji restore ke path baru
  sebelum cutover. Jangan memulai PostgreSQL major version baru pada
  direktori cluster major version sebelumnya.
- PostgreSQL local lama mungkin memiliki `pg_hba.conf` berisi `trust`. Override
  baru tidak mengubah file itu. Migrasikan autentikasi cluster existing secara
  eksplisit dan uji penolakan password salah sebelum membuka akses jaringan.
- Volume MariaDB local sebelumnya diinisialisasi dengan credential hardcoded.
  Gunakan credential yang cocok dengan akun existing atau migrasikan akun;
  jangan menghapus volume untuk sekadar mengatasi kegagalan login.
- Redis adalah cache ephemeral dengan `allkeys-lfu`. Saat batas memori tercapai,
  key yang paling jarang digunakan dihapus. Jangan gunakan service ini untuk queue,
  session persisten, atau data yang harus bertahan setelah container restart.
- MinIO memakai storage `/mnt/data/minio`. Lihat runbook sebelum memindahkan data
  dari deployment lain.

## Operasional

- Redis dipakai sebagai cache ephemeral. `REDIS_MAXMEMORY` membatasi ukuran cache
  dan `allkeys-lfu` membuang key yang paling jarang dipakai saat batas tercapai.
- Semua service memakai `json-file` dengan rotasi 10 MB per file, maksimum
  tiga file. Siapkan pengiriman log terpusat sesuai kebutuhan.
- Backup PostgreSQL memakai dump/base backup yang konsisten; MariaDB memakai
  mariadb-dump/mariadb-backup yang kompatibel. Simpan off-host terenkripsi,
  tetapkan retensi/RPO/RTO, dan uji restore terisolasi berkala. Snapshot direktori
  database aktif tanpa koordinasi bukan bukti backup valid.
- Backup MinIO harus mencakup object dan metadata/IAM yang diperlukan. Simpan
  credential melalui secret storage terpisah dan uji IAM setelah restore.
- Shared network dipertahankan agar aplikasi existing tetap terhubung. Setiap
  aplikasi harus memiliki user database dan key S3 dengan hak minimum. Network
  ini belum mengisolasi aplikasi satu sama lain; segmentasi memerlukan perubahan
  Compose aplikasi di luar folder ini dan harus direncanakan tersendiri.
- `.gitignore` melindungi file baru dari tracking, tidak menghapus secret yang
  sudah pernah masuk Git. Jika pernah terpublikasi, rotasi dengan prosedur terpisah.

## Validasi konfigurasi

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s minio -p 'test_*.py' -v
```

Tes merge memakai `COMPOSE_BIN` (path absolut executable Compose standalone), atau
`.tools/docker-compose` bila tersedia. Jika tidak tersedia, tes merge ditandai
skip. CLI lokal di `.tools` hanya alat audit yang diabaikan Git, bukan dependency
runtime production. Gunakan Compose resmi dari instalasi Docker di server.

Pada perubahan ini, model base/local keenam layanan diuji menggunakan Compose
2.39.4 tanpa Docker daemon. Startup image, request HTTP nyata, S3/IAM/GUI, serta
restore masih harus diuji pada host staging sebelum production.
