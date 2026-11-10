# Satu workspace deployment

[Beranda](../README.md) · [Indeks dokumentasi](README.md)

`dynamic_deployment/` sekarang menjadi folder utama. Stack dari `makefile-devops/`
dipindahkan utuh ke `infrastructure/`, termasuk file tersembunyi. Tidak ada data
atau credential yang dimigrasikan ke container. Arsip asli dan data existing tetap
lokal dan diabaikan Git. Jangan menyalin seluruh folder sebagai paket ke server.

Untuk deployment baru, gunakan alur utama yang sudah tersedia:

```bash
make doctor
make wizard CONFIG=/path/deployment.json
make validate CONFIG=/path/deployment.json
make secrets-init CONFIG=/path/deployment.json
make plan CONFIG=/path/deployment.json
# Gunakan path plan yang dihasilkan dan identitas persis dari konfigurasi.
make apply PLAN=/path/plan.json ENVIRONMENT=staging DEPLOYMENT=demo
make status CONFIG=/path/deployment.json
```

Make memanggil CLI controller; controller memakai Ansible, Vault, preflight dan
host lock. Tidak perlu menjalankan operate.yml manual dengan payload buatan.
Lihat README dan docs/automation.md untuk konfigurasi host dan release evidence.

## Stack existing

```bash
make infra-help
make infra-check ENV=local SERVICES="postgres redis"
make infra-up ENV=local SERVICES="postgres redis"
make infra-ps ENV=local SERVICES="postgres redis"
```

`ENV`/`SERVICES` hanya untuk infrastructure existing. `ENVIRONMENT`/`CONFIG`/
`DEPLOYMENT` adalah parameter alur dynamic. Pemisahan ini mencegah `make apply`
menyentuh container shared existing tanpa sengaja. Stack existing mempertahankan
nama container, network dan volume, sehingga staging/production wajib daemon
terpisah. Jalankan perintah infrastructure lokal pada Docker context tujuan.

## Ansible untuk stack existing

Playbook `ansible/infrastructure.yml` memanggil manager Python yang sama dengan
Make. Ia membutuhkan checkout infrastructure yang telah direview di target,
Python 3 dan Docker Compose >=2.24.4. Deploy hanya file konfigurasi/kode yang
direview; .env, certificate dan data disediakan privat di host. Playbook tidak
mengirim file atau memasang dependency otomatis.

Sediakan inventory sendiri dengan grup `infrastructure`, host SSH dan user sudo.
Sediakan file vars di luar repository, misalnya:

```yaml
infra_root: /opt/dynamic_deployment/infrastructure
infra_environment: staging
infra_services: [postgres, redis]
infra_action: check
```

```bash
make infra-ansible INVENTORY=/path/hosts.yml INFRA_VARS=/path/infra-vars.yml
```

Default action adalah `check` (preflight read-only). Setelah lulus, ganti action
menjadi `up` untuk menjalankan dan menunggu healthcheck. `config` dan `ps` juga
tersedia. Playbook memakai root melalui become dan SSH host-key checking tetap
aktif. Check mode hanya memvalidasi input/keberadaan manager; tidak membuktikan
kesiapan Docker. Operasi up dilaporkan changed secara konservatif.

## Batas migrasi

Integrasi ini menyatukan workspace dan entrypoint, bukan format data kedua engine.
Redis existing ephemeral; Redis dynamic persisten. MinIO existing Community dan
dynamic AIStor memiliki persyaratan image/lisensi berbeda. PostgreSQL existing
bernama volume `postgres-career-data`; dynamic memakai layout per deployment.
Jangan arahkan dynamic langsung ke volume lama. Backup konsisten, isolated restore,
verifikasi aplikasi/IAM dan cutover diperlukan sebelum migrasi.

Jangan jalankan dua pengelola pada container/data yang sama. Host lock pada alur
dynamic tidak mencakup proses eksternal atau CLI Docker manual. Tidak ada rollback
data otomatis. Ikuti infrastructure/README.md untuk operasi stack existing.

Sites telah dievaluasi: hosting Sites tidak mengoperasikan Docker daemon/Ansible
pada server Anda, sehingga tidak ditambahkan sebagai dependency deployment.

Referensi: [Ansible copy](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/copy_module.html)
dan [Compose up](https://docs.docker.com/reference/cli/docker/compose/up/).
