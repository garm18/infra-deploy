# Status implementasi PRD

Semua kebutuhan inti PRD diterapkan sebagai konfigurasi tertutup, renderer Compose, controller Ansible, dan CLI interaktif. Validasi skema mengunci image pada digest, secret pada Ansible Vault, SSH pada key 0600 dan known-host checking, data root pada mount yang ditentukan, serta jaringan frontend/backend/data/admin terpisah.

Fitur PostgreSQL, MariaDB, Redis, MinIO AIStor, Nginx, Apache, phpMyAdmin, dan profil Laravel tersedia di katalog. Laravel tidak perlu dipisah menjadi frontend/backend repository. Worker dan scheduler memakai image/release/secret yang sama dengan PHP-FPM dan perbedaan profile ditolak.

Safety gate yang diterapkan mencakup plan HMAC, preflight seluruh host sebelum mutation, dependency order, lock lokal dan remote, staged Compose validation, secret immutable, data marker yang mencegah adopsi data unmanaged, dan pemblokiran perubahan host/kind/image layanan stateful. Stop tidak menghapus data; backup age streaming menuju NFS/CIFS eksternal; restore hanya ke target baru.

Hal yang bersifat bukti operasional tetap tidak dinyatakan selesai sampai operator menjalankannya di target: digest scan/SBOM, license AIStor yang berlaku, akses GUI melalui VPN/internal CIDR, probe S3, TLS/firewall, dan restore drill. Bukti tersebut disimpan sebagai release evidence ber-expiry; deployment MinIO dan production menolaknya bila tidak lengkap.

Pembatasan eksplisit saat ini: phpMyAdmin serta Laravel MariaDB/Redis hanya same-host; remote PostgreSQL dan MinIO memakai TLS terverifikasi. `upload_path` Laravel hanya `storage/app/public` sampai adapter path tambahan diimplementasikan. Backup terjadwal/retention dioperasikan oleh scheduler eksternal yang dipantau; controller menyediakan operasi backup aman per-run, tidak memasang cron tersembunyi.
