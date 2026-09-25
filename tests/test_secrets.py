import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dynamic_deployment.vault import load_secrets, redact, required_references


class VaultTests(unittest.TestCase):
    def test_reference_collection_excludes_disabled(self):
        config = {"services": [
            {"secrets": {"password": "DB_PASSWORD"}},
            {"enabled": False, "secrets": {"password": "OLD_PASSWORD"}},
        ]}
        self.assertEqual(required_references(config), {"DB_PASSWORD"})

    def test_redaction_nested_and_exact_secrets(self):
        self.assertEqual(redact({"password": "abc", "note": "value=private-value"}, ["private-value"]),
                         {"password": "[REDACTED]", "note": "value=[REDACTED]"})

    def test_plaintext_vault_refused_without_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plain.yml"
            path.write_text("DB_PASSWORD: insecure\n")
            with patch("dynamic_deployment.vault.subprocess.run") as run:
                with self.assertRaises(ValueError):
                    load_secrets({"secrets_file": str(path), "services": []})
                run.assert_not_called()

    def test_decrypt_rejects_missing_reference_and_never_leaks_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vault.yml"
            path.write_text("$ANSIBLE_VAULT;1.1;AES256\n")
            config = {"secrets_file": str(path), "services": [{"secrets": {"password": "DB_PASSWORD"}}]}
            result = subprocess.CompletedProcess([], 0, "OTHER: sufficient-secret-value\n", "")
            with patch("dynamic_deployment.vault.subprocess.run", return_value=result):
                with self.assertRaisesRegex(ValueError, "DB_PASSWORD"):
                    load_secrets(config)
            result = subprocess.CompletedProcess([], 1, "", "do-not-leak")
            with patch("dynamic_deployment.vault.subprocess.run", return_value=result):
                with self.assertRaises(ValueError) as error:
                    load_secrets(config)
                self.assertNotIn("do-not-leak", str(error.exception))

    def test_no_references_needs_no_vault(self):
        self.assertEqual(load_secrets({"services": []}), {})
