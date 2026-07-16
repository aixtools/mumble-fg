from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import EveCharacter, UserProfile
from fg.control import BgSyncError
from fg.models import AccessRule, ENTITY_TYPE_ALLIANCE, ENTITY_TYPE_PILOT
from fg.panels import build_profile_panels
from fg.views import profile_password_pilot_choices

_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)


def _make_member(username='profilepaneluser'):
    user = User.objects.create_user(username, password='pass', is_staff=True)
    UserProfile.objects.create(user=user, is_member=True)
    return user


def _make_character(
    user,
    *,
    character_id,
    character_name,
    corporation_id,
    corporation_name,
    alliance_id,
    alliance_name,
    is_main=False,
):
    return EveCharacter.objects.create(
        user=user,
        character_id=character_id,
        character_name=character_name,
        corporation_id=corporation_id,
        corporation_name=corporation_name,
        alliance_id=alliance_id,
        alliance_name=alliance_name,
        is_main=is_main,
        access_token='x',
        refresh_token='x',
        token_expires=timezone.now(),
        scopes='',
    )


@override_settings(**_NO_REDIS)
class ProfilePanelEligibilityTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        eve_setup = patch('fg.views._eve_char_setup', return_value=(EveCharacter, 'default'))
        self.mock_eve_setup = eve_setup.start()
        self.addCleanup(eve_setup.stop)
        self.user = _make_member('eligibleprofileuser')
        self.main = _make_character(
            self.user,
            character_id=820001,
            character_name='Eligible Main',
            corporation_id=920001,
            corporation_name='Eligible Corp',
            alliance_id=930001,
            alliance_name='Eligible Alliance',
            is_main=True,
        )
        AccessRule.objects.create(
            entity_id=self.main.alliance_id,
            entity_type=ENTITY_TYPE_ALLIANCE,
            deny=False,
        )

    def _request(self, user=None):
        request = self.factory.get('/profile/')
        request.user = user or self.user
        request.session = {}
        return request

    @patch('fg.panels.providers.safe_list_servers', return_value=[])
    def test_profile_panel_renders_for_acl_eligible_user_without_bg_servers(self, _mock_safe_list_servers):
        panels = build_profile_panels(self._request())

        self.assertEqual(len(panels), 1)
        self.assertIsNone(panels[0]['server'])
        self.assertEqual(panels[0]['server_label'], 'Mumble Authentication')
        self.assertEqual(
            panels[0]['eligible_pilots'],
            [
                {
                    'character_id': self.main.character_id,
                    'character_name': self.main.character_name,
                    'is_main': True,
                }
            ],
        )
        self.assertFalse(panels[0]['show_pilot_selector'])

    @patch('fg.panels.providers.safe_list_servers')
    def test_shitspeak_server_gets_its_own_panel(self, mock_list):
        """ShitSpeak (different stack) renders as its own card with a distinct
        template + key and a region selector over the cluster endpoints, while
        Murmur servers keep the existing panel."""
        from fg.runtime import RuntimeServer, _normalize_endpoint

        mock_list.return_value = [
            RuntimeServer(
                id=1, name='voice.example.com:64738', address='voice.example.com:64738',
                server_key='k-ice', is_active=True, driver='ice',
            ),
            RuntimeServer(
                id=5, name='mumble-beta', address='eu-voice.insidiousevil.org:64738',
                server_key='k-ss', is_active=True, driver='shitspeak',
                endpoints=tuple(_normalize_endpoint(d) for d in (
                    {'label': 'US Voice', 'host': 'us-voice.insidiousevil.org', 'port': '64738'},
                    {'label': 'EU Voice', 'host': 'eu-voice.insidiousevil.org', 'port': '64738'},
                    {'label': 'HK Voice', 'host': 'evil-voice-hk.undock.wtf', 'port': '64739'},
                )),
            ),
        ]
        by_key = {p['key']: p for p in build_profile_panels(self._request())}

        # Murmur server: unchanged panel + template.
        self.assertIn('murmur-server-1', by_key)
        self.assertEqual(by_key['murmur-server-1']['template'], 'fg/panels/profile_panel.html')

        # ShitSpeak server: its own card, its own template, endpoints exposed with labels.
        self.assertIn('mumble-beta-server-5', by_key)
        ss = by_key['mumble-beta-server-5']
        self.assertEqual(ss['template'], 'fg/panels/shitspeak_panel.html')
        self.assertEqual(ss['server_label'], 'mumble-beta')
        self.assertEqual(
            [(e['label'], e['host'], e['port']) for e in ss['endpoints']],
            [
                ('US Voice', 'us-voice.insidiousevil.org', '64738'),
                ('EU Voice', 'eu-voice.insidiousevil.org', '64738'),
                ('HK Voice', 'evil-voice-hk.undock.wtf', '64739'),
            ],
        )
        # Still opts into the /comms dashboard via the 'mumble-' key prefix.
        self.assertTrue(ss['key'].startswith('mumble-'))

    def test_normalize_endpoint_forms_and_runtime_server_hashable(self):
        from fg.runtime import RuntimeServer, _normalize_endpoint

        # dict with a region label
        e = _normalize_endpoint({'label': 'US Voice', 'host': 'us.example', 'port': '64738'})
        self.assertEqual(
            (e.label, e.host, e.port, e.address),
            ('US Voice', 'us.example', '64738', 'us.example:64738'),
        )
        # plain 'host:port' string (older BG) -> label defaults to host
        e2 = _normalize_endpoint('eu.example:64739')
        self.assertEqual((e2.label, e2.host, e2.port), ('eu.example', 'eu.example', '64739'))
        # empty forms drop out
        self.assertIsNone(_normalize_endpoint(''))
        self.assertIsNone(_normalize_endpoint({}))
        # RuntimeServer must stay hashable (it's a frozen dataclass) even with endpoints
        rs = RuntimeServer(
            id=5, name='mumble-beta', address='a:1', server_key='k',
            driver='shitspeak', endpoints=(e, e2),
        )
        self.assertIsInstance(hash(rs), int)

    @patch('fg.panels.providers.safe_list_servers', return_value=[])
    def test_profile_panel_hides_for_non_eligible_user(self, _mock_safe_list_servers):
        other_user = _make_member('ineligibleprofileuser')
        _make_character(
            other_user,
            character_id=820002,
            character_name='Ineligible Main',
            corporation_id=920002,
            corporation_name='Ineligible Corp',
            alliance_id=930002,
            alliance_name='Ineligible Alliance',
            is_main=True,
        )

        panels = build_profile_panels(self._request(other_user))

        self.assertEqual(panels, [])

    @patch('fg.panels.providers.safe_list_servers', return_value=[])
    def test_profile_panel_groups_main_and_explicit_alt_for_selector(self, _mock_safe_list_servers):
        alt = _make_character(
            self.user,
            character_id=820003,
            character_name='Allowed Alt',
            corporation_id=920003,
            corporation_name='Alt Corp',
            alliance_id=930003,
            alliance_name='Alt Alliance',
        )
        AccessRule.objects.create(
            entity_id=alt.character_id,
            entity_type=ENTITY_TYPE_PILOT,
            deny=False,
        )

        panels = build_profile_panels(self._request())

        self.assertEqual(len(panels), 1)
        self.assertEqual(
            panels[0]['eligible_pilots'],
            [
                {
                    'character_id': self.main.character_id,
                    'character_name': self.main.character_name,
                    'is_main': True,
                },
                {
                    'character_id': alt.character_id,
                    'character_name': alt.character_name,
                    'is_main': False,
                },
            ],
        )
        self.assertTrue(panels[0]['show_pilot_selector'])


@override_settings(**_NO_REDIS)
class ProfilePasswordActionTest(TestCase):
    def setUp(self):
        eve_setup = patch('fg.views._eve_char_setup', return_value=(EveCharacter, 'default'))
        self.mock_eve_setup = eve_setup.start()
        self.addCleanup(eve_setup.stop)
        self.user = _make_member('passwordpaneluser')
        self.client.force_login(self.user)
        self.main = _make_character(
            self.user,
            character_id=821001,
            character_name='Password Main',
            corporation_id=921001,
            corporation_name='Password Corp',
            alliance_id=931001,
            alliance_name='Password Alliance',
            is_main=True,
        )
        AccessRule.objects.create(
            entity_id=self.main.alliance_id,
            entity_type=ENTITY_TYPE_ALLIANCE,
            deny=False,
        )

    def test_profile_password_choices_use_main_plus_explicit_alts(self):
        self.assertEqual(
            profile_password_pilot_choices(self.user),
            [
                {
                    'character_id': self.main.character_id,
                    'character_name': self.main.character_name,
                    'is_main': True,
                }
            ],
        )

    def test_profile_reset_password_returns_bg_unavailable_for_ajax(self):
        response = self.client.post(
            reverse('mumble:profile_reset_password'),
            {'pilot_id': self.main.character_id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 503)
        self.assertJSONEqual(
            response.content,
            {'error': 'BG unavailable', 'bg_unavailable': True},
        )

    def test_profile_set_password_returns_bg_unavailable_for_ajax(self):
        response = self.client.post(
            reverse('mumble:profile_set_password'),
            {'pilot_id': self.main.character_id, 'murmur_password': 'longenoughpw'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 503)
        self.assertJSONEqual(
            response.content,
            {'error': 'BG unavailable', 'bg_unavailable': True},
        )

    @patch(
        'fg.views._CONTROL_CLIENT.reset_password_for_user',
        side_effect=BgSyncError('Control request failed (404): Mumble registration not found'),
    )
    def test_profile_reset_password_returns_inactive_for_ajax_when_bg_available(self, _mock_reset):
        response = self.client.post(
            reverse('mumble:profile_reset_password'),
            {'pilot_id': self.main.character_id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 409)
        self.assertJSONEqual(
            response.content,
            {'error': 'Mumble account inactive, try again later.', 'bg_unavailable': False},
        )
