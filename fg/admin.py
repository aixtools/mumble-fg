import json

from django.contrib import admin, messages
from django.db.models import Q
from django.http import JsonResponse
from django.urls import path
from django.utils.html import format_html

from .acl_sync import sync_acl_rules_to_bg
from .control import MurmurSyncError
from .models import (
    ACL_AUDIT_ACTION_CREATE,
    ACL_AUDIT_ACTION_DELETE,
    ACL_AUDIT_ACTION_UPDATE,
    AccessRule,
    AccessRuleAudit,
    ENTITY_TYPE_ALLIANCE,
    ENTITY_TYPE_CORPORATION,
    ENTITY_TYPE_PILOT,
    access_rule_snapshot,
    append_access_rule_audit,
)
from .models import MurmurModelLookupError, resolve_murmur_models


def _get_eve_character_model():
    try:
        import accounts.models as accounts_models
        return getattr(accounts_models, 'EveCharacter', None)
    except ImportError:
        return None


def _get_db_for_eve():
    """Return the database alias where EVE entity data lives.

    Prefers 'cube' if configured (for hosts like mockcube that keep real
    EVE data in a separate database). Falls back to the router, then 'default'.
    """
    from django.db import connections
    if 'cube' in connections.databases:
        return 'cube'
    EveCharacter = _get_eve_character_model()
    if EveCharacter is None:
        return None
    from django.db import router
    return router.db_for_read(EveCharacter) or 'default'


def _parse_id_query(query):
    """Parse a numeric query. Returns (is_id, sql_param) tuple.

    Rules: purely numeric (min 6 digits) = exact match.
    Trailing % or * = prefix wildcard (min 6 digit prefix).
    Returns (False, None) if not a valid ID query.
    """
    stripped = query.rstrip('%*')
    has_wildcard = len(stripped) < len(query)
    if not stripped.isdigit() or len(stripped) < 6:
        return False, None
    if has_wildcard:
        return True, f'{stripped}%'
    return True, int(stripped)


def _search_info_tables(query, entity_type, limit, db_alias):
    """Search alliance/corp info tables for name or ticker matches."""
    from django.db import connections
    results = []
    seen_ids = set()
    name_param = f'%{query}%'
    is_id, id_param = _parse_id_query(query)

    if entity_type in (None, ENTITY_TYPE_ALLIANCE):
        try:
            cursor = connections[db_alias].cursor()
            if is_id and isinstance(id_param, int):
                cursor.execute(
                    'SELECT alliance_id, alliance_name, alliance_ticker'
                    ' FROM accounts_eveallianceinfo'
                    ' WHERE alliance_id = %s'
                    ' LIMIT %s',
                    [id_param, limit],
                )
            elif is_id:
                cursor.execute(
                    'SELECT alliance_id, alliance_name, alliance_ticker'
                    ' FROM accounts_eveallianceinfo'
                    ' WHERE CAST(alliance_id AS TEXT) LIKE %s'
                    ' LIMIT %s',
                    [id_param, limit],
                )
            else:
                cursor.execute(
                    'SELECT alliance_id, alliance_name, alliance_ticker'
                    ' FROM accounts_eveallianceinfo'
                    ' WHERE alliance_name ILIKE %s OR alliance_ticker ILIKE %s'
                    ' LIMIT %s',
                    [name_param, name_param, limit],
                )
            for aid, name, ticker in cursor.fetchall():
                if aid and aid not in seen_ids:
                    seen_ids.add(aid)
                    label = f'{name} [{ticker}]' if ticker else name
                    results.append({
                        'entity_id': aid,
                        'entity_type': ENTITY_TYPE_ALLIANCE,
                        'label': label,
                    })
        except Exception:
            pass

    if entity_type in (None, ENTITY_TYPE_CORPORATION):
        try:
            cursor = connections[db_alias].cursor()
            if is_id and isinstance(id_param, int):
                cursor.execute(
                    'SELECT corporation_id, corporation_name, corporation_ticker'
                    ' FROM accounts_evecorporationinfo'
                    ' WHERE corporation_id = %s'
                    ' LIMIT %s',
                    [id_param, limit],
                )
            elif is_id:
                cursor.execute(
                    'SELECT corporation_id, corporation_name, corporation_ticker'
                    ' FROM accounts_evecorporationinfo'
                    ' WHERE CAST(corporation_id AS TEXT) LIKE %s'
                    ' LIMIT %s',
                    [id_param, limit],
                )
            else:
                cursor.execute(
                    'SELECT corporation_id, corporation_name, corporation_ticker'
                    ' FROM accounts_evecorporationinfo'
                    ' WHERE corporation_name ILIKE %s OR corporation_ticker ILIKE %s'
                    ' LIMIT %s',
                    [name_param, name_param, limit],
                )
            for cid, name, ticker in cursor.fetchall():
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    label = f'{name} [{ticker}]' if ticker else name
                    results.append({
                        'entity_id': cid,
                        'entity_type': ENTITY_TYPE_CORPORATION,
                        'label': label,
                    })
        except Exception:
            pass

    return results, seen_ids


def _search_eve_entities(query, entity_type=None, limit=20):
    """Search EVE info tables (with tickers) and character table for matches."""
    db_alias = _get_db_for_eve()
    if db_alias is None:
        return []

    query = (query or '').strip()
    if not query:
        return []

    is_id, _ = _parse_id_query(query)

    # Search info tables first (alliances/corps with tickers)
    results, seen_ids = _search_info_tables(query, entity_type, limit, db_alias)

    EveCharacter = _get_eve_character_model()
    if EveCharacter is None:
        return results[:limit]

    # Fill in alliances/corps from character table (name only, no ID queries)
    if not is_id and entity_type in (None, ENTITY_TYPE_ALLIANCE):
        alliances = (
            EveCharacter.objects.using(db_alias)
            .filter(
                alliance_name__icontains=query,
                alliance_id__isnull=False,
                pending_delete=False,
            )
            .values('alliance_id', 'alliance_name')
            .distinct()[:limit]
        )
        for row in alliances:
            aid = row['alliance_id']
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                results.append({
                    'entity_id': aid,
                    'entity_type': ENTITY_TYPE_ALLIANCE,
                    'label': row['alliance_name'],
                })

    if not is_id and entity_type in (None, ENTITY_TYPE_CORPORATION):
        corps = (
            EveCharacter.objects.using(db_alias)
            .filter(
                corporation_name__icontains=query,
                corporation_id__isnull=False,
                pending_delete=False,
            )
            .values('corporation_id', 'corporation_name')
            .distinct()[:limit]
        )
        for row in corps:
            cid = row['corporation_id']
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                results.append({
                    'entity_id': cid,
                    'entity_type': ENTITY_TYPE_CORPORATION,
                    'label': row['corporation_name'],
                })

    # Pilots (character table only, name search only)
    if not is_id and entity_type in (None, ENTITY_TYPE_PILOT):
        pilots = (
            EveCharacter.objects.using(db_alias)
            .filter(
                character_name__icontains=query,
                pending_delete=False,
            )
            .values('character_id', 'character_name')
            .distinct()[:limit]
        )
        for row in pilots:
            pid = row['character_id']
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                results.append({
                    'entity_id': pid,
                    'entity_type': ENTITY_TYPE_PILOT,
                    'label': row['character_name'],
                })

    return results[:limit]


@admin.register(AccessRule)
class AccessRuleAdmin(admin.ModelAdmin):
    list_display = ('entity_id', 'entity_type_badge', 'deny_badge', 'resolved_name', 'note', 'created_by', 'updated_at')
    list_filter = ('entity_type', 'deny')
    search_fields = ('entity_id', 'note', 'created_by')
    list_editable = ()
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Eligibility Rules', {
            'fields': (),
            'description': (
                '<p>Precedence (most specific wins): '
                '<strong>Pilot</strong> &gt; <strong>Corporation</strong> &gt; <strong>Alliance</strong></p>'
                '<ul>'
                '<li><strong>Alliance</strong>: deny=off permits the alliance. '
                'deny=on blocks any account with a main or alt in that alliance. '
                'Alliances not listed are implicitly denied.</li>'
                '<li><strong>Corporation</strong>: deny=on blocks a corp within an allowed alliance.</li>'
                '<li><strong>Pilot</strong>: overrides corp and alliance. '
                'deny=off rescues a pilot even if their corp or alliance is denied.</li>'
                '</ul>'
                '<p>Deny checks are <strong>account-wide</strong>: '
                'if main or any alt matches a deny rule, the entire account is denied '
                '&mdash; unless a pilot-level allow overrides it.</p>'
                '<p><strong>Lookup:</strong> Enter an EVE ID directly, or use the '
                'search below to find by name.</p>'
            ),
        }),
        (None, {
            'fields': ('entity_id', 'entity_type', 'deny', 'note', 'created_by'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    class Media:
        css = {'all': ()}
        js = ()

    def _has_accessrule_perm(self, request, codename):
        return request.user.is_active and (
            request.user.is_superuser
            or request.user.has_perm(f'mumble_fg.{codename}')
        )

    def has_module_permission(self, request):
        return self._has_accessrule_perm(request, 'view_accessrule')

    def has_view_permission(self, request, obj=None):
        return self._has_accessrule_perm(request, 'view_accessrule')

    def has_add_permission(self, request):
        return self._has_accessrule_perm(request, 'add_accessrule')

    def has_change_permission(self, request, obj=None):
        return self._has_accessrule_perm(request, 'change_accessrule')

    def has_delete_permission(self, request, obj=None):
        return self._has_accessrule_perm(request, 'delete_accessrule')

    def get_urls(self):
        custom_urls = [
            path(
                'eve-entity-search/',
                self.admin_site.admin_view(self.eve_entity_search_view),
                name='mumble_fg_accessrule_eve_search',
            ),
            path(
                'batch-create/',
                self.admin_site.admin_view(self.batch_create_view),
                name='mumble_fg_accessrule_batch_create',
            ),
        ]
        return custom_urls + super().get_urls()

    def eve_entity_search_view(self, request):
        if not self.has_add_permission(request):
            return JsonResponse({'error': 'Forbidden'}, status=403)
        query = request.GET.get('q', '').strip()
        entity_type = request.GET.get('type', '').strip() or None
        if entity_type and entity_type not in (ENTITY_TYPE_ALLIANCE, ENTITY_TYPE_CORPORATION, ENTITY_TYPE_PILOT):
            entity_type = None
        results = _search_eve_entities(query, entity_type=entity_type)
        return JsonResponse({'results': results})

    def batch_create_view(self, request):
        if not self.has_add_permission(request):
            return JsonResponse({'error': 'Forbidden'}, status=403)
        if request.method != 'POST':
            return JsonResponse({'error': 'POST required'}, status=405)
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
                    source='admin_batch_create',
                )
            else:
                skipped.append(entity_id)

        sync_status = 'not_needed'
        sync_error = ''
        if created:
            try:
                response = sync_acl_rules_to_bg(
                    requested_by=request.user.get_username() or 'system',
                    actor_username=request.user.get_username() or 'system',
                    source='admin_batch_create_sync',
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

    def _sync_acl_rules(self, request, *, source, trigger, rule=None, acl_id=None):
        actor_username = request.user.get_username() or 'system'
        try:
            sync_acl_rules_to_bg(
                requested_by=actor_username,
                actor_username=actor_username,
                source=source,
                trigger=trigger,
                rule=rule,
                acl_id=acl_id,
            )
        except MurmurSyncError as exc:
            self.message_user(
                request,
                f'ACL was updated locally, but BG sync failed: {exc}',
                level=messages.WARNING,
            )

    def entity_type_badge(self, obj):
        colors = {
            ENTITY_TYPE_ALLIANCE: '#2196f3',
            ENTITY_TYPE_CORPORATION: '#ff9800',
            ENTITY_TYPE_PILOT: '#9c27b0',
        }
        color = colors.get(obj.entity_type, '#999')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:999px;'
            'font-size:11px;font-weight:700;">{}</span>',
            color,
            obj.get_entity_type_display(),
        )
    entity_type_badge.short_description = 'Type'
    entity_type_badge.admin_order_field = 'entity_type'

    def deny_badge(self, obj):
        if obj.deny:
            return format_html(
                '<span style="background:#f44336;color:#fff;padding:2px 8px;border-radius:999px;'
                'font-size:11px;font-weight:700;">DENY</span>'
            )
        return format_html(
            '<span style="background:#4caf50;color:#fff;padding:2px 8px;border-radius:999px;'
            'font-size:11px;font-weight:700;">ALLOW</span>'
        )
    deny_badge.short_description = 'Rule'
    deny_badge.admin_order_field = 'deny'

    def resolved_name(self, obj):
        EveCharacter = _get_eve_character_model()
        if EveCharacter is None:
            return '-'
        db = _get_db_for_eve() or 'default'
        if obj.entity_type == ENTITY_TYPE_ALLIANCE:
            row = EveCharacter.objects.using(db).filter(alliance_id=obj.entity_id).values('alliance_name').first()
            return (row or {}).get('alliance_name', '-')
        elif obj.entity_type == ENTITY_TYPE_CORPORATION:
            row = EveCharacter.objects.using(db).filter(corporation_id=obj.entity_id).values('corporation_name').first()
            return (row or {}).get('corporation_name', '-')
        elif obj.entity_type == ENTITY_TYPE_PILOT:
            row = EveCharacter.objects.using(db).filter(character_id=obj.entity_id).values('character_name').first()
            return (row or {}).get('character_name', '-')
        return '-'
    resolved_name.short_description = 'Name'

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            # Add form: hide created_by and timestamps
            return (
                ('Eligibility Rules', self.fieldsets[0][1]),
                (None, {'fields': ('entity_id', 'entity_type', 'deny', 'note')}),
            )
        return super().get_fieldsets(request, obj)

    def save_model(self, request, obj, form, change):
        previous = None
        if change:
            previous = access_rule_snapshot(AccessRule.objects.get(pk=obj.pk))
        if not change and not obj.created_by:
            obj.created_by = request.user.get_username()
        super().save_model(request, obj, form, change)
        append_access_rule_audit(
            action=ACL_AUDIT_ACTION_UPDATE if change else ACL_AUDIT_ACTION_CREATE,
            actor_username=request.user.get_username(),
            rule=obj,
            source='admin_changeform',
            previous=previous,
        )
        self._sync_acl_rules(
            request,
            source='admin_changeform_sync',
            trigger='implicit',
            rule=obj,
        )

    def delete_model(self, request, obj):
        append_access_rule_audit(
            action=ACL_AUDIT_ACTION_DELETE,
            actor_username=request.user.get_username(),
            rule=obj,
            source='admin_changeform',
            previous=access_rule_snapshot(obj),
        )
        deleted_acl_id = obj.pk
        super().delete_model(request, obj)
        self._sync_acl_rules(
            request,
            source='admin_changeform_sync',
            trigger='implicit',
            rule=obj,
            acl_id=deleted_acl_id,
        )

    def delete_queryset(self, request, queryset):
        rules = list(queryset)
        for obj in rules:
            append_access_rule_audit(
                action=ACL_AUDIT_ACTION_DELETE,
                actor_username=request.user.get_username(),
                rule=obj,
                source='admin_delete_queryset',
                previous=access_rule_snapshot(obj),
            )
        super().delete_queryset(request, queryset)
        if rules:
            self._sync_acl_rules(
                request,
                source='admin_delete_queryset_sync',
                trigger='implicit',
            )

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = extra_context or {}
        from django.urls import reverse
        extra_context['eve_search_url'] = reverse('admin:mumble_fg_accessrule_eve_search')
        extra_context['batch_create_url'] = reverse('admin:mumble_fg_accessrule_batch_create')
        return super().changeform_view(request, object_id, form_url, extra_context)


try:
    (MumbleUser,) = resolve_murmur_models()
except MurmurModelLookupError:
    MumbleUser = None
else:
    @admin.register(MumbleUser)
    class MumbleUserAdmin(admin.ModelAdmin):
        list_display = (
            'username',
            'display_name',
            'mumble_userid',
            'user',
            'server',
            'is_mumble_admin',
            'is_active',
            'certhash',
            'last_authenticated',
            'last_connected',
            'last_disconnected',
            'last_seen',
            'last_spoke',
            'groups',
            'created_at',
        )
        search_fields = ('username', 'display_name', 'user__username', 'certhash')
        list_filter = ('is_active', 'server')
        readonly_fields = (
            'pwhash',
            'hashfn',
            'pw_salt',
            'kdf_iterations',
            'certhash',
            'last_authenticated',
            'last_connected',
            'last_disconnected',
            'last_seen',
            'last_spoke',
            'created_at',
            'updated_at',
        )
        fieldsets = (
            (None, {
                'fields': ('user', 'server', 'mumble_userid', 'username', 'display_name', 'is_mumble_admin', 'is_active'),
            }),
            ('Authentication', {
                'fields': ('pwhash', 'hashfn', 'pw_salt', 'kdf_iterations', 'certhash'),
            }),
            ('Groups', {
                'fields': ('groups',),
            }),
            ('Timestamps', {
                'fields': (
                    'last_authenticated',
                    'last_connected',
                    'last_disconnected',
                    'last_seen',
                    'last_spoke',
                    'created_at',
                    'updated_at',
                ),
            }),
        )


@admin.register(AccessRuleAudit)
class AccessRuleAuditAdmin(admin.ModelAdmin):
    list_display = (
        'occurred_at',
        'action',
        'entity_id',
        'entity_type',
        'deny',
        'actor_username',
        'source',
    )
    list_filter = ('action', 'entity_type', 'deny', 'source')
    search_fields = ('=entity_id', 'actor_username', 'source', 'note', 'acl_created_by')
    readonly_fields = (
        'occurred_at',
        'acl_id',
        'action',
        'actor_username',
        'source',
        'entity_id',
        'entity_type',
        'deny',
        'note',
        'acl_created_by',
        'previous',
        'metadata',
    )

    def _has_audit_view_perm(self, request):
        return request.user.is_active and (
            request.user.is_superuser
            or request.user.has_perm('mumble_fg.view_accessruleaudit')
        )

    def has_module_permission(self, request):
        return self._has_audit_view_perm(request)

    def has_view_permission(self, request, obj=None):
        return self._has_audit_view_perm(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
