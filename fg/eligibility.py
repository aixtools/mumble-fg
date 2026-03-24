"""FG-side eligibility evaluation helpers."""

from __future__ import annotations

from typing import Any

from fgbg_common.entity_types import (
    ENTITY_TYPE_ALLIANCE,
    ENTITY_TYPE_CORPORATION,
    ENTITY_TYPE_PILOT,
)


def build_rule_sets(rules: list[dict[str, Any]]) -> dict[str, set[int]]:
    """Build categorized ID sets from ACL rules."""
    rs: dict[str, set[int]] = {
        'allowed_alliances': set(),
        'denied_alliances': set(),
        'allowed_corps': set(),
        'denied_corps': set(),
        'allowed_pilots': set(),
        'denied_pilots': set(),
    }
    for rule in rules:
        entity_id = int(rule['entity_id'])
        entity_type = rule['entity_type']
        deny = bool(rule.get('deny', False))
        if entity_type == ENTITY_TYPE_ALLIANCE:
            (rs['denied_alliances'] if deny else rs['allowed_alliances']).add(entity_id)
        elif entity_type == ENTITY_TYPE_CORPORATION:
            (rs['denied_corps'] if deny else rs['allowed_corps']).add(entity_id)
        elif entity_type == ENTITY_TYPE_PILOT:
            (rs['denied_pilots'] if deny else rs['allowed_pilots']).add(entity_id)
    return rs


DENIAL_REASON_LABELS: dict[str, str] = {
    ENTITY_TYPE_ALLIANCE: 'alliance',
    ENTITY_TYPE_CORPORATION: 'corp',
    ENTITY_TYPE_PILOT: 'pilot',
}

DENIAL_REASON_RANK: dict[str, int] = {
    ENTITY_TYPE_ALLIANCE: 1,
    ENTITY_TYPE_CORPORATION: 2,
    ENTITY_TYPE_PILOT: 3,
}


def _denial_reason_detail(reason_type: str, row: dict[str, Any]) -> str:
    if reason_type == ENTITY_TYPE_PILOT:
        return row['character_name'] or str(row['character_id'])
    if reason_type == ENTITY_TYPE_CORPORATION:
        return row['corporation_name'] or str(row['corporation_id'])
    return row['alliance_name'] or str(row['alliance_id'])


def _prefer_reason(current: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if current is None:
        return candidate
    current_rank = DENIAL_REASON_RANK[current['reason_type']]
    candidate_rank = DENIAL_REASON_RANK[candidate['reason_type']]
    if candidate_rank > current_rank:
        return candidate
    if candidate_rank < current_rank:
        return current
    if candidate['detail'].lower() < current['detail'].lower():
        return candidate
    return current


def explicit_rule_match(rs: dict[str, set[int]], row: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first (highest-priority) matching rule for a character row."""
    cid = row['character_id']
    corp = row['corporation_id']
    ally = row['alliance_id']

    if cid in rs['allowed_pilots']:
        return {'action': 'allow', 'reason_type': ENTITY_TYPE_PILOT, 'detail': _denial_reason_detail(ENTITY_TYPE_PILOT, row)}
    if cid in rs['denied_pilots']:
        return {'action': 'deny', 'reason_type': ENTITY_TYPE_PILOT, 'detail': _denial_reason_detail(ENTITY_TYPE_PILOT, row)}
    if corp in rs['allowed_corps']:
        return {'action': 'allow', 'reason_type': ENTITY_TYPE_CORPORATION, 'detail': _denial_reason_detail(ENTITY_TYPE_CORPORATION, row)}
    if corp in rs['denied_corps']:
        return {'action': 'deny', 'reason_type': ENTITY_TYPE_CORPORATION, 'detail': _denial_reason_detail(ENTITY_TYPE_CORPORATION, row)}
    if ally in rs['allowed_alliances']:
        return {'action': 'allow', 'reason_type': ENTITY_TYPE_ALLIANCE, 'detail': _denial_reason_detail(ENTITY_TYPE_ALLIANCE, row)}
    if ally in rs['denied_alliances']:
        return {'action': 'deny', 'reason_type': ENTITY_TYPE_ALLIANCE, 'detail': _denial_reason_detail(ENTITY_TYPE_ALLIANCE, row)}
    return None


def explicit_rule_matches(rs: dict[str, set[int]], row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all matching rules for a character row."""
    matches: list[dict[str, Any]] = []
    cid = row['character_id']
    corp = row['corporation_id']
    ally = row['alliance_id']

    if cid in rs['allowed_pilots']:
        matches.append({'action': 'allow', 'reason_type': ENTITY_TYPE_PILOT, 'detail': _denial_reason_detail(ENTITY_TYPE_PILOT, row)})
    if cid in rs['denied_pilots']:
        matches.append({'action': 'deny', 'reason_type': ENTITY_TYPE_PILOT, 'detail': _denial_reason_detail(ENTITY_TYPE_PILOT, row)})
    if corp in rs['allowed_corps']:
        matches.append({'action': 'allow', 'reason_type': ENTITY_TYPE_CORPORATION, 'detail': _denial_reason_detail(ENTITY_TYPE_CORPORATION, row)})
    if corp in rs['denied_corps']:
        matches.append({'action': 'deny', 'reason_type': ENTITY_TYPE_CORPORATION, 'detail': _denial_reason_detail(ENTITY_TYPE_CORPORATION, row)})
    if ally in rs['allowed_alliances']:
        matches.append({'action': 'allow', 'reason_type': ENTITY_TYPE_ALLIANCE, 'detail': _denial_reason_detail(ENTITY_TYPE_ALLIANCE, row)})
    if ally in rs['denied_alliances']:
        matches.append({'action': 'deny', 'reason_type': ENTITY_TYPE_ALLIANCE, 'detail': _denial_reason_detail(ENTITY_TYPE_ALLIANCE, row)})
    return matches


def account_rule_decisions(character_rows: list[dict[str, Any]], rs: dict[str, set[int]]) -> dict[int, dict[str, Any]]:
    """Build per-account allow/deny decision from character rows and rule sets."""
    account_rules: dict[int, dict[str, Any]] = {}
    for row in character_rows:
        matches = explicit_rule_matches(rs, row)
        if not matches:
            continue
        user_rules = account_rules.setdefault(row['user_id'], {'allow': None, 'deny': None})
        for match in matches:
            reason = {'reason_type': match['reason_type'], 'detail': match['detail']}
            user_rules[match['action']] = _prefer_reason(user_rules[match['action']], reason)
    return account_rules


def blocked_user_reasons(account_rules: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Identify blocked users: allowed and denied, where deny rank >= allow rank."""
    return {
        user_id: rules['deny']
        for user_id, rules in account_rules.items()
        if rules['allow']
        and rules['deny']
        and DENIAL_REASON_RANK[rules['deny']['reason_type']] >= DENIAL_REASON_RANK[rules['allow']['reason_type']]
    }


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
