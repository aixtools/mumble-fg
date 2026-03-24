"""Pure eligibility evaluation engine — no ORM, no Django dependencies.

All functions operate on plain dicts and sets. The caller (FG or BG) is
responsible for querying its own data source and feeding the results here.

Character row dicts must have these keys:
    user_id, character_id, character_name,
    corporation_id, corporation_name,
    alliance_id, alliance_name

Rule sets dict (``rs``) must have these keys:
    allowed_alliances, denied_alliances,
    allowed_corps, denied_corps,
    allowed_pilots, denied_pilots
Each value is a set of integer entity IDs.
"""

from __future__ import annotations

from typing import Any

from .entity_types import (
    ENTITY_TYPE_ALLIANCE,
    ENTITY_TYPE_CORPORATION,
    ENTITY_TYPE_PILOT,
)
from .snapshot import PilotAccount, PilotSnapshot


# ------------------------------------------------------------------
# Rule set construction
# ------------------------------------------------------------------

def build_rule_sets(rules: list[dict[str, Any]]) -> dict[str, set[int]]:
    """Build categorised ID sets from a list of rule dicts.

    Each rule dict must have: entity_id (int), entity_type (str), deny (bool).
    """
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


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# Single-character rule matching
# ------------------------------------------------------------------

def _denial_reason_detail(reason_type: str, row: dict[str, Any]) -> str:
    if reason_type == ENTITY_TYPE_PILOT:
        return row['character_name'] or str(row['character_id'])
    if reason_type == ENTITY_TYPE_CORPORATION:
        return row['corporation_name'] or str(row['corporation_id'])
    return row['alliance_name'] or str(row['alliance_id'])


def _prefer_reason(current: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    """Choose the most specific reason (higher rank wins, alphabetic tie-break)."""
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
    """Return the first (highest-priority) matching rule for one character row.

    Check order: pilot > corp > alliance. Within a tier, allow is checked first.
    Returns None if no rule matches.
    """
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
    """Return ALL matching rules for one character row (can have both allow and deny)."""
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


# ------------------------------------------------------------------
# Account-level decisions
# ------------------------------------------------------------------

def account_rule_decisions(character_rows: list[dict[str, Any]], rs: dict[str, set[int]]) -> dict[int, dict[str, Any]]:
    """Build per-account allow/deny decision from character rows and rule sets.

    Returns: {user_id: {'allow': reason|None, 'deny': reason|None}}
    """
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
    """Identify blocked users: allowed AND denied, where deny rank >= allow rank.

    Returns: {user_id: deny_reason} for blocked users only.
    """
    return {
        user_id: rules['deny']
        for user_id, rules in account_rules.items()
        if rules['allow']
        and rules['deny']
        and DENIAL_REASON_RANK[rules['deny']['reason_type']] >= DENIAL_REASON_RANK[rules['allow']['reason_type']]
    }


def _snapshot_character_row(account: PilotAccount, *, character) -> dict[str, Any]:
    return {
        'user_id': account.pkid,
        'character_id': character.character_id,
        'character_name': character.character_name,
        'corporation_id': character.corporation_id,
        'corporation_name': character.corporation_name,
        'alliance_id': character.alliance_id,
        'alliance_name': character.alliance_name,
    }


def account_rule_decisions_from_snapshot(snapshot: PilotSnapshot, rs: dict[str, set[int]]) -> dict[int, dict[str, Any]]:
    """Build per-account allow/deny decision from an account-oriented snapshot."""
    account_rules: dict[int, dict[str, Any]] = {}
    for account in snapshot.accounts:
        user_rules = account_rules.setdefault(account.pkid, {'allow': None, 'deny': None})
        for character in account.characters:
            matches = explicit_rule_matches(rs, _snapshot_character_row(account, character=character))
            for match in matches:
                reason = {'reason_type': match['reason_type'], 'detail': match['detail']}
                user_rules[match['action']] = _prefer_reason(user_rules[match['action']], reason)
    return account_rules

