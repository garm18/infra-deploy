# Apache reverse proxy existing

[Beranda](../../README.md) · [Indeks dokumentasi](../../docs/README.md)

Apache memakai `httpd:2.4.68-alpine` sebagai HTTP origin di belakang TLS load
balancer/proxy. Host port 8081 diteruskan ke port container 80. Batasi akses origin
ke load balancer yang dipercaya. Konfigurasi ini tidak mengaktifkan HTTPS langsung.

## Siapkan virtual host

Review ServerName dan upstream pada sites-enabled/. File sumber tersedia di
sites-available/. Upstream aplikasi harus bergabung ke shared-network. Vhost
staging meneruskan /elrt/ ke e-lrt-app:80; header forwarded HTTPS mengasumsikan TLS
diterminasi upstream. Sesuaikan dengan jalur traffic sebenarnya.

## Jalankan dan periksa

Dari root repository:

```bash
make infra-check ENV=local SERVICES=apache
make infra-up ENV=local SERVICES=apache
make infra-ps ENV=local SERVICES=apache
```

Local hanya membuka 127.0.0.1:8081. Untuk server tujuan, gunakan ENV=staging atau
production sesudah review domain, network dan firewall. Sebelum restart konfigurasi,
jalankan `docker compose exec proxy-apache httpd -t` dari direktori layanan.

Probe loopback container port 8083 hanya memeriksa proxy hidup, bukan aplikasi.
Uji URL aplikasi terpisah. Log stdout/stderr dirotasi Docker: 10 MB per file,
maksimum tiga file. Direktori ssl/ disediakan untuk aset lokal sesuai konfigurasi.
