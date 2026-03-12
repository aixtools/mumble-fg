import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import EveCharacter, Group, GroupMembership, UserProfile
from fg.passwords import (
    LEGACY_BCRYPT_SHA256,
    MURMUR_PBKDF2_SHA384,
    build_murmur_password_record,
    verify_murmur_password,
)
from modules.corporation.models import CorporationSettings
from fg.pilot.control import MumbleSyncError, _post_json, sync_live_admin_membership
from fg.pilot.models import MumbleServer, MumbleSession, MumbleUser
from fg.views import (
    _PASSWORD_ALPHABET,
    _generate_password,
    _get_mumble_username,
    _compute_display_name,
    _compute_groups,
)

# Override cache and session backends so tests don't require Redis
_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)


class _JsonResponseStub:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode('utf-8')


def _make_server(**kwargs):
    defaults = dict(
        name='Test Server',
        address='mumble.example.com:64738',
        ice_host='127.0.0.1',
        ice_port=6502,
    )
    defaults.update(kwargs)
    return MumbleServer.objects.create(**defaults)


def _make_char(user, **kwargs):
    defaults = dict(
        user=user,
        character_id=12345,
        character_name='Test Pilot',
        is_main=True,
        access_token='x',
        refresh_token='x',
        token_expires=timezone.now(),
        scopes='',
    )
    defaults.update(kwargs)
    return EveCharacter.objects.create(**defaults)


def _make_member(username='testuser'):
    """Create a staff user to bypass AllianceCheckMiddleware."""
    user = User.objects.create_user(username, password='pass', is_staff=True)
    UserProfile.objects.create(user=user, is_member=True)
    return user


def _make_regular_member(username='memberuser'):
    user = User.objects.create_user(username, password='pass')
    UserProfile.objects.create(user=user, is_member=True)
    return user


def _grant_alliance_leader_group(user):
    group = Group.objects.create(name=f'Alliance Leaders {user.username}')
    GroupMembership.objects.create(user=user, group=group, status='approved')
    settings = CorporationSettings.load()
    settings.alliance_leader_groups.add(group)
    return group


class GeneratePasswordTest(TestCase):
    def test_default_length(self):
        pw = _generate_password()
        self.assertEqual(len(pw), 16)

    def test_custom_length(self):
        pw = _generate_password(length=32)
        self.assertEqual(len(pw), 32)

    def test_supported_ascii_charset_only(self):
        pw = _generate_password(length=200)
        self.assertTrue(all(ch in _PASSWORD_ALPHABET for ch in pw))

    def test_unique(self):
        passwords = {_generate_password() for _ in range(50)}
        self.assertEqual(len(passwords), 50)


class MurmurPasswordHashTest(TestCase):
    def test_round_trip(self):
        record = build_murmur_password_record('fleetpass123')
        self.assertEqual(record['hashfn'], MURMUR_PBKDF2_SHA384)
        self.assertTrue(record['pw_salt'])
        self.assertTrue(record['kdf_iterations'] >= 1000)
        self.assertTrue(
            verify_murmur_password(
                'fleetpass123',
                pwhash=record['pwhash'],
                hashfn=record['hashfn'],
                pw_salt=record['pw_salt'],
                kdf_iterations=record['kdf_iterations'],
            )
        )
        self.assertFalse(
            verify_murmur_password(
                'wrongpass',
                pwhash=record['pwhash'],
                hashfn=record['hashfn'],
                pw_salt=record['pw_salt'],
                kdf_iterations=record['kdf_iterations'],
            )
        )


class GetMumbleUsernameTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', password='pass')

    def test_with_main_character(self):
        _make_char(self.user)
        self.assertEqual(_get_mumble_username(self.user), 'Test_Pilot')

    def test_without_main_character(self):
        self.assertEqual(_get_mumble_username(self.user), 'testuser')

    def test_spaces_replaced(self):
        _make_char(self.user, character_id=99999, character_name='A B C')
        self.assertEqual(_get_mumble_username(self.user), 'A_B_C')


class ComputeGroupsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', password='pass')
        self.char = _make_char(
            self.user,
            corporation_name='Test Corp',
            alliance_name='Test Alliance',
        )

    def test_includes_alliance_and_corp(self):
        groups = _compute_groups(self.user)
        self.assertIn('Test_Alliance', groups)
        self.assertIn('Test_Corp', groups)

    def test_includes_approved_group_memberships(self):
        g = Group.objects.create(name='Fleet Ops')
        GroupMembership.objects.create(user=self.user, group=g, status='approved')
        groups = _compute_groups(self.user)
        self.assertIn('Fleet_Ops', groups)

    def test_excludes_pending_group_memberships(self):
        g = Group.objects.create(name='Pending Group')
        GroupMembership.objects.create(user=self.user, group=g, status='pending')
        groups = _compute_groups(self.user)
        self.assertNotIn('Pending_Group', groups)

    def test_no_alliance(self):
        self.char.alliance_name = None
        self.char.save()
        groups = _compute_groups(self.user)
        self.assertNotIn('None', groups)
        self.assertIn('Test_Corp', groups)

    def test_comma_separated(self):
        groups = _compute_groups(self.user)
        parts = groups.split(',')
        self.assertEqual(parts, ['Test_Alliance', 'Test_Corp'])


# ── Display name ────────────────────────────────────────────────────

class ComputeDisplayNameTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', password='pass')

    def _mock_ticker(self, alliance_ticker=None, corp_ticker=None):
        """Return a side_effect function for _get_ticker that returns controlled values."""
        def side_effect(endpoint, label):
            if 'alliances' in endpoint and alliance_ticker is not None:
                return alliance_ticker
            if 'corporations' in endpoint and corp_ticker is not None:
                return corp_ticker
            return ''
        return side_effect

    @patch('fg.views._get_ticker')
    def test_alliance_and_corp_tickers(self, mock_get_ticker):
        _make_char(self.user, alliance_id=99000001, corporation_id=98000001)
        mock_get_ticker.side_effect = self._mock_ticker('ALLY', 'CORP')
        result = _compute_display_name(self.user)
        self.assertEqual(result, '[ALLY CORP] Test Pilot')

    @patch('fg.views._get_ticker')
    def test_alliance_only(self, mock_get_ticker):
        _make_char(self.user, alliance_id=99000001, corporation_id=98000001)
        mock_get_ticker.side_effect = self._mock_ticker('ALLY', '')
        result = _compute_display_name(self.user)
        self.assertEqual(result, '[ALLY] Test Pilot')

    @patch('fg.views._get_ticker')
    def test_corp_only(self, mock_get_ticker):
        _make_char(self.user, corporation_id=98000001)
        mock_get_ticker.side_effect = self._mock_ticker(None, 'CORP')
        result = _compute_display_name(self.user)
        self.assertEqual(result, '[CORP] Test Pilot')

    @patch('fg.views._get_ticker')
    def test_no_tickers(self, mock_get_ticker):
        _make_char(self.user, alliance_id=99000001, corporation_id=98000001)
        mock_get_ticker.side_effect = self._mock_ticker('', '')
        result = _compute_display_name(self.user)
        self.assertEqual(result, 'Test Pilot')

    def test_no_main_character(self):
        result = _compute_display_name(self.user)
        self.assertEqual(result, 'testuser')


# ── Model ───────────────────────────────────────────────────────────

class MumbleServerModelTest(TestCase):
    def test_str(self):
        server = _make_server(name='Fleet Comms')
        self.assertEqual(str(server), 'Fleet Comms')

    def test_ordering(self):
        s2 = _make_server(name='Bravo', display_order=2)
        s1 = _make_server(name='Alpha', display_order=1, address='a.example.com:64738')
        servers = list(MumbleServer.objects.all())
        self.assertEqual(servers[0], s1)
        self.assertEqual(servers[1], s2)


class MumbleModelTest(TestCase):
    def setUp(self):
        self.server = _make_server()

    def test_str(self):
        user = User.objects.create_user('testuser', password='pass')
        mu = MumbleUser.objects.create(
            user=user, server=self.server, username='Test_Pilot', pwhash='fakehash'
        )
        self.assertEqual(str(mu), 'Test_Pilot')

    def test_defaults(self):
        user = User.objects.create_user('testuser', password='pass')
        mu = MumbleUser.objects.create(
            user=user, server=self.server, username='Test_Pilot', pwhash='fakehash'
        )
        self.assertEqual(mu.hashfn, MURMUR_PBKDF2_SHA384)
        self.assertEqual(mu.pw_salt, '')
        self.assertIsNone(mu.kdf_iterations)
        self.assertIsNone(mu.mumble_userid)
        self.assertEqual(mu.groups, '')
        self.assertIsNone(mu.last_authenticated)
        self.assertIsNone(mu.last_connected)
        self.assertIsNone(mu.last_disconnected)
        self.assertIsNone(mu.last_seen)
        self.assertIsNone(mu.last_spoke)
        self.assertTrue(mu.is_active)
        self.assertIsNotNone(mu.created_at)
        self.assertIsNotNone(mu.updated_at)

    def test_db_table(self):
        self.assertEqual(MumbleUser._meta.db_table, 'mumble_mumbleuser')

    def test_fk_relationship(self):
        user = User.objects.create_user('testuser', password='pass')
        MumbleUser.objects.create(user=user, server=self.server, username='Test_Pilot', pwhash='h')
        self.assertEqual(user.mumble_accounts.first().username, 'Test_Pilot')

    def test_unique_together(self):
        user = User.objects.create_user('testuser', password='pass')
        MumbleUser.objects.create(user=user, server=self.server, username='Test_Pilot', pwhash='h')
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            MumbleUser.objects.create(user=user, server=self.server, username='Other', pwhash='h')

    def test_multi_server_accounts(self):
        user = User.objects.create_user('testuser', password='pass')
        server2 = _make_server(name='Server 2', address='mumble2.example.com:64738')
        MumbleUser.objects.create(user=user, server=self.server, username='Test_Pilot', pwhash='h')
        MumbleUser.objects.create(user=user, server=server2, username='Test_Pilot', pwhash='h')
        self.assertEqual(user.mumble_accounts.count(), 2)

    def test_mumble_userid_unique_per_server(self):
        user1 = User.objects.create_user('testuser1', password='pass')
        user2 = User.objects.create_user('testuser2', password='pass')
        MumbleUser.objects.create(
            user=user1, server=self.server, username='Test_Pilot1', pwhash='h', mumble_userid=17
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            MumbleUser.objects.create(
                user=user2, server=self.server, username='Test_Pilot2', pwhash='h', mumble_userid=17
            )

    def test_manage_admin_permission_exists(self):
        content_type = ContentType.objects.get_for_model(MumbleUser)
        codenames = set(
            Permission.objects.filter(content_type=content_type).values_list('codename', flat=True)
        )
        self.assertIn('manage_mumble_admin', codenames)


class MumbleSessionModelTest(TestCase):
    def setUp(self):
        self.server = _make_server()

    def test_str(self):
        user = User.objects.create_user('pulseuser', password='pass')
        mumble_user = MumbleUser.objects.create(
            user=user,
            server=self.server,
            username='Pulse_User',
            pwhash='h',
        )
        session = MumbleSession.objects.create(
            server=self.server,
            mumble_user=mumble_user,
            session_id=91,
            username='Pulse_User',
            connected_at=timezone.now(),
            last_seen=timezone.now(),
            last_state=timezone.now(),
        )
        self.assertEqual(str(session), 'Test Server:Pulse_User#91')

    def test_unique_active_session(self):
        user = User.objects.create_user('pulseuser', password='pass')
        mumble_user = MumbleUser.objects.create(
            user=user,
            server=self.server,
            username='Pulse_User',
            pwhash='h',
        )
        MumbleSession.objects.create(
            server=self.server,
            mumble_user=mumble_user,
            session_id=91,
            username='Pulse_User',
            connected_at=timezone.now(),
            last_seen=timezone.now(),
            last_state=timezone.now(),
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            MumbleSession.objects.create(
                server=self.server,
                mumble_user=mumble_user,
                session_id=91,
                username='Pulse_User',
                connected_at=timezone.now(),
                last_seen=timezone.now(),
                last_state=timezone.now(),
            )

    def test_custom_permissions_exist(self):
        content_type = ContentType.objects.get_for_model(MumbleSession)
        codenames = set(
            Permission.objects.filter(content_type=content_type).values_list('codename', flat=True)
        )
        self.assertIn('view_mumble_presence', codenames)
        self.assertIn('view_mumble_presence_history', codenames)


class ControlClientAuthTest(TestCase):
    @override_settings(MUMBLE_CONTROL_PSK='primary-control-secret')
    @patch('fg.pilot.control.urlopen')
    def test_post_json_sends_control_psk_header(self, mock_urlopen):
        mock_urlopen.return_value = _JsonResponseStub({'status': 'completed'})

        _post_json('/v1/test', {'pkid': 1}, requested_by='tester')

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.get_header('X-mumble-control-psk'), 'primary-control-secret')

    @override_settings(MUMBLE_CONTROL_PSK='', MUMBLE_CONTROL_SHARED_SECRET='fallback-control-secret')
    @patch('fg.pilot.control.urlopen')
    def test_post_json_uses_shared_secret_fallback_header(self, mock_urlopen):
        mock_urlopen.return_value = _JsonResponseStub({'status': 'completed'})

        _post_json('/v1/test', {'pkid': 1}, requested_by='tester')

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.get_header('X-mumble-control-psk'), 'fallback-control-secret')


class LiveAdminSyncTest(TestCase):
    def setUp(self):
        self.server = _make_server()
        self.user = User.objects.create_user('pulseuser', password='pass')
        self.mu = MumbleUser.objects.create(
            user=self.user,
            server=self.server,
            username='Pulse_User',
            pwhash='h',
            is_mumble_admin=True,
        )
        observed_at = timezone.now()
        for session_id in (17, 18):
            MumbleSession.objects.create(
                server=self.server,
                mumble_user=self.mu,
                session_id=session_id,
                username='Pulse_User',
                connected_at=observed_at,
                last_seen=observed_at,
                last_state=observed_at,
            )

    @patch('fg.pilot.control._post_json')
    def test_grant_updates_all_active_sessions(self, mock_post_json):
        mock_post_json.return_value = {'synced_sessions': 2, 'status': 'completed'}

        synced_sessions = sync_live_admin_membership(self.mu)

        self.assertEqual(synced_sessions, 2)
        mock_post_json.assert_called_once()
        path, payload = mock_post_json.call_args.args
        self.assertEqual(path, '/v1/admin-membership/sync')
        self.assertTrue(payload['admin'])
        self.assertEqual(payload['server_name'], self.server.name)
        self.assertEqual(set(payload['session_ids']), {17, 18})

    @patch('fg.pilot.control._post_json')
    def test_revoke_updates_all_active_sessions(self, mock_post_json):
        mock_post_json.return_value = {'synced_sessions': 2, 'status': 'completed'}
        self.mu.is_mumble_admin = False

        synced_sessions = sync_live_admin_membership(self.mu)

        self.assertEqual(synced_sessions, 2)
        path, payload = mock_post_json.call_args.args
        self.assertEqual(path, '/v1/admin-membership/sync')
        self.assertFalse(payload['admin'])
        self.assertEqual(set(payload['session_ids']), {17, 18})

    @patch('fg.pilot.control._post_json')
    def test_no_active_sessions_skips_control(self, mock_post_json):
        MumbleSession.objects.filter(mumble_user=self.mu).update(is_active=False)

        synced_sessions = sync_live_admin_membership(self.mu)
        self.assertEqual(synced_sessions, 0)
        mock_post_json.assert_not_called()


# ── Views ───────────────────────────────────────────────────────────

@override_settings(**_NO_REDIS)
class ActivateViewTest(TestCase):
    def setUp(self):
        self.user = _make_member()
        _make_char(self.user)
        self.server = _make_server()
        self.client.force_login(self.user)
        self.sync_patcher = patch('fg.views._sync_remote_registration', return_value=501)
        self.sync_patcher.start()
        self.addCleanup(self.sync_patcher.stop)

    def test_get_not_allowed(self):
        resp = self.client.get(reverse('mumble:activate', args=[self.server.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_activate_creates_mumble_user(self):
        resp = self.client.post(reverse('mumble:activate', args=[self.server.pk]))
        self.assertEqual(resp.status_code, 302)
        mu = MumbleUser.objects.get(user=self.user, server=self.server)
        self.assertEqual(mu.username, 'Test_Pilot')
        self.assertEqual(mu.mumble_userid, 501)

    def test_activate_sets_session_password(self):
        self.client.post(reverse('mumble:activate', args=[self.server.pk]))
        session = self.client.session
        key = f'mumble_temp_password_{self.server.pk}'
        self.assertIn(key, session)
        pw = session[key]
        self.assertEqual(len(pw), 16)

    def test_activate_twice_no_duplicate(self):
        self.client.post(reverse('mumble:activate', args=[self.server.pk]))
        self.client.post(reverse('mumble:activate', args=[self.server.pk]), follow=True)
        self.assertEqual(MumbleUser.objects.filter(user=self.user, server=self.server).count(), 1)

    def test_activate_requires_login(self):
        self.client.logout()
        resp = self.client.post(reverse('mumble:activate', args=[self.server.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_activate_on_two_servers(self):
        server2 = _make_server(name='Server 2', address='mumble2.example.com:64738')
        self.client.post(reverse('mumble:activate', args=[self.server.pk]))
        self.client.post(reverse('mumble:activate', args=[server2.pk]))
        self.assertEqual(MumbleUser.objects.filter(user=self.user).count(), 2)


@override_settings(**_NO_REDIS)
class ResetPasswordViewTest(TestCase):
    def setUp(self):
        self.user = _make_member()
        self.server = _make_server()
        self.client.force_login(self.user)
        self.sync_patcher = patch('fg.views._sync_password', return_value=('generated-pass', 601))
        self.sync_patcher.start()
        self.addCleanup(self.sync_patcher.stop)
        self.mu = MumbleUser.objects.create(
            user=self.user,
            server=self.server,
            username='Test_Pilot',
            pwhash='oldhash',
            hashfn=LEGACY_BCRYPT_SHA256,
        )

    def test_reset_updates_userid(self):
        self.client.post(reverse('mumble:reset_password', args=[self.server.pk]))
        self.mu.refresh_from_db()
        self.assertEqual(self.mu.mumble_userid, 601)

    def test_reset_sets_session_password(self):
        self.client.post(reverse('mumble:reset_password', args=[self.server.pk]))
        session = self.client.session
        key = f'mumble_temp_password_{self.server.pk}'
        self.assertIn(key, session)

    def test_reset_no_account(self):
        self.mu.delete()
        resp = self.client.post(reverse('mumble:reset_password', args=[self.server.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)


@override_settings(**_NO_REDIS)
class SetPasswordViewTest(TestCase):
    def setUp(self):
        self.user = _make_member()
        self.server = _make_server()
        self.client.force_login(self.user)
        self.sync_patcher = patch('fg.views._sync_password', return_value=('mysecurepassword', 701))
        self.sync_patcher.start()
        self.addCleanup(self.sync_patcher.stop)
        self.mu = MumbleUser.objects.create(
            user=self.user,
            server=self.server,
            username='Test_Pilot',
            pwhash='oldhash',
            hashfn=LEGACY_BCRYPT_SHA256,
        )

    def test_set_valid_password(self):
        resp = self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'mumble_password': 'mysecurepassword'},
        )
        self.assertEqual(resp.status_code, 302)
        self.mu.refresh_from_db()
        self.assertEqual(self.mu.mumble_userid, 701)

    def test_set_short_password_rejected(self):
        self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'mumble_password': 'short'},
            follow=True,
        )
        self.mu.refresh_from_db()
        self.assertEqual(self.mu.pwhash, 'oldhash')

    def test_set_restricted_characters_rejected(self):
        self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'mumble_password': 'bad\\pass1'},
            follow=True,
        )
        self.mu.refresh_from_db()
        self.assertEqual(self.mu.pwhash, 'oldhash')
        self.assertIsNone(self.mu.mumble_userid)

    def test_set_password_no_account(self):
        self.mu.delete()
        resp = self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'mumble_password': 'longenoughpw'},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)

    def test_password_verifies(self):
        self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'mumble_password': 'myfleetpassword'},
        )
        self.mu.refresh_from_db()
        self.assertEqual(self.mu.pwhash, 'oldhash')


@override_settings(**_NO_REDIS)
class DeactivateViewTest(TestCase):
    def setUp(self):
        self.user = _make_member()
        self.server = _make_server()
        self.client.force_login(self.user)
        self.unregister_patcher = patch('fg.views._unregister_remote_registration', return_value=True)
        self.unregister_patcher.start()
        self.addCleanup(self.unregister_patcher.stop)

    def test_deactivate_deletes_account(self):
        MumbleUser.objects.create(
            user=self.user, server=self.server, username='Test_Pilot', pwhash='h'
        )
        resp = self.client.post(reverse('mumble:deactivate', args=[self.server.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(MumbleUser.objects.filter(user=self.user, server=self.server).exists())

    def test_deactivate_no_account(self):
        resp = self.client.post(reverse('mumble:deactivate', args=[self.server.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)


@override_settings(**_NO_REDIS)
class ToggleAdminViewTest(TestCase):
    def setUp(self):
        self.manager = _make_regular_member('manager')
        _make_char(self.manager)
        permission = Permission.objects.get(codename='manage_mumble_admin')
        self.manager.user_permissions.add(permission)
        self.target_user = User.objects.create_user('target', password='pass')
        self.server = _make_server()
        self.client.force_login(self.manager)
        self.mu = MumbleUser.objects.create(
            user=self.target_user,
            server=self.server,
            username='Target_User',
            pwhash='h',
        )

    @patch('fg.views._sync_live_admin_membership', return_value=2)
    def test_toggle_admin_updates_live_sessions_immediately(self, mock_sync_live_admin_membership):
        response = self.client.post(
            reverse('mumble:toggle_admin', args=[self.mu.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.mu.refresh_from_db()
        self.assertTrue(self.mu.is_mumble_admin)
        self.assertIn('admin', [group for group in self.mu.groups.split(',') if group])
        self.assertEqual(mock_sync_live_admin_membership.call_args[0][0].pk, self.mu.pk)
        messages = [message.message for message in response.context['messages']]
        self.assertIn('Mumble admin granted for Target_User.', messages)
        self.assertIn('Updated 2 active Murmur session(s) immediately.', messages)

    @patch('fg.views._sync_live_admin_membership', side_effect=MumbleSyncError('boom'))
    def test_toggle_admin_keeps_cube_state_when_live_sync_fails(self, mock_sync_live_admin_membership):
        response = self.client.post(
            reverse('mumble:toggle_admin', args=[self.mu.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.mu.refresh_from_db()
        self.assertTrue(self.mu.is_mumble_admin)
        self.assertIn('admin', [group for group in self.mu.groups.split(',') if group])
        self.assertEqual(mock_sync_live_admin_membership.call_args[0][0].pk, self.mu.pk)
        messages = [message.message for message in response.context['messages']]
        self.assertIn('Mumble admin granted for Target_User.', messages)
        self.assertIn(
            'Admin status was updated locally, but live Murmur session sync failed. Connected users may need to reconnect.',
            messages,
        )

    def test_toggle_admin_forbidden_for_plain_staff_viewer(self):
        plain_staff = _make_member('plainstaff')
        self.client.force_login(plain_staff)

        response = self.client.post(reverse('mumble:toggle_admin', args=[self.mu.pk]))

        self.assertEqual(response.status_code, 403)
        self.mu.refresh_from_db()
        self.assertFalse(self.mu.is_mumble_admin)


@override_settings(**_NO_REDIS)
class MumbleManagePermissionsViewTest(TestCase):
    def setUp(self):
        self.server = _make_server()
        self.target_user = _make_regular_member('targetuser')
        self.mu = MumbleUser.objects.create(
            user=self.target_user,
            server=self.server,
            username='Target_User',
            pwhash='h',
        )

    def test_plain_staff_can_view_but_not_see_action_column(self):
        viewer = _make_member('staffviewer')
        self.client.force_login(viewer)

        response = self.client.get(reverse('mumble:manage'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin')
        self.assertNotContains(response, 'Action')
        self.assertNotContains(response, 'Grant Admin')

    def test_superuser_can_view_action_column(self):
        viewer = User.objects.create_superuser('root', 'root@example.com', 'pass')
        UserProfile.objects.create(user=viewer, is_member=True)
        self.client.force_login(viewer)

        response = self.client.get(reverse('mumble:manage'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Action')
        self.assertContains(response, 'Grant Admin')


@override_settings(**_NO_REDIS)
class MumbleManagePresenceColumnsViewTest(TestCase):
    def setUp(self):
        self.viewer = _make_member('presenceviewer')
        self.client.force_login(self.viewer)
        self.server = _make_server()
        self.target_user = _make_regular_member('cubepilot')
        observed_at = timezone.now()
        self.mu = MumbleUser.objects.create(
            user=self.target_user,
            server=self.server,
            username='Translated_Pilot',
            display_name='Translated Pilot',
            pwhash='h',
            mumble_userid=904,
            last_authenticated=observed_at - timedelta(minutes=10),
            last_connected=observed_at - timedelta(minutes=9),
            last_seen=observed_at - timedelta(minutes=1),
            last_spoke=observed_at - timedelta(seconds=20),
        )
        MumbleSession.objects.create(
            server=self.server,
            mumble_user=self.mu,
            session_id=41,
            mumble_userid=904,
            username='Translated_Pilot',
            channel_id=7,
            priority_speaker=True,
            connected_at=observed_at - timedelta(minutes=9),
            last_seen=observed_at - timedelta(minutes=1),
            last_state=observed_at - timedelta(minutes=1),
            last_spoke=observed_at - timedelta(seconds=20),
        )
        MumbleSession.objects.create(
            server=self.server,
            mumble_user=self.mu,
            session_id=42,
            mumble_userid=904,
            username='Translated_Pilot',
            channel_id=8,
            priority_speaker=False,
            connected_at=observed_at - timedelta(minutes=8),
            last_seen=observed_at - timedelta(minutes=1),
            last_state=observed_at - timedelta(minutes=1),
            last_spoke=observed_at - timedelta(seconds=45),
        )

    def test_manage_view_exposes_presence_columns(self):
        response = self.client.get(reverse('mumble:manage'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pilot Account')
        self.assertContains(response, 'Murmur ID')
        self.assertContains(response, 'Last Auth')
        self.assertContains(response, 'Last Connected')
        self.assertContains(response, 'Last Seen')
        self.assertContains(response, 'Last Spoke')
        self.assertContains(response, 'Active Sessions')
        self.assertContains(response, 'Priority Speaker')
        self.assertContains(response, f'cubepilot (#{self.target_user.pk})')

        mumble_users = list(response.context['mumble_users'])
        self.assertEqual(len(mumble_users), 1)
        self.assertEqual(mumble_users[0].active_session_count, 2)
        self.assertTrue(mumble_users[0].has_priority_speaker)
        self.assertContains(response, 'YES', count=1)

    def test_staff_alliance_leader_can_view_action_column(self):
        viewer = _make_member('leaderstaff')
        _grant_alliance_leader_group(viewer)
        self.client.force_login(viewer)

        response = self.client.get(reverse('mumble:manage'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Action')
        self.assertContains(response, 'Grant Admin')

    def test_perm_only_user_can_view_action_column(self):
        viewer = _make_regular_member('permviewer')
        _make_char(viewer)
        permission = Permission.objects.get(codename='manage_mumble_admin')
        viewer.user_permissions.add(permission)
        self.client.force_login(viewer)

        response = self.client.get(reverse('mumble:manage'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Action')
        self.assertContains(response, 'Grant Admin')


# ── Mumble group sync helpers ───────────────────────────────────────

class TasksTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', password='pass')
        _make_char(
            self.user,
            corporation_name='Corp A',
            alliance_name='Alliance A',
        )
        self.server = _make_server()
        self.mu = MumbleUser.objects.create(
            user=self.user, server=self.server, username='Test_Pilot', pwhash='h', groups=''
        )

    def test_update_mumble_groups(self):
        from fg.tasks import update_mumble_groups
        update_mumble_groups(self.mu.pk)
        self.mu.refresh_from_db()
        self.assertIn('Alliance_A', self.mu.groups)
        self.assertIn('Corp_A', self.mu.groups)

    def test_update_mumble_groups_nonexistent_user(self):
        from fg.tasks import update_mumble_groups
        update_mumble_groups(99999)  # should not raise

    def test_update_all_mumble_groups(self):
        from fg.tasks import update_all_mumble_groups
        with patch('fg.tasks.update_mumble_groups') as mock_update:
            mock_update.side_effect = lambda *_args, **_kwargs: None
            update_all_mumble_groups()
            mock_update.assert_called_once_with(self.mu.pk)

    def test_update_skips_inactive(self):
        self.mu.is_active = False
        self.mu.save()
        from fg.tasks import update_mumble_groups
        update_mumble_groups(self.mu.pk)
        self.mu.refresh_from_db()
        self.assertEqual(self.mu.groups, '')


# ── Profile integration ────────────────────────────────────────────

@override_settings(**_NO_REDIS)
class ProfileContextTest(TestCase):
    def setUp(self):
        self.user = _make_member()
        self.server = _make_server()
        self.client.force_login(self.user)

    def test_profile_has_mumble_context(self):
        resp = self.client.get(reverse('profile'))
        self.assertIn('mumble_server_data', resp.context)
        data = resp.context['mumble_server_data']
        self.assertEqual(len(data), 1)
        self.assertIsNone(data[0]['account'])

    def test_profile_shows_activate_button(self):
        resp = self.client.get(reverse('profile'))
        self.assertContains(resp, 'Get Mumble Credentials')

    def test_profile_shows_mumble_username(self):
        MumbleUser.objects.create(
            user=self.user, server=self.server, username='Test_User', pwhash='h'
        )
        resp = self.client.get(reverse('profile'))
        self.assertContains(resp, 'Test_User')
        self.assertNotContains(resp, 'Get Mumble Credentials')

    def test_temp_password_shown_once(self):
        session = self.client.session
        session[f'mumble_temp_password_{self.server.pk}'] = 'abc123secret'
        session.save()
        resp = self.client.get(reverse('profile'))
        self.assertContains(resp, 'abc123secret')
        # Second load should not have it
        resp2 = self.client.get(reverse('profile'))
        self.assertNotContains(resp2, 'abc123secret')

    def test_multiple_servers_shown(self):
        server2 = _make_server(name='Server 2', address='mumble2.example.com:64738')
        resp = self.client.get(reverse('profile'))
        data = resp.context['mumble_server_data']
        self.assertEqual(len(data), 2)
        self.assertContains(resp, 'Test Server')
        self.assertContains(resp, 'Server 2')
