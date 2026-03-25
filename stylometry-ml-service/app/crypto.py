"""
Enterprise Encryption at Rest — Fernet AES-128
================================================
Mirror of backend/app/crypto.py — kept as an independent copy to avoid any
shared-volume or cross-service import dependency.

Both services MUST share the same ENCRYPTION_KEY environment variable value
so that ciphertexts written by the backend can be decrypted here.

Public API:
  encrypt(text: str) -> str   — returns a URL-safe ciphertext string
  decrypt(token: str) -> str | None — returns plaintext or None on any error
"""

import os
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

def _load_fernet() -> Fernet:
    raw_key = os.environ.get("ENCRYPTION_KEY", "").strip()
    if raw_key:
        try:
            return Fernet(raw_key.encode())
        except Exception:
            logger.warning(
                "ENCRYPTION_KEY env-var is set but is not a valid Fernet key. "
                "Falling back to an ephemeral dev key — DO NOT use in production."
            )
    dev_key = Fernet.generate_key()
    logger.warning(
        "ENCRYPTION_KEY not set — using an ephemeral dev key. "
        "All ciphertexts written by backend will be UNREADABLE here unless "
        "both services share the same ENCRYPTION_KEY."
    )
    return Fernet(dev_key)


_fernet: Fernet = _load_fernet()


def encrypt(text: str) -> str:
    """Encrypt a plaintext string and return a URL-safe ciphertext string."""
    return _fernet.encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> Optional[str]:
    """
    Decrypt a ciphertext token.
    Returns the plaintext string on success, or None if the token is invalid
    (legacy plaintext line, wrong key, or corrupted data).
    """
    try:
        return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        return None
