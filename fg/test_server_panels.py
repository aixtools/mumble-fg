"""Per-server profile-tile visibility + heading (Servers tab)."""

from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import EveCharacter, UserProfile
from fg.models import (
    AccessRule,
    ENTITY_TYPE_ALLIANCE,
    ServerPanelSettings,
)
from fg.panels import build_profile_panels
from fg.runtime import RuntimeServer, _normalize_endpoint

_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)

_ICE_SERVER = RuntimeServer(
    id=1,
    name='voice.example.com:64738',
    address='voice.example.com:64738',
    server_key='k-ice',
    is_active=True,
    driver='ice',
)
_SHITSPEAK_SERVER = RuntimeServer(
    id=5,
    name='mumble-beta',
    address='eu-voice.example.org:64738',
    server_key='k-ss',
    is_active=True,
    driver='shitspeak',
    endpoints=(_normalize_endpoint({'label': 'EU Voice', 'host': 'eu-voice.example.org', 'port': '64738'}),),
)


def _make_member(username):
    user = User.objects.create_user(username, password='pass', is_staff=True)
    UserProfile.objects.create(user=user, is_member=True)
    return user


def _make_main(user, *, character_id, alliance_id):
    return EveCharacter.objects.create(
        user=user,
        character_id=character_id,
        character_name='Panel Main',
        corporation_id=920100,
        corporation_name='Panel Corp',
        alliance_id=alliance_id,
        alliance_name='Panel Alliance',
        is_main=True,
        access_token='x',
        refresh_token='x',
        token_expires=timezone.now(),
        scopes='',
    )


@override_settings(**_NO_REDIS)
class ServerPanelVisibilityTest(TestCase):
    """build_profile_panels honours BG is_active and the admin tile toggle."""

    def setUp(self):
        self.factory = RequestFactory()
        eve_setup = patch('fg.views._eve_char_setup', return_value=(EveCharacter, 'default'))
        eve_setup.start()
        self.addCleanup(eve_setup.stop)
        self.user = _make_member('panelvisibility')
        self.main = _make_main(self.user, character_id=821001, alliance_id=931001)
        AccessRule.objects.create(
            entity_id=self.main.alliance_id,
            entity_type=ENTITY_TYPE_ALLIANCE,
            deny=False,
        )

    def _request(self):
        request = self.factory.get('/profile/')
        request.user = self.user
        request.session = {}
        return request

    def _panels(self, servers):
        with patch('fg.panels.providers.safe_list_servers', return_value=list(servers)):
            return build_profile_panels(self._request())

    def test_default_titles_when_no_settings_row_exists(self):
        by_key = {panel['key']: panel for panel in self._panels([_ICE_SERVER, _SHITSPEAK_SERVER])}

        # BG's ice 'name' is a bare host:port — an address, not a heading.
        self.assertEqual(by_key['murmur-server-1']['panel_title'], 'MUMBLE')
        # A real (non-address) BG name wins over the driver default.
        self.assertEqual(by_key['mumble-beta-server-5']['panel_title'], 'mumble-beta')

    def test_admin_label_overrides_the_heading(self):
        ServerPanelSettings.objects.create(server_key='k-ss', label='Mumble')

        by_key = {panel['key']: panel for panel in self._panels([_ICE_SERVER, _SHITSPEAK_SERVER])}

        self.assertEqual(by_key['mumble-beta-server-5']['panel_title'], 'Mumble')
        self.assertEqual(by_key['murmur-server-1']['panel_title'], 'MUMBLE')

    def test_disabled_server_drops_its_tile(self):
        ServerPanelSettings.objects.create(server_key='k-ss', enabled=False)

        keys = {panel['key'] for panel in self._panels([_ICE_SERVER, _SHITSPEAK_SERVER])}

        self.assertEqual(keys, {'murmur-server-1'})

    def test_bg_inactive_server_drops_its_tile(self):
        inactive = RuntimeServer(
            id=7, name='Retired', address='old.example.com:64738',
            server_key='k-old', is_active=False, driver='ice',
        )

        keys = {panel['key'] for panel in self._panels([_ICE_SERVER, inactive])}

        self.assertEqual(keys, {'murmur-server-1'})

    def test_all_servers_hidden_renders_no_tiles(self):
        """Not even the no-BG fallback card — the tiles were turned off on purpose."""
        ServerPanelSettings.objects.create(server_key='k-ice', enabled=False)
        ServerPanelSettings.objects.create(server_key='k-ss', enabled=False)

        self.assertEqual(self._panels([_ICE_SERVER, _SHITSPEAK_SERVER]), [])

    def test_settings_read_failure_leaves_tiles_visible(self):
        """A broken settings read must not blank the profile page."""
        with patch(
            'fg.models.ServerPanelSettings.by_server_key',
            side_effect=RuntimeError('db down'),
        ):
            keys = {panel['key'] for panel in self._panels([_ICE_SERVER, _SHITSPEAK_SERVER])}

        self.assertEqual(keys, {'murmur-server-1', 'mumble-beta-server-5'})


@override_settings(**_NO_REDIS)
class ServerPanelsViewTest(TestCase):
    """The Servers tab under /mumble-ui/controls/."""

    def setUp(self):
        self.viewer = _make_member('panelviewer')
        self.editor = _make_member('paneleditor')
        self.editor.user_permissions.add(
            Permission.objects.get(codename='view_server_panels'),
            Permission.objects.get(codename='change_server_panels'),
        )
        self.viewer.user_permissions.add(Permission.objects.get(codename='view_server_panels'))
        self.list_url = reverse('mumble:server_panels')
        self.save_url = reverse('mumble:server_panels_save')

    def _servers_patch(self):
        return patch('fg.views.safe_list_servers', return_value=[_ICE_SERVER, _SHITSPEAK_SERVER])

    def test_requires_view_permission(self):
        nobody = _make_member('panelnobody')
        self.client.force_login(nobody)

        with self._servers_patch():
            self.assertEqual(self.client.get(self.list_url).status_code, 403)

    def test_lists_servers_with_effective_titles(self):
        self.client.force_login(self.viewer)
        ServerPanelSettings.objects.create(server_key='k-ss', label='Mumble')

        with self._servers_patch():
            response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        rows = {row['server_key']: row for row in response.context['server_rows']}
        self.assertEqual(rows['k-ice']['effective_title'], 'MUMBLE')
        self.assertTrue(rows['k-ice']['enabled'])
        self.assertEqual(rows['k-ss']['effective_title'], 'Mumble')
        self.assertFalse(response.context['can_change_server_panels'])

    def test_save_requires_change_permission(self):
        self.client.force_login(self.viewer)

        with self._servers_patch():
            response = self.client.post(self.save_url, {'server_key': ['k-ss']})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ServerPanelSettings.objects.exists())

    def test_save_writes_toggle_and_label(self):
        self.client.force_login(self.editor)

        with self._servers_patch():
            response = self.client.post(self.save_url, {
                'server_key': ['k-ice', 'k-ss'],
                'enabled__k-ice': 'on',
                'label__k-ice': '  Mumble  ',
                'label__k-ss': '',
            })

        self.assertRedirects(response, self.list_url, fetch_redirect_response=False)
        ice = ServerPanelSettings.objects.get(server_key='k-ice')
        self.assertTrue(ice.enabled)
        self.assertEqual(ice.label, 'Mumble')
        # No enabled__k-ss checkbox in the POST means the tile was unticked.
        self.assertFalse(ServerPanelSettings.objects.get(server_key='k-ss').enabled)

    def test_save_ignores_server_keys_bg_does_not_report(self):
        self.client.force_login(self.editor)

        with self._servers_patch():
            self.client.post(self.save_url, {
                'server_key': ['k-bogus'],
                'label__k-bogus': 'Injected',
            })

        self.assertFalse(ServerPanelSettings.objects.filter(server_key='k-bogus').exists())
