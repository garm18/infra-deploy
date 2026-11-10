# Security best practices

[Beranda](../README.md) · [Indeks dokumentasi](README.md)

Ditujukan untuk operator dan reviewer sebelum staging/production. Tabel berikut
adalah catatan risiko audit, bukan daftar perbaikan yang telah terbukti selesai.
Konfirmasi kondisi kode dan bukti runtime terbaru sebelum menyatakan temuan ditutup.
Untuk cakupan penggabungan terbaru lihat [laporan integrasi](integration-validation.md).

Dokumen ini adalah hasil audit statis terhadap controller Python, renderer Docker
Compose, dan executor Ansible. Audit tidak menjalankan deployment pada host nyata.

## Prioritas perbaikan

| Prioritas | Temuan | Risiko | Perbaikan yang diperlukan |
| --- | --- | --- | --- |
| P0 | Upload Laravel dapat menjadi symlink ke TLS key Nginx | Kompromi PHP dapat membocorkan private key TLS | Sajikan upload melalui alias khusus dengan symlink dinonaktifkan, tolak symlink saat upload, dan jangan mount TLS key pada web server yang menyajikan direktori writable. |
| P1 | Semua secret deployment dikirim ke setiap host Ansible | Kompromi satu host dapat membuka secret layanan/host lain | Bentuk secret map per host dan per layanan; password SSH hanya boleh berada di controller. |
| P1 | Service yang dinonaktifkan dapat tetap berjalan | Endpoint admin/proxy lama masih terbuka setelah decommission | Turunkan daftar service terhapus dari state sebelumnya, stop secara eksplisit, lalu verifikasi container dan port sudah hilang. |
| P1 | Daftar `egress` belum menjadi aturan jaringan | Aplikasi yang disusupi dapat menghubungi tujuan di luar daftar | Kirim allowlist host/port ke firewall validator dan tegakkan dengan nftables, firewall host, atau egress proxy. |

## Aturan desain

### Secret dan akses host

- Satu host hanya menerima secret untuk service yang berjalan di host tersebut.
- Credential SSH adalah data controller; jangan teruskan ke extra-vars, Compose,
  runtime file, atau hasil operasi remote.
- Simpan Vault password, private key SSH, dan state controller di filesystem Linux
  dengan izin pemilik saja. Jangan simpan pada mount Windows.
- Gunakan `ssh-key` atau `ssh-agent`; mode `ssh-password` hanya untuk kebutuhan
  sementara dan tidak boleh menjadi credential lintas-host.
- Tetapkan rotasi secret sebagai operasi eksplisit. Jangan mengganti file credential
  secara diam-diam saat apply.

### Upload dan TLS

- Anggap semua isi upload sebagai tidak tepercaya, termasuk symlink, hardlink,
  nama file, MIME type, dan metadata.
- PHP boleh menulis ke direktori upload; Nginx hanya boleh menyajikan file reguler
  dari direktori itu. Nginx harus menolak symlink dan file PHP.
- Private key TLS hanya boleh dibaca oleh proses proxy. Pisahkan mount key dari
  filesystem yang dapat dicapai melalui static file serving.
- Tambahkan uji integrasi: buat symlink dari upload menuju `/run/assets/tls_key`,
  lalu pastikan request `/storage/...` menghasilkan `403` atau `404`.

### Lifecycle deployment

- Plan harus mencantumkan service yang dibuat, berubah, dihentikan, dan dihapus.
- Apply harus mengoperasikan host yang hanya memiliki service terhapus; jangan
  hanya melakukan loop atas service aktif.
- Setelah penghapusan, periksa `docker compose ps --all`, published port, DNS/route,
  dan health endpoint. Status sukses tidak cukup bila endpoint lama masih tersedia.
- Tetap pertahankan data saat stop, tetapi pisahkan stop container dari penghapusan
  data agar decommission dapat dibalik dengan aman.

### Network dan egress

- `egress` harus diperlakukan sebagai allowlist, bukan sekadar metadata validasi.
- Normalisasi tujuan menjadi IP/CIDR atau hostname yang di-resolve secara terkontrol,
  port, protocol, dan service pemilik sebelum menerapkannya di firewall.
- Firewall validator harus menerima policy egress lengkap, bukan hanya Compose.
- Uji positif untuk dependency yang diizinkan dan uji negatif untuk host/port yang
  tidak terdaftar. Rekam hasilnya dalam release evidence.
- Jaringan Docker `internal: false` menyediakan konektivitas; itu bukan pembatasan
  egress. Tegakkan aturan pada host firewall atau proxy egress.

## Gate sebelum staging dan production

1. Unit test dan integration test controller lulus.
2. Uji Docker nyata membuktikan upload symlink tidak dapat dibaca dari Nginx.
3. Uji multi-host membuktikan payload host A tidak mengandung secret host B.
4. Uji decommission membuktikan endpoint service yang dinonaktifkan tidak lagi
   menerima koneksi.
5. Uji egress membuktikan koneksi undeclared ditolak.
6. Scan image dan SBOM dibuat untuk digest yang akan dipakai; bukti release mencatat
   pemeriksa, tanggal kadaluarsa, dan hasil runtime/network/restore.
7. Jalankan restore drill pada target terisolasi sebelum production.

## Batas audit ini

Audit tidak memeriksa implementasi eksternal `firewall_check`, kondisi firewall
server, registry image, konfigurasi DNS/VPN, atau perilaku Docker/Nginx pada host
nyata. Semua kontrol tersebut perlu dibuktikan pada staging.
