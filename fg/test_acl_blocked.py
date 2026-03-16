from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import EveCharacter, UserProfile
from fg.models import AccessRule, ENTITY_TYPE_ALLIANCE, ENTITY_TYPE_CORPORATION, ENTITY_TYPE_PILOT


_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)


def _make_member(username='aclviewer'):
    user = User.objects.create_user(username, password='pass', is_staff=True)
    UserProfile.objects.create(user=user, is_member=True)
    return user


@override_settings(**_NO_REDIS)
class ACLBlockedViewTest(TestCase):
    def setUp(self):
        self.viewer = _make_member()
        self.client.force_login(self.viewer)
        eve_setup = patch('fg.views._eve_char_setup', return_value=(EveCharacter, 'default'))
        self.mock_eve_setup = eve_setup.start()
        self.addCleanup(eve_setup.stop)

    def _make_cube_character(
        self,
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

    def test_blocked_view_shows_main_when_alt_is_denied_pilot(self):
        blocked_user = User.objects.create_user('blockeduser', password='pass')
        UserProfile.objects.create(user=blocked_user, is_member=True)
        main = self._make_cube_character(
            blocked_user,
            character_id=900001,
            character_name='Zosmas Main',
            corporation_id=980001,
            corporation_name='Main Corp',
            alliance_id=990001,
            alliance_name='Main Alliance',
            is_main=True,
        )
        alt = self._make_cube_character(
            blocked_user,
            character_id=900002,
            character_name='Zosma',
            corporation_id=980001,
            corporation_name='Main Corp',
            alliance_id=990001,
            alliance_name='Main Alliance',
        )
        AccessRule.objects.create(
            entity_id=alt.character_id,
            entity_type=ENTITY_TYPE_PILOT,
            deny=True,
        )
        AccessRule.objects.create(
            entity_id=990001,
            entity_type=ENTITY_TYPE_ALLIANCE,
            deny=False,
        )

        response = self.client.get(reverse('mumble:acl_blocked'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['pilots'][0]['character_name'], main.character_name)
        self.assertEqual(data['pilots'][0]['denied_as'], 'pilot')
        self.assertEqual(data['pilots'][0]['denied_detail'], alt.character_name)
        self.assertEqual(
            data['pilots'][0]['display_name'],
            'Zosmas Main (denied as: Zosma)',
        )

    def test_blocked_view_uses_most_specific_reason_for_account(self):
        blocked_user = User.objects.create_user('corpblockeduser', password='pass')
        UserProfile.objects.create(user=blocked_user, is_member=True)
        self._make_cube_character(
            blocked_user,
            character_id=910001,
            character_name='Corp Main',
            corporation_id=980010,
            corporation_name='Denied Corp',
            alliance_id=990010,
            alliance_name='Denied Alliance',
            is_main=True,
        )
        self._make_cube_character(
            blocked_user,
            character_id=910002,
            character_name='Corp Alt',
            corporation_id=980010,
            corporation_name='Denied Corp',
            alliance_id=990010,
            alliance_name='Denied Alliance',
        )
        AccessRule.objects.create(
            entity_id=980010,
            entity_type=ENTITY_TYPE_CORPORATION,
            deny=True,
        )
        AccessRule.objects.create(
            entity_id=990010,
            entity_type=ENTITY_TYPE_ALLIANCE,
            deny=False,
        )

        response = self.client.get(reverse('mumble:acl_blocked'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['pilots'][0]['character_name'], 'Corp Main')
        self.assertEqual(data['pilots'][0]['denied_as'], 'corp')
        self.assertEqual(data['pilots'][0]['denied_detail'], 'Denied Corp')
        self.assertEqual(
            data['pilots'][0]['display_name'],
            'Corp Main (denied as: Denied Corp)',
        )

    def test_blocked_view_ignores_pure_denied_alliance_without_allow_path(self):
        blocked_user = User.objects.create_user('allianceblockeduser', password='pass')
        UserProfile.objects.create(user=blocked_user, is_member=True)
        self._make_cube_character(
            blocked_user,
            character_id=920001,
            character_name='Alliance Main',
            corporation_id=980020,
            corporation_name='Denied Corp',
            alliance_id=990021,
            alliance_name='Denied Alliance',
            is_main=True,
        )
        AccessRule.objects.create(entity_id=990021, entity_type=ENTITY_TYPE_ALLIANCE, deny=True)

        response = self.client.get(reverse('mumble:acl_blocked'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['pilots'], [])

    def test_blocked_view_shows_alt_in_denied_alliance_when_main_is_allowed_by_alliance(self):
        blocked_user = User.objects.create_user('mixedallianceuser', password='pass')
        UserProfile.objects.create(user=blocked_user, is_member=True)
        self._make_cube_character(
            blocked_user,
            character_id=930001,
            character_name='Allowed Main',
            corporation_id=980030,
            corporation_name='Allowed Corp',
            alliance_id=990030,
            alliance_name='Allowed Alliance',
            is_main=True,
        )
        self._make_cube_character(
            blocked_user,
            character_id=930002,
            character_name='Denied Alt',
            corporation_id=980031,
            corporation_name='Denied Corp',
            alliance_id=990031,
            alliance_name='Denied Alliance',
        )
        AccessRule.objects.create(entity_id=990030, entity_type=ENTITY_TYPE_ALLIANCE, deny=False)
        AccessRule.objects.create(entity_id=990031, entity_type=ENTITY_TYPE_ALLIANCE, deny=True)

        response = self.client.get(reverse('mumble:acl_blocked'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['pilots'][0]['character_name'], 'Allowed Main')
        self.assertEqual(data['pilots'][0]['denied_as'], 'alliance')
        self.assertEqual(data['pilots'][0]['denied_detail'], 'Denied Alliance')
        self.assertEqual(
            data['pilots'][0]['display_name'],
            'Allowed Main (denied as: Denied Alliance)',
        )

    def test_blocked_view_ignores_deny_alliance_when_account_has_allow_corp(self):
        blocked_user = User.objects.create_user('corpallowuser', password='pass')
        UserProfile.objects.create(user=blocked_user, is_member=True)
        self._make_cube_character(
            blocked_user,
            character_id=940001,
            character_name='Corp Allowed Main',
            corporation_id=980040,
            corporation_name='Allowed Corp',
            alliance_id=990041,
            alliance_name='Denied Alliance',
            is_main=True,
        )
        self._make_cube_character(
            blocked_user,
            character_id=940002,
            character_name='Alliance Denied Alt',
            corporation_id=980041,
            corporation_name='Other Corp',
            alliance_id=990041,
            alliance_name='Denied Alliance',
        )
        AccessRule.objects.create(entity_id=980040, entity_type=ENTITY_TYPE_CORPORATION, deny=False)
        AccessRule.objects.create(entity_id=990041, entity_type=ENTITY_TYPE_ALLIANCE, deny=True)

        response = self.client.get(reverse('mumble:acl_blocked'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['pilots'], [])

    def test_blocked_view_ignores_deny_when_account_has_allow_pilot(self):
        blocked_user = User.objects.create_user('pilotallowuser', password='pass')
        UserProfile.objects.create(user=blocked_user, is_member=True)
        self._make_cube_character(
            blocked_user,
            character_id=950001,
            character_name='Pilot Allowed Main',
            corporation_id=980050,
            corporation_name='Denied Corp',
            alliance_id=990050,
            alliance_name='Denied Alliance',
            is_main=True,
        )
        self._make_cube_character(
            blocked_user,
            character_id=950002,
            character_name='Denied Alt',
            corporation_id=980051,
            corporation_name='Other Denied Corp',
            alliance_id=990051,
            alliance_name='Other Denied Alliance',
        )
        AccessRule.objects.create(entity_id=950001, entity_type=ENTITY_TYPE_PILOT, deny=False)
        AccessRule.objects.create(entity_id=980050, entity_type=ENTITY_TYPE_CORPORATION, deny=True)
        AccessRule.objects.create(entity_id=990051, entity_type=ENTITY_TYPE_ALLIANCE, deny=True)

        response = self.client.get(reverse('mumble:acl_blocked'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['pilots'], [])
