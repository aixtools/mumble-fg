from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import UserProfile
from fg.models import TempLink

_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)


def _make_member(username='templinkuser'):
    user = User.objects.create_user(username, password='pass')
    UserProfile.objects.create(user=user, is_member=True)
    return user


def _grant_temp_link_perm(user, codename):
    permission = Permission.objects.get(
        content_type=ContentType.objects.get_for_model(TempLink),
        codename=codename,
    )
    user.user_permissions.add(permission)


@override_settings(**_NO_REDIS)
class TempLinksViewTest(TestCase):
    databases = {'default', 'cube'}

    def setUp(self):
        self.user = _make_member()

    def test_view_requires_permission(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('mumble:temp_links'))
        self.assertEqual(response.status_code, 403)

    def test_create_and_redeem_temp_link(self):
        _grant_temp_link_perm(self.user, 'view_temp_links')
        _grant_temp_link_perm(self.user, 'change_temp_links')
        self.client.force_login(self.user)

        server = type('Server', (), {'name': 'Finland', 'server_key': 'voice-example-com-64738-vs1', 'is_active': True})()
        with patch('fg.views.safe_list_servers', return_value=[server]):
            response = self.client.post(
                reverse('mumble:temp_link_create'),
                {
                    'server': server.server_key,
                    'label': 'Guest Link',
                    'duration_hours': '24',
                    'max_uses': '1',
                    'groups_csv': 'Guest',
                },
            )
        self.assertEqual(response.status_code, 302)
        link = TempLink.objects.get()
        self.assertEqual(link.server_key, server.server_key)

        with patch(
            'fg.views._CONTROL_CLIENT.redeem_temp_link',
            return_value={
                'server_name': 'Finland',
                'address': 'voice.example.com:64738',
                'username': 'temp_deadbeef',
                'display_name': 'Guest One',
                'password': 'Abcd1234!',
            },
        ):
            response = self.client.post(
                reverse('mumble:temp_link_public', args=[link.token]),
                {'display_name': 'Guest One'},
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'temp_deadbeef')
        self.assertContains(response, 'Abcd1234!')
        link.refresh_from_db()
        self.assertEqual(link.use_count, 1)
        self.assertFalse(link.is_active)
