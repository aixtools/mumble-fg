"""Reconcile Cube-group-driven pilot allow rules.

Approved members of the Cube groups configured in AccessGrantSettings get an
automatic pilot-level allow AccessRule for their main character, which is all
BG needs to provision full voice registrations (Murmur and ShitSpeak alike).
Rules created here are marked source='group_grant' so the reconciler can
remove them when the member leaves the group without ever touching rules an
admin entered by hand.
"""

from __future__ import annotations

import logging

from .host import get_host_adapter
from .models import (
    ACCESS_RULE_SOURCE_GROUP_GRANT,
    ACL_AUDIT_ACTION_CREATE,
    ACL_AUDIT_ACTION_DELETE,
    ENTITY_TYPE_PILOT,
    AccessGrantSettings,
    AccessRule,
    access_rule_snapshot,
    append_access_rule_audit,
)

logger = logging.getLogger(__name__)


def _desired_grants() -> tuple[dict[int, list[str]], dict[str, int]]:
    """Map main character_id -> granting group names, plus skip counters."""
    skips = {'skipped_denied_org': 0, 'skipped_no_main': 0}
    grant_groups = list(AccessGrantSettings.load().grant_groups.all())
    if not grant_groups:
        return {}, skips

    user_groups: dict[object, set[str]] = {}
    for group in grant_groups:
        memberships = group.memberships.filter(status='approved').select_related('user')
        for membership in memberships:
            user_groups.setdefault(membership.user, set()).add(group.name)

    # Imported lazily: fg.views pulls in optional host machinery at import time.
    from .views import _pilot_has_denied_corp_or_alliance

    adapter = get_host_adapter()
    desired: dict[int, list[str]] = {}
    for user, names in user_groups.items():
        main = adapter.get_main_character(user)
        if main is None:
            skips['skipped_no_main'] += 1
            continue
        character_id = int(main.character_id)
        if _pilot_has_denied_corp_or_alliance(character_id):
            # A managed pilot allow would override the corp/alliance deny
            # (pilot rules take precedence) — never punch through an
            # admin-entered deny automatically.
            skips['skipped_denied_org'] += 1
            continue
        desired[character_id] = sorted(names)
    return desired, skips


def reconcile_group_grants(
    *,
    actor_username: str = 'system',
    source: str = 'acl_group_grant',
) -> dict[str, int]:
    """Converge managed pilot allow rules with grant-group membership.

    Creates missing pilot allow rules for grant-group members (never adopting
    or modifying a pre-existing rule at the same entity_id) and deletes
    source='group_grant' rules whose pilot is no longer entitled. Every
    mutation lands in the ACL audit trail.
    """
    desired, skips = _desired_grants()
    stats = {'created': 0, 'deleted': 0, **skips}

    for character_id, group_names in desired.items():
        rule, created = AccessRule.objects.get_or_create(
            entity_id=character_id,
            defaults={
                'entity_type': ENTITY_TYPE_PILOT,
                'deny': False,
                'source': ACCESS_RULE_SOURCE_GROUP_GRANT,
                'note': 'Auto: comms grant via Cube group(s): ' + ', '.join(group_names),
                'created_by': 'system:group_grant',
            },
        )
        if not created:
            continue
        stats['created'] += 1
        append_access_rule_audit(
            action=ACL_AUDIT_ACTION_CREATE,
            actor_username=actor_username,
            rule=rule,
            source=source,
            metadata={'grant_groups': group_names},
        )

    stale = AccessRule.objects.filter(
        source=ACCESS_RULE_SOURCE_GROUP_GRANT,
    ).exclude(entity_id__in=desired.keys())
    for rule in stale:
        append_access_rule_audit(
            action=ACL_AUDIT_ACTION_DELETE,
            actor_username=actor_username,
            rule=rule,
            source=source,
            previous=access_rule_snapshot(rule),
        )
        rule.delete()
        stats['deleted'] += 1

    if any(stats.values()):
        logger.info(
            'Group-grant reconcile: created=%(created)s deleted=%(deleted)s '
            'skipped_denied_org=%(skipped_denied_org)s skipped_no_main=%(skipped_no_main)s',
            stats,
        )
    return stats
