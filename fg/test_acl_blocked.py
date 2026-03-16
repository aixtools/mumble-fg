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

    def test_eligible_view_excludes_blocked_account_when_alt_is_denied_pilot(self):
        blocked_user = User.objects.create_user('eligibleblockeduser', password='pass')
        UserProfile.objects.create(user=blocked_user, is_member=True)
        self._make_cube_character(
            blocked_user,
            character_id=960001,
            character_name='Leo Rises',
            corporation_id=980060,
            corporation_name='Allowed Corp',
            alliance_id=990060,
            alliance_name='Allowed Alliance',
            is_main=True,
        )
        self._make_cube_character(
            blocked_user,
            character_id=960002,
            character_name='Zosma Rises',
            corporation_id=980060,
            corporation_name='Allowed Corp',
            alliance_id=990060,
            alliance_name='Allowed Alliance',
        )
        AccessRule.objects.create(entity_id=990060, entity_type=ENTITY_TYPE_ALLIANCE, deny=False)
        AccessRule.objects.create(entity_id=960002, entity_type=ENTITY_TYPE_PILOT, deny=True)

        response = self.client.get(reverse('mumble:acl_eligible'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['pilots'], [])

    def test_eligible_view_excludes_account_when_alt_is_in_denied_alliance(self):
        blocked_user = User.objects.create_user('eligibleallianceblockeduser', password='pass')
        UserProfile.objects.create(user=blocked_user, is_member=True)
        self._make_cube_character(
            blocked_user,
            character_id=970001,
            character_name='Zeza',
            corporation_id=980070,
            corporation_name='Allowed Corp',
            alliance_id=990070,
            alliance_name='Allowed Alliance',
            is_main=True,
        )
        self._make_cube_character(
            blocked_user,
            character_id=970002,
            character_name='Saisaishi Muvila',
            corporation_id=980071,
            corporation_name='Denied Corp',
            alliance_id=990071,
            alliance_name='Denied Alliance',
        )
        AccessRule.objects.create(entity_id=990070, entity_type=ENTITY_TYPE_ALLIANCE, deny=False)
        AccessRule.objects.create(entity_id=990071, entity_type=ENTITY_TYPE_ALLIANCE, deny=True)

        response = self.client.get(reverse('mumble:acl_eligible'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['pilots'], [])

    def test_eligible_view_shows_only_main_for_alliance_allowed_account(self):
        eligible_user = User.objects.create_user('eligiblemainonlyuser', password='pass')
        UserProfile.objects.create(user=eligible_user, is_member=True)
        self._make_cube_character(
            eligible_user,
            character_id=980001,
            character_name='Leo Rises',
            corporation_id=980080,
            corporation_name='Allowed Corp',
            alliance_id=990080,
            alliance_name='Allowed Alliance',
            is_main=True,
        )
        self._make_cube_character(
            eligible_user,
            character_id=980002,
            character_name='Amori',
            corporation_id=980080,
            corporation_name='Allowed Corp',
            alliance_id=990080,
            alliance_name='Allowed Alliance',
        )
        self._make_cube_character(
            eligible_user,
            character_id=980003,
            character_name='Zosma',
            corporation_id=980080,
            corporation_name='Allowed Corp',
            alliance_id=990080,
            alliance_name='Allowed Alliance',
        )
        AccessRule.objects.create(entity_id=990080, entity_type=ENTITY_TYPE_ALLIANCE, deny=False)

        response = self.client.get(reverse('mumble:acl_eligible'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['pilots'][0]['character_name'], 'Leo Rises')
        self.assertEqual(data['pilots'][0]['pilot_lines'], ['Leo Rises'])

    def test_eligible_view_groups_main_with_explicitly_allowed_alt(self):
        eligible_user = User.objects.create_user('eligiblealtuser', password='pass')
        UserProfile.objects.create(user=eligible_user, is_member=True)
        self._make_cube_character(
            eligible_user,
            character_id=990001,
            character_name='Main Pilot',
            corporation_id=980090,
            corporation_name='Denied Corp',
            alliance_id=990090,
            alliance_name='Denied Alliance',
            is_main=True,
        )
        self._make_cube_character(
            eligible_user,
            character_id=990002,
            character_name='Allowed Alt',
            corporation_id=980091,
            corporation_name='Denied Corp',
            alliance_id=990091,
            alliance_name='Denied Alliance',
        )
        AccessRule.objects.create(entity_id=990002, entity_type=ENTITY_TYPE_PILOT, deny=False)

        response = self.client.get(reverse('mumble:acl_eligible'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['pilots'][0]['character_name'], 'Main Pilot')
        self.assertEqual(data['pilots'][0]['pilot_lines'], ['Main Pilot', 'Allowed Alt'])
