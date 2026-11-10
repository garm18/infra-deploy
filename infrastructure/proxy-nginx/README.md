# Nginx reverse proxy existing

[Beranda](../../README.md) · [Indeks dokumentasi](../../docs/README.md)

Nginx memakai nginx:1.27-alpine. Compose base mempublish HTTP 8080 dan port 8443
ke container 443. Port 8443 baru melayani TLS bila vhost listen 443 ssl serta
certificate/key sudah disiapkan. Batasi origin ke load balancer yang dipercaya.

## Siapkan virtual host

Review seluruh file sites-enabled/. Template disimpan di sites-available/.
Ganti domain .localhost sebelum server diakses melalui domain staging/production.
Vhost staging Nginx adalah referensi bila domain itu sudah ditangani Apache;
jangan mengaktifkan dua konfigurasi tanpa menentukan jalur traffic yang benar.
Header forwarded HTTPS mengasumsikan TLS termination pada load balancer.

Template minio.conf memerlukan hostname S3 dan Console berbeda sebelum diaktifkan.
Ia dapat digunakan untuk endpoint MinIO yang sesuai upstream; stack existing ini
menggunakan Community, sedangkan controller dynamic menggunakan profil AIStor.

## Jalankan dan periksa

Dari root repository:

```bash
make infra-check ENV=local SERVICES=proxy-nginx
make infra-up ENV=local SERVICES=proxy-nginx
make infra-ps ENV=local SERVICES=proxy-nginx
```

Local membatasi port ke 127.0.0.1. Ganti ENV dengan staging/production pada server
tujuan setelah review firewall dan TLS. Periksa konfigurasi dari direktori layanan
dengan `docker compose exec proxy-nginx nginx -t` sebelum restart.

DNS Docker me-resolve upstream dinamis; aplikasi yang belum tersedia dapat
menghasilkan 502. Probe 127.0.0.1:8081 di container hanya membuktikan proxy hidup.
Uji URL aplikasi dan autentikasi secara terpisah. Log Docker dibatasi 10 MB per
file dengan maksimum tiga file.
