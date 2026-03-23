"""FG-owned pilot snapshot exporter for BG synchronization."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.db import connections, router
from django.db.utils import OperationalError, ProgrammingError
from django.utils.timezone import now

from fg.models import PilotSnapshotHash
from fgbg_common.snapshot import PilotSnapshot

logger = logging.getLogger(__name__)


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
        try:
            if 'accounts_evecharacter' in connections['cube'].introspection.table_names():
                return 'cube'
        except Exception:
            pass
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
                'corporation_id',
                'alliance_id',
                'is_main',
            )
            .order_by('user_id', '-is_main', 'character_id')
        )
    except Exception as exc:  # noqa: BLE001
        raise PilotSnapshotError(f'Failed to build pilot snapshot: {exc}') from exc

    snapshot = PilotSnapshot.from_rows(rows, generated_at=now().isoformat())
    user_model = get_user_model()
    user_db_alias = router.db_for_read(user_model) or 'default'
    users_by_id = {
        int(user.id): user
        for user in user_model.objects.using(user_db_alias).filter(id__in=[account.pkid for account in snapshot.accounts])
    }

    from fg.views import _compute_display_name

    accounts = tuple(
        type(account)(
            pkid=account.pkid,
            account_username=str(users_by_id.get(account.pkid).username) if users_by_id.get(account.pkid) else '',
            display_name=_compute_display_name(users_by_id.get(account.pkid)) if users_by_id.get(account.pkid) else '',
            characters=account.characters,
        )
        for account in snapshot.accounts
    )
    return PilotSnapshot(accounts=accounts, generated_at=snapshot.generated_at)


def _cache_snapshot_hashes(snapshot: PilotSnapshot) -> None:
    accounts = tuple(snapshot.accounts)
    if not accounts:
        return

    pkids = [int(account.pkid) for account in accounts]
    existing = {
        int(row.pkid): row
        for row in PilotSnapshotHash.objects.filter(pkid__in=pkids)
    }

    to_create = []
    to_update = []
    for account in accounts:
        hash_value = str(account.pilot_data_hash or '')
        row = existing.get(int(account.pkid))
        if row is None:
            to_create.append(PilotSnapshotHash(pkid=account.pkid, pilot_data_hash=hash_value))
            continue
        if row.pilot_data_hash != hash_value:
            row.pilot_data_hash = hash_value
            to_update.append(row)

    if to_create:
        PilotSnapshotHash.objects.bulk_create(to_create)
    for row in to_update:
        row.save(update_fields=['pilot_data_hash', 'updated_at'])


def serialize_pilot_snapshot() -> dict[str, Any]:
    snapshot = build_pilot_snapshot()
    try:
        _cache_snapshot_hashes(snapshot)
    except (OperationalError, ProgrammingError):  # migration not applied yet
        logger.warning('Pilot snapshot hash cache table unavailable; continuing without FG hash persistence.')
    return snapshot.as_dict()
