"""Resolve Murmur contract models from the configured Django app label."""

from __future__ import annotations

from django.apps import apps
from django.conf import settings

_DEFAULT_MODEL_APP_LABEL = 'mumble'


class MurmurModelResolver:
    """Resolve host-provided Murmur contract models without import-path coupling."""

    def __init__(self, *, app_label: str | None = None):
        configured_label = app_label or getattr(settings, 'MURMUR_MODEL_APP_LABEL', _DEFAULT_MODEL_APP_LABEL)
        self._primary_label = str(configured_label or _DEFAULT_MODEL_APP_LABEL).strip() or _DEFAULT_MODEL_APP_LABEL

    def _candidate_labels(self) -> list[str]:
        labels = [self._primary_label]
        fallback_label = str(getattr(settings, 'MURMUR_MODEL_FALLBACK_APP_LABEL', '') or '').strip()
        if fallback_label and fallback_label not in labels:
            labels.append(fallback_label)
        return labels

    def resolve(self, model_name: str):
        for app_label in self._candidate_labels():
            try:
                return apps.get_model(app_label, model_name, require_ready=False)
            except LookupError:
                continue
        raise LookupError(
            f'Unable to resolve Murmur model {model_name!r}. '
            f'Checked app labels: {", ".join(self._candidate_labels())}'
        )


_resolver = MurmurModelResolver()

try:
    MumbleServer = _resolver.resolve('MumbleServer')
    MumbleSession = _resolver.resolve('MumbleSession')
    MumbleUser = _resolver.resolve('MumbleUser')
except LookupError as exc:
    raise ImportError(
        'fg.models could not resolve Murmur contract models. '
        'Set MURMUR_MODEL_APP_LABEL (and optionally MURMUR_MODEL_FALLBACK_APP_LABEL).'
    ) from exc


__all__ = ['MumbleServer', 'MumbleSession', 'MumbleUser', 'MurmurModelResolver']
