"""Field-level encryption helpers for sensitive data."""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("FIELD_ENCRYPTION_KEY is required")

    try:
        base64.urlsafe_b64decode(key)
    except Exception as exc:  # pragma: no cover - defensive validation
        raise RuntimeError("FIELD_ENCRYPTION_KEY must be a base64-encoded 32-byte Fernet key") from exc

    return Fernet(key.encode("utf-8"))


def encrypt_field(plaintext: str) -> bytes:
    """Encrypt a sensitive field value."""
    return _get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_field(ciphertext: bytes) -> str:
    """Decrypt a sensitive field value."""
    return _get_fernet().decrypt(ciphertext).decode("utf-8")