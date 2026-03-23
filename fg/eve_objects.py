"""FG-owned EVE object dictionary serializer for BG synchronization."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.db import connections, router

from fgbg_common.entity_types import (
    ENTITY_TYPE_ALLIANCE,
    ENTITY_TYPE_CORPORATION,
    ENTITY_TYPE_PILOT,
    TYPE_TO_CATEGORY,
)


class EveObjectError(RuntimeError):
    """Raised when FG cannot build the EVE object payload."""


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


def _ticker_maps(db_alias: str) -> tuple[dict[int, str], dict[int, str]]:
    """Return (alliance_tickers, corp_tickers) keyed by ID."""
    alliance_tickers: dict[int, str] = {}
    corp_tickers: dict[int, str] = {}
    try:
        import accounts.models as accounts_models
    except ImportError:
        return alliance_tickers, corp_tickers

    EveAllianceInfo = getattr(accounts_models, 'EveAllianceInfo', None)
    if EveAllianceInfo is not None:
        alliance_tickers = {
            int(row['alliance_id']): str(row['alliance_ticker'] or '')
            for row in EveAllianceInfo.objects.using(db_alias)
            .exclude(alliance_id__isnull=True)
            .values('alliance_id', 'alliance_ticker')
        }

    EveCorporationInfo = getattr(accounts_models, 'EveCorporationInfo', None)
    if EveCorporationInfo is not None:
        corp_tickers = {
            int(row['corporation_id']): str(row['corporation_ticker'] or '')
            for row in EveCorporationInfo.objects.using(db_alias)
            .exclude(corporation_id__isnull=True)
            .values('corporation_id', 'corporation_ticker')
        }

    return alliance_tickers, corp_tickers


def serialize_eve_objects() -> list[dict[str, Any]]:
    """
    Build immutable EVE object dictionary rows for BG.

    Output rows:
      - entity_id (int)
      - type (pilot|corporation|alliance)
      - category (character|corporation|alliance)
      - name (str)
      - ticker (str; pilot ticker is empty)
    """
    eve_character = _get_eve_character_model()
    db_alias = _get_db_for_eve()
    if eve_character is None or db_alias is None:
        return []

    try:
        rows = list(
            eve_character.objects.using(db_alias)
            .filter(pending_delete=False)
            .values(
                'character_id',
                'character_name',
                'corporation_id',
                'corporation_name',
                'alliance_id',
                'alliance_name',
            )
            .order_by('character_id')
        )
    except Exception as exc:  # noqa: BLE001
        raise EveObjectError(f'Failed to build EVE object payload: {exc}') from exc

    alliance_tickers, corp_tickers = _ticker_maps(db_alias)
    objects_by_type: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)

    for row in rows:
        pilot_id = row.get('character_id')
        if pilot_id:
            objects_by_type[ENTITY_TYPE_PILOT][int(pilot_id)] = {
                'entity_id': int(pilot_id),
                'type': ENTITY_TYPE_PILOT,
                'category': TYPE_TO_CATEGORY[ENTITY_TYPE_PILOT],
                'name': str(row.get('character_name') or ''),
                'ticker': '',
            }

        corp_id = row.get('corporation_id')
        if corp_id:
            corp_id = int(corp_id)
            objects_by_type[ENTITY_TYPE_CORPORATION][corp_id] = {
                'entity_id': corp_id,
                'type': ENTITY_TYPE_CORPORATION,
                'category': TYPE_TO_CATEGORY[ENTITY_TYPE_CORPORATION],
                'name': str(row.get('corporation_name') or ''),
                'ticker': str(corp_tickers.get(corp_id, '') or ''),
            }

        alliance_id = row.get('alliance_id')
        if alliance_id:
            alliance_id = int(alliance_id)
            objects_by_type[ENTITY_TYPE_ALLIANCE][alliance_id] = {
                'entity_id': alliance_id,
                'type': ENTITY_TYPE_ALLIANCE,
                'category': TYPE_TO_CATEGORY[ENTITY_TYPE_ALLIANCE],
                'name': str(row.get('alliance_name') or ''),
                'ticker': str(alliance_tickers.get(alliance_id, '') or ''),
            }

    output: list[dict[str, Any]] = []
    for entity_type in (ENTITY_TYPE_ALLIANCE, ENTITY_TYPE_CORPORATION, ENTITY_TYPE_PILOT):
        output.extend(
            objects_by_type[entity_type][entity_id]
            for entity_id in sorted(objects_by_type[entity_type])
        )
    return output
