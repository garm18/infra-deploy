# Panduan dokumentasi

[Beranda](../README.md)

Mulai dari [README utama](../README.md). Pilih deployment baru atau stack existing,
lalu ikuti panduan yang sesuai. Jangan mencampur parameter kedua alur.

## Pengguna dan operator

| Panduan | Dipakai ketika |
| --- | --- |
| [Automation Make](automation.md) | Membuat konfigurasi, Vault, plan dan apply dynamic |
| [Integrasi Make–Ansible](integration.md) | Memilih alur, inventory dan operasi stack existing |
| [Quick start infrastructure](../infrastructure/QUICKSTART.md) | Menjalankan layanan shared existing |
| [Runbook infrastructure](../infrastructure/README.md) | Menyiapkan storage, network, upgrade dan backup |
| [Build aplikasi Laravel](container-build.md) | Menyiapkan image PHP dan web untuk controller |
| [Release evidence](release-evidence.md) | Mencatat bukti scan, runtime, network dan restore |
| [Keamanan](security-best-practices.md) | Meninjau risiko dan gate sebelum staging/production |
| [Pemecahan masalah](troubleshooting.md) | Menangani kegagalan parameter, preflight dan koneksi |
| [Aturan Git](repository.md) | Mengetahui file yang disimpan dan diabaikan |

## Referensi pengembang dan hasil pemeriksaan

| Dokumen | Isi |
| --- | --- |
| [Status implementasi](implementation-status.md) | Fitur tersedia dan batas operasional |
| [Kontrak internal](implementation-contract.md) | Skema dan antarmuka controller/executor |
| [Validasi integrasi](integration-validation.md) | Pemeriksaan setelah penggabungan dan cakupannya |
| [Validasi awal infrastructure](../infrastructure/VALIDATION.md) | Catatan historis sebelum integrasi |

## Cara membaca contoh

Perintah Make pada docs/ dijalankan dari root `dynamic_deployment/`. Contoh
`/path/...`, `RUN_ID`, nama host/service dan digest harus diganti dengan nilai
milik Anda. Jangan memasukkan nilai password ke perintah, tiket atau chat.
`development` adalah nama environment alur dynamic; `local` adalah nilai ENV
stack existing. Environment staging/production tetap dipilih secara eksplisit.

Validasi konfigurasi memeriksa input. Preflight memeriksa prasyarat. Healthcheck
memeriksa probe yang dikonfigurasi. Ketiganya tidak menggantikan uji alur aplikasi
dan restore data pada staging.
