"""FG-owned pilot snapshot exporter for BG synchronization."""

from __future__ import annotations

from typing import Any

from django.db import connections, router
from django.utils.timezone import now

from fgbg_common.snapshot import PilotSnapshot


class PilotSnapshotError(RuntimeError):
    """Raised when FG cannot build the pilot snapshot payload."""


def _get_eve_character_model():
    try:
        import accounts.models as accounts_models
    except ImportError:
        return None
    return getattr(accounts_models, 'EveCharacter', None)


def _get_db_for_eve():
    if 'cube' in connections.databases:
        return 'cube'
    eve_character = _get_eve_character_model()
    if eve_character is None:
        return None
    return router.db_for_read(eve_character) or 'default'


def build_pilot_snapshot() -> PilotSnapshot:
    eve_character = _get_eve_character_model()
    db_alias = _get_db_for_eve()
    if eve_character is None or db_alias is None:
        return PilotSnapshot.empty()

    try:
        rows = list(
            eve_character.objects.using(db_alias)
            .filter(pending_delete=False)
            .values(
                'user_id',
                'character_id',
                'character_name',
                'corporation_id',
                'corporation_name',
                'alliance_id',
                'alliance_name',
                'is_main',
            )
            .order_by('user_id', '-is_main', 'character_name', 'character_id')
        )
    except Exception as exc:  # noqa: BLE001
        raise PilotSnapshotError(f'Failed to build pilot snapshot: {exc}') from exc

    return PilotSnapshot.from_rows(rows, generated_at=now().isoformat())


def serialize_pilot_snapshot() -> dict[str, Any]:
    return build_pilot_snapshot().as_dict()
