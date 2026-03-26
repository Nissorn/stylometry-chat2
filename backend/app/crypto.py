"""
Enterprise Encryption at Rest — Fernet AES-128
================================================
Reads ENCRYPTION_KEY from the environment (must be a valid Fernet key string,
i.e. 32 url-safe base64-encoded bytes produced by ``Fernet.generate_key()``).

PRODUCTION CONTRACT
-------------------
If ENCRYPTION_KEY is absent or malformed the module raises RuntimeError at
import time, which kills the uvicorn worker before it can accept any traffic.
There is NO silent fallback to an ephemeral key — that pattern allowed data
to become permanently unreadable after a container restart and is hereby
forbidden.

Generating a valid key (run once, store in your .env / Droplet secret):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Public API
----------
  encrypt(text: str) -> str
      Encrypts a UTF-8 string and returns a URL-safe ciphertext string.

  decrypt(token: str) -> str | None
      Decrypts a ciphertext token.  Returns the plaintext on success, or
      None on any error (wrong key, corrupted data, legacy plain-text line).
      Never raises — callers must treat None as "undecryptable".
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal key loader — runs exactly once at module import time
# ---------------------------------------------------------------------------


def _load_fernet() -> Fernet:
    """
    Load and validate the Fernet key from the environment.

    Raises
    ------
    RuntimeError
        If ENCRYPTION_KEY is not set or is not a valid Fernet key.
        This is intentional: the application must not start without a
        known, stable encryption key.
    """
    raw_key = os.environ.get("ENCRYPTION_KEY", "").strip()

    if not raw_key:
        raise RuntimeError(
            "\n\n"
            "╔══════════════════════════════════════════════════════════╗\n"
            "║  FATAL — ENCRYPTION_KEY environment variable is not set  ║\n"
            "╠══════════════════════════════════════════════════════════╣\n"
            "║  The application refuses to start without a stable       ║\n"
            "║  Fernet encryption key.  All baseline data on disk would ║\n"
            "║  become permanently unreadable if an ephemeral key were  ║\n"
            "║  used instead.                                           ║\n"
            "║                                                          ║\n"
            "║  Generate a key and add it to your .env:                 ║\n"
            '║    python -c "from cryptography.fernet import Fernet;    ║\n'
            '║               print(Fernet.generate_key().decode())"     ║\n'
            "║                                                          ║\n"
            "║  Then set:  ENCRYPTION_KEY=<the key above>               ║\n"
            "╚══════════════════════════════════════════════════════════╝\n"
        )

    try:
        fernet = Fernet(raw_key.encode())
        # Perform a round-trip smoke-test to catch base64-padding issues early.
        _probe = fernet.decrypt(fernet.encrypt(b"probe"))
        assert _probe == b"probe"
        logger.info("[CRYPTO] ENCRYPTION_KEY loaded and validated successfully.")
        print("[CRYPTO] ENCRYPTION_KEY loaded and validated successfully.")
        return fernet
    except Exception as exc:
        raise RuntimeError(
            "\n\n"
            "╔══════════════════════════════════════════════════════════╗\n"
            "║  FATAL — ENCRYPTION_KEY is set but is INVALID            ║\n"
            "╠══════════════════════════════════════════════════════════╣\n"
            f"║  Error: {str(exc)[:50]:<50} ║\n"
            "║                                                          ║\n"
            "║  A valid Fernet key is exactly 32 url-safe base64 bytes. ║\n"
            "║  Re-generate with:                                       ║\n"
            '║    python -c "from cryptography.fernet import Fernet;    ║\n'
            '║               print(Fernet.generate_key().decode())"     ║\n'
            "╚══════════════════════════════════════════════════════════╝\n"
        ) from exc


# Module-level singleton — validated at import time (= at uvicorn startup).
_fernet: Fernet = _load_fernet()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encrypt(text: str) -> str:
    """
    Encrypt *text* and return a URL-safe ciphertext string.

    Parameters
    ----------
    text:
        The plaintext UTF-8 string to encrypt.

    Returns
    -------
    str
        A Fernet token (URL-safe base64) that can be safely stored on disk
        and round-tripped through :func:`decrypt`.
    """
    return _fernet.encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> Optional[str]:
    """
    Decrypt a Fernet *token*.

    Returns the plaintext string on success, or ``None`` on any failure
    (wrong key, corrupted data, legacy plain-text line that was never
    encrypted).  This function never raises so that callers can safely
    fall back to treating the raw line as plain-text when migrating
    pre-encryption baseline files.

    Parameters
    ----------
    token:
        A Fernet ciphertext string as returned by :func:`encrypt`.

    Returns
    -------
    str | None
        Decrypted plaintext, or ``None`` if decryption failed.
    """
    try:
        return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        return None
