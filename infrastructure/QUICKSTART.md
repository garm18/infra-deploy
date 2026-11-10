# Perintah harian

Untuk entrypoint utama lihat ../docs/integration.md. Perintah tanpa prefix di bawah
dijalankan dari folder dynamic_deployment/infrastructure. Make membutuhkan GNU Make dan Bash; Python 3
serta Docker Compose >=2.24.4 dibutuhkan untuk operasi container.

```bash
make help
make init
# Edit .env tiap layanan; init tidak menimpa file existing.
make check ENV=local
make up ENV=local
make ps
make logs SERVICES="postgres redis"
make stop SERVICES=redis
```

Untuk deployment, SSH ke server tujuan dan periksa `docker context show`.
Staging dan production wajib daemon/server terpisah: container, network dan nama
volume existing belum diisolasi agar dapat dipakai bersamaan pada satu daemon.
Keduanya menggunakan Compose base; local menambahkan override port loopback.

```bash
make check ENV=staging
make deploy ENV=staging SERVICES="postgres mariadb redis minio"
make up ENV=staging SERVICES=proxy-nginx
```

Pilih apache jika itu proxy yang digunakan. Siapkan credential, bind mount
`/mnt/data/mariadb`, `/mnt/data/minio`, firewall, domain/certificate dan upstream
aplikasi sebelum deploy. PostgreSQL memakai volume `postgres-career-data`.
Network dibuat saat up/deploy setelah preflight. Preflight tidak membuat data dir.

Sesudah staging lulus smoke test aplikasi, autentikasi dan restore backup,
jalankan perintah yang sama di server production dengan ENV=production.
Deploy melakukan pull, build PostgreSQL dengan `--pull`, lalu up dengan penantian
healthcheck. Error menghentikan proses; perubahan layanan sebelumnya tidak
rollback otomatis. Jangan jalankan dua deployment bersamaan.

`down` mempertahankan volume dan external network. Tidak ada target prune/hapus
data. Ikuti runbook README untuk backup dan rencana rollback yang sesuai format
data; mengganti .env tidak mengganti password database yang sudah diinisialisasi.

Arsip mengandung .env dan data MinIO. Jangan commit/publikasikan arsip tersebut.
Review credential secara privat sebelum dipakai; jangan cetak Compose config
resolved karena berisi credential.

## Image dan log

Dockerfile PostgreSQL tetap satu stage karena hanya membungkus image resmi tanpa
kompilasi. Official entrypoint membutuhkan root untuk inisialisasi storage lalu
menjalankan database sebagai postgres. USER paksa berisiko memutus inisialisasi.
Build context dikecualikan seluruhnya; healthcheck ditambahkan. Base dapat dipin
saat build manual melalui argument POSTGRES_IMAGE; major default tidak diganti.
Ukuran image dan waktu build belum diukur. Log tiap layanan dibatasi 3 x 10 MB.

Rujukan: [Compose services](https://docs.docker.com/reference/compose-file/services/)
dan [Docker cache](https://docs.docker.com/build/cache/optimize/).
