from __future__ import annotations

import logging
from typing import Any

from .control import BgControlClient, MurmurSyncError
from .models import ACL_AUDIT_ACTION_SYNC, AccessRule, append_access_rule_audit
from .pilot_snapshot import PilotSnapshotError, serialize_pilot_snapshot

logger = logging.getLogger(__name__)
_CONTROL_CLIENT = BgControlClient()


def serialize_acl_rule(rule: AccessRule) -> dict[str, Any]:
    return {
        'entity_id': int(rule.entity_id),
        'entity_type': str(rule.entity_type),
        'deny': bool(rule.deny),
        'acl_admin': bool(rule.acl_admin),
        'note': str(rule.note or ''),
        'created_by': str(rule.created_by or ''),
    }


def serialize_acl_rules() -> list[dict[str, Any]]:
    return [serialize_acl_rule(rule) for rule in AccessRule.objects.order_by('entity_type', 'entity_id')]


def sync_acl_rules_to_bg(
    *,
    requested_by: str,
    actor_username: str,
    source: str,
    trigger: str,
    rule: AccessRule | None = None,
    acl_id: int | None = None,
    reconcile: bool = True,
    provision_server_id: int | None = None,
) -> dict[str, Any]:
    rules = serialize_acl_rules()
    pilot_snapshot = serialize_pilot_snapshot()
    control_url = _CONTROL_CLIENT.base_url()
    metadata = {
        'trigger': str(trigger or ''),
        'acl_count': len(rules),
        'pilot_snapshot_account_count': len(pilot_snapshot.get('accounts', [])),
    }

    try:
        response = _CONTROL_CLIENT.sync_access_rules(
            rules,
            requested_by=requested_by,
            is_super=True,
            pilot_snapshot=pilot_snapshot,
            reconcile=reconcile,
            server_id=provision_server_id,
        )
    except (MurmurSyncError, PilotSnapshotError) as exc:
        metadata.update(
            {
                'sync_status': 'failed',
                'error': str(exc),
                'control_url': control_url,
            }
        )
        append_access_rule_audit(
            action=ACL_AUDIT_ACTION_SYNC,
            actor_username=actor_username,
            rule=rule,
            acl_id=acl_id,
            source=source,
            metadata=metadata,
        )
        logger.warning(
            'ACL sync failed for source=%s requested_by=%s control_url=%s: %s',
            source,
            requested_by,
            control_url,
            exc,
        )
        raise

    metadata.update(
        {
            'sync_status': str(response.get('status', 'completed')).lower(),
            'created': response.get('created'),
            'updated': response.get('updated'),
            'deleted': response.get('deleted'),
            'total': response.get('total'),
        }
    )
    append_access_rule_audit(
        action=ACL_AUDIT_ACTION_SYNC,
        actor_username=actor_username,
        rule=rule,
        acl_id=acl_id,
        source=source,
        metadata=metadata,
    )
    return response
