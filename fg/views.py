import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .control import BgControlClient, MurmurSyncError
from .host import get_host_adapter
from .models import MumbleServer, MumbleSession, MumbleUser, MurmurModelLookupError, resolve_murmur_models
from .runtime import RuntimeRegistration, get_runtime_service, safe_list_servers, safe_registration_inventory

logger = logging.getLogger(__name__)
_CONTROL_CLIENT = BgControlClient()

_FORBIDDEN_PASSWORD_CHARS = frozenset({"'", '"', '`', '\\'})


def _password_has_supported_chars(password):
    """Validate user-provided password before sending to BG for hashing."""
    for ch in password:
        if ord(ch) < 33 or ord(ch) > 126:
            return False
        if ch in _FORBIDDEN_PASSWORD_CHARS:
            return False
    return True


def _sync_remote_registration(mumble_user, password=None):
    return _CONTROL_CLIENT.sync_murmur_registration(
        mumble_user,
        password=password,
        requested_by=str(getattr(mumble_user.user, 'username', 'unknown')),
    )


def _unregister_remote_registration(mumble_user):
    return _CONTROL_CLIENT.unregister_murmur_registration(
        mumble_user,
        requested_by=str(getattr(mumble_user.user, 'username', 'unknown')),
    )


def _sync_live_admin_membership(mumble_user):
    return _CONTROL_CLIENT.sync_live_admin_membership(
        mumble_user,
        requested_by=str(getattr(mumble_user.user, 'username', 'unknown')),
    )


def _sync_password(mumble_user, password=None):
    return _CONTROL_CLIENT.reset_murmur_password(
        mumble_user,
        password=password,
        requested_by=str(getattr(mumble_user.user, 'username', 'unknown')),
    )


def _sync_contract_metadata(
    mumble_user,
    *,
    evepilot_id,
    corporation_id,
    alliance_id,
    kdf_iterations,
    requested_by,
    is_super,
):
    return _CONTROL_CLIENT.sync_registration_contract(
        mumble_user,
        evepilot_id=evepilot_id,
        corporation_id=corporation_id,
        alliance_id=alliance_id,
        kdf_iterations=kdf_iterations,
        requested_by=requested_by,
        is_super=is_super,
    )


def _coerce_optional_int(value, *, field_name):
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except (TypeError, ValueError) as exc:
        raise MurmurSyncError(f'{field_name} must be an integer') from exc


def _apply_probe_contract_view(mumble_user, probe_row):
    mumble_user.contract_evepilot_id = probe_row.get('evepilot_id')
    mumble_user.contract_corporation_id = probe_row.get('corporation_id')
    mumble_user.contract_alliance_id = probe_row.get('alliance_id')
    mumble_user.contract_kdf_iterations = probe_row.get('kdf_iterations')


def _host_murmur_models_available() -> bool:
    try:
        resolve_murmur_models()
    except MurmurModelLookupError:
        return False
    return True


def _resolve_server(server_id):
    if _host_murmur_models_available():
        return get_object_or_404(MumbleServer, pk=server_id, is_active=True)

    server = next((server for server in safe_list_servers() if server.pk == int(server_id)), None)
    if server is None or not server.is_active:
        raise Http404()
    return server


def _runtime_registration(pkid: int, *, server_id: int):
    server = next((server for server in safe_list_servers() if server.pk == int(server_id)), None)
    if server is None:
        return None
    try:
        return get_runtime_service().registration_for_pilot_server(pkid, server_id=server_id, servers=[server])
    except MurmurSyncError as exc:
        logger.warning(
            'Failed to load BG registration for pkid=%s server_id=%s: %s',
            pkid,
            server_id,
            exc,
        )
        return None


def _user_registration(user, *, server_id: int):
    if _host_murmur_models_available():
        return MumbleUser.objects.filter(user=user, server_id=server_id).select_related('user', 'server').first()

    registration = _runtime_registration(user.pk, server_id=server_id)
    if registration is not None:
        registration.user = user
    return registration


def _build_registration_target(user, server, *, existing=None):
    target = RuntimeRegistration(
        user_id=user.pk,
        user=user,
        server=server,
        username=str(getattr(existing, 'username', '') or _get_mumble_username(user)),
        display_name=str(getattr(existing, 'display_name', '') or _compute_display_name(user)),
        mumble_userid=getattr(existing, 'mumble_userid', None),
        is_active=bool(getattr(existing, 'is_active', True)),
        is_mumble_admin=bool(getattr(existing, 'is_mumble_admin', False)),
        groups=str(getattr(existing, 'groups', '') or ''),
    )
    if not target.groups:
        target.groups = _compute_groups(user, mumble_user=target)
    return target


def _has_alliance_leader_membership(user):
    return get_host_adapter().has_alliance_leader_membership(user)


def _get_mumble_username(user):
    main = get_host_adapter().get_main_character(user)
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
    main = get_host_adapter().get_main_character(user)
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
    main = get_host_adapter().get_main_character(user)
    if main:
        if main.alliance_name:
            parts.append(main.alliance_name.replace(' ', '_'))
        if main.corporation_name:
            parts.append(main.corporation_name.replace(' ', '_'))
    for m in get_host_adapter().get_approved_group_memberships(user):
        parts.append(m.group.name.replace(' ', '_'))
    if mumble_user and mumble_user.is_mumble_admin:
        parts.append('admin')
    return ','.join(parts)


@require_POST
@login_required
def activate(request, server_id):
    server = _resolve_server(server_id)
    existing_registration = _user_registration(request.user, server_id=server.pk)
    if existing_registration is not None:
        messages.info(request, _('Murmur account already exists on this server.'))
        return redirect('profile')

    mumble_user = _build_registration_target(request.user, server)
    if _host_murmur_models_available():
        persisted_user = MumbleUser(
            user=request.user,
            server=server,
            username=mumble_user.username,
            display_name=mumble_user.display_name,
            groups=mumble_user.groups,
            pwhash='',
        )
        persisted_user.save()
        mumble_user = persisted_user
    try:
        murmur_userid = _sync_remote_registration(mumble_user)
    except MurmurSyncError as exc:
        logger.warning(
            'Failed to provision Murmur registration for MumbleUser pk=%s on server=%s: %s',
            getattr(mumble_user, 'pk', 'bg-runtime'),
            server.pk,
            exc,
        )
        messages.warning(
            request,
            _('Murmur registration sync failed. Requesting a new password later will retry it.'),
        )
        return redirect('profile')

    if _host_murmur_models_available() and mumble_user.mumble_userid != murmur_userid:
        mumble_user.mumble_userid = murmur_userid
        mumble_user.save(update_fields=['mumble_userid', 'updated_at'])

    # Request initial password from BG (BG generates it).
    try:
        password, _ = _sync_password(mumble_user)
        request.session[f'murmur_temp_password_{server_id}'] = password
    except MurmurSyncError:
        logger.warning('Initial password request failed for new registration on server=%s', server.pk)
    messages.success(request, _('Murmur account created.'))
    return redirect('profile')


@require_POST
@login_required
def reset_password(request, server_id):
    mumble_user = _user_registration(request.user, server_id=server_id)
    if mumble_user is None:
        messages.error(request, _('No Murmur account found.'))
        return redirect('profile')

    try:
        password, murmur_userid = _sync_password(mumble_user)
    except MurmurSyncError as exc:
        logger.warning(
            'Failed to sync Murmur password reset for MumbleUser pk=%s on server=%s: %s',
            mumble_user.pk,
            mumble_user.server_id,
            exc,
        )
        messages.warning(
            request,
            _('Murmur password reset request could not complete now. Retrying later will request a new password again.'),
        )
        return redirect('profile')

    if _host_murmur_models_available() and mumble_user.mumble_userid != murmur_userid:
        mumble_user.mumble_userid = murmur_userid
        mumble_user.save(update_fields=['mumble_userid', 'updated_at'])
    messages.success(request, _('Murmur password has been reset.'))
    request.session[f'murmur_temp_password_{server_id}'] = password
    return redirect('profile')


@require_POST
@login_required
def set_password(request, server_id):
    mumble_user = _user_registration(request.user, server_id=server_id)
    if mumble_user is None:
        messages.error(request, _('No Murmur account found.'))
        return redirect('profile')

    password = request.POST.get('murmur_password', '')
    if len(password) < 8:
        messages.error(request, _('Password must be at least 8 characters.'))
        return redirect('profile')
    if not _password_has_supported_chars(password):
        messages.error(request, _("Password may not contain any of: ' \" ` \\"))
        return redirect('profile')

    try:
        resolved_password, murmur_userid = _sync_password(mumble_user, password=password)
    except MurmurSyncError as exc:
        logger.warning(
            'Failed to sync Murmur custom password for MumbleUser pk=%s on server=%s: %s',
            mumble_user.pk,
            mumble_user.server_id,
            exc,
        )
        messages.warning(
            request,
            _('Murmur password set request could not complete now. Retrying later will re-issue the request.'),
        )
    else:
        del resolved_password
        if _host_murmur_models_available() and mumble_user.mumble_userid != murmur_userid:
            mumble_user.mumble_userid = murmur_userid
            mumble_user.save(update_fields=['mumble_userid', 'updated_at'])
        messages.success(request, _('Murmur password updated.'))
    return redirect('profile')


@require_POST
@login_required
def deactivate(request, server_id):
    mumble_user = _user_registration(request.user, server_id=server_id)
    if mumble_user is None:
        messages.error(request, _('No Murmur account found.'))
        return redirect('profile')

    try:
        _unregister_remote_registration(mumble_user)
    except MurmurSyncError as exc:
        logger.warning(
            'Failed to unregister Murmur user for MumbleUser pk=%s on server=%s: %s',
            mumble_user.pk,
            mumble_user.server_id,
            exc,
        )
        messages.error(
            request,
            _('Murmur account could not be deactivated because Murmur registration sync failed.'),
        )
        return redirect('profile')

    if _host_murmur_models_available():
        try:
            mumble_user.delete()
        except MumbleUser.DoesNotExist:
            messages.error(request, _('No Murmur account found.'))
            return redirect('profile')
    messages.success(request, _('Murmur account deactivated.'))
    return redirect('profile')


def _can_manage_mumble(user):
    # Legacy access path retained for now. This should eventually be replaced
    # by explicit Murmur permission checks so presence/admin access flows
    # through one permission model instead of overlapping staff/group gates.
    return (
        user.is_staff
        or get_host_adapter().user_is_alliance_leader(user)
        or user.has_perm('mumble.manage_mumble_admin')
    )


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
    if _host_murmur_models_available():
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
    else:
        servers = safe_list_servers()
        order_map = {server.pk: index for index, server in enumerate(servers)}
        mumble_users = get_runtime_service().attach_users(
            safe_registration_inventory(servers=servers)
        )
        mumble_users.sort(
            key=lambda registration: (
                order_map.get(registration.server_id, 999999),
                str(getattr(registration, 'username', '') or '').lower(),
            )
        )
    can_manage_contract = request.user.is_superuser
    if can_manage_contract and _host_murmur_models_available():
        probe_rows_by_key = {}
        for pkid in sorted({mumble_user.user_id for mumble_user in mumble_users}):
            try:
                registrations = _CONTROL_CLIENT.probe_pilot_registrations(pkid)
            except MurmurSyncError as exc:
                logger.warning('Failed to probe contract data for pkid=%s: %s', pkid, exc)
                continue
            for registration in registrations:
                server_name = registration.get('server_name')
                probe_rows_by_key[(pkid, server_name)] = registration

        for mumble_user in mumble_users:
            probe_row = probe_rows_by_key.get((mumble_user.user_id, mumble_user.server.name), {})
            _apply_probe_contract_view(mumble_user, probe_row)
    return render(
        request,
        'fg/manage.html',
        {
            'mumble_users': mumble_users,
            'can_manage_admin': _can_manage_mumble_admin(request.user),
            'can_manage_contract': can_manage_contract,
        },
    )


@require_POST
@login_required
def toggle_admin(request, mumble_user_id):
    if not _can_manage_mumble_admin(request.user):
        return HttpResponseForbidden()
    if not _host_murmur_models_available():
        raise Http404()
    mumble_user = get_object_or_404(MumbleUser, pk=mumble_user_id)
    return _toggle_admin_for_registration(request, mumble_user)


def _toggle_admin_for_registration(request, mumble_user):
    mumble_user.is_mumble_admin = not mumble_user.is_mumble_admin
    mumble_user.groups = _compute_groups(mumble_user.user, mumble_user=mumble_user)
    if _host_murmur_models_available() and hasattr(mumble_user, 'save'):
        mumble_user.save(update_fields=['is_mumble_admin', 'groups', 'updated_at'])
    synced_sessions = 0
    try:
        synced_sessions = _sync_live_admin_membership(mumble_user)
    except MurmurSyncError as exc:
        logger.warning(
            'Failed to sync live Murmur admin membership for MumbleUser pk=%s on server=%s: %s',
            mumble_user.pk,
            mumble_user.server_id,
            exc,
        )
        messages.warning(
            request,
            _('Admin status was updated, but live Murmur session sync failed. Connected users may need to reconnect.'),
        )
    status = _('granted') if mumble_user.is_mumble_admin else _('revoked')
    messages.success(request, _('Murmur admin %(status)s for %(user)s.') % {
        'status': status, 'user': mumble_user.username,
    })
    if synced_sessions:
        messages.info(
            request,
            _('Updated %(count)s active Murmur session(s) immediately.') % {'count': synced_sessions},
        )
    return redirect('mumble:manage')


@require_POST
@login_required
def toggle_admin_registration(request, pkid: int, server_id: int):
    if not _can_manage_mumble_admin(request.user):
        return HttpResponseForbidden()
    if _host_murmur_models_available():
        mumble_user = get_object_or_404(MumbleUser, user_id=pkid, server_id=server_id)
    else:
        mumble_user = _runtime_registration(pkid, server_id=server_id)
        if mumble_user is None:
            raise Http404()
        mumble_user.user = get_runtime_service().attach_users([mumble_user])[0].user
    return _toggle_admin_for_registration(request, mumble_user)


@require_POST
@login_required
def sync_contract(request, mumble_user_id):
    if not request.user.is_superuser:
        return HttpResponseForbidden()
    if not _host_murmur_models_available():
        raise Http404()

    mumble_user = get_object_or_404(MumbleUser, pk=mumble_user_id)
    return _sync_contract_for_registration(request, mumble_user)


def _sync_contract_for_registration(request, mumble_user):
    try:
        requested_values = {
            'evepilot_id': _coerce_optional_int(request.POST.get('evepilot_id'), field_name='evepilot_id'),
            'corporation_id': _coerce_optional_int(request.POST.get('corporation_id'), field_name='corporation_id'),
            'alliance_id': _coerce_optional_int(request.POST.get('alliance_id'), field_name='alliance_id'),
            'kdf_iterations': _coerce_optional_int(request.POST.get('kdf_iterations'), field_name='kdf_iterations'),
        }
    except MurmurSyncError as exc:
        messages.error(request, _('Invalid contract metadata: %(error)s') % {'error': exc})
        return redirect('mumble:manage')

    try:
        _sync_contract_metadata(
            mumble_user,
            requested_by=str(getattr(request.user, 'username', 'unknown')),
            is_super=True,
            **requested_values,
        )
        registration = _CONTROL_CLIENT.probe_murmur_registration(mumble_user)
    except MurmurSyncError as exc:
        logger.warning(
            'Failed to sync contract metadata for MumbleUser pk=%s on server=%s: %s',
            mumble_user.pk,
            mumble_user.server_id,
            exc,
        )
        messages.warning(
            request,
            _('Contract metadata update request failed: %(error)s') % {'error': exc},
        )
        return redirect('mumble:manage')

    if not registration:
        messages.warning(
            request,
            _('Contract metadata was sent, but probe verification returned no registration row.'),
        )
        return redirect('mumble:manage')

    mismatched_fields = [
        field_name
        for field_name, expected in requested_values.items()
        if registration.get(field_name) != expected
    ]
    if mismatched_fields:
        messages.warning(
            request,
            _('Contract metadata update did not verify for fields: %(fields)s') % {
                'fields': ', '.join(sorted(mismatched_fields)),
            },
        )
        return redirect('mumble:manage')

    messages.success(request, _('Contract metadata synchronized for %(user)s.') % {'user': mumble_user.username})
    return redirect('mumble:manage')


@require_POST
@login_required
def sync_contract_registration(request, pkid: int, server_id: int):
    if not request.user.is_superuser:
        return HttpResponseForbidden()
    if _host_murmur_models_available():
        mumble_user = get_object_or_404(MumbleUser, user_id=pkid, server_id=server_id)
    else:
        mumble_user = _runtime_registration(pkid, server_id=server_id)
        if mumble_user is None:
            raise Http404()
    return _sync_contract_for_registration(request, mumble_user)
