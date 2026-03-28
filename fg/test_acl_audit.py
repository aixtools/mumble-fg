import json
from io import StringIO
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import UserProfile
from fg.acl_sync import sync_acl_rules_to_bg
from fg.admin import AccessRuleAdmin
from fg.control import BgControlClient, BgSyncError
from fg.models import (
    ACL_AUDIT_ACTION_CREATE,
    ACL_AUDIT_ACTION_DELETE,
    ACL_AUDIT_ACTION_SYNC,
    ACL_AUDIT_ACTION_UPDATE,
    AccessRule,
    AccessRuleAudit,
)

_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)


def _make_member(username='aclaudituser'):
    user = User.objects.create_user(username, password='pass')
    UserProfile.objects.create(user=user, is_member=True)
    return user


def _grant_acl_perm(user, codename):
    permission = Permission.objects.get(
        content_type=ContentType.objects.get_for_model(AccessRule),
        codename=codename,
    )
    user.user_permissions.add(permission)


@override_settings(**_NO_REDIS)
class ACLAuditTest(TestCase):
    def setUp(self):
        self.user = _make_member()
        self.client.force_login(self.user)
        self.factory = RequestFactory()
        self.admin_site = AdminSite()
        self.admin = AccessRuleAdmin(AccessRule, self.admin_site)
        self.mock_bg_client = BgControlClient()
        bg_clients_patcher = patch(
            'fg.acl_sync.get_active_bg_clients',
            return_value=[self.mock_bg_client],
        )
        bg_clients_patcher.start()
        self.addCleanup(bg_clients_patcher.stop)
        pilot_snapshot = patch(
            'fg.acl_sync.serialize_pilot_snapshot',
            return_value={'generated_at': '2026-03-20T00:00:00Z', 'accounts': []},
        )
        self.mock_serialize_pilot_snapshot = pilot_snapshot.start()
        self.addCleanup(pilot_snapshot.stop)

    @patch.object(BgControlClient, 'sync_access_rules', return_value={'status': 'completed', 'total': 1, 'created': 1, 'updated': 0, 'deleted': 0})
    def test_batch_create_logs_audit_entry(self, mock_sync_access_rules):
        _grant_acl_perm(self.user, 'view_accessrule')
        _grant_acl_perm(self.user, 'add_accessrule')

        response = self.client.post(
            reverse('mumble:acl_batch_create'),
            data=json.dumps({
                'entities': [{'entity_id': 12345678, 'entity_type': 'pilot'}],
                'deny': True,
                'note': 'seed',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        audits = list(AccessRuleAudit.objects.order_by('id'))
        self.assertEqual([audit.action for audit in audits], [ACL_AUDIT_ACTION_CREATE, ACL_AUDIT_ACTION_SYNC])
        audit = audits[0]
        self.assertEqual(audit.actor_username, self.user.username)
        self.assertEqual(audit.source, 'acl_ui_batch_create')
        self.assertEqual(audit.entity_id, 12345678)
        self.assertTrue(audit.deny)
        self.assertEqual(audit.previous, {})
        sync_audit = audits[1]
        self.assertEqual(sync_audit.source, 'acl_ui_batch_create_sync')
        self.assertEqual(sync_audit.metadata['trigger'], 'implicit')
        self.assertEqual(sync_audit.metadata['sync_status'], 'completed')

    @patch.object(BgControlClient, 'sync_access_rules', return_value={'status': 'completed', 'total': 1, 'created': 0, 'updated': 1, 'deleted': 0})
    def test_toggle_logs_previous_snapshot(self, mock_sync_access_rules):
        _grant_acl_perm(self.user, 'view_accessrule')
        _grant_acl_perm(self.user, 'change_accessrule')
        rule = AccessRule.objects.create(entity_id=99013537, entity_type='alliance', deny=False, note='before')

        response = self.client.post(reverse('mumble:acl_toggle_deny', args=[rule.pk]))

        self.assertEqual(response.status_code, 302)
        audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_UPDATE)
        self.assertEqual(audit.action, ACL_AUDIT_ACTION_UPDATE)
        self.assertEqual(audit.source, 'acl_ui_toggle_deny')
        self.assertEqual(audit.previous['deny'], False)
        self.assertEqual(audit.previous['note'], 'before')
        self.assertTrue(audit.deny)
        sync_audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_SYNC)
        self.assertEqual(sync_audit.source, 'acl_ui_toggle_deny_sync')
        self.assertEqual(sync_audit.acl_id, rule.pk)
        self.assertEqual(sync_audit.metadata['trigger'], 'implicit')

    @patch.object(BgControlClient, 'sync_access_rules', return_value={'status': 'completed', 'total': 0, 'created': 0, 'updated': 0, 'deleted': 1})
    def test_delete_logs_snapshot_before_rule_removal(self, mock_sync_access_rules):
        _grant_acl_perm(self.user, 'view_accessrule')
        _grant_acl_perm(self.user, 'delete_accessrule')
        rule = AccessRule.objects.create(entity_id=99013941, entity_type='alliance', deny=True, note='gone')

        response = self.client.post(reverse('mumble:acl_delete', args=[rule.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AccessRule.objects.filter(pk=rule.pk).exists())
        audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_DELETE)
        self.assertEqual(audit.action, ACL_AUDIT_ACTION_DELETE)
        self.assertEqual(audit.source, 'acl_ui_delete')
        self.assertEqual(audit.note, 'gone')
        self.assertEqual(audit.previous['entity_id'], 99013941)
        sync_audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_SYNC)
        self.assertEqual(sync_audit.source, 'acl_ui_delete_sync')
        self.assertEqual(sync_audit.acl_id, rule.pk)
        self.assertEqual(sync_audit.metadata['deleted'], 1)

    def test_audit_model_is_append_only(self):
        audit = AccessRuleAudit.objects.create(
            acl_id=1,
            action=ACL_AUDIT_ACTION_CREATE,
            actor_username='tester',
            source='test',
            entity_id=1,
            entity_type='pilot',
            deny=False,
            note='',
            acl_created_by='tester',
        )

        audit.note = 'mutated'
        with self.assertRaises(RuntimeError):
            audit.save()
        with self.assertRaises(RuntimeError):
            audit.delete()

    @patch.object(BgControlClient, 'sync_access_rules', return_value={'status': 'completed', 'total': 1, 'created': 1, 'updated': 0, 'deleted': 0})
    def test_admin_batch_create_logs_audit_entry(self, mock_sync_access_rules):
        admin_user = User.objects.create_superuser('acladmin', 'admin@example.com', 'pass')
        request = self.factory.post(
            '/admin/mumble_fg/accessrule/batch-create/',
            data=json.dumps({
                'entities': [{'entity_id': 980010, 'entity_type': 'corporation'}],
                'deny': False,
                'note': 'admin batch',
            }),
            content_type='application/json',
        )
        request.user = admin_user

        response = self.admin.batch_create_view(request)

        self.assertEqual(response.status_code, 200)
        audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_CREATE)
        self.assertEqual(audit.action, ACL_AUDIT_ACTION_CREATE)
        self.assertEqual(audit.actor_username, admin_user.username)
        self.assertEqual(audit.source, 'admin_batch_create')
        self.assertEqual(audit.entity_id, 980010)
        sync_audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_SYNC)
        self.assertEqual(sync_audit.source, 'admin_batch_create_sync')
        self.assertEqual(sync_audit.metadata['trigger'], 'implicit')

    @patch.object(BgControlClient, 'sync_access_rules', return_value={'status': 'completed', 'total': 1, 'created': 0, 'updated': 1, 'deleted': 0})
    def test_admin_save_model_logs_update_snapshot(self, mock_sync_access_rules):
        admin_user = User.objects.create_superuser('acladmin2', 'admin2@example.com', 'pass')
        rule = AccessRule.objects.create(
            entity_id=980011,
            entity_type='corporation',
            deny=False,
            note='before admin update',
            created_by='seed',
        )
        rule.note = 'after admin update'
        request = self.factory.post(f'/admin/mumble_fg/accessrule/{rule.pk}/change/')
        request.user = admin_user

        self.admin.save_model(request, rule, form=None, change=True)

        audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_UPDATE)
        self.assertEqual(audit.action, ACL_AUDIT_ACTION_UPDATE)
        self.assertEqual(audit.source, 'admin_changeform')
        self.assertEqual(audit.note, 'after admin update')
        self.assertEqual(audit.previous['note'], 'before admin update')
        sync_audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_SYNC)
        self.assertEqual(sync_audit.source, 'admin_changeform_sync')
        self.assertEqual(sync_audit.metadata['trigger'], 'implicit')

    @patch.object(BgControlClient, 'sync_access_rules', return_value={'status': 'completed', 'total': 1, 'created': 0, 'updated': 1, 'deleted': 0})
    def test_manual_sync_logs_audit_entry(self, mock_sync_access_rules):
        _grant_acl_perm(self.user, 'view_accessrule')
        _grant_acl_perm(self.user, 'change_accessrule')
        AccessRule.objects.create(entity_id=123456, entity_type='pilot', deny=False, note='seed')

        response = self.client.post(reverse('mumble:acl_sync'))

        self.assertEqual(response.status_code, 302)
        audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_SYNC)
        self.assertEqual(audit.source, 'acl_ui_sync')
        self.assertEqual(audit.actor_username, self.user.username)
        self.assertEqual(audit.metadata['trigger'], 'manual')

    @patch.object(BgControlClient, 'sync_access_rules', return_value={'status': 'completed', 'total': 1, 'created': 0, 'updated': 1, 'deleted': 0})
    def test_manual_sync_ajax_returns_json(self, mock_sync_access_rules):
        _grant_acl_perm(self.user, 'view_accessrule')
        _grant_acl_perm(self.user, 'change_accessrule')
        AccessRule.objects.create(entity_id=123456, entity_type='pilot', deny=False, note='seed')

        response = self.client.post(
            reverse('mumble:acl_sync'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(data['total'], 1)
        self.assertIn('ACL synchronized to BG', data['message'])

    @patch(
        'fg.acl_sync.serialize_pilot_snapshot',
        return_value={
            'generated_at': '2026-03-20T00:00:00Z',
            'accounts': [
                {
                    'pkid': 42,
                    'main_character_id': 9001,
                    'main_character_name': 'Pilot One',
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
    )
    @patch.object(BgControlClient, 'sync_access_rules', return_value={'status': 'completed', 'total': 1, 'created': 0, 'updated': 1, 'deleted': 0})
    def test_sync_acl_rules_to_bg_defaults_to_reconcile_and_sends_snapshot(
        self,
        mock_sync_access_rules,
        mock_serialize_pilot_snapshot,
    ):
        rule = AccessRule.objects.create(entity_id=123456, entity_type='pilot', deny=False, note='seed')

        response = sync_acl_rules_to_bg(
            requested_by=self.user.username,
            actor_username=self.user.username,
            source='acl_ui_sync',
            trigger='manual',
            rule=rule,
        )

        self.assertEqual(response['status'], 'completed')
        mock_serialize_pilot_snapshot.assert_called_once_with()
        mock_sync_access_rules.assert_called_once()
        _, kwargs = mock_sync_access_rules.call_args
        self.assertIs(kwargs.get('reconcile'), True)
        self.assertEqual(kwargs.get('pilot_snapshot', {}).get('accounts', [])[0]['pkid'], 42)

    @patch('fg.views._sync_acl_rules_after_change', side_effect=BgSyncError('Control endpoint unreachable: connection refused'))
    def test_manual_sync_ajax_reports_bg_unavailable(self, mock_sync_acl_rules_after_change):
        _grant_acl_perm(self.user, 'view_accessrule')
        _grant_acl_perm(self.user, 'change_accessrule')
        AccessRule.objects.create(entity_id=123456, entity_type='pilot', deny=False, note='seed')

        response = self.client.post(
            reverse('mumble:acl_sync'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data['error'], 'BG unavailable')
        self.assertTrue(data['bg_unavailable'])

    @patch.object(BgControlClient, 'base_url', return_value='http://monitor.aixtools.org:18080')
    @patch.object(BgControlClient, 'sync_access_rules', side_effect=BgSyncError('Control endpoint unreachable: [Errno 111] Connection refused'))
    def test_sync_failure_logs_control_url_and_audits_it(self, mock_sync_access_rules, mock_base_url):
        AccessRule.objects.create(entity_id=123456, entity_type='pilot', deny=False, note='seed')

        with self.assertLogs('fg.acl_sync', level='WARNING') as captured:
            with self.assertRaises(BgSyncError):
                sync_acl_rules_to_bg(
                    requested_by='leorises',
                    actor_username=self.user.username,
                    source='acl_ui_sync',
                    trigger='manual',
                )

        mock_sync_access_rules.assert_called_once()
        mock_base_url.assert_called_once_with()
        self.assertIn(
            'ACL sync failed for source=acl_ui_sync requested_by=leorises control_url=http://monitor.aixtools.org:18080',
            captured.output[0],
        )
        audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_SYNC)
        self.assertEqual(audit.metadata['sync_status'], 'failed')
        self.assertEqual(audit.metadata['control_url'], 'http://monitor.aixtools.org:18080')

    @patch.object(BgControlClient, 'sync_access_rules', return_value={'status': 'completed', 'total': 1, 'created': 0, 'updated': 1, 'deleted': 0})
    def test_periodic_command_logs_audit_entry(self, mock_sync_access_rules):
        AccessRule.objects.create(entity_id=123456, entity_type='pilot', deny=False, note='seed')
        out = StringIO()

        call_command('sync_mumble_acl', stdout=out)

        audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_SYNC)
        self.assertEqual(audit.source, 'acl_periodic_sync')
        self.assertEqual(audit.actor_username, 'system')
        self.assertEqual(audit.metadata['trigger'], 'periodic')
        self.assertIn('ACL synchronized to BG', out.getvalue())
