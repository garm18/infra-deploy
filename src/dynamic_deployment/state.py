"""Private atomic controller state and advisory process locks."""

import contextlib
import fcntl
import json
import os
import re
import secrets
import tempfile
from pathlib import Path


def safe_local(path):
    candidate = Path(path).absolute()
    for part in (candidate, *candidate.parents):
        if part.is_symlink():
            raise ValueError(f"Symlink tidak diizinkan: {part}")
    return candidate


class StateStore:
    def __init__(self, root):
        self.root = safe_local(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def path(self, name):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Path state harus relatif dan berada di direktori state.")
        result = safe_local(self.root / relative)
        if not result.is_relative_to(self.root):
            raise ValueError("Path state keluar dari direktori yang dikelola.")
        return result

    def write_json(self, name, value):
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.parent.chmod(0o700)
        self.path(name)
        fd, temporary = tempfile.mkstemp(prefix=".write-", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    def read_json(self, name, default=None):
        target = self.path(name)
        if not target.exists():
            return default
        if target.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Berkas state melebihi batas ukuran.")
        return json.loads(target.read_text(encoding="utf-8"))

    def key(self):
        target = self.path("signing.key")
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(secrets.token_bytes(32))
                handle.flush()
                os.fsync(handle.fileno())
        self.path("signing.key")
        if target.stat().st_mode & 0o077:
            raise ValueError("signing.key harus hanya dapat dibaca pemilik (0600).")
        value = target.read_bytes()
        if len(value) != 32:
            raise ValueError("Kunci penandatanganan state tidak valid.")
        return value

    @contextlib.contextmanager
    def lock(self, scope):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,150}", scope):
            raise ValueError("Nama lock tidak valid.")
        target = self.path(f"locks/{scope}.lock")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(target, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(f"Operasi lain masih memegang lock {scope}.") from exc
            yield
        finally:
            os.close(fd)
