"""OO host-integration entry points for mumble-fg consumers."""

from __future__ import annotations


class MurmurHostIntegration:
    """Host integration facade exposed to external Django projects."""

    host = 'generic'

    def __init__(self, *, host: str | None = None):
        resolved_host = host or self.host
        from fg.panels.service import ProfilePanelService

        self._panel_service = ProfilePanelService(host=resolved_host)

    def get_profile_panels(self, request):
        return self._panel_service.build_panels(request)


class CubeMurmurIntegration(MurmurHostIntegration):
    host = 'cube'


class AllianceAuthMurmurIntegration(MurmurHostIntegration):
    host = 'allianceauth'
