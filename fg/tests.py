import json
from datetime import timedelta
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

try:
    from accounts.models import EveAllianceInfo, EveCharacter, EveCorporationInfo, Group, GroupMembership, UserProfile
except ImportError as exc:  # pragma: no cover - environment-specific host model availability
    raise unittest.SkipTest(f'Host model set unavailable for fg.tests in this environment: {exc}') from exc
from fg.panels import build_profile_panels, get_profile_panel_provider
from fg.cube_extension import get_i18n_urlpatterns, get_profile_panels as get_cube_profile_panels
from fg.integration import CubeMurmurIntegration
from fg.pilot_snapshot import _canonical_account_username, build_pilot_snapshot, serialize_pilot_snapshot
from modules.corporation.models import CorporationSettings
from fg.control import BgControlClient, MurmurSyncError, _post_json
from fg.models import (
    AccessRule,
    ENTITY_TYPE_ALLIANCE,
    ENTITY_TYPE_PILOT,
    MumbleUser,
    MurmurModelLookupError,
    PilotSnapshotHash,
)
from fg.runtime import BgRuntimeService, RuntimeRegistration, RuntimeServer
from fg.views import (
    _get_mumble_username,
    _compute_display_name,
    _compute_groups,
    profile_password_pilot_choices,
)

# Override cache and session backends so tests don't require Redis
_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)

_RUN_HOST_MURMUR_TESTS = os.environ.get('FG_RUN_HOST_MURMUR_TESTS', '0') in {
    '1', 'true', 'True', 'yes', 'Yes', 'on', 'On',
}


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
    if not _RUN_HOST_MURMUR_TESTS:
        raise unittest.SkipTest('Host Murmur test models are disabled in this environment.')
    from fg.models import resolve_murmur_model
    try:
        MumbleServer = resolve_murmur_model('MumbleServer')
    except MurmurModelLookupError:
        raise unittest.SkipTest('Host Murmur test models are unavailable in this environment.')
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


def _grant_profile_panel_access(
    user,
    *,
    character_id,
    character_name,
    corporation_id,
    corporation_name,
    alliance_id,
    alliance_name,
):
    _make_char(
        user,
        character_id=character_id,
        character_name=character_name,
        corporation_id=corporation_id,
        corporation_name=corporation_name,
        alliance_id=alliance_id,
        alliance_name=alliance_name,
    )
    AccessRule.objects.create(
        entity_id=alliance_id,
        entity_type=ENTITY_TYPE_ALLIANCE,
        deny=False,
    )


class GetMumbleUsernameTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', password='pass')

    def test_with_main_character(self):
        _make_char(self.user)
        self.assertEqual(_get_mumble_username(self.user), 'testuser')

    def test_without_main_character(self):
        self.assertEqual(_get_mumble_username(self.user), 'testuser')

    def test_spaces_replaced(self):
        self.user.username = 'A B C'
        self.user.save(update_fields=['username'])
        _make_char(self.user, character_id=99999, character_name='Ignored Character')
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

    def _cache_orgs(self, *, alliance_id=None, alliance_ticker='', corporation_id=None, corp_ticker=''):
        if alliance_id:
            EveAllianceInfo.objects.create(
                alliance_id=alliance_id,
                alliance_name='Alliance',
                alliance_ticker=alliance_ticker,
            )
        if corporation_id:
            EveCorporationInfo.objects.create(
                corporation_id=corporation_id,
                corporation_name='Corporation',
                corporation_ticker=corp_ticker,
            )

    def test_alliance_and_corp_tickers(self):
        _make_char(self.user, alliance_id=99000001, corporation_id=98000001)
        self._cache_orgs(alliance_id=99000001, alliance_ticker='ALLY', corporation_id=98000001, corp_ticker='CORP')
        result = _compute_display_name(self.user)
        self.assertEqual(result, '[ALLY CORP] Test Pilot')

    def test_alliance_only(self):
        _make_char(self.user, alliance_id=99000001, corporation_id=98000001)
        self._cache_orgs(alliance_id=99000001, alliance_ticker='ALLY')
        result = _compute_display_name(self.user)
        self.assertEqual(result, '[ALLY ????] Test Pilot')

    def test_corp_only(self):
        _make_char(self.user, corporation_id=98000001)
        self._cache_orgs(corporation_id=98000001, corp_ticker='CORP')
        result = _compute_display_name(self.user)
        self.assertEqual(result, '[CORP] Test Pilot')

    def test_unknown_tickers_use_placeholder(self):
        _make_char(self.user, alliance_id=99000001, corporation_id=98000001)
        result = _compute_display_name(self.user)
        self.assertEqual(result, '[???? ????] Test Pilot')

    def test_no_main_character(self):
        result = _compute_display_name(self.user)
        self.assertEqual(result, 'testuser')


class PilotSnapshotExportTest(TestCase):
    def test_snapshot_username_canonicalization(self):
        self.assertEqual(_canonical_account_username('Leo Rises'), 'leorises')
        self.assertEqual(_canonical_account_username('cube_login_name'), 'cube_login_name')
        self.assertEqual(_canonical_account_username('', fallback=''), '')
        self.assertEqual(_canonical_account_username('', fallback='', pkid=42), 'pkid_42')

    def test_snapshot_includes_account_username(self):
        user = _make_member('cube_login_name')
        _make_char(user, character_id=777001, character_name='Snapshot Main')

        snapshot = build_pilot_snapshot().as_dict()
        self.assertEqual(len(snapshot['accounts']), 1)
        self.assertEqual(snapshot['accounts'][0]['pkid'], user.pk)
        self.assertEqual(snapshot['accounts'][0]['account_username'], 'cube_login_name')
        self.assertEqual(len(snapshot['accounts'][0]['pilot_data_hash']), 32)

    def test_serialize_snapshot_caches_hash_by_pkid(self):
        user = _make_member('hash_cache_user')
        _make_char(user, character_id=777002, character_name='Hash Cache Main')

        snapshot = serialize_pilot_snapshot()
        account_payload = snapshot['accounts'][0]
        cache_row = PilotSnapshotHash.objects.get(pkid=user.pk)

        self.assertEqual(cache_row.pilot_data_hash, account_payload['pilot_data_hash'])


# ── Model ───────────────────────────────────────────────────────────

class MumbleModelTest(TestCase):
    def setUp(self):
        self.server = _make_server()

    def test_str(self):
        user = User.objects.create_user('testuser', password='pass')
        mu = MumbleUser.objects.create(
            user=user, server=self.server, username='Test_Pilot', pwhash=''
        )
        self.assertEqual(str(mu), 'Test_Pilot')

    def test_defaults(self):
        user = User.objects.create_user('testuser', password='pass')
        mu = MumbleUser.objects.create(
            user=user, server=self.server, username='Test_Pilot', pwhash=''
        )
        self.assertEqual(mu.hashfn, 'murmur-pbkdf2-sha384')
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
        self.assertEqual(MumbleUser._meta.db_table, 'mumble_user')

    def test_fk_relationship(self):
        user = User.objects.create_user('testuser', password='pass')
        MumbleUser.objects.create(user=user, server=self.server, username='Test_Pilot', pwhash='h')
        self.assertEqual(user.murmur_registrations.first().username, 'Test_Pilot')

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
        self.assertEqual(user.murmur_registrations.count(), 2)

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


class ControlClientAuthTest(TestCase):
    @override_settings(FGBG_PSK='primary-control-secret')
    @patch('fg.control.urlopen')
    def test_post_json_sends_fgbg_psk_headers(self, mock_urlopen):
        mock_urlopen.return_value = _JsonResponseStub({'status': 'completed'})

        _post_json('/v1/test', {'pkid': 1}, requested_by='tester')

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.get_header('X-fgbg-psk'), 'primary-control-secret')
        self.assertEqual(request.get_header('X-murmur-control-psk'), 'primary-control-secret')

    @override_settings(
        FGBG_PSK='',
        MURMUR_CONTROL_PSK='',
        MURMUR_CONTROL_SHARED_SECRET='fallback-control-secret',
    )
    @patch('fg.control.urlopen')
    def test_post_json_uses_legacy_shared_secret_fallback_header(self, mock_urlopen):
        mock_urlopen.return_value = _JsonResponseStub({'status': 'completed'})

        _post_json('/v1/test', {'pkid': 1}, requested_by='tester')

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.get_header('X-fgbg-psk'), 'fallback-control-secret')
        self.assertEqual(request.get_header('X-murmur-control-psk'), 'fallback-control-secret')


class LiveAdminSyncTest(TestCase):
    def setUp(self):
        self.server = _make_server()
        self.user = User.objects.create_user('pulseuser', password='pass')
        self.control_client = BgControlClient()
        self.mu = MumbleUser.objects.create(
            user=self.user,
            server=self.server,
            username='Pulse_User',
            pwhash='h',
            is_mumble_admin=True,
        )

    @patch('fg.control._post_json')
    def test_grant_posts_contract_payload(self, mock_post_json):
        mock_post_json.return_value = {'synced_sessions': 2, 'status': 'completed'}

        synced_sessions = self.control_client.sync_live_admin_membership(self.mu)

        self.assertEqual(synced_sessions, 2)
        mock_post_json.assert_called_once()
        path, payload = mock_post_json.call_args.args
        self.assertEqual(path, '/v1/admin-membership/sync')
        self.assertTrue(payload['admin'])
        self.assertEqual(payload['groups'], '')
        self.assertEqual(payload['server_name'], self.server.name)
        self.assertEqual(payload['pkid'], self.mu.user_id)
        self.assertNotIn('session_ids', payload)

    @patch('fg.control._post_json')
    def test_revoke_posts_contract_payload(self, mock_post_json):
        mock_post_json.return_value = {'synced_sessions': 2, 'status': 'completed'}
        self.mu.is_mumble_admin = False

        synced_sessions = self.control_client.sync_live_admin_membership(self.mu)

        self.assertEqual(synced_sessions, 2)
        path, payload = mock_post_json.call_args.args
        self.assertEqual(path, '/v1/admin-membership/sync')
        self.assertFalse(payload['admin'])
        self.assertEqual(payload['groups'], '')
        self.assertNotIn('session_ids', payload)

    @patch('fg.control._post_json')
    def test_explicit_session_ids_are_forwarded(self, mock_post_json):
        mock_post_json.return_value = {'synced_sessions': 2, 'status': 'completed'}
        self.mu.groups = 'alpha,admin'

        synced_sessions = self.control_client.sync_live_admin_membership(self.mu, session_ids=[17, 18])

        self.assertEqual(synced_sessions, 2)
        _, payload = mock_post_json.call_args.args
        self.assertEqual(payload['groups'], 'alpha,admin')
        self.assertEqual(payload['session_ids'], [17, 18])

    @patch('fg.control._post_json')
    def test_invalid_session_id_raises(self, mock_post_json):
        with self.assertRaises(MurmurSyncError):
            self.control_client.sync_live_admin_membership(self.mu, session_ids=['bad'])
        mock_post_json.assert_not_called()

    @patch('fg.control.BgControlClient.probe_murmur_registration')
    @patch('fg.control._post_json')
    def test_probe_fallback_used_when_sync_count_missing(self, mock_post_json, mock_probe):
        mock_post_json.return_value = {'status': 'completed'}
        mock_probe.return_value = {'active_session_count': 4}

        synced_sessions = self.control_client.sync_live_admin_membership(self.mu)

        self.assertEqual(synced_sessions, 4)


class ContractMetadataSyncTest(TestCase):
    def setUp(self):
        self.server = _make_server()
        self.user = User.objects.create_user('contractpilot', password='pass')
        self.control_client = BgControlClient()
        self.mu = MumbleUser.objects.create(
            user=self.user,
            server=self.server,
            username='Contract_Pilot',
            pwhash='h',
        )

    @patch('fg.control._post_json')
    def test_sync_contract_posts_superuser_payload(self, mock_post_json):
        mock_post_json.return_value = {
            'status': 'completed',
            'evepilot_id': 90000001,
            'corporation_id': 98000001,
            'alliance_id': 99000001,
            'kdf_iterations': 120000,
        }

        payload = self.control_client.sync_registration_contract(
            self.mu,
            evepilot_id='90000001',
            corporation_id=98000001,
            alliance_id=99000001,
            kdf_iterations='120000',
            is_super=True,
        )

        self.assertEqual(payload['evepilot_id'], 90000001)
        self.assertEqual(payload['corporation_id'], 98000001)
        self.assertEqual(payload['alliance_id'], 99000001)
        self.assertEqual(payload['kdf_iterations'], 120000)
        path, sent = mock_post_json.call_args.args
        self.assertEqual(path, '/v1/registrations/contract-sync')
        self.assertEqual(sent['pkid'], self.mu.user_id)
        self.assertEqual(sent['server_name'], self.server.name)
        self.assertTrue(sent['is_super'])

    @patch('fg.control._post_json')
    def test_sync_contract_rejects_non_integer_fields(self, mock_post_json):
        with self.assertRaises(MurmurSyncError):
            self.control_client.sync_registration_contract(self.mu, evepilot_id='not-an-int', is_super=True)
        mock_post_json.assert_not_called()


class AccessRuleSyncClientTest(TestCase):
    def setUp(self):
        self.control_client = BgControlClient()

    @patch('fg.control._post_json')
    def test_sync_access_rules_without_reconcile_only_posts_access_rules(self, mock_post_json):
        mock_post_json.return_value = {'status': 'completed', 'total': 1}

        response = self.control_client.sync_access_rules(
            [
                {
                    'entity_id': 99000001,
                    'entity_type': 'pilot',
                    'deny': False,
                    'acl_admin': True,
                    'note': 'seed',
                    'created_by': 'tester',
                }
            ],
            requested_by='test-user',
            is_super=False,
        )

        self.assertEqual(response, {'status': 'completed', 'total': 1})
        mock_post_json.assert_called_once()
        path, payload = mock_post_json.call_args.args
        self.assertEqual(path, '/v1/access-rules/sync')
        self.assertFalse(payload['is_super'])
        self.assertEqual(payload['rules'][0]['entity_id'], 99000001)
        self.assertEqual(payload['rules'][0]['entity_type'], 'pilot')
        self.assertTrue(payload['rules'][0]['acl_admin'])

    def test_sync_access_rules_rejects_acl_admin_for_non_pilot(self):
        with self.assertRaises(MurmurSyncError):
            self.control_client.sync_access_rules(
                [{'entity_id': 98000001, 'entity_type': 'corporation', 'deny': False, 'acl_admin': True}],
                requested_by='test-user',
                is_super=True,
            )

    @patch('fg.control._post_json')
    def test_sync_access_rules_with_reconcile_posts_provision_payload(self, mock_post_json):
        responses = [
            {'status': 'completed', 'total': 1, 'created': 0, 'updated': 1, 'deleted': 0},
            {'status': 'completed', 'murmur_reconcile': [{'server': 'main', 'action': 'noop'}]},
        ]

        def side_effect(*args, **kwargs):
            return responses.pop(0)

        mock_post_json.side_effect = side_effect

        response = self.control_client.sync_access_rules(
            [{'entity_id': 99000001, 'entity_type': 'pilot', 'deny': False, 'note': 'seed', 'created_by': 'tester'}],
            requested_by='sync-user',
            is_super=True,
            reconcile=True,
            server_id=7,
            dry_run=True,
        )

        self.assertEqual(response['status'], 'completed')
        self.assertIn('provision', response)
        self.assertEqual(response['provision']['status'], 'completed')
        self.assertEqual(mock_post_json.call_count, 2)
        first_path, first_payload = mock_post_json.call_args_list[0].args
        second_path, second_payload = mock_post_json.call_args_list[1].args
        self.assertEqual(first_path, '/v1/access-rules/sync')
        self.assertEqual(first_payload['rules'][0]['entity_id'], 99000001)
        self.assertEqual(second_path, '/v1/provision')
        self.assertTrue(second_payload['reconcile'])
        self.assertTrue(second_payload['dry_run'])
        self.assertEqual(second_payload['server_id'], 7)

    @patch('fg.control._post_json')
    def test_sync_access_rules_with_snapshot_posts_snapshot_before_provision(self, mock_post_json):
        responses = [
            {'status': 'completed', 'total': 1, 'created': 0, 'updated': 1, 'deleted': 0},
            {'status': 'completed', 'changed': True, 'account_count': 1, 'character_count': 2},
            {'status': 'completed', 'murmur_reconcile': [{'server': 'main', 'action': 'noop'}]},
        ]

        def side_effect(*args, **kwargs):
            return responses.pop(0)

        mock_post_json.side_effect = side_effect

        response = self.control_client.sync_access_rules(
            [{'entity_id': 99000001, 'entity_type': 'pilot', 'deny': False, 'note': 'seed', 'created_by': 'tester'}],
            requested_by='sync-user',
            is_super=True,
            pilot_snapshot={
                'generated_at': '2026-03-20T00:00:00Z',
                'accounts': [
                    {
                        'pkid': 42,
                        'characters': [
                            {
                                'character_id': 9001,
                                'character_name': 'Pilot One',
                                'corporation_id': 77,
                                'corporation_name': 'Corp One',
                                'alliance_id': 88,
                                'alliance_name': 'Alliance One',
                                'is_main': True,
                            }
                        ],
                    }
                ],
            },
            reconcile=True,
        )

        self.assertEqual(response['status'], 'completed')
        self.assertIn('pilot_snapshot', response)
        self.assertIn('provision', response)
        self.assertEqual(mock_post_json.call_count, 3)
        first_path, _ = mock_post_json.call_args_list[0].args
        second_path, second_payload = mock_post_json.call_args_list[1].args
        third_path, _ = mock_post_json.call_args_list[2].args
        self.assertEqual(first_path, '/v1/access-rules/sync')
        self.assertEqual(second_path, '/v1/pilot-snapshot/sync')
        self.assertTrue(second_payload['is_super'])
        self.assertEqual(second_payload['accounts'][0]['pkid'], 42)
        self.assertEqual(third_path, '/v1/provision')


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
        key = f'murmur_temp_password_{self.server.pk}'
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
            pwhash='',
        )

    def test_reset_updates_userid(self):
        self.client.post(reverse('mumble:reset_password', args=[self.server.pk]))
        self.mu.refresh_from_db()
        self.assertEqual(self.mu.mumble_userid, 601)

    def test_reset_sets_session_password(self):
        self.client.post(reverse('mumble:reset_password', args=[self.server.pk]))
        session = self.client.session
        key = f'murmur_temp_password_{self.server.pk}'
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
            pwhash='',
        )

    def test_set_valid_password(self):
        resp = self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'murmur_password': 'mysecurepassword'},
        )
        self.assertEqual(resp.status_code, 302)
        self.mu.refresh_from_db()
        self.assertEqual(self.mu.mumble_userid, 701)

    def test_set_short_password_rejected(self):
        self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'murmur_password': 'short'},
            follow=True,
        )
        self.mu.refresh_from_db()
        self.assertEqual(self.mu.pwhash, 'oldhash')

    def test_set_restricted_characters_rejected(self):
        self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'murmur_password': 'bad\\pass1'},
            follow=True,
        )
        self.mu.refresh_from_db()
        self.assertEqual(self.mu.pwhash, 'oldhash')
        self.assertIsNone(self.mu.mumble_userid)

    def test_set_password_no_account(self):
        self.mu.delete()
        resp = self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'murmur_password': 'longenoughpw'},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)

    def test_password_verifies(self):
        self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'murmur_password': 'myfleetpassword'},
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
        self.assertIn('Murmur admin granted for Target_User.', messages)
        self.assertIn('Updated 2 active Murmur session(s) immediately.', messages)

    @patch('fg.views._sync_live_admin_membership', side_effect=MurmurSyncError('boom'))
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
        self.assertIn('Murmur admin granted for Target_User.', messages)
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
class ContractMetadataViewTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser('contractroot', 'root@example.com', 'pass')
        UserProfile.objects.create(user=self.superuser, is_member=True)
        self.target_user = User.objects.create_user('contracttarget', password='pass')
        self.server = _make_server()
        self.mu = MumbleUser.objects.create(
            user=self.target_user,
            server=self.server,
            username='Contract_Target',
            pwhash='h',
        )

    @patch('fg.views._CONTROL_CLIENT.probe_murmur_registration')
    @patch('fg.views._sync_contract_metadata')
    def test_superuser_contract_sync_requires_probe_match(self, mock_sync_contract_metadata, mock_probe):
        self.client.force_login(self.superuser)
        mock_sync_contract_metadata.return_value = {
            'evepilot_id': 90000001,
            'corporation_id': 98000001,
            'alliance_id': 99000001,
            'kdf_iterations': 120000,
        }
        mock_probe.return_value = {
            'evepilot_id': 90000001,
            'corporation_id': 98000001,
            'alliance_id': 99000001,
            'kdf_iterations': 120000,
        }

        response = self.client.post(
            reverse('mumble:sync_contract', args=[self.mu.pk]),
            {
                'evepilot_id': '90000001',
                'corporation_id': '98000001',
                'alliance_id': '99000001',
                'kdf_iterations': '120000',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        mock_sync_contract_metadata.assert_called_once()
        self.assertTrue(mock_sync_contract_metadata.call_args.kwargs['is_super'])
        messages = [message.message for message in response.context['messages']]
        self.assertIn('Contract metadata synchronized for Contract_Target.', messages)

    def test_non_superuser_contract_sync_forbidden(self):
        manager = _make_member('contractstaff')
        self.client.force_login(manager)

        response = self.client.post(
            reverse('mumble:sync_contract', args=[self.mu.pk]),
            {'evepilot_id': '1'},
        )

        self.assertEqual(response.status_code, 403)


@override_settings(**_NO_REDIS, MURMUR_MODEL_APP_LABEL='missing_app_label')
class RuntimeFallbackAccountViewsTest(TestCase):
    def setUp(self):
        self.user = _make_member('runtimepilot')
        _make_char(self.user)
        self.server = RuntimeServer(
            id=77,
            name='Runtime Server',
            address='runtime.example.com:64738',
        )
        self.client.force_login(self.user)

    def _registration(self):
        return RuntimeRegistration(
            user_id=self.user.pk,
            server=self.server,
            username='Test_Pilot',
            display_name='Test Pilot',
            mumble_userid=901,
            groups='corp',
        )

    @patch('fg.views._sync_remote_registration', return_value=812)
    @patch('fg.views.get_runtime_service')
    @patch('fg.views.safe_list_servers')
    def test_activate_uses_runtime_registration_target_when_models_missing(
        self,
        mock_safe_list_servers,
        mock_get_runtime_service,
        mock_sync_remote_registration,
    ):
        mock_safe_list_servers.return_value = [self.server]
        mock_get_runtime_service.return_value = SimpleNamespace(
            registration_for_pilot_server=lambda *_args, **_kwargs: None
        )

        response = self.client.post(reverse('mumble:activate', args=[self.server.pk]))

        self.assertEqual(response.status_code, 302)
        synced_registration = mock_sync_remote_registration.call_args.args[0]
        self.assertIsInstance(synced_registration, RuntimeRegistration)
        self.assertEqual(synced_registration.user_id, self.user.pk)
        self.assertEqual(synced_registration.server_id, self.server.pk)
        self.assertEqual(synced_registration.user, self.user)
        self.assertIn(f'murmur_temp_password_{self.server.pk}', self.client.session)

    @patch('fg.views._sync_password', return_value=('generated-pass', 601))
    @patch('fg.views.get_runtime_service')
    @patch('fg.views.safe_list_servers')
    def test_reset_password_uses_runtime_registration_when_models_missing(
        self,
        mock_safe_list_servers,
        mock_get_runtime_service,
        mock_sync_password,
    ):
        registration = self._registration()
        mock_safe_list_servers.return_value = [self.server]
        mock_get_runtime_service.return_value = SimpleNamespace(
            registration_for_pilot_server=lambda *_args, **_kwargs: registration
        )

        response = self.client.post(reverse('mumble:reset_password', args=[self.server.pk]))

        self.assertEqual(response.status_code, 302)
        synced_registration = mock_sync_password.call_args.args[0]
        self.assertIsInstance(synced_registration, RuntimeRegistration)
        self.assertEqual(synced_registration.user, self.user)
        self.assertEqual(self.client.session[f'murmur_temp_password_{self.server.pk}'], 'generated-pass')

    @patch('fg.views._sync_password', return_value=('longenoughpw', 701))
    @patch('fg.views.get_runtime_service')
    @patch('fg.views.safe_list_servers')
    def test_set_password_uses_runtime_registration_when_models_missing(
        self,
        mock_safe_list_servers,
        mock_get_runtime_service,
        mock_sync_password,
    ):
        registration = self._registration()
        mock_safe_list_servers.return_value = [self.server]
        mock_get_runtime_service.return_value = SimpleNamespace(
            registration_for_pilot_server=lambda *_args, **_kwargs: registration
        )

        response = self.client.post(
            reverse('mumble:set_password', args=[self.server.pk]),
            {'murmur_password': 'longenoughpw'},
        )

        self.assertEqual(response.status_code, 302)
        synced_registration = mock_sync_password.call_args.args[0]
        self.assertIsInstance(synced_registration, RuntimeRegistration)
        self.assertEqual(synced_registration.user, self.user)
        self.assertEqual(mock_sync_password.call_args.kwargs['password'], 'longenoughpw')

    @patch('fg.views._unregister_remote_registration', return_value=True)
    @patch('fg.views.get_runtime_service')
    @patch('fg.views.safe_list_servers')
    def test_deactivate_uses_runtime_registration_when_models_missing(
        self,
        mock_safe_list_servers,
        mock_get_runtime_service,
        mock_unregister_remote_registration,
    ):
        registration = self._registration()
        mock_safe_list_servers.return_value = [self.server]
        mock_get_runtime_service.return_value = SimpleNamespace(
            registration_for_pilot_server=lambda *_args, **_kwargs: registration
        )

        response = self.client.post(reverse('mumble:deactivate', args=[self.server.pk]))

        self.assertEqual(response.status_code, 302)
        synced_registration = mock_unregister_remote_registration.call_args.args[0]
        self.assertIsInstance(synced_registration, RuntimeRegistration)
        self.assertEqual(synced_registration.user, self.user)


class RuntimePayloadCompatibilityTest(TestCase):
    def setUp(self):
        self.server = RuntimeServer(
            id=77,
            name='Test Runtime Server',
            address='runtime.example.com:64738',
        )
        self.service = BgRuntimeService()

    def test_runtime_parser_prefers_pkid(self):
        registration = self.service._registration_from_payload(
            {
                'pkid': 901,
                'server_id': 77,
                'server_name': 'Runtime Server',
                'username': 'Pilot_Main',
                'active_session_ids': [12, 13],
            },
            servers_by_id={77: self.server},
        )

        self.assertIsNotNone(registration)
        self.assertEqual(registration.user_id, 901)
        self.assertEqual(registration.server_id, self.server.id)

    def test_runtime_parser_rejects_missing_pkid(self):
        registration = self.service._registration_from_payload(
            {
                'user_id': 902,
                'server_id': 77,
                'server_name': 'Runtime Server',
                'username': 'Pilot_Alt',
            },
            servers_by_id={77: self.server},
        )

        self.assertIsNone(registration)


@override_settings(**_NO_REDIS, MURMUR_MODEL_APP_LABEL='missing_app_label')
class RuntimeFallbackManageViewTest(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_superuser('runtimeadmin', 'runtimeadmin@example.com', 'pass')
        UserProfile.objects.create(user=self.viewer, is_member=True)
        self.target_user = _make_regular_member('runtime_target')
        self.server = RuntimeServer(
            id=83,
            name='Runtime Admin Server',
            address='runtime-admin.example.com:64738',
        )
        observed_at = timezone.now()
        self.registration = RuntimeRegistration(
            user_id=self.target_user.pk,
            server=self.server,
            username='Runtime_Target',
            display_name='Runtime Target',
            mumble_userid=904,
            contract_evepilot_id=90000001,
            contract_corporation_id=98000001,
            contract_alliance_id=99000001,
            contract_kdf_iterations=120000,
            active_session_ids=(41, 42),
            has_priority_speaker=True,
            last_authenticated=observed_at - timedelta(minutes=10),
            last_connected=observed_at - timedelta(minutes=9),
            last_seen=observed_at - timedelta(minutes=1),
            last_spoke=observed_at - timedelta(seconds=20),
        )
        self.client.force_login(self.viewer)

    @patch('fg.views.safe_registration_inventory')
    @patch('fg.views.safe_list_servers')
    def test_manage_view_uses_runtime_inventory_when_models_missing(
        self,
        mock_safe_list_servers,
        mock_safe_registration_inventory,
    ):
        mock_safe_list_servers.return_value = [self.server]
        mock_safe_registration_inventory.return_value = [self.registration]

        response = self.client.get(reverse('mumble:manage'))

        self.assertEqual(response.status_code, 200)
        mumble_users = list(response.context['mumble_users'])
        self.assertEqual(len(mumble_users), 1)
        self.assertEqual(mumble_users[0].user, self.target_user)
        self.assertEqual(mumble_users[0].active_session_count, 2)
        self.assertTrue(mumble_users[0].has_priority_speaker)
        self.assertContains(response, reverse('mumble:toggle_admin_registration', args=[self.target_user.pk, self.server.pk]))
        self.assertContains(response, reverse('mumble:sync_contract_registration', args=[self.target_user.pk, self.server.pk]))


@override_settings(**_NO_REDIS, MURMUR_MODEL_APP_LABEL='missing_app_label')
class RuntimeFallbackManageActionViewTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser('runtime_root', 'root@example.com', 'pass')
        UserProfile.objects.create(user=self.superuser, is_member=True)
        self.target_user = _make_regular_member('runtime_action_target')
        self.server = RuntimeServer(
            id=91,
            name='Runtime Action Server',
            address='runtime-action.example.com:64738',
        )

    def _registration(self, *, is_mumble_admin=False):
        return RuntimeRegistration(
            user_id=self.target_user.pk,
            user=self.target_user,
            server=self.server,
            username='Runtime_Action_Target',
            display_name='Runtime Action Target',
            is_mumble_admin=is_mumble_admin,
            groups='admin' if is_mumble_admin else '',
        )

    @patch('fg.views.safe_registration_inventory')
    @patch('fg.views.safe_list_servers')
    @patch('fg.views._sync_live_admin_membership', return_value=3)
    @patch('fg.views.get_runtime_service')
    @patch('fg.views._runtime_registration')
    def test_toggle_admin_registration_uses_runtime_registration_when_models_missing(
        self,
        mock_runtime_registration,
        mock_get_runtime_service,
        mock_sync_live_admin_membership,
        mock_safe_list_servers,
        mock_safe_registration_inventory,
    ):
        registration = self._registration()
        mock_runtime_registration.return_value = registration
        mock_get_runtime_service.return_value = SimpleNamespace(attach_users=lambda registrations: registrations)
        mock_safe_list_servers.return_value = [self.server]
        mock_safe_registration_inventory.return_value = [registration]
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('mumble:toggle_admin_registration', args=[self.target_user.pk, self.server.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(registration.is_mumble_admin)
        self.assertEqual(registration.groups, 'admin')
        self.assertIs(mock_sync_live_admin_membership.call_args.args[0], registration)
        messages = [message.message for message in response.context['messages']]
        self.assertIn('Murmur admin granted for Runtime_Action_Target.', messages)

    def test_legacy_toggle_admin_route_404s_when_models_missing(self):
        self.client.force_login(self.superuser)

        response = self.client.post(reverse('mumble:toggle_admin', args=[1]))

        self.assertEqual(response.status_code, 404)

    @patch('fg.views.safe_registration_inventory')
    @patch('fg.views.safe_list_servers')
    @patch('fg.views._CONTROL_CLIENT.probe_murmur_registration')
    @patch('fg.views._sync_contract_metadata')
    @patch('fg.views._runtime_registration')
    def test_sync_contract_registration_uses_runtime_registration_when_models_missing(
        self,
        mock_runtime_registration,
        mock_sync_contract_metadata,
        mock_probe_murmur_registration,
        mock_safe_list_servers,
        mock_safe_registration_inventory,
    ):
        registration = self._registration()
        mock_runtime_registration.return_value = registration
        mock_sync_contract_metadata.return_value = {
            'evepilot_id': 90000001,
            'corporation_id': 98000001,
            'alliance_id': 99000001,
            'kdf_iterations': 120000,
        }
        mock_probe_murmur_registration.return_value = {
            'evepilot_id': 90000001,
            'corporation_id': 98000001,
            'alliance_id': 99000001,
            'kdf_iterations': 120000,
        }
        mock_safe_list_servers.return_value = [self.server]
        mock_safe_registration_inventory.return_value = [registration]
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('mumble:sync_contract_registration', args=[self.target_user.pk, self.server.pk]),
            {
                'evepilot_id': '90000001',
                'corporation_id': '98000001',
                'alliance_id': '99000001',
                'kdf_iterations': '120000',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(mock_sync_contract_metadata.call_args.args[0], registration)
        messages = [message.message for message in response.context['messages']]
        self.assertIn('Contract metadata synchronized for Runtime_Action_Target.', messages)

    def test_legacy_sync_contract_route_404s_when_models_missing(self):
        self.client.force_login(self.superuser)

        response = self.client.post(reverse('mumble:sync_contract', args=[1]), {'evepilot_id': '1'})

        self.assertEqual(response.status_code, 404)


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
        self.assertContains(response, 'Sync Contract Metadata')


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


class ProfilePanelProviderTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = _make_member('paneluser')
        _grant_profile_panel_access(
            self.user,
            character_id=301001,
            character_name='Panel Main',
            corporation_id=401001,
            corporation_name='Panel Corp',
            alliance_id=501001,
            alliance_name='Panel Alliance',
        )
        self.server1 = _make_server(name='Server 1', address='s1.example.com:64738')
        self.server2 = _make_server(name='Server 2', address='s2.example.com:64738')

    def _request(self):
        request = self.factory.get('/profile/')
        request.user = self.user
        request.session = {}
        return request

    def test_generic_provider_builds_server_panels(self):
        request = self._request()

        panels = build_profile_panels(request)

        self.assertEqual(len(panels), 2)
        self.assertEqual({panel['server'].pk for panel in panels}, {self.server1.pk, self.server2.pk})
        self.assertEqual({panel['template'] for panel in panels}, {'fg/panels/profile_panel.html'})

    def test_profile_panel_defaults_port_when_server_address_has_no_port(self):
        server_without_port = _make_server(name='Server No Port', address='voice-dev.aixtools.com')
        request = self._request()

        panels = build_profile_panels(request)

        panel = next(panel for panel in panels if panel['server'].pk == server_without_port.pk)
        self.assertEqual(panel['server_address'], 'voice-dev.aixtools.com')
        self.assertEqual(panel['server_port'], '64738')

    def test_duplicate_username_keeps_base_username(self):
        MumbleUser.objects.create(user=self.user, server=self.server1, username='Pilot_Name', pwhash='h')
        MumbleUser.objects.create(user=self.user, server=self.server2, username='Pilot_Name', pwhash='h')
        request = self._request()

        panels = build_profile_panels(request)
        usernames = sorted(panel['username_with_slot'] for panel in panels if panel['username_with_slot'])

        self.assertEqual(usernames, ['Pilot_Name', 'Pilot_Name'])

    def test_panel_marks_admin_flag_when_registration_is_admin(self):
        MumbleUser.objects.create(
            user=self.user,
            server=self.server1,
            username='Panel_Main',
            pwhash='h',
            is_mumble_admin=True,
        )
        request = self._request()

        panels = build_profile_panels(request)

        panel = next(panel for panel in panels if panel['server'].pk == self.server1.pk)
        self.assertTrue(panel['is_admin'])

    def test_panel_prefers_computed_display_name(self):
        EveAllianceInfo.objects.create(
            alliance_id=501001,
            alliance_name='Panel Alliance',
            alliance_ticker='ALLY',
        )
        EveCorporationInfo.objects.create(
            corporation_id=401001,
            corporation_name='Panel Corp',
            corporation_ticker='CORP',
        )
        MumbleUser.objects.create(
            user=self.user,
            server=self.server1,
            username='Panel_Main',
            display_name='Old Display Name',
            pwhash='h',
        )
        request = self._request()

        panels = build_profile_panels(request)

        panel = next(panel for panel in panels if panel['server'].pk == self.server1.pk)
        self.assertEqual(panel['display_name'], '[ALLY CORP] Panel Main')
        self.assertFalse(panel['display_name_is_fallback'])

    def test_panel_uses_placeholder_display_name_when_cached_tickers_are_missing(self):
        request = self._request()

        panels = build_profile_panels(request)

        panel = next(panel for panel in panels if panel['server'].pk == self.server1.pk)
        self.assertEqual(panel['display_name'], '[???? ????] Panel Main')
        self.assertFalse(panel['display_name_is_fallback'])

    @patch('fg.views._compute_display_name', side_effect=RuntimeError('broken display-name computation'))
    def test_panel_falls_back_to_character_name_when_display_name_unavailable(self, _mock_display_name):
        request = self._request()

        panels = build_profile_panels(request)

        panel = next(panel for panel in panels if panel['server'].pk == self.server1.pk)
        self.assertEqual(panel['display_name'], 'Panel Main')
        self.assertTrue(panel['display_name_is_fallback'])

    def test_temp_password_is_read_once(self):
        MumbleUser.objects.create(user=self.user, server=self.server1, username='Pilot_Name', pwhash='h')
        request = self._request()
        request.session[f'murmur_temp_password_{self.server1.pk}'] = 'abc123'

        panels1 = build_profile_panels(request)
        panels2 = build_profile_panels(request)

        first = next(panel for panel in panels1 if panel['server'].pk == self.server1.pk)
        second = next(panel for panel in panels2 if panel['server'].pk == self.server1.pk)
        self.assertEqual(first['temp_password'], 'abc123')
        self.assertIsNone(second['temp_password'])

    def test_panel_hidden_when_user_is_not_acl_eligible(self):
        request = self.factory.get('/profile/')
        request.user = _make_member('ineligiblepaneluser')
        request.session = {}

        panels = build_profile_panels(request)

        self.assertEqual(panels, [])

    def test_panel_includes_main_and_explicit_alt_selector_choices(self):
        _make_char(
            self.user,
            character_id=301002,
            character_name='Allowed Alt',
            is_main=False,
            corporation_id=401002,
            corporation_name='Alt Corp',
            alliance_id=501002,
            alliance_name='Alt Alliance',
        )
        AccessRule.objects.create(
            entity_id=301002,
            entity_type=ENTITY_TYPE_PILOT,
            deny=False,
        )

        panels = build_profile_panels(self._request())

        self.assertEqual(
            [pilot['character_name'] for pilot in panels[0]['eligible_pilots']],
            ['Panel Main', 'Allowed Alt'],
        )
        self.assertTrue(panels[0]['show_pilot_selector'])

    @patch('fg.panels.providers.safe_list_servers', return_value=[])
    def test_panel_still_renders_without_bg_server_inventory(self, _mock_safe_list_servers):
        panels = build_profile_panels(self._request())

        self.assertEqual(len(panels), 1)
        self.assertIsNone(panels[0]['server'])
        self.assertEqual(panels[0]['server_label'], 'Mumble Authentication')

    @override_settings(MURMUR_PANEL_HOST='cube')
    def test_host_provider_resolution(self):
        provider = get_profile_panel_provider()
        self.assertEqual(provider.provider_name, 'cube')

    def test_cube_integration_uses_cube_provider(self):
        integration = CubeMurmurIntegration()
        request = self._request()
        panels = integration.get_profile_panels(request)
        self.assertEqual(len(panels), 2)


@override_settings(MURMUR_MODEL_APP_LABEL='missing_app_label')
class RuntimeFallbackProfilePanelProviderTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = _make_member('runtimepaneluser')
        _grant_profile_panel_access(
            self.user,
            character_id=302001,
            character_name='Runtime Main',
            corporation_id=402001,
            corporation_name='Runtime Corp',
            alliance_id=502001,
            alliance_name='Runtime Alliance',
        )

    def _request(self):
        request = self.factory.get('/profile/')
        request.user = self.user
        request.session = {}
        return request

    @patch('fg.panels.providers.safe_pilot_registrations')
    @patch('fg.panels.providers.safe_list_servers')
    def test_provider_falls_back_to_runtime_inventory_when_models_missing(
        self,
        mock_safe_list_servers,
        mock_safe_pilot_registrations,
    ):
        runtime_server = RuntimeServer(
            id=41,
            name='Runtime Server',
            address='runtime.example.com:64738',
        )
        runtime_registration = RuntimeRegistration(
            user_id=self.user.pk,
            user=self.user,
            server=runtime_server,
            username='Runtime_Pilot',
            display_name='Runtime Pilot',
        )
        mock_safe_list_servers.return_value = [runtime_server]
        mock_safe_pilot_registrations.return_value = [runtime_registration]

        panels = build_profile_panels(self._request())

        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]['server'].pk, runtime_server.pk)
        self.assertEqual(panels[0]['account'].username, 'Runtime_Pilot')


class CubeExtensionTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = _make_member('cubeextuser')
        _grant_profile_panel_access(
            self.user,
            character_id=303001,
            character_name='Cube Main',
            corporation_id=403001,
            corporation_name='Cube Corp',
            alliance_id=503001,
            alliance_name='Cube Alliance',
        )
        self.server = _make_server(name='Cube Server', address='cube.example.com:64738')

    def _request(self):
        request = self.factory.get('/profile/')
        request.user = self.user
        request.session = {}
        return request

    def test_profile_panels_delegate_to_cube_provider(self):
        request = self._request()

        panels = get_cube_profile_panels(request)

        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]['server'].pk, self.server.pk)

    def test_i18n_urlpatterns_mount_when_models_available(self):
        patterns = get_i18n_urlpatterns()

        self.assertEqual(len(patterns), 1)


@override_settings(MURMUR_MODEL_APP_LABEL='missing_app_label')
class CubeExtensionMissingModelsTest(TestCase):
    def test_i18n_urlpatterns_mount_when_models_missing(self):
        patterns = get_i18n_urlpatterns()

        self.assertEqual(len(patterns), 1)


@override_settings(**_NO_REDIS)
class ProfilePasswordPanelActionTest(TestCase):
    def setUp(self):
        self.user = _make_member('profilepanelpassworduser')
        self.client.force_login(self.user)
        self.main = _make_char(
            self.user,
            character_id=304001,
            character_name='Profile Main',
            corporation_id=404001,
            corporation_name='Profile Corp',
            alliance_id=504001,
            alliance_name='Profile Alliance',
        )
        AccessRule.objects.create(
            entity_id=504001,
            entity_type=ENTITY_TYPE_ALLIANCE,
            deny=False,
        )

    def test_profile_password_choices_return_main_for_alliance_allow(self):
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
        self.assertContains(resp, 'Get Murmur Credentials')

    def test_profile_shows_mumble_username(self):
        MumbleUser.objects.create(
            user=self.user, server=self.server, username='Test_User', pwhash='h'
        )
        resp = self.client.get(reverse('profile'))
        self.assertContains(resp, 'Test_User')
        self.assertNotContains(resp, 'Get Murmur Credentials')

    def test_temp_password_shown_once(self):
        session = self.client.session
        session[f'murmur_temp_password_{self.server.pk}'] = 'abc123secret'
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
        self.assertEqual([data[0]['server'].pk, data[1]['server'].pk], [self.server.pk, server2.pk])
        self.assertContains(resp, 'MUMBLE')


# ── ACL tests ─────────────────────────────────────────────────────

from fg.models import AccessRule, ENTITY_TYPE_ALLIANCE, ENTITY_TYPE_CORPORATION, ENTITY_TYPE_PILOT


@override_settings(**_NO_REDIS)
class AccessRuleModelTest(TestCase):
    def test_create_allow_rule(self):
        rule = AccessRule.objects.create(entity_id=99013537, entity_type=ENTITY_TYPE_ALLIANCE)
        self.assertFalse(rule.deny)
        self.assertEqual(str(rule), 'ALLOW alliance 99013537')

    def test_create_deny_rule(self):
        rule = AccessRule.objects.create(entity_id=98618881, entity_type=ENTITY_TYPE_CORPORATION, deny=True)
        self.assertTrue(rule.deny)
        self.assertEqual(str(rule), 'DENY corporation 98618881')

    def test_entity_id_unique(self):
        AccessRule.objects.create(entity_id=12345678, entity_type=ENTITY_TYPE_PILOT)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            AccessRule.objects.create(entity_id=12345678, entity_type=ENTITY_TYPE_PILOT)


@override_settings(**_NO_REDIS)
class ACLBatchCreateViewTest(TestCase):
    def setUp(self):
        self.user = _make_member()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_batch_create(self):
        resp = self.client.post(
            reverse('mumble:acl_batch_create'),
            data=json.dumps({
                'entities': [
                    {'entity_id': 99013537, 'entity_type': 'alliance'},
                    {'entity_id': 99013941, 'entity_type': 'alliance'},
                ],
                'note': 'test batch',
                'deny': False,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['created'], 2)
        self.assertEqual(data['skipped'], 0)
        self.assertEqual(AccessRule.objects.count(), 2)

    def test_batch_create_skips_duplicates(self):
        AccessRule.objects.create(entity_id=99013537, entity_type=ENTITY_TYPE_ALLIANCE)
        resp = self.client.post(
            reverse('mumble:acl_batch_create'),
            data=json.dumps({
                'entities': [{'entity_id': 99013537, 'entity_type': 'alliance'}],
                'note': '',
                'deny': False,
            }),
            content_type='application/json',
        )
        data = resp.json()
        self.assertEqual(data['created'], 0)
        self.assertEqual(data['skipped'], 1)
        self.assertIn(99013537, data['skipped_ids'])

    def test_batch_create_sets_created_by(self):
        self.client.post(
            reverse('mumble:acl_batch_create'),
            data=json.dumps({
                'entities': [{'entity_id': 12345678, 'entity_type': 'pilot'}],
                'note': '',
                'deny': False,
            }),
            content_type='application/json',
        )
        rule = AccessRule.objects.get(entity_id=12345678)
        self.assertEqual(rule.created_by, self.user.username)

    def test_batch_create_forbidden_for_non_staff(self):
        self.user.is_staff = False
        self.user.save()
        resp = self.client.post(
            reverse('mumble:acl_batch_create'),
            data=json.dumps({'entities': [{'entity_id': 1, 'entity_type': 'alliance'}], 'deny': False}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)


@override_settings(**_NO_REDIS)
class ACLDeleteViewTest(TestCase):
    def setUp(self):
        self.user = _make_member()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_delete_rule(self):
        rule = AccessRule.objects.create(entity_id=99013537, entity_type=ENTITY_TYPE_ALLIANCE)
        resp = self.client.post(reverse('mumble:acl_delete', args=[rule.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(AccessRule.objects.filter(pk=rule.pk).exists())

    def test_delete_forbidden_for_non_staff(self):
        rule = AccessRule.objects.create(entity_id=99013537, entity_type=ENTITY_TYPE_ALLIANCE)
        self.user.is_staff = False
        self.user.save()
        resp = self.client.post(reverse('mumble:acl_delete', args=[rule.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(AccessRule.objects.filter(pk=rule.pk).exists())


@override_settings(**_NO_REDIS)
class ACLListViewTest(TestCase):
    def setUp(self):
        self.user = _make_member()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_list_view(self):
        AccessRule.objects.create(entity_id=99013537, entity_type=ENTITY_TYPE_ALLIANCE, note='test')
        resp = self.client.get(reverse('mumble:acl_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['rules']), 1)
        self.assertTrue(resp.context['can_edit'])

    def test_list_forbidden_for_non_staff(self):
        self.user.is_staff = False
        self.user.save()
        resp = self.client.get(reverse('mumble:acl_list'))
        self.assertEqual(resp.status_code, 403)
