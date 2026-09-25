# Bukti kelayakan release

Validasi konfigurasi dan unit test bukan bukti bahwa image, jaringan, atau restore sudah berhasil pada server nyata. Production membutuhkan bukti operator setelah pengujian pada staging yang representatif. Berkas approval merupakan input tepercaya yang harus dilindungi melalui izin file dan proses review; validator ini tidak menyediakan tanda tangan digital atau membuktikan kebenaran pernyataan operator.

## Format evidence

```json
{
  "approved_images": ["registry.example.org/team/app:1.0@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
  "approved_by": "nama-reviewer",
  "expires_at": "2026-10-01T00:00:00+00:00",
  "checks": {
    "runtime_verified": true,
    "network_verified": true,
    "restore_verified": true,
    "image_scan_verified": true,
    "sbom_verified": true
  }
}
```

Contoh di atas hanya menjelaskan struktur, bukan approval siap pakai. Isi daftar image dengan referensi digest persis dari konfigurasi yang diuji. `expires_at` wajib menggunakan timezone dan berada di masa depan. Nilai checks wajib boolean; check yang diwajibkan pemanggil harus bernilai `true`. JSON dengan key duplikat ditolak.

```bash
python3 scripts/check_release.py --evidence /secure/release.json \
  --image registry.example.org/team/app:1.0@sha256:DIGEST_ASLI \
  --required-check runtime_verified --required-check network_verified \
  --required-check restore_verified --required-check image_scan_verified \
  --required-check sbom_verified
```

Simpan output pengujian dan identitas konfigurasi, versi alat, host staging, tanggal, serta tautan laporan bersama approval di penyimpanan tim. Buat ulang approval saat image atau kondisi jaringan/runtime berubah. Jangan mengubah checks menjadi true hanya untuk melewati preflight.

## Scan image dan SBOM

```bash
python3 scripts/check_release.py --scan IMAGE_DENGAN_DIGEST --output .reports/candidate-1
```

Perintah membutuhkan Trivy yang sudah tersedia dan akses registry/database scanner. Ia menjalankan scan HIGH/CRITICAL dengan exit code nonzero untuk temuan, lalu menghasilkan SBOM CycloneDX. Hasil nyata tersimpan sebagai `scan.json`, `sbom.json`, `scan.log`, dan `sbom.log`. Gunakan direktori baru per kandidat; kegagalan tidak membuat approval. Trivy tidak tersedia atau gagal berarti bukti belum tersedia, bukan lolos pemeriksaan. Tinjau hasil scan dan SBOM sebelum memberi approval.

## Pengujian yang harus dilakukan pada staging

- Runtime: cold start, healthcheck, restart, limits, proses non-root jika didukung, secrets, dan alur Laravel termasuk worker/scheduler sesuai konfigurasi.
- Network: jalur proxy ke aplikasi dan aplikasi ke data berhasil; jalur yang tidak diizinkan ditolak; GUI administrasi hanya dapat diakses dari VPN/internal.
- Restore: backup disalin ke target terisolasi, checksum diverifikasi, restore berhasil, dan isi data/alur aplikasi diverifikasi. Catat durasi untuk dibandingkan dengan RPO/RTO.

## Coverage lokal

```bash
python3 scripts/measure_coverage.py
```

Alat berbasis standard-library `trace` menjalankan discovery `tests` dan `ansible/tests`, termasuk import di bawah tracing. Semua executable line file Python `src` dan `ansible/files` dimasukkan meskipun file tidak dijalankan. Output `.reports/coverage.json` memuat line yang belum dijalankan; exit nonzero jika test gagal, suite kosong/hilang, atau coverage `src` kurang dari 80%. Coverage helper Ansible dilaporkan terpisah. Pengukuran ini **line coverage**, bukan branch coverage. Ini tidak menjalankan deployment Docker nyata dan tidak memberikan status lolos untuk runtime/network/restore. Coverage tinggi tidak menggantikan pengujian staging.
