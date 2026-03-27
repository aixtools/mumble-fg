import logging

from .acl_sync import sync_acl_rules_to_bg
from .control import BgControlClient, BgSyncError
from .group_mapping import build_group_mapping_config, effective_groups_csv_for_user
from .models import MumbleUser
from .runtime import get_runtime_service
from .views import _compute_display_name

logger = logging.getLogger(__name__)
_CONTROL_CLIENT = BgControlClient()


def _push_groups_to_bg(obj):
    try:
        _CONTROL_CLIENT.sync_live_admin_membership(
            obj, requested_by='fg.periodic_group_update',
        )
    except BgSyncError:
        logger.warning(
            'Failed to push groups to BG for user_id=%s',
            obj.user_id, exc_info=True,
        )


def update_mumble_groups(mumble_user_id):
    try:
        mumble_user = MumbleUser.objects.select_related('user').get(
            pk=mumble_user_id, is_active=True
        )
    except MumbleUser.DoesNotExist:
        return
    changed_fields = []
    groups = effective_groups_csv_for_user(mumble_user.user, mumble_user=mumble_user)
    if mumble_user.groups != groups:
        mumble_user.groups = groups
        changed_fields.append('groups')
    display_name = _compute_display_name(mumble_user.user)
    if mumble_user.display_name != display_name:
        mumble_user.display_name = display_name
        changed_fields.append('display_name')
    if changed_fields:
        changed_fields.append('updated_at')
        mumble_user.save(update_fields=changed_fields)
        logger.info(
            'Updated MumbleUser %s (pk=%s): %s',
            mumble_user.username, mumble_user_id, ', '.join(changed_fields),
        )
        if 'groups' in changed_fields:
            _push_groups_to_bg(mumble_user)


def _update_registration_groups(registration, *, config=None):
    new_groups = effective_groups_csv_for_user(
        registration.user, mumble_user=registration, _config=config,
    )

    if registration.groups == new_groups:
        return

    logger.info(
        'Updating groups for user_id=%s (%s): %s -> %s',
        registration.user_id, registration.display_name, registration.groups, new_groups,
    )
    registration.groups = new_groups
    _push_groups_to_bg(registration)


def update_all_mumble_groups():
    try:
        service = get_runtime_service()
        registrations = service.list_registrations()
        service.attach_users(registrations)
    except BgSyncError:
        logger.warning('Failed to fetch BG registrations for periodic group sync', exc_info=True)
        return

    active = [r for r in registrations if r.is_active and r.user is not None]
    logger.info('Running mumble group updates for %d active registrations', len(active))
    config = build_group_mapping_config()
    for reg in active:
        _update_registration_groups(reg, config=config)


def periodic_acl_sync():
    response = sync_acl_rules_to_bg(
        requested_by='fg.periodic',
        actor_username='system',
        source='acl_periodic_sync',
        trigger='periodic',
    )
    logger.info(
        'Periodic ACL sync completed: total=%s created=%s updated=%s deleted=%s',
        response.get('total'),
        response.get('created'),
        response.get('updated'),
        response.get('deleted'),
    )
    return response
