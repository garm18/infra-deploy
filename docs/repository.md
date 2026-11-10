# Aturan Git dan format file

[Beranda](../README.md) · [Indeks dokumentasi](README.md)

`.gitignore` di root melindungi state controller, inventory operator, virtualenv,
cache, log, credential dan artefak infrastructure. `.gitattributes` menjaga format
file lintas Windows–Linux; aturan infrastructure mengikuti root.

| File | Perlakuan |
| --- | --- |
| Python, shell, Makefile, Dockerfile, YAML/JSON, Markdown | Teks dengan LF |
| `.bat` dan `.cmd` | Teks dengan CRLF |
| Arsip, gambar, PDF, key/certificate dan dump binary | Tanpa konversi teks |
| `.env`, key, certificate, Vault dan file password lokal | Diabaikan Git |
| `.env.example` dan `.env.*.example` | Boleh dilacak; gunakan nilai contoh saja |
| Data, backup dan arsip infrastructure | Diabaikan Git |
| `.gitkeep` dalam direktori ssl infrastructure | Boleh dilacak |

Inventory dan Vault milik operator disediakan di luar repository. Jangan menaruh
secret pada nama file lain dan menganggap Git akan mendeteksinya: ignore bekerja
berdasarkan pola nama/path. File yang sudah tracked tidak otomatis keluar dari Git.
Review `git status` dan `git diff --cached` sebelum commit; jangan membagikan output
jika ada credential. Bila secret pernah terpublikasi, hapus dari tracking/history
sesuai prosedur tim dan rotasikan credential terkait.

```bash
git check-ignore -v infrastructure/redis/.env
git check-attr text eol -- Makefile setup.sh ansible/infrastructure.yml
git diff --check
```

Perintah hanya memeriksa aturan. Tidak perlu menjalankan renormalisasi massal
atau menghapus file lokal untuk menggunakan struktur baru.
