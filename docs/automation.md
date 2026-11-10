# Automation dengan Make dan Ansible

[Beranda](../README.md) · [Indeks dokumentasi](README.md)

Jalankan perintah dari root `dynamic_deployment/`. Make adalah pintasan untuk CLI;
CLI memvalidasi konfigurasi dan menyiapkan operasi Ansible. `plan` hanya membuat
rencana; `apply` menjalankannya setelah target dan preflight sesuai.

Panduan ini membahas deployment dynamic. Untuk container shared existing gunakan
[infra-* dan playbook infrastructure](integration.md). Backup dan restore dynamic
memakai `./setup.sh`; target Make khusus keduanya belum tersedia.

## Batas tanggung jawab

| Komponen | Tugas |
| --- | --- |
| Makefile | Menyediakan perintah pendek dan memeriksa parameter wajib |
| CLI Python | Wizard, validasi, render, pembuatan plan, dan pemilihan target |
| Ansible yang sudah ada | Menjalankan operasi pada host melalui controller |
| Docker Compose | Menjalankan layanan pada setiap host |

Aturan layanan tetap berada di katalog/controller, bukan diduplikasi dalam Makefile.
`make` tanpa target hanya menampilkan bantuan. Setiap operasi dijalankan terpisah;
`plan` tidak otomatis menjalankan `apply`. Jalankan satu target operasional setiap kali,
tanpa `make -j`, agar urutan dapat ditinjau.

Stack `infrastructure/` digunakan untuk pola pemeriksaan
Compose sebelum startup, healthcheck, pemisahan data dan konfigurasi, serta
dependency database sebelum aplikasi. `/mnt/data/postgres` dan `shared-network`
adalah contoh milik referensi, bukan nilai yang perlu dimasukkan ke wizard proyek
ini. Untuk server baru, isi root seperti `/mnt/data/dynamic-deployment` untuk data
dan `/opt/dynamic-deployment` untuk runtime. PRD tetap menentukan pilihan image,
data per environment/deployment, jaringan dependency, dan MinIO
AIStor. Redis referensi adalah cache ephemeral; jangan menjadikannya default untuk
queue atau session persisten tanpa meninjau kebutuhan aplikasi.

## Contoh penempatan direktori

Pada controller Linux/WSL:

```text
/mnt/d/project_local/dynamic_deployment/     # source, Makefile, setup.sh
/mnt/d/testing/dynamic-deployment/
├── development.json                      # konfigurasi hasil wizard
├── staging.json
└── production.json
~/.local/state/dynamic-deployment/plans/    # plan hasil perintah plan
~/.local/share/dynamic-deployment/          # Vault sesuai path yang diisi
```

File konfigurasi berada pada controller. Data container berada pada host yang
dipilih di wizard; pada mode `local`, host tersebut adalah komputer sendiri.
Contoh jika `environment=development`, `deployment=local-test`:

```text
data_root=/tmp/dynamic-deployment-data
  → /tmp/dynamic-deployment-data/development/local-test/
runtime_root=/tmp/dynamic-deployment-runtime
  → /tmp/dynamic-deployment-runtime/development/local-test/
```

`/tmp` hanya contoh untuk uji sementara dan dapat dibersihkan sistem. Untuk server,
contohkan data root `/mnt/data/dynamic-deployment` pada disk yang sudah terpasang,
dan runtime root `/opt/dynamic-deployment`. Dengan staging dan deployment `demo`,
hasilnya `/mnt/data/dynamic-deployment/staging/demo/` dan
`/opt/dynamic-deployment/staging/demo/`. Isi root saja di wizard; suffix environment
dan deployment ditambahkan controller. Direktori data existing dari referensi
infrastructure tidak otomatis diadopsi atau dipindahkan.

## Jalankan deployment dynamic

Prasyarat: GNU Make, Bash, Python sesuai `pyproject.toml`, dan dependency controller
pada [README](../README.md#prasyarat). Makefile tidak memasang paket otomatis.
Mulai dengan satu layanan PostgreSQL lokal.

```bash
cd /path/to/dynamic_deployment
make help
make doctor
make catalog
make wizard CONFIG=/mnt/d/testing/dynamic-deployment/development.json
make validate CONFIG=/mnt/d/testing/dynamic-deployment/development.json
make secrets-init CONFIG=/mnt/d/testing/dynamic-deployment/development.json
make plan CONFIG=/mnt/d/testing/dynamic-deployment/development.json
```

Tinjau output plan. Ganti `RUN_ID` berikut dengan nama file yang benar dari output;
jangan memilih plan secara otomatis berdasarkan file terbaru.

```bash
make apply PLAN="$HOME/.local/state/dynamic-deployment/plans/RUN_ID.json" \
  ENVIRONMENT=development DEPLOYMENT=local-test
make status CONFIG=/mnt/d/testing/dynamic-deployment/development.json HOST=local
```

`apply` menggunakan konfigurasi yang direkam dalam plan. `ENVIRONMENT` dan
`DEPLOYMENT` harus sama dengan plan tersebut. Mengubah konfigurasi berarti
menjalankan `validate` dan membuat plan baru sebelum apply.

Contoh operasi satu layanan; gunakan ID sebenarnya dari output `validate`:

```bash
make logs CONFIG=/mnt/d/testing/dynamic-deployment/development.json \
  HOST=local SERVICE=postgres-local
make stop CONFIG=/mnt/d/testing/dynamic-deployment/development.json \
  HOST=local SERVICE=postgres-local CONFIRM=yes
```

`stop` mempertahankan data. Tidak ada target penghapusan volume atau `prune`.
Untuk path dengan spasi, kutip seluruh nilai, misalnya `CONFIG="/mnt/d/testing/my app/development.json"`.
Jika perintah gagal, selesaikan penyebabnya sebelum berpindah ke langkah berikutnya.

## Isi versi dan image tanpa bingung

**Versi** adalah tag, misalnya `16.8`. **Image** adalah nama beserta tag,
misalnya `postgres:16.8`. Angka ini contoh format dari proyek, bukan rekomendasi
versi terbaru atau versi yang sudah diuji pada server Anda.

Pilih salah satu cara berikut:

| Cara | Jawaban |
| --- | --- |
| Langsung, disarankan | Pada pertanyaan image PostgreSQL, isi `postgres:16.8`; tidak ada pertanyaan versi tambahan |
| Isi versi saja | Pada konfigurasi baru, tekan Enter pada image; ketika ditanya versi, isi `16.8` |
| Gunakan konfigurasi lama | Jika nilai image tampil dalam `[ ... ]`, Enter mempertahankan nilai itu |

Pada pertanyaan image, jangan isi `16.8` saja. Pada pertanyaan versi, jangan isi
`postgres:16.8`. Jangan mengosongkan keduanya. Controller mengambil digest dari
registry secara otomatis; koneksi registry diperlukan. Digest adalah identitas
image yang dikunci agar deployment memakai artefak yang sama. Operator tidak
perlu menyusun digest secara manual untuk image publik yang didukung.

Untuk image Laravel buatan tim, masukkan referensi lengkap
`registry/nama:tag@sha256:DIGEST_ASLI` dari pipeline build; tulisan `DIGEST_ASLI`
hanya penanda, bukan nilai yang dapat digunakan. MinIO mengikuti pilihan AIStor
dalam PRD dan membutuhkan input tambahan; kerjakan setelah uji pertama berhasil.

## Kriteria selesai tahap pertama

- `make help` jelas dan tidak menjalankan deployment.
- Parameter wajib yang kosong menghasilkan pesan sebelum CLI dijalankan.
- Argumen diteruskan utuh, termasuk path dengan spasi; kegagalan CLI membuat Make gagal.
- `make test` menjalankan suite controller dan helper Ansible yang sudah tersedia.
- `make coverage` menjalankan pengukuran coverage baris kode Python controller
  dengan ambang 80%; coverage helper Ansible dilaporkan terpisah oleh tool yang ada.

Pengujian wrapper tidak membuktikan deployment pada host nyata. Uji runtime lokal
tetap memerlukan Docker, Ansible, dan input deployment yang valid.

## Tahap berikutnya: Ansible

Setelah tahap Makefile, evaluasi `ansible/preflight.yml` dan `ansible/operate.yml`
yang sudah ada. Cocokkan healthcheck, batas resource, dan kebutuhan persistence
dengan referensi infrastructure, lalu terapkan sesuai PRD. Pertahankan controller
sebagai pembentuk inventory dan variabel; pengguna tidak perlu menyunting YAML
untuk alur biasa.

Urutan verifikasi: preflight → satu layanan development → jalankan ulang konfigurasi
yang sama untuk menguji idempotensi → status/logs/stop → dependency layanan →
multi-host staging. Catat bukti nyata untuk setiap tahap. Review security menyusul
setelah automation fungsional selesai, sebelum penerimaan production.
