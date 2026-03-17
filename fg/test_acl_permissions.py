import json
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import UserProfile
from fg.admin import AccessRuleAdmin, AccessRuleAuditAdmin
from fg.models import AccessRule, AccessRuleAudit
from fg.sidebar import SIDEBAR_ITEMS

_NO_REDIS = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)


def _make_member(username='acluser'):
    user = User.objects.create_user(username, password='pass')
    UserProfile.objects.create(user=user, is_member=True)
    return user


def _grant_acl_perm(user, codename):
    permission = Permission.objects.get(
        content_type=ContentType.objects.get_for_model(AccessRule),
        codename=codename,
    )
    user.user_permissions.add(permission)


def _grant_audit_perm(user, codename):
    permission = Permission.objects.get(
        content_type=ContentType.objects.get_for_model(AccessRuleAudit),
        codename=codename,
    )
    user.user_permissions.add(permission)


@override_settings(**_NO_REDIS)
class ACLPermissionViewTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = _make_member()
        self.rule = AccessRule.objects.create(entity_id=99013537, entity_type='alliance', note='test')

    def _login(self):
        self.client.force_login(self.user)

    def _sidebar_item(self):
        return next(item for item in SIDEBAR_ITEMS if item['key'] == 'mumble_acl')

    def test_view_permission_controls_sidebar_and_page_access(self):
        request = self.factory.get('/')
        request.user = self.user
        self.assertFalse(self._sidebar_item()['visible'](request))

        self._login()
        response = self.client.get(reverse('mumble:acl_list'))
        self.assertEqual(response.status_code, 403)

        _grant_acl_perm(self.user, 'view_accessrule')
        self.user = User.objects.get(pk=self.user.pk)
        request.user = self.user
        self.assertTrue(self._sidebar_item()['visible'](request))

        with patch('fg.views._resolve_name_for_rule', return_value='Resolved Name'):
            response = self.client.get(reverse('mumble:acl_list'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['can_create_acl'])
        self.assertFalse(response.context['can_change_acl'])
        self.assertFalse(response.context['can_delete_acl'])
        self.assertFalse(response.context['can_sync_acl'])

    def test_staff_without_model_permissions_gets_no_acl_access(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])

        request = self.factory.get('/')
        request.user = self.user
        self.assertFalse(self._sidebar_item()['visible'](request))

        self._login()
        response = self.client.get(reverse('mumble:acl_list'))
        self.assertEqual(response.status_code, 403)

    def test_add_permission_controls_create_area_and_endpoint(self):
        _grant_acl_perm(self.user, 'view_accessrule')
        self._login()

        with patch('fg.views._resolve_name_for_rule', return_value='Resolved Name'):
            response = self.client.get(reverse('mumble:acl_list'))
        self.assertNotContains(response, 'Search EVE Entities')

        response = self.client.get(reverse('mumble:acl_search'), {'q': 'test'})
        self.assertEqual(response.status_code, 403)

        _grant_acl_perm(self.user, 'add_accessrule')
        with patch('fg.views._resolve_name_for_rule', return_value='Resolved Name'):
            response = self.client.get(reverse('mumble:acl_list'))
        self.assertContains(response, 'Search EVE Entities')

        with patch('fg.views._sync_acl_rules_after_change', return_value={'status': 'completed'}):
            response = self.client.post(
                reverse('mumble:acl_batch_create'),
                data=json.dumps({
                    'entities': [{'entity_id': 12345678, 'entity_type': 'pilot'}],
                    'deny': False,
                }),
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 200)

    def test_change_permission_controls_toggle_button_and_endpoint(self):
        _grant_acl_perm(self.user, 'view_accessrule')
        self._login()

        with patch('fg.views._resolve_name_for_rule', return_value='Resolved Name'):
            response = self.client.get(reverse('mumble:acl_list'))
        self.assertNotContains(response, reverse('mumble:acl_toggle_deny', args=[self.rule.pk]))
        self.assertNotContains(response, reverse('mumble:acl_sync'))

        response = self.client.post(reverse('mumble:acl_toggle_deny', args=[self.rule.pk]))
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse('mumble:acl_sync'))
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse('mumble:acl_sync'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error'], 'Forbidden')

        _grant_acl_perm(self.user, 'change_accessrule')
        with patch('fg.views._resolve_name_for_rule', return_value='Resolved Name'):
            response = self.client.get(reverse('mumble:acl_list'))
        self.assertContains(response, reverse('mumble:acl_toggle_deny', args=[self.rule.pk]))
        self.assertContains(response, reverse('mumble:acl_sync'))
        self.assertNotContains(response, reverse('mumble:acl_delete', args=[self.rule.pk]))

        with patch('fg.views._sync_acl_rules_after_change', return_value={'status': 'completed', 'total': 1}):
            response = self.client.post(reverse('mumble:acl_toggle_deny', args=[self.rule.pk]))
        self.assertEqual(response.status_code, 302)
        self.rule.refresh_from_db()
        self.assertTrue(self.rule.deny)

        with patch('fg.views._sync_acl_rules_after_change', return_value={'status': 'completed', 'total': 1}):
            response = self.client.post(reverse('mumble:acl_sync'))
        self.assertEqual(response.status_code, 302)

    def test_delete_permission_controls_delete_button_and_endpoint(self):
        _grant_acl_perm(self.user, 'view_accessrule')
        self._login()

        with patch('fg.views._resolve_name_for_rule', return_value='Resolved Name'):
            response = self.client.get(reverse('mumble:acl_list'))
        self.assertNotContains(response, reverse('mumble:acl_delete', args=[self.rule.pk]))

        response = self.client.post(reverse('mumble:acl_delete', args=[self.rule.pk]))
        self.assertEqual(response.status_code, 403)

        _grant_acl_perm(self.user, 'delete_accessrule')
        with patch('fg.views._resolve_name_for_rule', return_value='Resolved Name'):
            response = self.client.get(reverse('mumble:acl_list'))
        self.assertContains(response, reverse('mumble:acl_delete', args=[self.rule.pk]))

        with patch('fg.views._sync_acl_rules_after_change', return_value={'status': 'completed'}):
            response = self.client.post(reverse('mumble:acl_delete', args=[self.rule.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AccessRule.objects.filter(pk=self.rule.pk).exists())


@override_settings(**_NO_REDIS)
class ACLAdminPermissionTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.site = admin.site
        self.rule_admin = AccessRuleAdmin(AccessRule, self.site)
        self.audit_admin = AccessRuleAuditAdmin(AccessRuleAudit, self.site)
        self.user = _make_member('adminperm')

    def test_accessrule_admin_requires_explicit_permissions(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        request = self.factory.get('/')
        request.user = self.user

        self.assertFalse(self.rule_admin.has_module_permission(request))
        self.assertFalse(self.rule_admin.has_view_permission(request))
        self.assertFalse(self.rule_admin.has_add_permission(request))
        self.assertFalse(self.rule_admin.has_change_permission(request))
        self.assertFalse(self.rule_admin.has_delete_permission(request))

        _grant_acl_perm(self.user, 'view_accessrule')
        _grant_acl_perm(self.user, 'add_accessrule')
        _grant_acl_perm(self.user, 'change_accessrule')
        _grant_acl_perm(self.user, 'delete_accessrule')
        self.user = User.objects.get(pk=self.user.pk)
        request.user = self.user

        self.assertTrue(self.rule_admin.has_module_permission(request))
        self.assertTrue(self.rule_admin.has_view_permission(request))
        self.assertTrue(self.rule_admin.has_add_permission(request))
        self.assertTrue(self.rule_admin.has_change_permission(request))
        self.assertTrue(self.rule_admin.has_delete_permission(request))

    def test_audit_visibility_is_separate_and_immutable(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        request = self.factory.get('/')
        request.user = self.user

        self.assertFalse(self.audit_admin.has_module_permission(request))
        self.assertFalse(self.audit_admin.has_view_permission(request))
        self.assertFalse(self.audit_admin.has_add_permission(request))
        self.assertFalse(self.audit_admin.has_change_permission(request))
        self.assertFalse(self.audit_admin.has_delete_permission(request))

        _grant_audit_perm(self.user, 'view_accessruleaudit')
        self.user = User.objects.get(pk=self.user.pk)
        request.user = self.user

        self.assertTrue(self.audit_admin.has_module_permission(request))
        self.assertTrue(self.audit_admin.has_view_permission(request))
        self.assertFalse(self.audit_admin.has_add_permission(request))
        self.assertFalse(self.audit_admin.has_change_permission(request))
        self.assertFalse(self.audit_admin.has_delete_permission(request))

    def test_superuser_can_view_but_not_mutate_audit_log(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=['is_staff', 'is_superuser'])
        request = self.factory.get('/')
        request.user = self.user

        self.assertTrue(self.audit_admin.has_module_permission(request))
        self.assertTrue(self.audit_admin.has_view_permission(request))
        self.assertFalse(self.audit_admin.has_add_permission(request))
        self.assertFalse(self.audit_admin.has_change_permission(request))
        self.assertFalse(self.audit_admin.has_delete_permission(request))
