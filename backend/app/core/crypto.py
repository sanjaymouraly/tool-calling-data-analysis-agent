"""Secret storage for provider API keys.

API keys are encrypted at rest with Fernet (AES-128-CBC + HMAC).  The
encryption key comes from ``SECRET_KEY`` when it is configured; otherwise a
key is generated once and stored in the data directory with ``0600``
permissions.  Only the masked hint is ever returned through the API.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import stat
from pathlib import Path

from ..core.config import settings
from ..core.errors import ValidationError
from ..core.logging import get_logger

log = get_logger("core.crypto")

_KEY_FILE_NAME = "secret.key"


def _key_path() -> Path:
    return settings.data_dir / _KEY_FILE_NAME


def _load_or_create_key() -> bytes:
    configured = (settings.secret_key or "").strip()
    if configured:
        try:
            return base64.urlsafe_b64encode(hashlib.sha256(configured.encode("utf-8")).digest())
        except Exception:  # pragma: no cover - defensive
            pass

    path = _key_path()
    if path.exists():
        return path.read_bytes().strip()

    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    with contextlib.suppress(OSError):  # pragma: no cover - platform dependent
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    log.info("crypto.key_created", path=str(path))
    return key


_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet

        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except Exception as exc:  # pragma: no cover - wrong key / rotated key
        raise ValidationError(
            "the stored provider key could not be decrypted; re-enter the key to continue"
        ) from exc


def mask_secret(value: str | None) -> str | None:
    """Return a display-safe hint such as ``sk-a...9xY2``."""
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}...{value[-4:]}"


def key_hint(value: str | None) -> str | None:
    if not value:
        return None
    return value[-4:]


def secret_file_permissions_ok() -> bool:
    path = _key_path()
    if not path.exists():
        return True
    mode = os.stat(path).st_mode
    return not (mode & stat.S_IRGRP) and not (mode & stat.S_IROTH)
