"""Resolve Murmur contract models without hard-failing at import time."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, NamedTuple

from django.apps import apps
from django.conf import settings

_DEFAULT_MODEL_APP_LABEL = 'mumble'


class MurmurModelLookupError(LookupError):
    """Raised when the configured Murmur contract models are unavailable."""


class ResolvedMurmurModels(NamedTuple):
    MumbleServer: Any
    MumbleSession: Any
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
        MumbleServer=resolver.resolve('MumbleServer'),
        MumbleSession=resolver.resolve('MumbleSession'),
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


MumbleServer = LazyMurmurModel('MumbleServer')
MumbleSession = LazyMurmurModel('MumbleSession')
MumbleUser = LazyMurmurModel('MumbleUser')


__all__ = [
    'MumbleServer',
    'MumbleSession',
    'MumbleUser',
    'MurmurModelLookupError',
    'MurmurModelResolver',
    'ResolvedMurmurModels',
    'resolve_murmur_model',
    'resolve_murmur_models',
]
