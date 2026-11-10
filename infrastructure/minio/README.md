# MinIO Community existing

[Beranda](../../README.md) · [Indeks dokumentasi](../../docs/README.md)

Compose memakai `minio/minio:RELEASE.2025-04-22T22-12-26Z`. Release ini dipertahankan
untuk kompatibilitas Console existing, bukan rekomendasi versi terbaru. Profil
MinIO dynamic memakai AIStor dan persyaratan berbeda; jangan menukar image langsung.

## Siapkan konfigurasi

Dari root repository jalankan `make infra-init SERVICES=minio`. File .env existing
tidak ditimpa. Edit `infrastructure/minio/.env`: gunakan root user/password unik,
MINIO_DATA_DIR pada storage persisten dan MINIO_BROWSER_REDIRECT_URL sesuai URL
Console bila menggunakan proxy. Aplikasi memakai access key dengan hak minimum.

## Jalankan

Semua perintah berikut dari root repository:

```bash
make infra-check ENV=local SERVICES=minio
make infra-up ENV=local SERVICES=minio
make infra-ps ENV=local SERVICES=minio
```

Local memakai named volume dan port 127.0.0.1:9000 untuk S3, 9001 untuk Console.
Untuk staging/production, siapkan bind mount lalu ganti ENV sesuai server tujuan.
Compose base tidak mempublish port MinIO ke host.

## Akses melalui proxy

Template `../proxy-nginx/sites-available/minio.conf` belum aktif. Isi hostname
S3 dan Console yang berbeda, lalu aktifkan di sites-enabled sesuai kebutuhan.
Upstream S3 adalah minio-storage:9000; Console minio-storage:9001. Set redirect URL
ke hostname Console final. Uji upload/download, autentikasi IAM, Console dan
restore sebelum perubahan image atau cutover.
