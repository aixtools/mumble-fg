from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connections
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import EveCharacter, Group, GroupMembership, UserProfile
from fg.acl_grants import reconcile_group_grants
from fg.models import (
    ACCESS_RULE_SOURCE_GROUP_GRANT,
    ACCESS_RULE_SOURCE_MANUAL,
    ACL_AUDIT_ACTION_CREATE,
    ACL_AUDIT_ACTION_DELETE,
    ENTITY_TYPE_CORPORATION,
    ENTITY_TYPE_PILOT,
    AccessGrantSettings,
    AccessRule,
    AccessRuleAudit,
)

_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)

_ALLY_CORP_ID = 98000001
_ALLY_ALLIANCE_ID = 99000001


def _make_user(username, *, is_member=False):
    user = User.objects.create_user(username, password='pass')
    UserProfile.objects.create(user=user, is_member=is_member)
    return user


def _make_main(user, character_id, character_name):
    return EveCharacter.objects.create(
        user=user,
        character_id=character_id,
        character_name=character_name,
        corporation_id=_ALLY_CORP_ID,
        corporation_name='Allied Corp',
        alliance_id=_ALLY_ALLIANCE_ID,
        alliance_name='Allied Alliance',
        is_main=True,
        access_token='x',
        refresh_token='x',
        token_expires=timezone.now(),
        scopes='',
    )


def _make_grant_group(name='Allied Comms'):
    group = Group.objects.create(name=name, allow_non_alliance_members=True)
    settings = AccessGrantSettings.load()
    settings.grant_groups.add(group)
    return group


def _approve(user, group):
    return GroupMembership.objects.create(user=user, group=group, status='approved')


@override_settings(**_NO_REDIS)
class ReconcileGroupGrantsTest(TestCase):
    databases = frozenset(connections.databases)

    def setUp(self):
        eve_setup = patch('fg.views._eve_char_setup', return_value=(EveCharacter, 'default'))
        eve_setup.start()
        self.addCleanup(eve_setup.stop)
        self.group = _make_grant_group()
        self.user = _make_user('alliedpilot')
        self.main = _make_main(self.user, 95000001, 'Allied Pilot')

    def test_approved_member_gets_managed_allow_rule(self):
        _approve(self.user, self.group)

        stats = reconcile_group_grants()

        self.assertEqual(stats['created'], 1)
        rule = AccessRule.objects.get(entity_id=self.main.character_id)
        self.assertEqual(rule.entity_type, ENTITY_TYPE_PILOT)
        self.assertFalse(rule.deny)
        self.assertEqual(rule.source, ACCESS_RULE_SOURCE_GROUP_GRANT)
        self.assertIn('Allied Comms', rule.note)
        audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_CREATE)
        self.assertEqual(audit.entity_id, self.main.character_id)

    def test_reconcile_is_idempotent(self):
        _approve(self.user, self.group)
        reconcile_group_grants()

        stats = reconcile_group_grants()

        self.assertEqual(stats['created'], 0)
        self.assertEqual(stats['deleted'], 0)
        self.assertEqual(AccessRule.objects.count(), 1)

    def test_pending_membership_gets_no_rule(self):
        GroupMembership.objects.create(user=self.user, group=self.group, status='pending')

        stats = reconcile_group_grants()

        self.assertEqual(stats['created'], 0)
        self.assertFalse(AccessRule.objects.exists())

    def test_member_of_non_grant_group_gets_no_rule(self):
        other_group = Group.objects.create(name='Unrelated', allow_non_alliance_members=True)
        _approve(self.user, other_group)

        stats = reconcile_group_grants()

        self.assertEqual(stats['created'], 0)
        self.assertFalse(AccessRule.objects.exists())

    def test_leaving_group_deletes_managed_rule_only(self):
        _approve(self.user, self.group)
        manual = AccessRule.objects.create(
            entity_id=95000099,
            entity_type=ENTITY_TYPE_PILOT,
            deny=False,
            source=ACCESS_RULE_SOURCE_MANUAL,
        )
        reconcile_group_grants()

        GroupMembership.objects.filter(user=self.user).delete()
        stats = reconcile_group_grants()

        self.assertEqual(stats['deleted'], 1)
        self.assertFalse(
            AccessRule.objects.filter(entity_id=self.main.character_id).exists()
        )
        self.assertTrue(AccessRule.objects.filter(pk=manual.pk).exists())
        audit = AccessRuleAudit.objects.get(action=ACL_AUDIT_ACTION_DELETE)
        self.assertEqual(audit.entity_id, self.main.character_id)
        self.assertEqual(audit.previous.get('source'), ACCESS_RULE_SOURCE_GROUP_GRANT)

    def test_existing_manual_rule_is_never_adopted(self):
        _approve(self.user, self.group)
        AccessRule.objects.create(
            entity_id=self.main.character_id,
            entity_type=ENTITY_TYPE_PILOT,
            deny=True,
            note='banned by hand',
        )

        stats = reconcile_group_grants()

        self.assertEqual(stats['created'], 0)
        rule = AccessRule.objects.get(entity_id=self.main.character_id)
        self.assertTrue(rule.deny)
        self.assertEqual(rule.source, ACCESS_RULE_SOURCE_MANUAL)
        self.assertEqual(rule.note, 'banned by hand')

        # Leaving the group must not garbage-collect the manual rule either.
        GroupMembership.objects.filter(user=self.user).delete()
        stats = reconcile_group_grants()
        self.assertEqual(stats['deleted'], 0)
        self.assertTrue(
            AccessRule.objects.filter(entity_id=self.main.character_id).exists()
        )

    def test_pilot_with_denied_corp_is_skipped(self):
        _approve(self.user, self.group)
        AccessRule.objects.create(
            entity_id=_ALLY_CORP_ID,
            entity_type=ENTITY_TYPE_CORPORATION,
            deny=True,
        )

        stats = reconcile_group_grants()

        self.assertEqual(stats['created'], 0)
        self.assertEqual(stats['skipped_denied_org'], 1)
        self.assertFalse(
            AccessRule.objects.filter(entity_id=self.main.character_id).exists()
        )

    def test_member_without_main_is_skipped(self):
        no_main = _make_user('nomainpilot')
        _approve(no_main, self.group)

        stats = reconcile_group_grants()

        # self.user is not in the group in this test, so only no_main counts.
        self.assertEqual(stats['created'], 0)
        self.assertEqual(stats['skipped_no_main'], 1)

    def test_no_grant_groups_configured_is_a_noop(self):
        AccessGrantSettings.load().grant_groups.clear()
        _approve(self.user, self.group)

        stats = reconcile_group_grants()

        self.assertEqual(stats['created'], 0)
        self.assertFalse(AccessRule.objects.exists())


@override_settings(**_NO_REDIS)
class AdoptOnTouchTest(TestCase):
    databases = frozenset(connections.databases)

    def setUp(self):
        eve_setup = patch('fg.views._eve_char_setup', return_value=(EveCharacter, 'default'))
        eve_setup.start()
        self.addCleanup(eve_setup.stop)
        self.group = _make_grant_group()
        self.user = _make_user('alliedpilot')
        self.main = _make_main(self.user, 95000001, 'Allied Pilot')
        _approve(self.user, self.group)
        reconcile_group_grants()
        self.rule = AccessRule.objects.get(entity_id=self.main.character_id)
        self.admin = User.objects.create_superuser('acladmin', password='pass')
        UserProfile.objects.create(user=self.admin, is_member=True)

    def test_toggle_deny_adopts_managed_rule_as_manual(self):
        self.client.force_login(self.admin)
        with patch('fg.views._sync_acl_rules_after_change', return_value={'status': 'completed'}):
            response = self.client.post(reverse('mumble:acl_toggle_deny', args=[self.rule.pk]))
        self.assertEqual(response.status_code, 302)

        self.rule.refresh_from_db()
        self.assertTrue(self.rule.deny)
        self.assertEqual(self.rule.source, ACCESS_RULE_SOURCE_MANUAL)

        # The admin's deny now survives the pilot leaving the grant group.
        GroupMembership.objects.filter(user=self.user).delete()
        stats = reconcile_group_grants()
        self.assertEqual(stats['deleted'], 0)
        self.assertTrue(AccessRule.objects.filter(pk=self.rule.pk).exists())

    def test_toggle_admin_adopts_managed_rule_as_manual(self):
        self.client.force_login(self.admin)
        with patch('fg.views._sync_acl_rules_after_change', return_value={'status': 'completed'}), \
                patch('fg.views._pilot_has_denied_corp_or_alliance', return_value=False):
            response = self.client.post(reverse('mumble:acl_toggle_admin', args=[self.rule.pk]))
        self.assertEqual(response.status_code, 302)

        self.rule.refresh_from_db()
        self.assertTrue(self.rule.acl_admin)
        self.assertEqual(self.rule.source, ACCESS_RULE_SOURCE_MANUAL)


@override_settings(**_NO_REDIS)
class PeriodicSyncFaultIsolationTest(TestCase):
    databases = frozenset(connections.databases)

    def test_bg_push_survives_reconcile_failure(self):
        from fg import tasks

        with patch.object(tasks, 'reconcile_group_grants', side_effect=RuntimeError('boom')), \
                patch.object(tasks, 'sync_acl_rules_to_bg', return_value={'total': 0}) as push:
            tasks.periodic_acl_sync()

        push.assert_called_once()
