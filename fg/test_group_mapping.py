from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from fg.models import (
    CubeGroupMapping,
    IgnoredCubeGroup,
    IgnoredMurmurGroup,
    MurmurInventorySnapshot,
)
from fg.group_mapping import effective_murmur_groups_for_user
from fg.sidebar import SIDEBAR_ITEMS

_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)


def _make_member(username='groupmapuser'):
    user = User.objects.create_user(username, password='pass')
    UserProfile.objects.create(user=user, is_member=True)
    return user


def _grant_group_mapping_perm(user, codename):
    permission = Permission.objects.get(
        content_type=ContentType.objects.get_for_model(CubeGroupMapping),
        codename=codename,
    )
    user.user_permissions.add(permission)


def _runtime_server(pk=1, name='Finland'):
    return SimpleNamespace(pk=pk, name=name, is_active=True, address='voice.example.com:64738')


def _snapshot(server_id=1, server_name='Finland', *, root_groups=None, channel_groups=None):
    groups = channel_groups or [{'name': 'ops'}, {'name': 'command'}]
    return MurmurInventorySnapshot(
        server_id=server_id,
        server_name=server_name,
        freshness_seconds=600,
        is_real_time=True,
        fetched_at=timezone.now(),
        inventory={
            'root_groups': root_groups or [{'name': 'ops'}, {'name': 'command'}],
            'channels': [
                {
                    'id': 0,
                    'name': 'Root',
                    'path': 'Root',
                    'groups': groups,
                    'acls': [],
                }
            ],
            'summary': {'channel_count': 1, 'acl_count': 2, 'group_count': 2},
        },
    )


@override_settings(**_NO_REDIS)
class GroupMappingViewTest(TestCase):
    databases = {'default', 'cube'}

    def setUp(self):
        self.factory = RequestFactory()
        self.user = _make_member()

    def _login(self):
        self.client.force_login(self.user)

    def _sidebar_item(self):
        return next(item for item in SIDEBAR_ITEMS if item['key'] == 'mumble_controls')

    def test_view_permission_controls_sidebar_and_page_access(self):
        request = self.factory.get('/')
        request.user = self.user
        self.assertFalse(self._sidebar_item()['visible'](request))

        self._login()
        response = self.client.get(reverse('mumble:group_mapping'))
        self.assertEqual(response.status_code, 403)

        _grant_group_mapping_perm(self.user, 'view_group_mapping')
        self.user = User.objects.get(pk=self.user.pk)
        request.user = self.user
        self.assertTrue(self._sidebar_item()['visible'](request))

        with patch('fg.views.safe_list_servers', return_value=[_runtime_server()]), patch(
            'fg.views.all_cube_group_names',
            return_value=['Command'],
        ), patch('fg.views._load_inventory_snapshot', return_value=(_snapshot(), '')):
            response = self.client.get(reverse('mumble:group_mapping'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mumble Controls')
        self.assertContains(response, 'Groups')

    def test_mumble_admin_bypass_does_not_grant_group_mapping_access(self):
        request = self.factory.get('/')
        request.user = self.user
        with patch('fg.group_mapping.user_has_mumble_admin_bypass', return_value=True):
            self.assertFalse(self._sidebar_item()['visible'](request))

        self._login()
        with patch('fg.views.user_has_mumble_admin_bypass', return_value=True), patch(
            'fg.views.safe_list_servers',
            return_value=[_runtime_server()],
        ), patch('fg.views.all_cube_group_names', return_value=['Command']), patch(
            'fg.views._load_inventory_snapshot',
            return_value=(_snapshot(), ''),
        ):
            response = self.client.get(reverse('mumble:group_mapping'))

        self.assertEqual(response.status_code, 403)

    def test_controls_route_redirects_to_groups_when_only_group_access_exists(self):
        _grant_group_mapping_perm(self.user, 'view_group_mapping')
        self._login()

        response = self.client.get(reverse('mumble:controls'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('mumble:group_mapping'))

    def test_refresh_stores_snapshot_from_bg(self):
        _grant_group_mapping_perm(self.user, 'view_group_mapping')
        _grant_group_mapping_perm(self.user, 'change_group_mapping')
        self._login()

        fetched_at = timezone.now().isoformat()
        with patch('fg.views.safe_list_servers', return_value=[_runtime_server(pk=7)]), patch(
            'fg.views._CONTROL_CLIENT.get_server_inventory',
            return_value={
                'server_id': 7,
                'server_label': 'Finland',
                'freshness_seconds': 600,
                'is_real_time': True,
                'fetched_at': fetched_at,
                'inventory': {
                    'root_groups': [{'name': 'ops'}],
                    'summary': {'channel_count': 1, 'acl_count': 2, 'group_count': 1},
                },
            },
        ):
            response = self.client.post(
                reverse('mumble:group_mapping_refresh'),
                {
                    'server_id': '7',
                    'cube_group_name': 'Command',
                },
            )

        self.assertEqual(response.status_code, 302)
        snapshot = MurmurInventorySnapshot.objects.get(server_id=7)
        self.assertEqual(snapshot.server_name, 'Finland')
        self.assertEqual(snapshot.inventory['root_groups'][0]['name'], 'ops')
        self.assertTrue(snapshot.is_real_time)

    def test_add_remove_ignore_and_cleanup_mapping_rows(self):
        _grant_group_mapping_perm(self.user, 'view_group_mapping')
        _grant_group_mapping_perm(self.user, 'change_group_mapping')
        self._login()

        response = self.client.post(
            reverse('mumble:group_mapping_add'),
            {
                'server_id': '1',
                'cube_group_name': 'Command',
                'murmur_group_name': 'ops',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CubeGroupMapping.objects.filter(cube_group_name='Command', murmur_group_name='ops').exists())

        response = self.client.post(
            reverse('mumble:group_mapping_toggle_cube_ignore'),
            {
                'server_id': '1',
                'cube_group_name': 'Command',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(IgnoredCubeGroup.objects.filter(cube_group_name='Command').exists())

        response = self.client.post(
            reverse('mumble:group_mapping_toggle_murmur_ignore'),
            {
                'server_id': '1',
                'cube_group_name': 'Command',
                'murmur_group_name': 'ops',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(IgnoredMurmurGroup.objects.filter(murmur_group_name='ops').exists())

        response = self.client.post(
            reverse('mumble:group_mapping_cleanup_ignored'),
            {
                'server_id': '1',
                'cube_group_name': 'Command',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CubeGroupMapping.objects.filter(cube_group_name='Command', murmur_group_name='ops').exists())

    def test_single_server_renders_fixed_text_and_suppressed_ignored_group(self):
        _grant_group_mapping_perm(self.user, 'view_group_mapping')
        _grant_group_mapping_perm(self.user, 'change_group_mapping')
        IgnoredMurmurGroup.objects.create(murmur_group_name='ops')
        self._login()

        with patch('fg.views.safe_list_servers', return_value=[_runtime_server()]), patch(
            'fg.views.all_cube_group_names',
            return_value=['Command'],
        ), patch(
            'fg.views._load_inventory_snapshot',
            return_value=(_snapshot(root_groups=[{'name': 'ops'}]), ''),
        ):
            response = self.client.get(reverse('mumble:group_mapping'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Finland')
        self.assertContains(response, 'Murmur group ignored')
        self.assertContains(response, 'Restore')
        self.assertNotContains(response, '<select name="server"', html=False)

    def test_groups_view_uses_all_channel_groups_not_only_root_groups(self):
        _grant_group_mapping_perm(self.user, 'view_group_mapping')
        self._login()

        with patch('fg.views.safe_list_servers', return_value=[_runtime_server()]), patch(
            'fg.views.all_cube_group_names',
            return_value=['Command'],
        ), patch(
            'fg.views._load_inventory_snapshot',
            return_value=(
                _snapshot(
                    root_groups=[{'name': 'admin'}],
                    channel_groups=[{'name': 'admin'}, {'name': 'ops'}, {'name': 'command'}],
                ),
                '',
            ),
        ):
            response = self.client.get(reverse('mumble:group_mapping'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'admin')
        self.assertContains(response, 'ops')
        self.assertContains(response, 'command')
        self.assertContains(response, 'Load View')
        self.assertContains(response, 'Refresh From BG')


class EffectiveMurmurGroupsMemberTest(TestCase):
    databases = {'default', 'cube'}

    def test_member_gets_member_group(self):
        user = _make_member('memberuser')
        groups = effective_murmur_groups_for_user(user)
        self.assertIn('Member', groups)

    def test_non_member_does_not_get_member_group(self):
        user = User.objects.create_user('nonmember', password='pass')
        UserProfile.objects.create(user=user, is_member=False)
        groups = effective_murmur_groups_for_user(user)
        self.assertNotIn('Member', groups)

    def test_no_profile_does_not_get_member_group(self):
        user = User.objects.create_user('noprofile', password='pass')
        groups = effective_murmur_groups_for_user(user)
        self.assertNotIn('Member', groups)
