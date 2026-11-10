# Dynamic Deployment

Workspace ini menyediakan dua alur. Pilih alur sebelum menjalankan perintah:

| Kebutuhan | Perintah awal | Panduan |
| --- | --- | --- |
| Deployment baru, konfigurasi per environment, Vault dan plan/apply | `make help` | [Automation](docs/automation.md) |
| Mengelola container shared yang sudah ada | `make infra-help` | [Infrastructure](infrastructure/QUICKSTART.md) |
| Menjalankan stack existing melalui SSH/Ansible | `make infra-ansible` dengan inventory dan vars | [Integrasi](docs/integration.md) |

Semua perintah `make` pada panduan utama dijalankan dari root `dynamic_deployment/`.
`CONFIG`, `PLAN`, `INVENTORY` dan path lainnya adalah file milik operator; ganti
contoh `/path/...` sesuai lokasi Anda. Jangan menyalin contoh digest sebagai image
siap deploy.

Struktur folder:

```text
dynamic_deployment/
├── Makefile          # entrypoint Make untuk kedua alur
├── setup.sh          # CLI dynamic
├── src/              # validasi, render, plan, state dan executor
├── ansible/          # playbook dan helper remote
├── catalog/          # kontrak layanan dynamic
├── templates/        # template build aplikasi
├── infrastructure/   # stack shared existing beserta data lokal yang diabaikan Git
├── tests/            # tes controller dan integrasi
└── docs/             # panduan dan laporan validasi
```

[Indeks dokumentasi](docs/README.md) memisahkan panduan penggunaan, referensi
pengembang dan laporan pemeriksaan. Menggabungkan folder tidak memigrasikan data:
Redis, MinIO dan layout PostgreSQL kedua alur berbeda. Baca
[batas migrasi](docs/integration.md#batas-migrasi) sebelum berpindah alur.

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

- [Mulai dari komputer baru](#mulai-dari-komputer-baru)
- [Prasyarat](#prasyarat)
- [Cara menjawab wizard](#cara-menjawab-wizard)
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

## Mulai dari komputer baru

Clone diperlukan jika source belum ada di komputer controller. Jika folder proyek
sudah tersedia, masuk ke folder itu; tidak perlu clone ulang. Controller adalah
komputer Linux/WSL yang menjalankan Make dan Ansible. Server tujuan adalah mesin
yang akan menjalankan container; keduanya dapat berupa mesin yang sama untuk tes.

### 1. Ambil source

Pastikan Git dan akses repository tersedia. Remote yang dikonfigurasi proyek ini
adalah `git@github.com:garm18/infra-deploy.git`. Untuk clone SSH, akun Anda perlu
akses repository dan SSH key GitHub yang sudah disiapkan.

```bash
mkdir -p ~/projects
cd ~/projects
git clone git@github.com:garm18/infra-deploy.git dynamic_deployment
cd dynamic_deployment
```

Alternatif HTTPS bila akses akun menggunakannya:

```bash
git clone https://github.com/garm18/infra-deploy.git dynamic_deployment
cd dynamic_deployment
```

Pilih salah satu cara clone. Jangan menjalankan keduanya pada folder yang sama.
Checkout harus berisi `Makefile`, `setup.sh`, `requirements.txt`, `ansible/` dan
`infrastructure/`. Perubahan lokal workspace baru tersedia bagi pengguna lain
setelah maintainer melakukan commit dan push; remote di atas belum diverifikasi
memuat seluruh perubahan sesi ini.

### 2. Siapkan controller

Gunakan Linux atau WSL, GNU Make, Bash, Python >=3.12 dengan venv/pip, OpenSSH
client dan OpenSSL. Pasang paket melalui package manager OS bila belum tersedia.
Kemudian, dari root repository:

```bash
python3 -m venv ~/.venvs/dynamic-deployment
source ~/.venvs/dynamic-deployment/bin/activate
python -m pip install -r requirements.txt
python -m pip install ansible-core
ansible-galaxy collection install -r ansible/requirements.yml
export DD_PYTHON="$VIRTUAL_ENV/bin/python"
make help
make doctor
```

Instalasi dependency memerlukan internet atau mirror internal. Jika `venv` gagal,
siapkan paket venv/pip untuk versi Python Anda terlebih dahulu. Pada terminal baru,
aktifkan virtualenv dan set DD_PYTHON kembali sebelum menjalankan perintah.

### 3. Siapkan host container

Docker Engine dan plugin Compose harus tersedia pada host yang menjalankan
container. Stack existing memerlukan Compose >=2.24.4. Docker lokal dibutuhkan
untuk tes local dan operasi `infra-*` yang diarahkan ke daemon lokal. Untuk host
remote siapkan SSH, known_hosts, sudo, mount data serta firewall sesuai konfigurasi.
Wizard memiliki pilihan bootstrap Docker untuk host remote; tetap review
prasyarat host dan kebijakan paket sebelum mengaktifkannya.

```bash
# Pada host container yang Anda siapkan:
docker version
docker compose version
docker info
```

### 4. Pilih alur dan mulai

Untuk deployment baru, buat konfigurasi melalui wizard berikut. Ini belum
menjalankan container:

```bash
mkdir -p ~/deployment-configs
make wizard CONFIG="$HOME/deployment-configs/development.json"
make validate CONFIG="$HOME/deployment-configs/development.json"
```

Ikuti [cara menjawab wizard](#cara-menjawab-wizard), lalu langkah Vault, plan dan
apply pada [quick start PostgreSQL](#quick-start-local-postgresql). Contoh path
`/mnt/d/testing` pada quick start adalah pilihan workstation WSL; Anda boleh
menggantinya dengan `~/deployment-configs` yang dibuat di atas.

Untuk stack shared existing, gunakan alur berbeda:

```bash
make infra-init SERVICES="postgres redis"
# Edit infrastructure/postgres/.env dan infrastructure/redis/.env secara privat.
make infra-check ENV=local SERVICES="postgres redis"
make infra-up ENV=local SERVICES="postgres redis"
```

`infra-init` tidak mengisi credential valid dan tidak menimpa file existing.
Pengguna baru hasil clone perlu menyediakan .env, certificate, license dan aset
host yang diperlukan sendiri karena file tersebut diabaikan Git.

## Prasyarat

Siapkan GNU Make, Bash, Python >=3.12, Ansible dan Docker Compose sesuai kebutuhan
host. Dependency Python controller tercatat di `requirements.txt`. Bila memakai
virtualenv, pilih filesystem Linux untuk menyimpan environment dan credential.
Contoh persiapan dependency Python (memerlukan dukungan venv/pip pada OS):

```bash
python3 -m venv ~/.venvs/dynamic-deployment
~/.venvs/dynamic-deployment/bin/python -m pip install -r requirements.txt
export DD_PYTHON=~/.venvs/dynamic-deployment/bin/python
```

Perintah tersebut dijalankan dari root repository. Dependency Ansible dan akses
Docker diperiksa terpisah; `make doctor` tidak memasang paket otomatis.

Masuk ke direktori project dan jalankan pemeriksaan controller:

```bash
cd /path/to/dynamic_deployment
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

## Cara menjawab wizard

Wizard sudah tersedia di kode. Kedua perintah berikut setara; pilih satu:

```bash
make wizard CONFIG="$HOME/deployment-configs/development.json"
# Atau:
bash setup.sh wizard --output "$HOME/deployment-configs/development.json"
```

Jawaban perlu mengikuti format pertanyaan, tetapi nama/path tidak harus menyalin
contoh README. Validasi konfigurasi akhir tetap ketat untuk mencegah target salah.

| Pertanyaan | Aturan jawaban | Contoh |
| --- | --- | --- |
| Environment | Persis salah satu nilai huruf kecil | `development`, `staging`, `production` |
| Deployment name dan Host ID | Mulai huruf kecil; huruf kecil, angka, tanda minus; maksimal 40 karakter | `team-app`, `db-01` |
| Connection mode | Persis salah satu pilihan | `local`, `ssh-key`, `ssh-agent`, `ssh-password` |
| Pilihan layanan | Nomor dipisahkan spasi, bukan koma; lihat daftar di terminal | `1 3` untuk PostgreSQL dan Redis pada daftar saat ini |
| Image layanan standar | Versi yang diuji, bukan latest; wizard me-resolve digest melalui registry | `postgres:16.8` hanya contoh format |
| Image Laravel | Image hasil build tim dengan tag dan digest nyata | Isi referensi hasil build Anda |
| Dependency | ID layanan yang ditampilkan, bukan nama bebas | Pilih ID provider yang tersedia |
| Path file | Lokasi file milik Anda; `~` diperluas oleh wizard | `~/.local/share/dynamic-deployment/demo.vault.yml` |
| Pertanyaan y/n | `y`, `yes`, `ya` berarti setuju; gunakan `n` untuk menolak | `y` atau `n` |

Enter mempertahankan nilai dalam `[ ... ]`. Tanpa default, jawaban kosong tetap
kosong dan dapat ditolak bila wajib. Spasi di awal/akhir dibuang; nilai pilihan
seperti environment tidak otomatis diubah menjadi huruf kecil. Pada pertanyaan
y/n, input lain saat ini dianggap tidak, sehingga gunakan jawaban yang jelas.
Ketik `cancel` atau `batal`, atau tekan Ctrl+C untuk membatalkan.

Pemilihan `-` pada daftar layanan menonaktifkan semuanya untuk host tersebut;
ini bukan pilihan untuk pemula yang sedang menyiapkan layanan pertama. Nilai
layanan yang sudah tersimpan dapat dipakai kembali saat mengedit konfigurasi.

File output baru ditulis setelah konfigurasi lolos validasi akhir. Wizard bukan
perintah deploy: lanjutkan dengan validate, secrets-init, plan, lalu apply.
Jika file sudah ada, perintah biasa menolak menimpanya. Untuk mengedit file
existing, backup konfigurasi terlebih dahulu, lalu gunakan opsi CLI eksplisit:

```bash
bash setup.sh wizard --output "$HOME/deployment-configs/development.json" --force
```

`--force` belum memiliki parameter pada target `make wizard`; gunakan CLI di atas.
Nilai lama dibaca sebagai default, tetapi tetap review hasil sebelum plan/apply.
Jangan menganggap semua kesalahan akan ditanyakan ulang: beberapa input tidak
valid menghentikan wizard dengan error dan perlu diperbaiki saat menjalankan ulang.

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

Pada alur dynamic, profil GUI administrasi menggunakan **MinIO AIStor Free**:

- Image: `quay.io/minio/aistor/minio`
- License operator
- TLS internal
- Nginx admin proxy
- Akses hanya dari internal network atau VPN

Apply MinIO memerlukan evidence yang belum kedaluwarsa untuk runtime, network, GUI, serta authenticated S3 write/read/delete probe. Stack existing di `infrastructure/minio` memakai release Community berbeda; lihat runbook layanan tersebut. Jangan mengganti image antar alur tanpa rencana migrasi.

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
