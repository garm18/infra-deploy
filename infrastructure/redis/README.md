# Redis Cache

Redis adalah cache bersama pada `shared-network`. Ia tidak terhubung langsung ke
PostgreSQL atau MariaDB; aplikasi yang mengelola alurnya:

```text
aplikasi → redis:6379  (cache hit)
aplikasi → database    (cache miss), lalu aplikasi menyimpan hasil ke Redis
```

Setiap aplikasi di jaringan yang sama memakai host `redis`, port `6379`, dan
`REDIS_PASSWORD` dari konfigurasi aplikasi masing-masing.

## Cache prefix

`CACHE_PREFIX` bukan pengaturan server Redis dan tidak perlu ditambahkan ke
`.env` Redis. Atur prefix di setiap aplikasi, misalnya:

```text
catalog:cache:
billing:cache:
```

Prefix membedakan key antar aplikasi yang berbagi Redis, sehingga `catalog:cache:user:42`
tidak berbenturan dengan `billing:cache:user:42`. Gunakan prefix yang berbeda per
aplikasi dan per environment, misalnya `catalog:prod:` dan `catalog:staging:`.

## Memory dan local

Redis dikonfigurasi sebagai cache ephemeral: data hilang saat container restart.
`REDIS_MAXMEMORY` adalah kapasitas cache, sedangkan `allkeys-lfu` menghapus key
yang paling jarang dipakai saat batas tercapai. Ini melindungi RAM host tanpa
menetapkan limit CPU atau RAM Docker.

Untuk eksperimen local:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

Port local hanya tersedia di `127.0.0.1:6379`.
