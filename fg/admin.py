from django.contrib import admin

from .models import AccessRule, MurmurModelLookupError, resolve_murmur_models


@admin.register(AccessRule)
class AccessRuleAdmin(admin.ModelAdmin):
    list_display = ('entity_id', 'entity_type', 'block', 'note', 'created_by', 'updated_at')
    list_filter = ('entity_type', 'block')
    search_fields = ('entity_id', 'note', 'created_by')
    list_editable = ('block',)
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('entity_id', 'entity_type', 'block', 'note', 'created_by'),
            'description': (
                '<h3>Eligibility Rules</h3>'
                '<p>Precedence (most specific wins): '
                '<strong>Pilot</strong> &gt; <strong>Corporation</strong> &gt; <strong>Alliance</strong></p>'
                '<ul>'
                '<li><strong>Alliance</strong>: block=False means the alliance is permitted. '
                'Alliances not listed are implicitly denied.</li>'
                '<li><strong>Corporation</strong>: block=True denies a corp within an allowed alliance.</li>'
                '<li><strong>Pilot</strong>: overrides corp and alliance. '
                'block=False rescues a pilot even if their corp is blocked.</li>'
                '</ul>'
                '<p>Block checks are <strong>account-wide</strong>: '
                'if main or any alt matches a block, the entire account is denied '
                '&mdash; unless a pilot-level allow overrides it.</p>'
            ),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )


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
