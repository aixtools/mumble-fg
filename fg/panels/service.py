"""Public OO service entrypoint for host profile panel integration."""

from __future__ import annotations


class ProfilePanelService:
    """Thin service facade that delegates to configured provider objects."""

    def __init__(self, host: str | None = None):
        self._host = host

    def build_panels(self, request):
        from .registry import get_profile_panel_provider

        provider = get_profile_panel_provider(self._host)
        return provider.build_panels(request)


def build_profile_panels(request, *, host: str | None = None):
    return ProfilePanelService(host=host).build_panels(request)
