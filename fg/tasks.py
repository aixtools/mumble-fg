import logging

from .acl_sync import sync_acl_rules_to_bg
from .control import BgControlClient, BgSyncError
from .models import MumbleUser
from .views import _compute_display_name, _compute_groups

logger = logging.getLogger(__name__)
_CONTROL_CLIENT = BgControlClient()


def update_mumble_groups(mumble_user_id):
    try:
        mumble_user = MumbleUser.objects.select_related('user').get(
            pk=mumble_user_id, is_active=True
        )
    except MumbleUser.DoesNotExist:
        return
    changed_fields = []
    groups = _compute_groups(mumble_user.user, mumble_user=mumble_user)
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
            try:
                _CONTROL_CLIENT.sync_live_admin_membership(
                    mumble_user,
                    requested_by='fg.periodic_group_update',
                )
            except BgSyncError:
                logger.warning(
                    'Failed to sync groups to BG for MumbleUser %s (pk=%s)',
                    mumble_user.username, mumble_user_id,
                    exc_info=True,
                )


def update_all_mumble_groups():
    mu_ids = list(MumbleUser.objects.filter(is_active=True).values_list('pk', flat=True))
    logger.info('Running mumble group updates for %d active users', len(mu_ids))
    for mu_id in mu_ids:
        update_mumble_groups(mu_id)


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
