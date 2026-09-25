# Build Laravel yang wajib divalidasi dengan aplikasi aktual

Template `templates/laravel` adalah titik awal PHP-FPM + Nginx, bukan image aplikasi
siap production. Salin Dockerfile, `.dockerignore`, dan direktori `docker/` ke root
source aplikasi. Sesuaikan versi PHP/extension dari composer.lock, bukan upgrade
framework otomatis. Baseline asset memakai npm/package-lock.json dan output
`public/build`; untuk aplikasi tanpa asset Node, hapus stage assets dan COPY-nya.
Package discovery Composer yang diperlukan aplikasi harus ditambahkan sesudah
source tersedia, tanpa koneksi database atau secret production.

Berikan PHP_IMAGE, COMPOSER_IMAGE, NODE_IMAGE dan NGINX_IMAGE menggunakan
`--build-arg` berupa versi dan digest immutable. PHP_IMAGE harus sudah memuat
extension production yang tepat; tidak ada digest contoh yang dapat dianggap
terverifikasi. Build target `php` dan `web` dari commit/source sama lalu rekam
release ID dan digest kedua hasil. Build host harus memverifikasi argumen immutable;
Dockerfile sendiri tidak menegakkan kebijakan registry sebelum FROM diproses.
Jangan membangun ulang untuk production. Template web berkomunikasi ke service
`laravel-php:9000`; ubah hanya bila nama service renderer berbeda.

Sediakan writable mount storage sesuai driver session/upload aktual dan mount
bootstrap/cache per container, ber-UID/GID sesuai www-data image aktual. Jangan
menutup seluruh source/vendor dengan volume. Hanya subtree upload publik dapat
dimount read-only ke web; file PHP upload tidak boleh dieksekusi. Root filesystem
read-only memerlukan `/tmp` writable. Entrypoint melakukan config cache setelah
injeksi environment dan APP_KEY; tidak menjalankan migrasi, dependency install,
asset build, atau key generation. Konfigurasi cache dapat memuat secret: lindungi
izin dan jangan masukkan ke backup publik. Jangan sertakan secret yang tidak
dibutuhkan aplikasi karena pool FPM meneruskan environment container.

Untuk package privat, tambahkan BuildKit secret mount pada tahap dependency;
jangan COPY auth.json/.npmrc atau menggunakan ARG token. Review output builder
karena secret mount tidak mencegah script dependency menyalin secret ke artefak.

Sebelum penerimaan wajib uji aplikasi melalui FPM (termasuk DB/dependency), stop
dengan request/job berjalan, upload/session recreate dan restore, penolakan `.env`
dan PHP upload, kecocokan aset/source, serta matriks jaringan. Ukur ukuran image
dan waktu cold/cached build terhadap baseline yang disetujui. Hasil unit test alat
deployment bukan bukti uji Dockerfile atau kesiapan aplikasi. Rekam SBOM dan scan
High/Critical untuk digest yang tepat; alat scan tidak tersedia berarti belum lolos.

## Kontrak image dengan renderer

Target `web` menyimpan hanya `public/` di `/usr/share/nginx/html`; front controller
PHP tetap `/var/www/html/public/index.php`. Renderer mengganti konfigurasi Nginx
standalone dengan TLS dan DNS service terpilih. UID/GID default PHP adalah 1000:1000,
web 101:101; `group_add` web mengikuti GID PHP untuk membaca upload bersama. Jika
UID/GID PHP dikustomisasi, build image dengan kepemilikan yang sesuai terlebih dulu.
Direktori upload publik memiliki akses grup baca/traverse; jangan memberi izin
baca global ke seluruh storage. Cache konfigurasi secret dibuat dengan umask077,
kemudian proses aplikasi memakai umask027. Runtime tidak perlu menulis root storage.

PHP_IMAGE merupakan base yang dibangun/disetujui tim, berbasis tata letak image
PHP resmi: `/usr/local/bin/php`, `/usr/local/sbin/php-fpm`, extension pcntl, driver
PDO yang dipilih, Redis bila digunakan, dan binary `cgi-fcgi`. Composer dijalankan
pada PHP_IMAGE yang sama dengan runtime agar pemeriksaan platform relevan. Image
Composer hanya menyumbang executable. Template tidak memasang extension secara
spekulatif. Node/npm hanya pada build stage dan lockfile wajib tersedia.

Database PostgreSQL/Redis/MariaDB default memakai UID/GID999; image Alpine tertentu
memakai UID lain. Verifikasi `/etc/passwd`, owner data, binary probe dan versi image
aktual; isi uid/gid berdasarkan hasil tersebut. PostgreSQL initdb memerlukan UID
yang ada pada image; jangan mengandalkan fallback NSS pada filesystem read-only.
Lihat [catatan arbitrary user PostgreSQL](https://hub.docker.com/_/postgres).
`root_password` PostgreSQL hanya untuk bootstrap/admin; aplikasi memakai role
terpisah tanpa SUPERUSER/CREATEDB/CREATEROLE/REPLICATION. Inisialisasi bukan rotasi
password untuk data yang sudah ada.

Nginx merelokasi seluruh temporary path ke `/tmp`. Proxy S3 menjaga Host termasuk
port, menonaktifkan request buffering, dan mengizinkan body besar. Pengujian upload
serta signature S3 pada domain/port aktual tetap wajib. Probe AIStor menggunakan
HTTP readiness; keberadaan curl harus dibuktikan pada digest image, dan readiness
bukan bukti lisensi, GUI, maupun IAM. Lihat [healthcheck AIStor](https://docs.min.io/aistor/operations/monitoring/healthcheck-probe/).

TLS lokal dan remote PostgreSQL menggunakan hostname/CA terverifikasi untuk
Laravel. Laravel→MariaDB/Redis TLS dan phpMyAdmin→MariaDB TLS belum memiliki adapter
client terverifikasi, sehingga ditolak; gunakan provider lokal tanpa TLS di network
internal yang terisolasi untuk kombinasi tersebut. Apache mendukung upstream HTTP
lokal; gunakan Nginx untuk upstream HTTPS. Uji Docker/HTTP/FPM nyata belum tersedia
dalam environment pengerjaan ini; pemeriksaan struktur dan unit tidak menggantikannya.
