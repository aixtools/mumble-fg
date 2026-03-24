"""FG-side eligibility helpers built on shared core logic."""

from __future__ import annotations

from typing import Any

from fgbg_common.eligibility import (
    DENIAL_REASON_LABELS,
    account_rule_decisions,
    blocked_user_reasons,
    explicit_rule_match,
)
from fgbg_common.entity_types import ENTITY_TYPE_PILOT


def all_referenced_ids(rs: dict[str, set[int]]) -> dict[str, set[int]]:
    """Return union of allow+deny IDs per entity type, for FG query filters."""
    return {
        'alliance_ids': rs['allowed_alliances'] | rs['denied_alliances'],
        'corporation_ids': rs['allowed_corps'] | rs['denied_corps'],
        'pilot_ids': rs['allowed_pilots'] | rs['denied_pilots'],
    }


def blocked_main_list(
    character_rows: list[dict[str, Any]],
    main_rows: dict[int, dict[str, Any]],
    rs: dict[str, set[int]],
) -> list[dict[str, Any]]:
    """Return blocked accounts with their main character and deny reason."""
    blocked_by_user = blocked_user_reasons(account_rule_decisions(character_rows, rs))
    if not blocked_by_user:
        return []

    pilots: list[dict[str, Any]] = []
    for user_id, reason in blocked_by_user.items():
        main = main_rows.get(user_id)
        if not main:
            continue
        character_name = main['character_name']
        denied_as = DENIAL_REASON_LABELS[reason['reason_type']]
        denied_detail = reason['detail']
        pilots.append({
            'character_name': character_name,
            'display_name': f'{character_name} (denied as: {denied_detail})',
            'corporation': main.get('corporation_name') or '-',
            'alliance': main.get('alliance_name') or '-',
            'denied_as': denied_as,
            'denied_detail': denied_detail,
        })

    pilots.sort(key=lambda p: p['character_name'].lower())
    return pilots


def eligible_account_list(
    character_rows: list[dict[str, Any]],
    main_rows: dict[int, dict[str, Any]],
    rs: dict[str, set[int]],
) -> list[dict[str, Any]]:
    """Return eligible accounts (allowed, not blocked) with pilot alt lines."""
    blocked_ids = set(blocked_user_reasons(account_rule_decisions(character_rows, rs)))

    allowed_rows_by_user: dict[int, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for row in character_rows:
        if row['user_id'] in blocked_ids:
            continue
        match = explicit_rule_match(rs, row)
        if not match or match.get('action') != 'allow':
            continue
        allowed_rows_by_user.setdefault(row['user_id'], []).append((row, match))

    if not allowed_rows_by_user:
        return []

    pilots: list[dict[str, Any]] = []
    for user_id, allowed_rows in allowed_rows_by_user.items():
        main = main_rows.get(user_id)
        if not main:
            continue

        alt_lines = sorted(
            {
                row['character_name']
                for row, match in allowed_rows
                if match['reason_type'] == ENTITY_TYPE_PILOT
                and row['character_id'] != main['character_id']
            },
            key=str.lower,
        )
        pilot_lines = [main['character_name'], *alt_lines]
        pilots.append({
            'character_name': main['character_name'],
            'pilot_lines': pilot_lines,
            'corporation': main.get('corporation_name') or '-',
            'alliance': main.get('alliance_name') or '-',
        })

    pilots.sort(key=lambda p: p['character_name'].lower())
    return pilots
