"""MinIO deployment contracts; run with python3 -m unittest discover -s Infrastructure/minio."""
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent
class Loader(yaml.SafeLoader):
    pass
Loader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node, deep=True))

class ComposeContract(unittest.TestCase):
    def load(self, name):
        return yaml.load((ROOT / name).read_text(), Loader=Loader)

    def test_single_file_keeps_api_and_console_internal(self):
        services = self.load("docker-compose.yml")["services"]
        service = services["minio-storage"]
        self.assertEqual(set(services), {"minio-storage"})
        self.assertNotIn("ports", service)
        self.assertEqual(service["image"], "minio/minio:RELEASE.2025-04-22T22-12-26Z")
        self.assertIn("--console-address", service["command"])
        self.assertIn("no-new-privileges:true", service["security_opt"])
        self.assertEqual(service["env_file"], [".env"])
        self.assertIn("TZ", service["environment"])
        self.assertEqual(service["expose"], ["9000", "9001"])
        self.assertTrue((ROOT.parents[0] / "proxy-nginx/sites-available/minio.conf").is_file())
        for key in ("cpus", "mem_limit", "pids_limit"):
            self.assertNotIn(key, service)

    def test_data_mount_fails_if_missing(self):
        service = self.load("docker-compose.yml")["services"]["minio-storage"]
        mounts = {mount["target"]: mount for mount in service["volumes"]}
        self.assertEqual(set(mounts), {"/data"})
        for mount in mounts.values():
            self.assertFalse(mount["bind"]["create_host_path"])

    def test_local_uses_loopback_ports_and_disposable_data(self):
        service = self.load("docker-compose.local.yml")["services"]["minio-storage"]
        self.assertTrue(all(port.startswith("127.0.0.1:") for port in service["ports"]))
        self.assertEqual(service["volumes"], ["minio-data-local:/data"])

if __name__ == "__main__":
    unittest.main()
