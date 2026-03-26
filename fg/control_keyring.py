from __future__ import annotations

import uuid

from django.db import transaction

from fg.models import ControlChannelKeyEntry
from fg.pki import can_decrypt as pki_can_decrypt, decrypt_secret


KEEP_MAX = 80


def prune() -> None:
    keep_ids: set[int] = set(
        ControlChannelKeyEntry.objects.order_by("-created_at", "-id")
        .values_list("id", flat=True)[:KEEP_MAX]
    )
    ControlChannelKeyEntry.objects.exclude(id__in=keep_ids).delete()


def has_key_id(key_id: str) -> bool:
    try:
        uuid.UUID(str(key_id))
    except Exception:
        return False
    return ControlChannelKeyEntry.objects.filter(key_id=str(key_id)).exists()


def store_encrypted(*, key_id: str, secret_ciphertext_b64: str) -> None:
    """Upsert a keyring entry. Ciphertext is assumed to be encrypted for FG."""
    key_id_value = str(uuid.UUID(str(key_id)))
    with transaction.atomic():
        ControlChannelKeyEntry.objects.update_or_create(
            key_id=key_id_value,
            defaults={"secret_ciphertext_b64": str(secret_ciphertext_b64)},
        )
        prune()


def decrypt_active_keypairs(*, limit: int = KEEP_MAX) -> list[tuple[str, str]]:
    """Return (key_id, plaintext_secret) newest-first.

    Requires FG PKI private key to be available for decryption.
    """
    if not pki_can_decrypt():
        return []
    prune()
    rows = list(
        ControlChannelKeyEntry.objects.order_by("-created_at", "-id")
        .only("key_id", "secret_ciphertext_b64")[: int(limit)]
    )
    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        secret = decrypt_secret(row.secret_ciphertext_b64)
        if secret in seen:
            continue
        values.append((str(row.key_id), secret))
        seen.add(secret)
    return values

