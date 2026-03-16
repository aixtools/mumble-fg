import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .acl_sync import sync_acl_rules_to_bg
from .control import BgControlClient, MurmurSyncError
from .host import get_host_adapter
from .models import (
    ACL_AUDIT_ACTION_CREATE,
    ACL_AUDIT_ACTION_DELETE,
    ACL_AUDIT_ACTION_UPDATE,
    AccessRule, ENTITY_TYPE_ALLIANCE, ENTITY_TYPE_CORPORATION, ENTITY_TYPE_PILOT,
    MumbleUser, MurmurModelLookupError, access_rule_snapshot, append_access_rule_audit,
    resolve_murmur_models,
)
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
    if can_manage_contract:
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


# ---------------------------------------------------------------------------
# Mumble ACL (user-facing access control list)
# ---------------------------------------------------------------------------

def _acl_admin_bypass(user):
    return user.is_staff or get_host_adapter().user_is_alliance_leader(user)


def _has_acl_perm(user, codename):
    return user.is_authenticated and (
        _acl_admin_bypass(user)
        or user.has_perm(f'mumble_fg.{codename}')
    )


def _can_view_acl(user):
    return _has_acl_perm(user, 'view_accessrule')


def _can_create_acl(user):
    return _can_view_acl(user) and _has_acl_perm(user, 'add_accessrule')


def _can_change_acl(user):
    return _can_view_acl(user) and _has_acl_perm(user, 'change_accessrule')


def _can_delete_acl(user):
    return _can_view_acl(user) and _has_acl_perm(user, 'delete_accessrule')


def _sync_acl_rules_after_change(request, *, source, trigger, rule=None, acl_id=None):
    actor_username = request.user.get_username() or 'system'
    return sync_acl_rules_to_bg(
        requested_by=actor_username,
        actor_username=actor_username,
        source=source,
        trigger=trigger,
        rule=rule,
        acl_id=acl_id,
    )


def _acl_sync_failure_message(request, exc):
    messages.warning(
        request,
        _('ACL was updated locally, but BG sync failed: %(error)s.') % {'error': str(exc)},
    )


def _resolve_name_for_rule(rule):
    """Resolve an entity name for display. Returns the name or '-'."""
    from .admin import _get_eve_character_model, _get_db_for_eve
    EveCharacter = _get_eve_character_model()
    if EveCharacter is None:
        return '-'
    db = _get_db_for_eve() or 'default'
    if rule.entity_type == ENTITY_TYPE_ALLIANCE:
        row = EveCharacter.objects.using(db).filter(alliance_id=rule.entity_id).values('alliance_name').first()
        return (row or {}).get('alliance_name', '-')
    elif rule.entity_type == ENTITY_TYPE_CORPORATION:
        row = EveCharacter.objects.using(db).filter(corporation_id=rule.entity_id).values('corporation_name').first()
        return (row or {}).get('corporation_name', '-')
    elif rule.entity_type == ENTITY_TYPE_PILOT:
        row = EveCharacter.objects.using(db).filter(character_id=rule.entity_id).values('character_name').first()
        return (row or {}).get('character_name', '-')
    return '-'


@login_required
def acl_list(request):
    if not _can_view_acl(request.user):
        return HttpResponseForbidden()

    rules = list(AccessRule.objects.all())
    for rule in rules:
        rule.resolved_name = _resolve_name_for_rule(rule)

    return render(request, 'fg/acl.html', {
        'rules': rules,
        'can_create_acl': _can_create_acl(request.user),
        'can_change_acl': _can_change_acl(request.user),
        'can_delete_acl': _can_delete_acl(request.user),
        'can_sync_acl': _can_change_acl(request.user),
        'search_url': reverse('mumble:acl_search'),
        'batch_url': reverse('mumble:acl_batch_create'),
        'eligible_url': reverse('mumble:acl_eligible'),
        'blocked_url': reverse('mumble:acl_blocked'),
        'sync_url': reverse('mumble:acl_sync'),
    })


@login_required
def acl_search(request):
    if not _can_create_acl(request.user):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    from .admin import _search_eve_entities
    query = request.GET.get('q', '').strip()
    entity_type = request.GET.get('type', '').strip() or None
    if entity_type and entity_type not in (ENTITY_TYPE_ALLIANCE, ENTITY_TYPE_CORPORATION, ENTITY_TYPE_PILOT):
        entity_type = None
    results = _search_eve_entities(query, entity_type=entity_type)
    return JsonResponse({'results': results})


@require_POST
@login_required
def acl_batch_create(request):
    if not _can_create_acl(request.user):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    entities = data.get('entities', [])
    note = (data.get('note') or '').strip()
    deny = bool(data.get('deny', False))
    created_by = request.user.get_username()

    if not entities:
        return JsonResponse({'error': 'No entities provided'}, status=400)

    created = []
    skipped = []
    for entry in entities:
        entity_id = entry.get('entity_id')
        entity_type = entry.get('entity_type')
        if not entity_id or entity_type not in (ENTITY_TYPE_ALLIANCE, ENTITY_TYPE_CORPORATION, ENTITY_TYPE_PILOT):
            continue
        rule, was_created = AccessRule.objects.get_or_create(
            entity_id=entity_id,
            defaults={
                'entity_type': entity_type,
                'deny': deny,
                'note': note,
                'created_by': created_by,
            },
        )
        if was_created:
            created.append(entity_id)
            append_access_rule_audit(
                action=ACL_AUDIT_ACTION_CREATE,
                actor_username=request.user.get_username(),
                rule=rule,
                source='acl_ui_batch_create',
            )
        else:
            skipped.append(entity_id)

    sync_status = 'not_needed'
    sync_error = ''
    if created:
        try:
            response = _sync_acl_rules_after_change(
                request,
                source='acl_ui_batch_create_sync',
                trigger='implicit',
            )
        except MurmurSyncError as exc:
            sync_status = 'failed'
            sync_error = str(exc)
        else:
            sync_status = str(response.get('status', 'completed')).lower()

    return JsonResponse({
        'created': len(created),
        'skipped': len(skipped),
        'skipped_ids': skipped,
        'sync_status': sync_status,
        'sync_error': sync_error,
    })


def _no_cache_json(data, **kwargs):
    """Return a JsonResponse with no-cache headers."""
    response = JsonResponse(data, **kwargs)
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


def _acl_rule_sets():
    """Parse ACL rules into categorised ID sets."""
    rules = list(AccessRule.objects.all())
    return {
        'allowed_alliances': {r.entity_id for r in rules if r.entity_type == ENTITY_TYPE_ALLIANCE and not r.deny},
        'denied_alliances': {r.entity_id for r in rules if r.entity_type == ENTITY_TYPE_ALLIANCE and r.deny},
        'allowed_corps': {r.entity_id for r in rules if r.entity_type == ENTITY_TYPE_CORPORATION and not r.deny},
        'denied_corps': {r.entity_id for r in rules if r.entity_type == ENTITY_TYPE_CORPORATION and r.deny},
        'allowed_pilots': {r.entity_id for r in rules if r.entity_type == ENTITY_TYPE_PILOT and not r.deny},
        'denied_pilots': {r.entity_id for r in rules if r.entity_type == ENTITY_TYPE_PILOT and r.deny},
    }


def _eve_char_setup():
    from .admin import _get_eve_character_model, _get_db_for_eve
    return _get_eve_character_model(), _get_db_for_eve()


def _char_list(queryset):
    return [
        {
            'character_name': c['character_name'],
            'corporation': c['corporation_name'] or '-',
            'alliance': c['alliance_name'] or '-',
        }
        for c in queryset.values(
            'character_id', 'character_name', 'corporation_name', 'alliance_name',
        ).order_by('character_name')
    ]


def _char_list_from_rows(rows):
    pilots = [
        {
            'character_name': row['character_name'],
            'corporation': row['corporation_name'] or '-',
            'alliance': row['alliance_name'] or '-',
        }
        for row in rows
    ]
    pilots.sort(key=lambda pilot: pilot['character_name'].lower())
    return pilots


_DENIAL_REASON_LABELS = {
    ENTITY_TYPE_ALLIANCE: 'alliance',
    ENTITY_TYPE_CORPORATION: 'corp',
    ENTITY_TYPE_PILOT: 'pilot',
}
_DENIAL_REASON_RANK = {
    ENTITY_TYPE_ALLIANCE: 1,
    ENTITY_TYPE_CORPORATION: 2,
    ENTITY_TYPE_PILOT: 3,
}


def _denial_reason_detail(reason_type, row):
    if reason_type == ENTITY_TYPE_PILOT:
        return row['character_name'] or str(row['character_id'])
    if reason_type == ENTITY_TYPE_CORPORATION:
        return row['corporation_name'] or str(row['corporation_id'])
    return row['alliance_name'] or str(row['alliance_id'])


def _prefer_denial_reason(current, candidate):
    if current is None:
        return candidate
    current_type = current['reason_type']
    candidate_type = candidate['reason_type']
    if _DENIAL_REASON_RANK[candidate_type] > _DENIAL_REASON_RANK[current_type]:
        return candidate
    if _DENIAL_REASON_RANK[candidate_type] < _DENIAL_REASON_RANK[current_type]:
        return current
    if candidate['detail'].lower() < current['detail'].lower():
        return candidate
    return current


def _explicit_rule_match(rs, row):
    if row['character_id'] in rs['allowed_pilots']:
        return {'action': 'allow', 'reason_type': ENTITY_TYPE_PILOT, 'detail': _denial_reason_detail(ENTITY_TYPE_PILOT, row)}
    if row['character_id'] in rs['denied_pilots']:
        return {'action': 'deny', 'reason_type': ENTITY_TYPE_PILOT, 'detail': _denial_reason_detail(ENTITY_TYPE_PILOT, row)}
    if row['corporation_id'] in rs['allowed_corps']:
        return {'action': 'allow', 'reason_type': ENTITY_TYPE_CORPORATION, 'detail': _denial_reason_detail(ENTITY_TYPE_CORPORATION, row)}
    if row['corporation_id'] in rs['denied_corps']:
        return {'action': 'deny', 'reason_type': ENTITY_TYPE_CORPORATION, 'detail': _denial_reason_detail(ENTITY_TYPE_CORPORATION, row)}
    if row['alliance_id'] in rs['allowed_alliances']:
        return {'action': 'allow', 'reason_type': ENTITY_TYPE_ALLIANCE, 'detail': _denial_reason_detail(ENTITY_TYPE_ALLIANCE, row)}
    if row['alliance_id'] in rs['denied_alliances']:
        return {'action': 'deny', 'reason_type': ENTITY_TYPE_ALLIANCE, 'detail': _denial_reason_detail(ENTITY_TYPE_ALLIANCE, row)}
    return None


def _explicit_rule_matches(rs, row):
    matches = []
    if row['character_id'] in rs['allowed_pilots']:
        matches.append({'action': 'allow', 'reason_type': ENTITY_TYPE_PILOT, 'detail': _denial_reason_detail(ENTITY_TYPE_PILOT, row)})
    if row['character_id'] in rs['denied_pilots']:
        matches.append({'action': 'deny', 'reason_type': ENTITY_TYPE_PILOT, 'detail': _denial_reason_detail(ENTITY_TYPE_PILOT, row)})
    if row['corporation_id'] in rs['allowed_corps']:
        matches.append({'action': 'allow', 'reason_type': ENTITY_TYPE_CORPORATION, 'detail': _denial_reason_detail(ENTITY_TYPE_CORPORATION, row)})
    if row['corporation_id'] in rs['denied_corps']:
        matches.append({'action': 'deny', 'reason_type': ENTITY_TYPE_CORPORATION, 'detail': _denial_reason_detail(ENTITY_TYPE_CORPORATION, row)})
    if row['alliance_id'] in rs['allowed_alliances']:
        matches.append({'action': 'allow', 'reason_type': ENTITY_TYPE_ALLIANCE, 'detail': _denial_reason_detail(ENTITY_TYPE_ALLIANCE, row)})
    if row['alliance_id'] in rs['denied_alliances']:
        matches.append({'action': 'deny', 'reason_type': ENTITY_TYPE_ALLIANCE, 'detail': _denial_reason_detail(ENTITY_TYPE_ALLIANCE, row)})
    return matches


def _matching_character_rows(EveCharacter, db, rs):
    from django.db.models import Q

    q = Q()
    alliance_ids = rs['allowed_alliances'] | rs['denied_alliances']
    corp_ids = rs['allowed_corps'] | rs['denied_corps']
    pilot_ids = rs['allowed_pilots'] | rs['denied_pilots']

    if alliance_ids:
        q |= Q(alliance_id__in=alliance_ids)
    if corp_ids:
        q |= Q(corporation_id__in=corp_ids)
    if pilot_ids:
        q |= Q(character_id__in=pilot_ids)
    if not q:
        return []

    return list(
        EveCharacter.objects.using(db)
        .filter(q, pending_delete=False)
        .values(
            'user_id',
            'character_id',
            'character_name',
            'corporation_id',
            'corporation_name',
            'alliance_id',
            'alliance_name',
        )
        .order_by('user_id', 'character_name')
    )


def _main_character_rows(EveCharacter, db, user_ids):
    mains = {}
    queryset = (
        EveCharacter.objects.using(db)
        .filter(user_id__in=user_ids, pending_delete=False)
        .values(
            'user_id',
            'character_id',
            'character_name',
            'corporation_name',
            'alliance_name',
            'is_main',
        )
        .order_by('user_id', '-is_main', 'character_name')
    )
    for row in queryset:
        mains.setdefault(row['user_id'], row)
    return mains


def _blocked_main_list(EveCharacter, db, rs):
    account_rules = {}
    for row in _matching_character_rows(EveCharacter, db, rs):
        matches = _explicit_rule_matches(rs, row)
        if not matches:
            continue
        user_rules = account_rules.setdefault(row['user_id'], {'allow': None, 'deny': None})
        for match in matches:
            current = user_rules[match['action']]
            reason = {
                'reason_type': match['reason_type'],
                'detail': match['detail'],
            }
            user_rules[match['action']] = _prefer_denial_reason(current, reason)

    blocked_by_user = {
        user_id: rules['deny']
        for user_id, rules in account_rules.items()
        if rules['allow']
        and rules['deny']
        and _DENIAL_REASON_RANK[rules['deny']['reason_type']] >= _DENIAL_REASON_RANK[rules['allow']['reason_type']]
    }

    if not blocked_by_user:
        return []

    mains = _main_character_rows(EveCharacter, db, blocked_by_user.keys())
    pilots = []
    for user_id, reason in blocked_by_user.items():
        main = mains.get(user_id)
        if not main:
            continue
        denied_as = _DENIAL_REASON_LABELS[reason['reason_type']]
        denied_detail = reason['detail']
        character_name = main['character_name']
        pilots.append(
            {
                'character_name': character_name,
                'display_name': f'{character_name} (denied as: {denied_detail})',
                'corporation': main['corporation_name'] or '-',
                'alliance': main['alliance_name'] or '-',
                'denied_as': denied_as,
                'denied_detail': denied_detail,
            }
        )

    pilots.sort(key=lambda pilot: pilot['character_name'].lower())
    return pilots


@login_required
def acl_eligible(request):
    if not _can_view_acl(request.user):
        return _no_cache_json({'error': 'Forbidden'}, status=403)

    EveCharacter, db = _eve_char_setup()
    if EveCharacter is None or db is None:
        return _no_cache_json({'error': 'EVE data unavailable'}, status=503)

    rs = _acl_rule_sets()
    pilots = _char_list_from_rows(
        row
        for row in _matching_character_rows(EveCharacter, db, rs)
        if (_explicit_rule_match(rs, row) or {}).get('action') == 'allow'
    )
    return _no_cache_json({'pilots': pilots, 'count': len(pilots)})


@login_required
def acl_blocked(request):
    """Return blocked accounts as their main pilot plus the most specific deny reason."""
    if not _can_view_acl(request.user):
        return _no_cache_json({'error': 'Forbidden'}, status=403)

    EveCharacter, db = _eve_char_setup()
    if EveCharacter is None or db is None:
        return _no_cache_json({'error': 'EVE data unavailable'}, status=503)

    rs = _acl_rule_sets()
    pilots = _blocked_main_list(EveCharacter, db, rs)
    return _no_cache_json({'pilots': pilots, 'count': len(pilots)})


@require_POST
@login_required
def acl_sync(request):
    if not _can_change_acl(request.user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Forbidden'}, status=403)
        return HttpResponseForbidden()

    try:
        response = _sync_acl_rules_after_change(
            request,
            source='acl_ui_sync',
            trigger='manual',
        )
    except MurmurSyncError as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {'error': _('ACL sync failed: %(error)s.') % {'error': str(exc)}},
                status=502,
            )
        messages.warning(request, _('ACL sync failed: %(error)s.') % {'error': str(exc)})
    else:
        total = response.get('total')
        if not isinstance(total, int):
            total = AccessRule.objects.count()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'completed',
                'message': _('ACL synchronized to BG (%(count)s entries).') % {'count': total},
                'total': total,
            })
        messages.success(request, _('ACL synchronized to BG (%(count)s entries).') % {'count': total})
    return redirect('mumble:acl_list')


@require_POST
@login_required
def acl_toggle_deny(request, rule_id):
    if not _can_change_acl(request.user):
        return HttpResponseForbidden()

    rule = get_object_or_404(AccessRule, pk=rule_id)
    previous = access_rule_snapshot(rule)
    rule.deny = not rule.deny
    rule.save(update_fields=['deny', 'updated_at'])
    append_access_rule_audit(
        action=ACL_AUDIT_ACTION_UPDATE,
        actor_username=request.user.get_username(),
        rule=rule,
        source='acl_ui_toggle_deny',
        previous=previous,
    )
    try:
        _sync_acl_rules_after_change(
            request,
            source='acl_ui_toggle_deny_sync',
            trigger='implicit',
            rule=rule,
        )
    except MurmurSyncError as exc:
        _acl_sync_failure_message(request, exc)
    return redirect('mumble:acl_list')


@require_POST
@login_required
def acl_delete(request, rule_id):
    if not _can_delete_acl(request.user):
        return HttpResponseForbidden()

    rule = get_object_or_404(AccessRule, pk=rule_id)
    append_access_rule_audit(
        action=ACL_AUDIT_ACTION_DELETE,
        actor_username=request.user.get_username(),
        rule=rule,
        source='acl_ui_delete',
        previous=access_rule_snapshot(rule),
    )
    deleted_acl_id = rule.pk
    rule.delete()
    try:
        _sync_acl_rules_after_change(
            request,
            source='acl_ui_delete_sync',
            trigger='implicit',
            rule=rule,
            acl_id=deleted_acl_id,
        )
    except MurmurSyncError as exc:
        _acl_sync_failure_message(request, exc)
    messages.success(request, _('ACL entry deleted.'))
    return redirect('mumble:acl_list')
