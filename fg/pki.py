"""FG-side PKI for decrypting secrets sent by BG.

This is separate from fg.crypto (which is BG-public-key-only and used for
encrypting passwords to BG).
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_private_key = None
_public_key_pem: bytes | None = None
_initialized = False


def initialize(*, private_key_path: str | None = None, public_key_path: str | None = None) -> bool:
    """Load FG keypair.

    Sources:
    - FG_PRIVATE_KEY_PATH / settings.FG_PRIVATE_KEY_PATH
    - FG_PUBLIC_KEY_PATH / settings.FG_PUBLIC_KEY_PATH
    - FG_PKI_PASSPHRASE / settings.FG_PKI_PASSPHRASE
    """
    global _private_key, _public_key_pem, _initialized

    if private_key_path is None:
        private_key_path = os.environ.get("FG_PRIVATE_KEY_PATH", "").strip()
        if not private_key_path:
            try:
                from django.conf import settings
                private_key_path = str(getattr(settings, "FG_PRIVATE_KEY_PATH", "") or "").strip()
            except Exception:
                private_key_path = ""

    if public_key_path is None:
        public_key_path = os.environ.get("FG_PUBLIC_KEY_PATH", "").strip()
        if not public_key_path:
            try:
                from django.conf import settings
                public_key_path = str(getattr(settings, "FG_PUBLIC_KEY_PATH", "") or "").strip()
            except Exception:
                public_key_path = ""

    passphrase = (os.environ.get("FG_PKI_PASSPHRASE") or "").encode("utf-8") or None
    if passphrase is None:
        try:
            from django.conf import settings
            value = getattr(settings, "FG_PKI_PASSPHRASE", None)
            if isinstance(value, str) and value:
                passphrase = value.encode("utf-8")
        except Exception:
            passphrase = None

    if not private_key_path:
        _initialized = True
        logger.info("No FG_PRIVATE_KEY_PATH configured — FG PKI disabled")
        return False

    key_path = Path(private_key_path)
    if not key_path.exists():
        _initialized = True
        logger.info("FG private key not found at %s — FG PKI disabled", key_path)
        return False

    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    raw_private = key_path.read_bytes()
    _private_key = load_pem_private_key(raw_private, password=passphrase)

    # Optional public key PEM (used when requesting BG key exports)
    if public_key_path:
        pub_path = Path(public_key_path)
        if pub_path.exists():
            _public_key_pem = pub_path.read_bytes()
    _initialized = True
    return True


def is_initialized() -> bool:
    return _initialized


def can_decrypt() -> bool:
    return _initialized and _private_key is not None


def public_key_pem() -> bytes | None:
    return _public_key_pem


def decrypt_secret(ciphertext_b64: str) -> str:
    """Decrypt a base64 RSA-OAEP ciphertext sent by BG (encrypted to FG public key)."""
    if _private_key is None:
        raise RuntimeError("FG private key not available — cannot decrypt")
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes

    ciphertext = base64.b64decode(ciphertext_b64.encode("ascii"))
    plaintext = _private_key.decrypt(
        ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return plaintext.decode("utf-8")


def status() -> dict[str, Any]:
    return {
        "initialized": _initialized,
        "has_private_key": _private_key is not None,
        "has_public_key": _public_key_pem is not None,
        "can_decrypt": can_decrypt(),
    }

