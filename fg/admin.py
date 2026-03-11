from django.contrib import admin

from .pilot.models import MumbleServer, MumbleSession, MumbleUser


@admin.register(MumbleServer)
class MumbleServerAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'ice_host', 'ice_port', 'virtual_server_id', 'is_active', 'display_order')
    list_filter = ('is_active',)
    list_editable = ('is_active', 'display_order')
    fieldsets = (
        (None, {
            'fields': ('name', 'address', 'ice_host', 'ice_port', 'ice_secret', 'virtual_server_id', 'is_active', 'display_order'),
            'description': (
                '<h3>Setup Instructions</h3>'
                '<ol>'
                '<li>On the Mumble server: set <code>ice="tcp -h 0.0.0.0 -p 6502"</code> '
                'and <code>icesecretwrite=&lt;secret&gt;</code></li>'
                '<li>Ensure the mumble-bg auth service can reach the ICE endpoint over the network</li>'
                '<li>Add the server here with matching ICE host, port, secret, and virtual server ID when needed</li>'
                '<li>Restart the mumble-bg auth service after inventory changes</li>'
                '</ol>'
            ),
        }),
    )


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


@admin.register(MumbleSession)
class MumbleSessionAdmin(admin.ModelAdmin):
    list_display = (
        'server',
        'session_id',
        'username',
        'mumble_userid',
        'mumble_user',
        'channel_id',
        'is_active',
        'connected_at',
        'last_seen',
        'last_spoke',
        'disconnected_at',
    )
    search_fields = ('username', 'mumble_user__username', 'mumble_user__user__username', 'address')
    list_filter = ('is_active', 'server')
    readonly_fields = (
        'server',
        'mumble_user',
        'session_id',
        'mumble_userid',
        'username',
        'channel_id',
        'address',
        'cert_hash',
        'tcponly',
        'mute',
        'deaf',
        'suppress',
        'priority_speaker',
        'self_mute',
        'self_deaf',
        'recording',
        'onlinesecs',
        'idlesecs',
        'connected_at',
        'last_seen',
        'last_state',
        'last_spoke',
        'disconnected_at',
        'created_at',
        'updated_at',
    )
