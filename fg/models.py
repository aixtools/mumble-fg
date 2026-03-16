"""FG-owned models and Murmur contract model resolution."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, NamedTuple

from django.apps import apps
from django.conf import settings
from django.db import models

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

    def __str__(self):
        action = 'DENY' if self.deny else 'ALLOW'
        return f'{action} {self.entity_type} {self.entity_id}'


__all__ = [
    'AccessRule',
    'ENTITY_TYPE_ALLIANCE',
    'ENTITY_TYPE_CORPORATION',
    'ENTITY_TYPE_PILOT',
    'MumbleUser',
    'MurmurModelLookupError',
    'MurmurModelResolver',
    'ResolvedMurmurModels',
    'resolve_murmur_model',
    'resolve_murmur_models',
]
