# Dynamic Deployment

Stack `makefile-devops` kini berada di `infrastructure/`. Gunakan satu Makefile
utama; lihat [panduan integrasi Make dan Ansible](docs/integration.md).

Deploy layanan Docker Compose dengan alur aman dan mudah:

```text
Wizard → Validate → Secrets → Plan → Apply → Status
```

Layanan yang tersedia: PostgreSQL, MariaDB, Redis, MinIO AIStor, Nginx, Apache, phpMyAdmin, dan profil Laravel.

Untuk automation bertahap, mulai dari [panduan Makefile dan contoh direktori](docs/automation.md).
Jalankan `make help` dari folder ini. Make memakai controller Ansible existing; stack shared juga memiliki entrypoint Ansible tersendiri.

Hasil audit dan gate keamanan sebelum staging/production tersedia di
[security best practices](docs/security-best-practices.md).

## Daftar isi

- [Prasyarat](#prasyarat)
- [Quick start: local PostgreSQL](#quick-start-local-postgresql)
- [Perbedaan environment](#perbedaan-environment)
- [Staging](#staging)
- [Production](#production)
- [Mode koneksi host](#mode-koneksi-host)
- [Jaringan Laravel](#jaringan-laravel)
- [MinIO full GUI](#minio-full-gui)
- [Operasi harian](#operasi-harian)
- [Aturan keamanan](#aturan-keamanan)

---

## Prasyarat

Masuk ke direktori project dan jalankan pemeriksaan controller:

```bash
cd /mnt/d/project_local/dynamic_deployment
./setup.sh doctor
```

Pastikan output `doctor` menampilkan nilai `true` untuk:

- `ansible-playbook`
- `ansible-vault`
- `openssl`
- `docker` untuk menjalankan layanan container

### Lokasi file yang aman

| File | Lokasi yang disarankan |
| --- | --- |
| Konfigurasi deployment | `/mnt/d/testing/*.json` |
| SSH private key | Filesystem Linux/WSL, mode `0600` |
| Vault password file | Filesystem Linux/WSL, mode `0600` |
| Controller state | `~/.local/state/dynamic-deployment` |

> [!IMPORTANT]
> Jangan menyimpan SSH private key atau Vault password file di `/mnt/d`. Mount Windows tidak menyimpan permission Linux `0600` dengan benar sehingga controller akan menolaknya. File konfigurasi boleh disimpan di `/mnt/d` karena tidak memuat nilai secret.

---

## Quick start: local PostgreSQL

Gunakan panduan ini untuk test awal di komputer sendiri. Mode `local` tidak membutuhkan SSH private key maupun password SSH, dan seluruh port hanya terikat ke `127.0.0.1`.

### 1. Periksa Docker dan sudo

```bash
docker info
sudo -n true
```

Kedua perintah harus berhasil. User local memerlukan `sudo` tanpa prompt password karena operasi Docker dijalankan sebagai root oleh Ansible.

### 2. Jalankan wizard

```bash
./setup.sh wizard --output /mnt/d/testing/development.json
```

Gunakan jawaban berikut untuk test PostgreSQL minimal:

```text
Environment: development
Deployment name: local-test
Host ID: local
Connection mode: local
Local user with passwordless sudo: press Enter
Existing data mount: /
Local persistent data root: /tmp/dynamic-deployment-data
Local runtime root: /tmp/dynamic-deployment-runtime
Add or edit another host: n
Active service numbers separated by spaces: 1
Image for postgres: postgres:16.8
Application database name: testapp
Application user: testuser
Environment Ansible Vault path: ~/.local/share/dynamic-deployment/local-test.vault.yml
```

> [!TIP]
> Cara paling mudah: isi `postgres:16.8` pada pertanyaan image. Untuk konfigurasi baru, Anda juga bisa menekan Enter lalu mengisi `16.8` pada pertanyaan versi. Jika nilai lama tampil dalam `[ ... ]`, Enter mempertahankannya. Angka `16.8` adalah contoh format, bukan rekomendasi versi terbaru. Controller mencari dan mengunci digest secara otomatis.

Untuk test pertama, pilih service nomor `1` saja. MinIO dan Laravel membutuhkan asset tambahan.

### 3. Validasi konfigurasi

```bash
./setup.sh validate /mnt/d/testing/development.json
```

Perbaiki seluruh error sebelum melanjutkan.

### 4. Buat Ansible Vault

```bash
./setup.sh secrets-init --config /mnt/d/testing/development.json
```

Ansible akan meminta password Vault. Simpan password tersebut dengan aman karena diperlukan untuk apply berikutnya.

### 5. Buat plan

```bash
./setup.sh plan /mnt/d/testing/development.json
```

Salin path plan dari output, misalnya:

```text
~/.local/state/dynamic-deployment/plans/RUN_ID.json
```

### 6. Terapkan plan

```bash
./setup.sh apply \
  --plan ~/.local/state/dynamic-deployment/plans/RUN_ID.json \
  --environment development \
  --deployment local-test
```

### 7. Periksa status

```bash
./setup.sh status \
  --config /mnt/d/testing/development.json \
  --host local
```

---

## Perbedaan environment

Gunakan konfigurasi, Vault, data root, dan deployment name yang berbeda untuk setiap environment.

| Area | Development | Staging | Production |
| --- | --- | --- | --- |
| Tujuan | Belajar dan development local | Uji deployment menyerupai production | Menjalankan layanan pengguna nyata |
| Lokasi | Mesin local | Server privat terpisah | Server privat terpisah |
| Connection mode | `local` | `ssh-password`, `ssh-key`, atau `ssh-agent` | Sebaiknya `ssh-key` atau `ssh-agent` |
| Port binding | `127.0.0.1` | IP privat + firewall/CIDR | IP privat + firewall/CIDR |
| Data | Data test | Data sintetis atau tersanitasi | Data nyata, tidak dihapus controller |
| Image | Version dan digest wajib | Digest release candidate wajib | Digest + release evidence wajib |
| Backup | Opsional | Restore drill disarankan | Backup terenkripsi + restore evidence wajib |
| MinIO GUI | Tidak disarankan untuk test awal | Internal/VPN + GUI/S3 evidence | Internal/VPN + license + GUI/S3 evidence |

Contoh penamaan file:

```text
/mnt/d/testing/development.json
/mnt/d/testing/staging.json
/mnt/d/testing/production.json
```

---

## Staging

### Persiapan server

1. Siapkan Ubuntu Server privat.
2. Buat user SSH yang dapat menjalankan `sudo -n`.
3. Siapkan Docker Compose v2.
4. Siapkan data mount khusus staging.
5. Pastikan IP target adalah private IPv4.

### Deployment staging

```bash
./setup.sh wizard --output /mnt/d/testing/staging.json
./setup.sh validate /mnt/d/testing/staging.json
./setup.sh plan /mnt/d/testing/staging.json
```

Pilih `Environment: staging`, lalu gunakan path plan yang dihasilkan:

```bash
./setup.sh apply \
  --plan ~/.local/state/dynamic-deployment/plans/RUN_ID.json \
  --environment staging \
  --deployment staging-app \
  --vault-password-file /path/to/vault-password
```

> [!NOTE]
> Bila memakai `ssh-password`, password login server harus dimasukkan manual ke Ansible Vault. `secrets-init` tidak membuat password SSH acak karena password tersebut tidak bisa dipakai untuk login ke server.

---

## Production

Production mengikuti langkah staging dengan gate tambahan.

### Checklist sebelum apply

- [ ] Server dan data mount khusus production tersedia.
- [ ] SSH key atau SSH agent digunakan bila tersedia.
- [ ] Owner, RPO, RTO, retention, dan backup destination sudah diisi.
- [ ] Image scan dan SBOM sudah dilakukan.
- [ ] [Release evidence](docs/release-evidence.md) masih berlaku.
- [ ] Restore drill telah berhasil pada deployment baru yang terisolasi.
- [ ] Output `plan` sudah ditinjau.

### Apply production

```bash
./setup.sh apply \
  --plan ~/.local/state/dynamic-deployment/plans/RUN_ID.json \
  --environment production \
  --deployment production-app \
  --vault-password-file /path/to/vault-password
```

Production menolak:

- Evidence kedaluwarsa atau belum lengkap.
- Image digest yang belum diterima.
- Restore evidence yang belum ada.
- Perubahan host, kind, atau image pada layanan stateful.

Untuk perubahan layanan stateful, buat deployment baru lalu lakukan isolated restore.

---

## Mode koneksi host

| Mode | Digunakan untuk | Credential |
| --- | --- | --- |
| `local` | Test pada komputer sendiri | Tidak memakai SSH |
| `ssh-password` | Server sementara yang hanya menerima password | Password existing dalam Ansible Vault |
| `ssh-key` | Server dengan SSH private key | Key Linux/WSL mode `0600` |
| `ssh-agent` | Key sudah dimuat pada SSH agent | Tidak menyimpan key path di konfigurasi |

> [!WARNING]
> Password SSH bukan pengganti password sudo. Semua operasi remote tetap memerlukan user yang dapat menjalankan `sudo -n`.

---

## Jaringan Laravel

Laravel dapat tetap menjadi satu repository dan satu aplikasi PHP. Controller memisahkan jaringan container, bukan memaksa pemisahan repository frontend/backend.

| Kebutuhan | Jalur jaringan |
| --- | --- |
| Browser ke Laravel | frontend → `laravel-web` melalui HTTPS |
| Web ke PHP-FPM | backend privat pada host yang sama |
| PHP ke PostgreSQL/MariaDB/Redis/MinIO | Jaringan data per dependency |
| MinIO Console/phpMyAdmin | Nginx admin HTTPS, hanya CIDR internal/VPN |

Database dan MinIO tidak dipublish secara default. Remote PostgreSQL dan MinIO wajib menggunakan TLS, CA, hostname, firewall validator, dan CIDR allowlist. Laravel MariaDB/Redis serta phpMyAdmin saat ini harus berada pada host yang sama dengan provider datanya.

---

## MinIO full GUI

Full GUI administrasi memerlukan **MinIO AIStor Free**:

- Image: `quay.io/minio/aistor/minio`
- License operator
- TLS internal
- Nginx admin proxy
- Akses hanya dari internal network atau VPN

Apply MinIO memerlukan evidence yang belum kedaluwarsa untuk runtime, network, GUI, serta authenticated S3 write/read/delete probe. MinIO Community tidak diklaim memiliki full admin GUI.

---

## Operasi harian

### Status dan log

```bash
./setup.sh status --config /path/to/staging.json --host app-01
./setup.sh logs --config /path/to/staging.json --host app-01 --service laravel-php-app-01
```

### Stop service

```bash
./setup.sh stop \
  --config /path/to/staging.json \
  --host app-01 \
  --service laravel-php-app-01 \
  --yes
```

`stop` mempertahankan data dan menolak penghentian provider yang masih memiliki consumer aktif.

### Backup terenkripsi

```bash
./setup.sh backup \
  --config /path/to/production.json \
  --host db-01 \
  --service postgres-db-01 \
  --backup-id YYYYMMDDT000000Z-db \
  --destination /mnt/backup \
  --recipient age1... \
  --vault-password-file /path/to/vault-password
```

Backup hanya menerima mount NFS/CIFS eksternal dan mengenkripsinya dengan `age`.

Restore hanya menerima target baru yang terisolasi, identity engine/image/database yang sama persis, `age` identity file terlindungi, dan archive yang aman. Verifikasi data bisnis sebelum cutover.

---

## Aturan keamanan

- Tag image `latest` dan image tanpa digest ditolak.
- Nilai secret hanya disimpan pada Ansible Vault terenkripsi dan disensor dari output.
- Konfigurasi tidak dapat menjalankan arbitrary shell command.
- Data unmanaged tidak pernah diadopsi otomatis.
- `plan` ditandatangani dan harus masih cocok ketika `apply` dijalankan.
- Compose, firewall, TLS, dan release evidence diperiksa sebelum deployment terlindungi.
