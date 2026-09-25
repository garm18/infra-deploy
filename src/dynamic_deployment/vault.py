"""Vault-only credentials. Decrypted material is never included in a plan."""

import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

import yaml

from .state import safe_local


SENSITIVE_KEYS = re.compile(r"password|secret|token|app_key|private_key|authorization", re.I)


def redact(value, secret_values=()):
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if SENSITIVE_KEYS.search(str(key)) else redact(item, secret_values)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, secret_values) for item in value]
    if isinstance(value, str):
        result = value
        for secret in sorted((str(v) for v in secret_values if v), key=len, reverse=True):
            result = result.replace(secret, "[REDACTED]")
        return result
    return value


def required_references(config):
    service_refs = {reference for service in config["services"] if service.get("enabled", True)
                    for reference in service.get("secrets", {}).values()}
    ssh_refs = {host['ssh_password_ref'] for host in config.get('hosts', {}).values()
                if host.get('connection') == 'ssh-password'}
    return service_refs | ssh_refs


def _command(action, password_file=None):
    args = ["ansible-vault", action]
    if password_file:
        path = safe_local(password_file)
        if not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("File password Vault harus ada dan berizin 0600.")
        args += ["--vault-password-file", str(path)]
    return args


def _run(args, **kwargs):
    env = {**os.environ, "ANSIBLE_LOCAL_TEMP": str(Path(tempfile.gettempdir()) / "dd-ansible")}
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=60, env=env, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Ansible Vault tidak tersedia atau operasi melebihi timeout.") from exc
    if result.returncode:
        raise ValueError("Operasi Vault gagal. Periksa password, izin file, dan format Vault.")
    return result.stdout


def load_secrets(config, password_file=None):
    refs = required_references(config)
    vault_path = config.get("secrets_file")
    if not vault_path:
        if refs:
            raise ValueError("secrets_file terenkripsi diperlukan untuk layanan terpilih.")
        return {}
    path = safe_local(vault_path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("File Vault tidak ditemukan atau terlalu besar.")
    if not path.read_bytes().startswith(b"$ANSIBLE_VAULT;"):
        raise ValueError("secrets_file harus Ansible Vault terenkripsi; plaintext ditolak.")
    text = _run([*_command("view", password_file), str(path)])
    try:
        values = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError("Isi Vault bukan mapping yang valid.") from exc
    if not isinstance(values, dict):
        raise ValueError("Isi Vault harus mapping nama referensi ke nilai secret.")
    for ref in refs:
        value = values.get(ref)
        if not isinstance(value, str) or not value or len(value) > 8192 or any(c in value for c in "\x00\r\n"):
            raise ValueError(f"Secret {ref} hilang atau bukan string satu baris yang valid.")
    for service in config["services"]:
        if not service.get("enabled", True):
            continue
        for name, ref in service.get("secrets", {}).items():
            value = values[ref]
            if "password" in name and (len(value) < 16 or value.lower() in {"minioadmin", "password", "changeme"}):
                raise ValueError(f"Secret {ref} harus password kuat minimal 16 karakter.")
            if name == "root_user" and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{2,63}", value):
                raise ValueError(f"Secret {ref} bukan nama administrator yang valid.")
    return {ref: values[ref] for ref in sorted(refs)}


def initialize_secrets(config, password_file=None):
    """Create missing credentials once; never rotate an existing vault implicitly."""
    path = safe_local(config.get("secrets_file") or "secrets.vault.yml")
    if path.exists():
        load_secrets(config, password_file)
        return {"path": str(path), "created": False}
    values = {}
    if any(host.get('connection') == 'ssh-password' for host in config.get('hosts', {}).values()):
        raise ValueError("SSH password must be entered into the encrypted Vault manually; secrets-init never invents server login passwords.")
    for service in config["services"]:
        if not service.get("enabled", True):
            continue
        for name, ref in service.get("secrets", {}).items():
            if name.startswith("storage_"):
                raise ValueError("Access key S3 aplikasi harus diprovisikan dengan policy terbatas dan dimasukkan ke Vault.")
            generated = secrets.token_urlsafe(32)
            if name == "root_user":
                generated = "admin_" + secrets.token_hex(8)
            if name == "app_key":
                import base64
                generated = "base64:" + base64.b64encode(secrets.token_bytes(32)).decode()
            values.setdefault(ref, generated)
    if not values:
        raise ValueError("Tidak ada referensi secret untuk dibuat.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".vault-", dir=path.parent) as temporary:
        output = Path(temporary) / "encrypted.yml"
        _run([*_command("encrypt", password_file), "--output", str(output)], input=json.dumps(values))
        if not output.read_bytes().startswith(b"$ANSIBLE_VAULT;"):
            raise ValueError("Vault tidak menghasilkan file terenkripsi.")
        output.chmod(0o600)
        # link fails atomically if another process has created the destination.
        os.link(output, path, follow_symlinks=False)
    return {"path": str(path), "created": True}
