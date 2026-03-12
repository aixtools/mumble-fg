import logging
import secrets
import string

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Exists, OuterRef, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.models import EveCharacter, GroupMembership
from modules.corporation.core import _user_is_alliance_leader
from modules.corporation.models import CorporationSettings
from .pilot.control import (
    MumbleSyncError,
    reset_mumble_password,
    sync_live_admin_membership,
    sync_mumble_registration,
    unregister_mumble_registration,
)
from .pilot.models import MumbleServer, MumbleSession, MumbleUser

logger = logging.getLogger(__name__)


def _generate_password(length=16):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _sync_remote_registration(mumble_user, password=None):
    return sync_mumble_registration(
        mumble_user,
        password=password,
        requested_by=str(getattr(mumble_user.user, 'username', 'unknown')),
    )


def _unregister_remote_registration(mumble_user):
    return unregister_mumble_registration(
        mumble_user,
        requested_by=str(getattr(mumble_user.user, 'username', 'unknown')),
    )


def _sync_live_admin_membership(mumble_user):
    return sync_live_admin_membership(
        mumble_user,
        requested_by=str(getattr(mumble_user.user, 'username', 'unknown')),
    )


def _sync_password(mumble_user, password=None):
    return reset_mumble_password(
        mumble_user,
        password=password,
        requested_by=str(getattr(mumble_user.user, 'username', 'unknown')),
    )


def _has_alliance_leader_membership(user):
    if not user.is_authenticated:
        return False

    alliance_groups = CorporationSettings.load().alliance_leader_groups.all()
    if not alliance_groups:
        return False

    return GroupMembership.objects.filter(
        user=user,
        status='approved',
        group__in=alliance_groups,
    ).exists()


def _get_mumble_username(user):
    main = EveCharacter.objects.filter(user=user, is_main=True).first()
    if main:
        return main.character_name.replace(' ', '_')
    return user.username.replace(' ', '_')


def _get_ticker(endpoint, label):
    """Fetch a ticker from ESI. Returns the ticker string or empty string on failure."""
    try:
        from modules.esi_queue.adapter import EsiQueueClient
        esi = EsiQueueClient(source='mumble')
        data = esi.make_request(endpoint)
        if data and isinstance(data, dict):
            ticker = data.get('ticker', '')
            if not ticker:
                logger.warning('ESI %s response missing ticker key: %s', label, endpoint)
            return ticker
        logger.warning('ESI %s returned unexpected data for %s: %r', label, endpoint, data)
    except Exception:
        logger.exception('Failed to fetch %s ticker from ESI endpoint %s', label, endpoint)
    return ''


def _compute_display_name(user):
    """Build display name like [ALLIANCE.CORP] Character Name."""
    main = EveCharacter.objects.filter(user=user, is_main=True).first()
    if not main:
        return user.username

    char_name = main.character_name
    tags = []

    if main.alliance_id:
        ticker = _get_ticker(
            f'/alliances/{main.alliance_id}/', 'alliance'
        )
        if ticker:
            tags.append(ticker)

    if main.corporation_id:
        ticker = _get_ticker(
            f'/corporations/{main.corporation_id}/', 'corporation'
        )
        if ticker:
            tags.append(ticker)

    if tags:
        result = f'[{" ".join(tags)}] {char_name}'
    else:
        result = char_name
    logger.debug('Computed display name for user %s: %s', user, result)
    return result


def _compute_groups(user, mumble_user=None):
    parts = []
    main = EveCharacter.objects.filter(user=user, is_main=True).first()
    if main:
        if main.alliance_name:
            parts.append(main.alliance_name.replace(' ', '_'))
        if main.corporation_name:
            parts.append(main.corporation_name.replace(' ', '_'))
    memberships = GroupMembership.objects.filter(
        user=user, status='approved'
    ).select_related('group')
    for m in memberships:
        parts.append(m.group.name.replace(' ', '_'))
    if mumble_user and mumble_user.is_mumble_admin:
        parts.append('admin')
    return ','.join(parts)


@require_POST
@login_required
def activate(request, server_id):
    server = get_object_or_404(MumbleServer, pk=server_id, is_active=True)

    if MumbleUser.objects.filter(user=request.user, server=server).exists():
        messages.info(request, _('Mumble account already exists on this server.'))
        return redirect('profile')

    password = _generate_password()
    mumble_user = MumbleUser(
        user=request.user,
        server=server,
        username=_get_mumble_username(request.user),
        display_name=_compute_display_name(request.user),
        groups=_compute_groups(request.user, mumble_user=None),
        pwhash='',
    )
    mumble_user.save()
    try:
        mumble_userid = _sync_remote_registration(mumble_user, password=password)
    except MumbleSyncError as exc:
        logger.warning(
            'Failed to provision Murmur registration for MumbleUser pk=%s on server=%s: %s',
            mumble_user.pk,
            server.pk,
            exc,
        )
        messages.warning(
            request,
            _('Mumble account was created locally, but Murmur registration sync failed. Requesting a new password later will retry it.'),
        )
    else:
        if mumble_user.mumble_userid != mumble_userid:
            mumble_user.mumble_userid = mumble_userid
            mumble_user.save(update_fields=['mumble_userid', 'updated_at'])
        messages.success(request, _('Mumble account created.'))
    request.session[f'mumble_temp_password_{server_id}'] = password
    return redirect('profile')


@require_POST
@login_required
def reset_password(request, server_id):
    try:
        mumble_user = MumbleUser.objects.get(user=request.user, server_id=server_id)
    except MumbleUser.DoesNotExist:
        messages.error(request, _('No Mumble account found.'))
        return redirect('profile')

    password = _generate_password()
    try:
        password, mumble_userid = _sync_password(mumble_user)
    except MumbleSyncError as exc:
        logger.warning(
            'Failed to sync Murmur password reset for MumbleUser pk=%s on server=%s: %s',
            mumble_user.pk,
            mumble_user.server_id,
            exc,
        )
        messages.warning(
            request,
            _('Mumble password reset request could not complete now. Retrying later will request a new password again.'),
        )
    else:
        if mumble_user.mumble_userid != mumble_userid:
            mumble_user.mumble_userid = mumble_userid
            mumble_user.save(update_fields=['mumble_userid', 'updated_at'])
        messages.success(request, _('Mumble password has been reset.'))
    request.session[f'mumble_temp_password_{server_id}'] = password
    return redirect('profile')


@require_POST
@login_required
def set_password(request, server_id):
    try:
        mumble_user = MumbleUser.objects.get(user=request.user, server_id=server_id)
    except MumbleUser.DoesNotExist:
        messages.error(request, _('No Mumble account found.'))
        return redirect('profile')

    password = request.POST.get('mumble_password', '')
    if len(password) < 8:
        messages.error(request, _('Password must be at least 8 characters.'))
        return redirect('profile')

    try:
        _, mumble_userid = _sync_password(mumble_user, password=password)
    except MumbleSyncError as exc:
        logger.warning(
            'Failed to sync Murmur custom password for MumbleUser pk=%s on server=%s: %s',
            mumble_user.pk,
            mumble_user.server_id,
            exc,
        )
        messages.warning(
            request,
            _('Mumble password set request could not complete now. Retrying later will re-issue the request.'),
        )
    else:
        if mumble_user.mumble_userid != mumble_userid:
            mumble_user.mumble_userid = mumble_userid
            mumble_user.save(update_fields=['mumble_userid', 'updated_at'])
        messages.success(request, _('Mumble password updated.'))
    return redirect('profile')


@require_POST
@login_required
def deactivate(request, server_id):
    try:
        mumble_user = MumbleUser.objects.get(user=request.user, server_id=server_id)
    except MumbleUser.DoesNotExist:
        messages.error(request, _('No Mumble account found.'))
        return redirect('profile')

    try:
        _unregister_remote_registration(mumble_user)
    except MumbleSyncError as exc:
        logger.warning(
            'Failed to unregister Murmur user for MumbleUser pk=%s on server=%s: %s',
            mumble_user.pk,
            mumble_user.server_id,
            exc,
        )
        messages.error(
            request,
            _('Mumble account could not be deactivated because Murmur registration sync failed.'),
        )
        return redirect('profile')

    try:
        mumble_user.delete()
        messages.success(request, _('Mumble account deactivated.'))
    except MumbleUser.DoesNotExist:
        messages.error(request, _('No Mumble account found.'))
    return redirect('profile')


def _can_manage_mumble(user):
    # Legacy access path retained for now. This should eventually be replaced
    # by explicit Mumble permission checks so presence/admin access flows
    # through one permission model instead of overlapping staff/group gates.
    return user.is_staff or _user_is_alliance_leader(user) or user.has_perm('mumble.manage_mumble_admin')


def _can_manage_mumble_admin(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_staff and _has_alliance_leader_membership(user):
        return True
    return user.has_perm('mumble.manage_mumble_admin')


@login_required
def mumble_manage(request):
    if not _can_manage_mumble(request.user):
        return HttpResponseForbidden()
    active_priority_session = MumbleSession.objects.filter(
        mumble_user=OuterRef('pk'),
        is_active=True,
        priority_speaker=True,
    )
    mumble_users = (
        MumbleUser.objects
        .filter(server__is_active=True)
        .select_related('user', 'server')
        .annotate(
            active_session_count=Count(
                'murmur_sessions',
                filter=Q(murmur_sessions__is_active=True),
                distinct=True,
            ),
            has_priority_speaker=Exists(active_priority_session),
        )
        .order_by('server__display_order', 'username')
    )
    return render(
        request,
        'fg/manage.html',
        {
            'mumble_users': mumble_users,
            'can_manage_admin': _can_manage_mumble_admin(request.user),
        },
    )


@require_POST
@login_required
def toggle_admin(request, mumble_user_id):
    if not _can_manage_mumble_admin(request.user):
        return HttpResponseForbidden()
    mumble_user = get_object_or_404(MumbleUser, pk=mumble_user_id)
    mumble_user.is_mumble_admin = not mumble_user.is_mumble_admin
    mumble_user.groups = _compute_groups(mumble_user.user, mumble_user=mumble_user)
    mumble_user.save(update_fields=['is_mumble_admin', 'groups', 'updated_at'])
    synced_sessions = 0
    try:
        synced_sessions = _sync_live_admin_membership(mumble_user)
    except MumbleSyncError as exc:
        logger.warning(
            'Failed to sync live Murmur admin membership for MumbleUser pk=%s on server=%s: %s',
            mumble_user.pk,
            mumble_user.server_id,
            exc,
        )
        messages.warning(
            request,
            _('Admin status was updated locally, but live Murmur session sync failed. Connected users may need to reconnect.'),
        )
    status = _('granted') if mumble_user.is_mumble_admin else _('revoked')
    messages.success(request, _('Mumble admin %(status)s for %(user)s.') % {
        'status': status, 'user': mumble_user.username,
    })
    if synced_sessions:
        messages.info(
            request,
            _('Updated %(count)s active Murmur session(s) immediately.') % {'count': synced_sessions},
        )
    return redirect('mumble:manage')
