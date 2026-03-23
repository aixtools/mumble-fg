"""FG-owned models and Murmur contract model resolution."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, NamedTuple

from django.apps import apps
from django.conf import settings
from django.db import models
from django.db.models import Q

_DEFAULT_MODEL_APP_LABEL = 'mumble'


class MurmurModelLookupError(LookupError):
    """Raised when the configured Murmur contract models are unavailable."""


class ResolvedMurmurModels(NamedTuple):
    MumbleUser: Any


class MurmurModelResolver:
    """Resolve host-provided Murmur contract models without import-path coupling."""

    def __init__(self, *, app_label: str | None = None):
        configured_label = app_label or getattr(settings, 'MURMUR_MODEL_APP_LABEL', _DEFAULT_MODEL_APP_LABEL)
        self._primary_label = str(configured_label or _DEFAULT_MODEL_APP_LABEL).strip() or _DEFAULT_MODEL_APP_LABEL

    def candidate_labels(self) -> tuple[str, ...]:
        labels = [self._primary_label]
        fallback_label = str(getattr(settings, 'MURMUR_MODEL_FALLBACK_APP_LABEL', '') or '').strip()
        if fallback_label and fallback_label not in labels:
            labels.append(fallback_label)
        return tuple(labels)

    def resolve(self, model_name: str):
        return _resolve_model(model_name, self.candidate_labels())


@lru_cache(maxsize=None)
def _resolve_model(model_name: str, labels: tuple[str, ...]):
    for app_label in labels:
        try:
            return apps.get_model(app_label, model_name, require_ready=False)
        except LookupError:
            continue

    raise MurmurModelLookupError(
        f'Unable to resolve Murmur model {model_name!r}. Checked app labels: {", ".join(labels)}'
    )


def resolve_murmur_model(model_name: str, *, app_label: str | None = None):
    return MurmurModelResolver(app_label=app_label).resolve(model_name)


def resolve_murmur_models(*, app_label: str | None = None) -> ResolvedMurmurModels:
    resolver = MurmurModelResolver(app_label=app_label)
    return ResolvedMurmurModels(
        MumbleUser=resolver.resolve('MumbleUser'),
    )


class LazyMurmurModel:
    """Thin proxy that resolves a Murmur model on first use."""

    def __init__(self, model_name: str):
        self._model_name = model_name

    def _resolve(self):
        return resolve_murmur_model(self._model_name)

    def __call__(self, *args, **kwargs):
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, attr):
        return getattr(self._resolve(), attr)

    def __repr__(self) -> str:
        return f'<LazyMurmurModel {self._model_name}>'


MumbleUser = LazyMurmurModel('MumbleUser')


ENTITY_TYPE_ALLIANCE = 'alliance'
ENTITY_TYPE_CORPORATION = 'corporation'
ENTITY_TYPE_PILOT = 'pilot'

ENTITY_TYPE_CHOICES = [
    (ENTITY_TYPE_ALLIANCE, 'Alliance'),
    (ENTITY_TYPE_CORPORATION, 'Corporation'),
    (ENTITY_TYPE_PILOT, 'Pilot'),
]

ACL_AUDIT_ACTION_CREATE = 'create'
ACL_AUDIT_ACTION_UPDATE = 'update'
ACL_AUDIT_ACTION_DELETE = 'delete'
ACL_AUDIT_ACTION_SYNC = 'sync'

ACL_AUDIT_ACTION_CHOICES = [
    (ACL_AUDIT_ACTION_CREATE, 'Create'),
    (ACL_AUDIT_ACTION_UPDATE, 'Update'),
    (ACL_AUDIT_ACTION_DELETE, 'Delete'),
    (ACL_AUDIT_ACTION_SYNC, 'Sync'),
]


class AccessRule(models.Model):
    """
    Access control list for Mumble eligibility.

    Precedence (most specific wins):
      1. Pilot allow/deny overrides everything
      2. Corp deny applies if no pilot-level override
      3. Alliance allow is the baseline (alliance in = permitted)

    Default is permit (deny=False). When deny=True the entity is denied.
    EVE IDs are globally unique so entity_id is unique across the table.
    Block checks are account-wide: main or any alt matching triggers denial
    unless a pilot-level allow overrides it.

    TODO: FG-defined permission model for non-staff ACL manage/view access,
    keyed by pilot pkid (resolved via main character).
    """

    entity_id = models.BigIntegerField(
        unique=True,
        help_text='EVE Online ID (alliance, corporation, or character).',
    )
    entity_type = models.CharField(
        max_length=16,
        choices=ENTITY_TYPE_CHOICES,
        help_text='Deducible from ID range but kept for query convenience.',
    )
    deny = models.BooleanField(
        default=False,
        help_text='Off = permit (default). On = deny access.',
    )
    acl_admin = models.BooleanField(
        default=False,
        help_text='Pilot-only Murmur admin marker. Ignored for alliance/corporation rules.',
    )
    note = models.TextField(
        blank=True,
        default='',
        help_text='Admin notes (e.g. reason for denial, ticket reference).',
    )
    created_by = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Who added this rule.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fg_access_rule'
        ordering = ['entity_type', 'entity_id']
        verbose_name = 'access control entry'
        verbose_name_plural = 'access control list'
        permissions = [
            ('manage_acl_admin', 'Can set or clear ACL pilot admin markers'),
            ('view_acl_admin_my_corp', 'Can view ACL pilot admin markers in own corporation'),
            ('view_acl_admin_my_alliance', 'Can view ACL pilot admin markers in own alliance'),
            ('view_acl_admin_all', 'Can view ACL pilot admin markers for all pilots'),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(acl_admin=False) | Q(entity_type=ENTITY_TYPE_PILOT),
                name='fg_access_rule_acl_admin_pilot_only',
            ),
        ]

    def __str__(self):
        action = 'DENY' if self.deny else 'ALLOW'
        return f'{action} {self.entity_type} {self.entity_id}'

    def save(self, *args, **kwargs):
        if self.entity_type != ENTITY_TYPE_PILOT:
            self.acl_admin = False
        if self.deny:
            self.acl_admin = False
        return super().save(*args, **kwargs)


def access_rule_snapshot(rule: AccessRule | None) -> dict[str, Any]:
    if rule is None:
        return {}
    return {
        'entity_id': rule.entity_id,
        'entity_type': rule.entity_type,
        'deny': rule.deny,
        'acl_admin': rule.acl_admin,
        'note': rule.note,
        'created_by': rule.created_by,
    }


class AccessRuleAudit(models.Model):
    """Append-only audit trail for FG ACL mutations."""

    acl_id = models.IntegerField(
        null=True,
        blank=True,
        help_text='ACL primary key at the time of the audit event.',
    )
    action = models.CharField(
        max_length=16,
        choices=ACL_AUDIT_ACTION_CHOICES,
    )
    actor_username = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Username that initiated the change.',
    )
    source = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='Originating FG surface (e.g. ACL UI or admin).',
    )
    entity_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text='EVE Online ID (alliance, corporation, or character) when tied to one ACL row.',
    )
    entity_type = models.CharField(
        max_length=16,
        choices=ENTITY_TYPE_CHOICES,
        null=True,
        blank=True,
    )
    deny = models.BooleanField(
        null=True,
        blank=True,
    )
    note = models.TextField(blank=True, default='')
    acl_created_by = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Original creator recorded on the active ACL row.',
    )
    previous = models.JSONField(
        blank=True,
        default=dict,
        help_text='Prior ACL row snapshot for update events.',
    )
    metadata = models.JSONField(
        blank=True,
        default=dict,
        help_text='Additional event context such as sync trigger and BG response summary.',
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fg_access_rule_audit'
        ordering = ['-occurred_at', '-id']
        verbose_name = 'access control audit entry'
        verbose_name_plural = 'access control audit log'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError('AccessRuleAudit entries are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError('AccessRuleAudit entries are append-only.')

    def __str__(self):
        if self.entity_type and self.entity_id is not None:
            return f'{self.action.upper()} {self.entity_type} {self.entity_id}'
        return f'{self.action.upper()} {self.source or "acl"}'


class PilotSnapshotHash(models.Model):
    """FG-side cache of per-account pilot snapshot hashes sent to BG."""

    pkid = models.BigIntegerField(
        unique=True,
        help_text='Stable FG/BG account identity key.',
    )
    pilot_data_hash = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        help_text='Hash of pilot snapshot payload for this account (md5 placeholder).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fg_pilot_snapshot_hash'
        ordering = ['pkid']
        verbose_name = 'pilot snapshot hash'
        verbose_name_plural = 'pilot snapshot hashes'

    def __str__(self):
        return f'{self.pkid}:{self.pilot_data_hash}'


def append_access_rule_audit(
    *,
    action: str,
    actor_username: str,
    rule: AccessRule | None = None,
    acl_id: int | None = None,
    source: str,
    previous: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    entity_id: int | None = None,
    entity_type: str | None = None,
    deny: bool | None = None,
    note: str | None = None,
    acl_created_by: str | None = None,
) -> AccessRuleAudit:
    if rule is not None:
        if acl_id is None:
            acl_id = getattr(rule, 'pk', None)
        if entity_id is None:
            entity_id = rule.entity_id
        if entity_type is None:
            entity_type = rule.entity_type
        if deny is None:
            deny = rule.deny
        if note is None:
            note = rule.note
        if acl_created_by is None:
            acl_created_by = rule.created_by

    return AccessRuleAudit.objects.create(
        acl_id=acl_id,
        action=action,
        actor_username=str(actor_username or ''),
        source=str(source or ''),
        entity_id=entity_id,
        entity_type=entity_type,
        deny=deny,
        note=str(note or ''),
        acl_created_by=str(acl_created_by or ''),
        previous=previous or {},
        metadata=metadata or {},
    )


__all__ = [
    'AccessRule',
    'AccessRuleAudit',
    'ACL_AUDIT_ACTION_CREATE',
    'ACL_AUDIT_ACTION_DELETE',
    'ACL_AUDIT_ACTION_SYNC',
    'ACL_AUDIT_ACTION_UPDATE',
    'ENTITY_TYPE_ALLIANCE',
    'ENTITY_TYPE_CORPORATION',
    'ENTITY_TYPE_PILOT',
    'MumbleUser',
    'MurmurModelLookupError',
    'MurmurModelResolver',
    'PilotSnapshotHash',
    'ResolvedMurmurModels',
    'access_rule_snapshot',
    'append_access_rule_audit',
    'resolve_murmur_model',
    'resolve_murmur_models',
]
