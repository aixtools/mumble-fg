"""Provider registry for host profile panel adapters."""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings

from .providers import (
    AllianceAuthProfilePanelProvider,
    CubeProfilePanelProvider,
    GenericProfilePanelProvider,
    ProfilePanelProvider,
)

ProviderFactory = Callable[[], ProfilePanelProvider]


class ProfilePanelProviderRegistry:
    """OO registry used to resolve host-specific panel providers."""

    def __init__(self):
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, host: str, factory: ProviderFactory):
        key = str(host or 'generic').strip().lower() or 'generic'
        self._factories[key] = factory

    def resolve(self, host: str | None = None) -> ProfilePanelProvider:
        resolved_host = host or getattr(settings, 'MURMUR_PANEL_HOST', None) or 'generic'
        key = str(resolved_host).strip().lower() or 'generic'
        factory = self._factories.get(key) or self._factories.get('generic')
        if factory is None:
            raise RuntimeError('No profile panel provider is registered for generic host')
        return factory()


_REGISTRY = ProfilePanelProviderRegistry()
_REGISTRY.register('generic', GenericProfilePanelProvider)
_REGISTRY.register('cube', CubeProfilePanelProvider)
_REGISTRY.register('allianceauth', AllianceAuthProfilePanelProvider)


def register_profile_panel_provider(host: str, factory: ProviderFactory):
    _REGISTRY.register(host, factory)


def get_profile_panel_provider(host: str | None = None) -> ProfilePanelProvider:
    return _REGISTRY.resolve(host)
