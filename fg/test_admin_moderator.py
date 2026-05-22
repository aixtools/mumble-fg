"""Permission and behavior tests for the cube-admin moderator endpoints.

These views are the FG side of Cube's "Edit User" page (Cube spec 34): a
Cube cube-admin can force-reset another user's Mumble password and clear
their certhash on a per-server basis. The companion BG endpoint is tested
in mumble-bg's ``tests/test_control_clear_certhash.py``; here we cover
the permission gate, the BG client interaction (mocked), and the runtime
fallback path so the tests don't require a host MumbleUser model.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

try:
    from accounts.models import UserProfile
except ImportError as exc:  # pragma: no cover - environment-specific host model
    raise unittest.SkipTest(f'Host model unavailable: {exc}') from exc

from fg.control import BgSyncError


_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)


def _make_member(username='moder_actor', **kwargs):
    user = User.objects.create_user(username, password='pass', **kwargs)
    UserProfile.objects.create(user=user, is_member=True)
    try:
        # Cube's AllianceCheckMiddleware reads member status from cache; tests
        # need to seed it so authenticated requests don't 302 to /profile/.
        from accounts.cache import CacheManager
        CacheManager.set_user_member_status(user.pk, True)
    except ImportError:
        pass
    return user


def _add_to_group(user, name):
    group, _ = Group.objects.get_or_create(name=name)
    user.groups.add(group)


@override_settings(**_NO_REDIS, MURMUR_MODEL_APP_LABEL='missing_app_label')
class AdminModeratorEndpointPermissionTest(TestCase):
    """Verify the permission gate accepts each acceptable credential and
    rejects everyone else."""

    def setUp(self):
        self.target_pkid = 4242
        self.server_id = 7

    def _registration(self):
        return SimpleNamespace(
            user_id=self.target_pkid,
            server_id=self.server_id,
            username='target_user',
            user=None,
        )

    def _password_url(self):
        return reverse(
            'mumble:admin_reset_password_for_user',
            args=[self.target_pkid, self.server_id],
        )

    def _certhash_url(self):
        return reverse(
            'mumble:admin_clear_certhash',
            args=[self.target_pkid, self.server_id],
        )

    def test_anonymous_redirects(self):
        # @login_required redirects, doesn't 403
        response = self.client.post(self._password_url())
        self.assertIn(response.status_code, (302, 401, 403))

    def test_plain_authenticated_user_is_forbidden(self):
        user = _make_member('plain')
        self.client.force_login(user)
        response = self.client.post(self._password_url())
        self.assertEqual(response.status_code, 403)
        response = self.client.post(self._certhash_url())
        self.assertEqual(response.status_code, 403)

    @patch('fg.views._runtime_registration')
    @patch('fg.views._CONTROL_CLIENT.reset_password_for_user')
    def test_cube_admin_group_can_reset_password(self, reset_mock, runtime_mock):
        reset_mock.return_value = {'password': 'NEWPASSWORD'}
        runtime_mock.return_value = self._registration()

        user = _make_member('cube_admin_user')
        _add_to_group(user, 'cube-admin')
        self.client.force_login(user)

        response = self.client.post(self._password_url())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['password'], 'NEWPASSWORD')
        self.assertEqual(body['server_id'], self.server_id)
        self.assertEqual(body['username'], 'target_user')

        reset_mock.assert_called_once()
        kwargs = reset_mock.call_args.kwargs
        self.assertEqual(kwargs['pkid'], self.target_pkid)
        self.assertEqual(kwargs['requested_by'], f'cube_admin:{user.pk}')

    @patch('fg.views._runtime_registration')
    @patch('fg.views._CONTROL_CLIENT.clear_certhash_for_user')
    def test_cube_admin_group_can_clear_certhash(self, clear_mock, runtime_mock):
        clear_mock.return_value = {'status': 'completed'}
        runtime_mock.return_value = self._registration()

        user = _make_member('cube_admin_user')
        _add_to_group(user, 'cube-admin')
        self.client.force_login(user)

        response = self.client.post(self._certhash_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True})

        clear_mock.assert_called_once()
        kwargs = clear_mock.call_args.kwargs
        self.assertEqual(kwargs['pkid'], self.target_pkid)
        # server_id is the second positional arg
        self.assertEqual(clear_mock.call_args.args[1], self.server_id)

    @patch('fg.views._runtime_registration')
    @patch('fg.views._CONTROL_CLIENT.reset_password_for_user')
    def test_manage_mumble_admin_perm_is_sufficient(self, reset_mock, runtime_mock):
        reset_mock.return_value = {'password': 'PW'}
        runtime_mock.return_value = self._registration()

        # The ``manage_mumble_admin`` permission lives on the host's MumbleUser
        # model and only exists when host migrations have run. The view checks
        # via ``has_perm`` codenames, so we patch the lookup directly to keep
        # this test independent of host model installation.
        user = _make_member('mumble_admin_user')

        original_has_perm = User.has_perm

        def _has_perm(self_user, perm, obj=None):
            if perm in {'mumble.manage_mumble_admin', 'mumble_fg.manage_mumble_admin'}:
                return self_user.pk == user.pk
            return original_has_perm(self_user, perm, obj)

        with patch.object(User, 'has_perm', _has_perm):
            self.client.force_login(user)
            response = self.client.post(self._password_url())
        self.assertEqual(response.status_code, 200)

    @patch('fg.views._runtime_registration')
    @patch('fg.views._CONTROL_CLIENT.reset_password_for_user')
    def test_superuser_bypass(self, reset_mock, runtime_mock):
        reset_mock.return_value = {'password': 'SU_PW'}
        runtime_mock.return_value = self._registration()

        user = _make_member('su_user', is_superuser=True, is_staff=True)
        self.client.force_login(user)

        response = self.client.post(self._password_url())
        self.assertEqual(response.status_code, 200)


@override_settings(**_NO_REDIS, MURMUR_MODEL_APP_LABEL='missing_app_label')
class AdminModeratorEndpointBehaviorTest(TestCase):
    """Verify error paths: missing registration → 404, BG failure → 502."""

    def setUp(self):
        self.target_pkid = 9001
        self.server_id = 3
        self.user = _make_member('moderator')
        _add_to_group(self.user, 'cube-admin')
        self.client.force_login(self.user)

    @patch('fg.views._runtime_registration', return_value=None)
    def test_404_when_registration_missing_for_password_reset(self, _runtime_mock):
        url = reverse(
            'mumble:admin_reset_password_for_user',
            args=[self.target_pkid, self.server_id],
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {'error': 'not_found'})

    @patch('fg.views._runtime_registration', return_value=None)
    def test_404_when_registration_missing_for_clear_certhash(self, _runtime_mock):
        url = reverse(
            'mumble:admin_clear_certhash',
            args=[self.target_pkid, self.server_id],
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {'error': 'not_found'})

    @patch('fg.views._runtime_registration')
    @patch(
        'fg.views._CONTROL_CLIENT.reset_password_for_user',
        side_effect=BgSyncError('BG unreachable'),
    )
    def test_502_when_bg_sync_fails_for_password_reset(self, _reset_mock, runtime_mock):
        runtime_mock.return_value = SimpleNamespace(
            user_id=self.target_pkid,
            server_id=self.server_id,
            username='t',
            user=None,
        )
        url = reverse(
            'mumble:admin_reset_password_for_user',
            args=[self.target_pkid, self.server_id],
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error'], 'bg_sync_failed')

    @patch('fg.views._runtime_registration')
    @patch(
        'fg.views._CONTROL_CLIENT.clear_certhash_for_user',
        side_effect=BgSyncError('BG unreachable'),
    )
    def test_502_when_bg_sync_fails_for_clear_certhash(self, _clear_mock, runtime_mock):
        runtime_mock.return_value = SimpleNamespace(
            user_id=self.target_pkid,
            server_id=self.server_id,
            username='t',
            user=None,
        )
        url = reverse(
            'mumble:admin_clear_certhash',
            args=[self.target_pkid, self.server_id],
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error'], 'bg_sync_failed')

    @patch('fg.views._runtime_registration')
    @patch('fg.views._CONTROL_CLIENT.reset_password_for_user', return_value={})
    def test_502_when_bg_returns_no_password(self, _reset_mock, runtime_mock):
        runtime_mock.return_value = SimpleNamespace(
            user_id=self.target_pkid,
            server_id=self.server_id,
            username='t',
            user=None,
        )
        url = reverse(
            'mumble:admin_reset_password_for_user',
            args=[self.target_pkid, self.server_id],
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error'], 'no_password_in_response')
