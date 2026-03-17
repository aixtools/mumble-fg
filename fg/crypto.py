"""FG-side password encryption using BG's public key.

FG encrypts passwords before sending them over the control channel.
FG never has access to BG's private key.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_public_key = None
_public_key_pem: bytes | None = None
_initialized = False


def initialize(*, public_key_pem: bytes | None = None, public_key_path: str | None = None) -> bool:
    """Load BG's public key for password encryption.

    Sources (checked in order):
      1. public_key_pem argument
      2. public_key_path argument
      3. BG_PUBLIC_KEY_PATH env var
      4. settings.BG_PUBLIC_KEY_PATH
    """
    global _public_key, _public_key_pem, _initialized

    if public_key_pem is None and public_key_path is None:
        public_key_path = os.environ.get('BG_PUBLIC_KEY_PATH', '')
        if not public_key_path:
            try:
                from django.conf import settings
                public_key_path = getattr(settings, 'BG_PUBLIC_KEY_PATH', '')
            except Exception:
                pass

    if public_key_pem is not None:
        _public_key_pem = public_key_pem
    elif public_key_path:
        path = Path(public_key_path)
        if path.exists():
            _public_key_pem = path.read_bytes()
        else:
            logger.info('BG public key not found at %s — encryption disabled', path)
            _initialized = True
            return False
    else:
        logger.info('No BG public key configured — encryption disabled')
        _initialized = True
        return False

    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    _public_key = load_pem_public_key(_public_key_pem)
    _initialized = True
    logger.info('Loaded BG public key for password encryption')
    return True


def is_available() -> bool:
    return _initialized and _public_key is not None


def encrypt_password(plaintext: str) -> str:
    """Encrypt a password for transit to BG. Returns base64-encoded ciphertext."""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes

    if _public_key is None:
        raise RuntimeError('BG public key not available — cannot encrypt password')

    ciphertext = _public_key.encrypt(
        plaintext.encode('utf-8'),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode('ascii')


def fetch_from_bg(control_url: str | None = None) -> bool:
    """Fetch BG's public key from its /v1/public-key endpoint.

    Falls back to MURMUR_CONTROL_URL env var or Django settings.
    """
    if control_url is None:
        control_url = os.environ.get('MURMUR_CONTROL_URL', '')
        if not control_url:
            try:
                from django.conf import settings
                control_url = getattr(settings, 'MURMUR_CONTROL_URL', '')
            except Exception:
                pass
    if not control_url:
        logger.info('No MURMUR_CONTROL_URL configured — cannot fetch BG public key')
        return False

    import urllib.request
    url = f"{control_url.rstrip('/')}/v1/public-key"
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        pem = resp.read()
    except Exception:
        logger.info('Failed to fetch BG public key from %s', url)
        return False

    if not pem or not pem.startswith(b'-----BEGIN PUBLIC KEY-----'):
        logger.info('Invalid public key response from %s', url)
        return False

    return initialize(public_key_pem=pem)


def status() -> dict[str, Any]:
    return {
        'initialized': _initialized,
        'has_public_key': _public_key is not None,
        'can_encrypt': is_available(),
    }
