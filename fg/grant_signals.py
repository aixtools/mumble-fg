"""Event-driven grant reconciliation.

A brand-new allied pilot gets their Cube auto-group at first login, but the
grant reconciler only ran on the 10-minute beat — so their first minutes
showed "Mumble not configured" on the comms dashboard. Listening on the host's
GroupMembership model closes that window: any change to a membership in a
configured grant group enqueues one debounced ``periodic_acl_sync`` run
(reconcile + BG push), converging in seconds instead of minutes. Manual
adds/removals to grant groups get the same treatment.

Wired from ``MumbleFgConfig.ready()``; a host without the accounts app
(generic/mockcube) simply never connects.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)

_GRANT_IDS_CACHE_KEY = 'fg:grant_group_ids'
_GRANT_IDS_TTL = 60
_DEBOUNCE_CACHE_KEY = 'fg:grant_sync_pending'
_DEBOUNCE_SECONDS = 45


def _grant_group_ids() -> set:
    cached = cache.get(_GRANT_IDS_CACHE_KEY)
    if cached is not None:
        return cached
    from .models import AccessGrantSettings

    ids = set(
        AccessGrantSettings.load().grant_groups.values_list('id', flat=True)
    )
    cache.set(_GRANT_IDS_CACHE_KEY, ids, _GRANT_IDS_TTL)
    return ids


def _enqueue_grant_sync():
    # Debounce inside on_commit so a rolled-back transaction never burns the
    # window: many memberships changing in one sweep coalesce into one run.
    if not cache.add(_DEBOUNCE_CACHE_KEY, 1, _DEBOUNCE_SECONDS):
        return
    from .tasks import periodic_acl_sync

    try:
        periodic_acl_sync.delay()
        logger.info('Grant sync enqueued (grant-group membership changed)')
    except Exception:
        cache.delete(_DEBOUNCE_CACHE_KEY)
        logger.exception('Failed to enqueue grant sync; periodic beat will cover it')


def _on_membership_change(sender, instance, **kwargs):
    try:
        if instance.group_id not in _grant_group_ids():
            return
    except Exception:
        logger.exception('Grant-group check failed; skipping event-driven sync')
        return
    transaction.on_commit(_enqueue_grant_sync)


def connect_membership_signals() -> bool:
    """Connect to the host's GroupMembership post_save/post_delete.

    Returns True when connected (Cube-style host), False otherwise.
    """
    from django.apps import apps
    from django.db.models.signals import post_delete, post_save

    try:
        GroupMembership = apps.get_model('accounts', 'GroupMembership')
    except LookupError:
        return False

    post_save.connect(
        _on_membership_change,
        sender=GroupMembership,
        dispatch_uid='fg_grant_sync_on_membership_save',
    )
    post_delete.connect(
        _on_membership_change,
        sender=GroupMembership,
        dispatch_uid='fg_grant_sync_on_membership_delete',
    )
    return True
