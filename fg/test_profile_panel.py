from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import EveCharacter, UserProfile
from fg.control import MurmurSyncError
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
        side_effect=MurmurSyncError('Control request failed (404): Mumble registration not found'),
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
