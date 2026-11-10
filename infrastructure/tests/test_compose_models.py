"""Integration checks against real Compose merge semantics; no Docker daemon needed."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).absolute().parents[1]
BINARY = os.environ.get("COMPOSE_BIN") or str(ROOT / ".tools/docker-compose")
FIXTURES = {
    "POSTGRES_USER": "fixture_user", "POSTGRES_DB": "fixture_db",
    "POSTGRES_PASSWORD": "fixture-not-a-real-password",
    "MARIADB_ROOT_PASSWORD": "fixture-not-a-real-password",
    "MARIADB_USER": "fixture_user", "MARIADB_DATABASE": "fixture_db",
    "MARIADB_PASSWORD": "fixture-not-a-real-password",
    "REDIS_PASSWORD": "fixture-not-a-real-password",
    "REDIS_MAXMEMORY": "256mb", "REDIS_MAXMEMORY_POLICY": "noeviction",
    "MINIO_ROOT_USER": "fixture_user", "MINIO_ROOT_PASSWORD": "fixture-not-a-real-password",
    "MINIO_DATA_DIR": "/mnt/data/minio",
}

@unittest.skipUnless(Path(BINARY).is_file(), "Set COMPOSE_BIN to a native Compose >=2.24.4 executable")
class ComposeModels(unittest.TestCase):
    def model(self, directory, override=None):
        folder = ROOT / directory
        command = [BINARY, "-f", str(folder / "docker-compose.yml")]
        if override:
            command += ["-f", str(folder / ("docker-compose." + override + ".yml"))]
        result = subprocess.run(command + ["config", "--format", "json"],
                                cwd=folder, env={**os.environ, **FIXTURES}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "Compose model invalid for " + directory + " " + str(override))
        services = json.loads(result.stdout)["services"]
        return services["minio-storage"] if directory == "minio" else next(iter(services.values()))

    def test_production_contracts(self):
        for folder in ("mariadb", "postgres", "redis", "minio", "apache"):
            with self.subTest(folder=folder):
                service = self.model(folder)
                self.assertIn("no-new-privileges:true", service["security_opt"])
                self.assertIn("healthcheck", service)
                if folder in ("mariadb", "postgres", "minio"):
                    self.assertFalse(service.get("ports"))
                    data = [v for v in service["volumes"] if v["type"] == "bind" and v["source"].startswith("/mnt/data/")]
                    self.assertEqual(len(data), 0 if folder == "postgres" else 1)
                    if folder not in ("postgres", "mariadb"):
                        self.assertFalse(data[0].get("bind", {}).get("create_host_path", False))

    def test_local_ports_and_storage_are_isolated(self):
        for folder in ("mariadb", "postgres", "redis", "minio", "apache", "proxy-nginx"):
            with self.subTest(folder=folder):
                service = self.model(folder, "local")
                self.assertTrue(service["ports"])
                self.assertTrue(all(p["host_ip"] == "127.0.0.1" for p in service["ports"]))
                self.assertFalse(any(v.get("source", "").startswith("/mnt/data/") for v in service["volumes"]))
                if folder in ("mariadb", "postgres", "minio"):
                    self.assertEqual(len([v for v in service["volumes"] if v["type"] == "volume"]), 1)
                if folder == "postgres":
                    self.assertNotEqual(service["environment"].get("POSTGRES_HOST_AUTH_METHOD"), "trust")

    def test_proxy_uses_its_single_enabled_sites_directory(self):
        nginx = self.model("proxy-nginx")
        enabled = [volume["source"] for volume in nginx["volumes"]
                   if volume["target"] == "/etc/nginx/sites-enabled"]
        self.assertEqual(enabled, [str(ROOT / "proxy-nginx/sites-enabled")])
        self.assertEqual(nginx["image"], "nginx:1.27-alpine")
        self.assertEqual({port["published"] for port in nginx["ports"]}, {"8080", "8443"})
        self.assertNotIn("cpus", nginx)
        self.assertNotIn("mem_limit", nginx)
        self.assertNotIn("pids_limit", nginx)
        self.assertEqual(nginx["logging"]["options"]["max-size"], "10m")
        apache_vhost = (ROOT / "apache/sites-enabled/pasplus-newengine.conf").read_text()
        self.assertNotIn("ServerAlias localhost", apache_vhost)
        self.assertIn('X-Forwarded-Proto "https"', apache_vhost)

    def test_apache_matches_the_proxy_layout(self):
        apache = self.model("apache")
        enabled = [volume["source"] for volume in apache["volumes"]
                   if volume["target"] == "/usr/local/apache2/conf/sites-enabled"]
        self.assertEqual(enabled, [str(ROOT / "apache/sites-enabled")])
        self.assertEqual(apache["image"], "httpd:2.4.68-alpine")
        self.assertEqual({port["published"] for port in apache["ports"]}, {"8081"})
        for key in ("cpus", "mem_limit", "pids_limit"):
            self.assertNotIn(key, apache)

    def test_postgres_uses_env_file_and_fixed_standard_data_layout(self):
        postgres = self.model("postgres")
        compose = (ROOT / "postgres/docker-compose.yml").read_text()
        dockerfile = (ROOT / "postgres/Dockerfile").read_text()
        self.assertIn("build:", compose)
        self.assertIn("POSTGRES_IMAGE=postgres:16-alpine", dockerfile)
        self.assertIn("env_file:\n      - .env", compose)
        self.assertEqual(self.model("redis" if "redis" in compose else "postgres" if "postgres" in compose else "mariadb")["environment"]["TZ"], "Asia/Jakarta")
        self.assertNotIn("cpus", postgres)
        self.assertNotIn("mem_limit", postgres)
        self.assertNotIn("pids_limit", postgres)
        self.assertEqual(postgres["logging"]["options"]["max-file"], "3")
        data_mount = next(volume for volume in postgres["volumes"]
                          if volume["target"] == "/var/lib/postgresql/data")
        self.assertEqual(data_mount["source"], "postgres-career-data")
        self.assertEqual(data_mount["type"], "volume")

    def test_mariadb_matches_the_database_service_pattern(self):
        mariadb = self.model("mariadb")
        compose = (ROOT / "mariadb/docker-compose.yml").read_text()
        self.assertIn("image: mariadb:11", compose)
        self.assertIn("env_file:\n      - .env", compose)
        self.assertEqual(self.model("redis" if "redis" in compose else "postgres" if "postgres" in compose else "mariadb")["environment"]["TZ"], "Asia/Jakarta")
        for key in ("cpus", "mem_limit", "pids_limit"):
            self.assertNotIn(key, mariadb)
        data_mount = next(volume for volume in mariadb["volumes"]
                          if volume["target"] == "/var/lib/mysql")
        self.assertEqual(data_mount["source"], "/mnt/data/mariadb")

    def test_redis_is_an_ephemeral_shared_cache(self):
        redis = self.model("redis")
        compose = (ROOT / "redis/docker-compose.yml").read_text()
        entrypoint = (ROOT / "redis/start-redis.sh").read_text()
        self.assertEqual(redis["image"], "redis:7-alpine")
        self.assertIn("env_file:\n      - .env", compose)
        self.assertFalse(redis.get("ports"))
        self.assertEqual(self.model("redis" if "redis" in compose else "postgres" if "postgres" in compose else "mariadb")["environment"]["TZ"], "Asia/Jakarta")
        self.assertFalse(any(volume["target"] == "/data" for volume in redis["volumes"]))
        self.assertIn("/usr/local/bin/start-redis.sh", [volume["target"] for volume in redis["volumes"]])
        for key in ("cpus", "mem_limit", "pids_limit"):
            self.assertNotIn(key, redis)
        self.assertIn("appendonly no", entrypoint)
        self.assertIn('save ""', entrypoint)
        self.assertIn("allkeys-lfu", entrypoint)

if __name__ == "__main__":
    unittest.main()
