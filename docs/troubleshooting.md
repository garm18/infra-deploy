# Pemecahan masalah

[Beranda](../README.md) · [Indeks dokumentasi](README.md)

Jalankan pemeriksaan dari root `dynamic_deployment/`. Simpan output secara privat
jika log berisi data aplikasi. Hentikan percobaan apply sampai penyebabnya jelas.

| Gejala | Pemeriksaan | Tindakan |
| --- | --- | --- |
| `make` tidak ditemukan | `command -v make` | Pasang GNU Make melalui package manager OS |
| Modul Python tidak ditemukan | `make doctor`, versi Python dan dependency requirements.txt | Pilih Python >=3.12 yang memiliki PyYAML; DD_PYTHON dapat menunjuk interpreter tersebut |
| CONFIG atau PLAN wajib diisi | `make help` | Isi path file; kutip path dengan spasi |
| Environment/deployment berbeda dari plan | Bandingkan konfigurasi dengan argumen apply | Pakai identitas persis atau buat plan baru untuk konfigurasi yang berubah |
| Image tanpa digest ditolak | Lihat image pada konfigurasi dynamic | Pilih versi yang diuji dan resolve digest melalui alur wizard/plan |
| Private key/state ditolak karena permission | Lokasi file dan izin Linux | Simpan key, Vault password dan state pada filesystem Linux dengan izin privat |
| SSH host key gagal | Host dan known_hosts controller | Verifikasi fingerprint server sebelum memperbarui known_hosts; pertahankan host-key checking |
| Sudo gagal | User target dan `sudo -n true` | Siapkan hak sudo yang sesuai pada host tujuan |
| Docker tidak terjangkau | `docker context show`, `docker info` | Periksa context, daemon dan hak akses di mesin yang menjalankan operasi |
| Preflight infrastructure memeriksa storage yang hilang | Path mount dari Compose dan env | Siapkan disk/mount serta ownership; jangan membuat folder kosong untuk menutupi mount gagal |
| Port sudah dipakai | Container existing dan published port | Gunakan host terpisah untuk environment stack shared atau hentikan konflik melalui prosedur terencana |
| Password database tidak berubah setelah edit .env | Apakah data sudah diinisialisasi | Rotasikan akun melalui prosedur database; jangan hapus volume |
| `up --wait` gagal | Status dan log service terpilih | Periksa probe, dependency, mount dan vhost; jangan menganggap sebagian layanan ikut rollback |
| Ansible infrastructure tidak memilih host | Inventory harus memiliki grup infrastructure | Perbaiki inventory; variabel target di file INFRA_VARS |

Untuk dynamic, gunakan `make preflight CONFIG=/path/deployment.json`, lalu
`make status`/`make logs` dengan CONFIG yang sama. Untuk stack shared gunakan
`make infra-check`, `make infra-ps` dan `make infra-logs` dengan ENV serta SERVICES
yang sama. `make infra-ansible` default ke action check; ubah action di vars hanya
setelah target dan konfigurasi direview.

Jika meminta bantuan, sertakan operasi, environment, host/service ID dan pesan
error yang telah disensor. Jangan sertakan .env, Vault password, key SSH atau output
resolved Compose config.
