"""Host-agnostic and host-specific profile panel providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from django.urls import reverse

from fg.models import MumbleUser, MurmurModelLookupError
from fg.runtime import safe_list_servers, safe_pilot_registrations


@dataclass(frozen=True)
class MurmurPanelDescriptor:
    """Serializable profile panel descriptor used by host profile views."""

    key: str
    priority: int
    template: str
    server: Any
    account: Any
    temp_password: str | None
    username_with_slot: str | None
    display_name: str
    display_name_is_fallback: bool
    server_label: str
    server_hint: str
    server_address: str
    server_port: str
    is_admin: bool
    eligible_pilots: tuple[dict[str, Any], ...]
    show_pilot_selector: bool
    password_reset_url: str
    password_set_url: str

    def to_panel_context(self) -> dict[str, Any]:
        return {
            'key': self.key,
            'priority': self.priority,
            'template': self.template,
            'server': self.server,
            'account': self.account,
            'temp_password': self.temp_password,
            'username_with_slot': self.username_with_slot,
            'display_name': self.display_name,
            'display_name_is_fallback': self.display_name_is_fallback,
            'server_label': self.server_label,
            'server_hint': self.server_hint,
            'server_address': self.server_address,
            'server_port': self.server_port,
            'is_admin': self.is_admin,
            'eligible_pilots': list(self.eligible_pilots),
            'show_pilot_selector': self.show_pilot_selector,
            'password_reset_url': self.password_reset_url,
            'password_set_url': self.password_set_url,
        }


class ProfilePanelProvider(ABC):
    """Contract for host-specific panel providers."""

    provider_name = 'generic'
    panel_priority = 300
    panel_template = 'fg/panels/profile_panel.html'

    @abstractmethod
    def build_panels(self, request) -> list[dict[str, Any]]:
        """Return profile panel descriptors for the host app."""


class GenericProfilePanelProvider(ProfilePanelProvider):
    """Default profile panel provider usable by any host."""

    provider_name = 'generic'
    default_server_port = '64738'

    @staticmethod
    def _eligible_pilots(user) -> list[dict[str, Any]]:
        from fg.views import profile_password_pilot_choices

        return profile_password_pilot_choices(user)

    def _active_servers(self):
        return safe_list_servers()

    def _accounts_by_server(self, user_id: int) -> dict[int, Any]:
        try:
            return {
                mumble_user.server_id: mumble_user
                for mumble_user in MumbleUser.objects.filter(user_id=user_id).select_related('server')
            }
        except MurmurModelLookupError:
            return {
                registration.server_id: registration
                for registration in safe_pilot_registrations(user_id, servers=self._active_servers())
            }

    @staticmethod
    def _server_label(server) -> str:
        return str(getattr(server, 'name', '') or '').strip() or str(getattr(server, 'address', '') or '').strip() or f'server-{server.pk}'

    @staticmethod
    def _server_hint(server) -> str:
        explicit_name = str(getattr(server, 'name', '') or '').strip()
        if explicit_name:
            return explicit_name
        return str(getattr(server, 'address', '') or '').strip()

    @staticmethod
    def _server_address_port(server) -> tuple[str, str]:
        if server is None:
            return '', ''
        raw_address = str(getattr(server, 'address', '') or '').strip()
        if not raw_address:
            return '', ''
        address = raw_address
        port = ''

        if '://' in raw_address:
            parsed = urlparse(raw_address)
            host = str(parsed.hostname or '').strip()
            if host:
                address = host
            if parsed.port:
                port = str(parsed.port)

        if not port and address.startswith('['):
            if ']:' in address:
                end = address.find(']')
                host = address[1:end]
                parsed_port = address[end + 2 :].strip()
                return host, parsed_port or GenericProfilePanelProvider.default_server_port
            if address.endswith(']'):
                return address[1:-1].strip(), GenericProfilePanelProvider.default_server_port

        if not port and ':' in address and address.count(':') == 1:
            host, parsed_port = address.rsplit(':', 1)
            if parsed_port.isdigit():
                return str(host).strip(), parsed_port

        return address, port or GenericProfilePanelProvider.default_server_port

    def _panel_descriptor(
        self,
        *,
        request,
        server,
        account,
        eligible_pilots: list[dict[str, Any]],
    ) -> MurmurPanelDescriptor:
        display_name, display_name_is_fallback = self._display_name(
            request.user,
            account=account,
            eligible_pilots=eligible_pilots,
        )
        username_with_slot = None
        if account is not None:
            username = str(getattr(account, 'username', '') or '').strip()
            if username:
                username_with_slot = username
        if not username_with_slot:
            username_with_slot = display_name or None
        if not username_with_slot and eligible_pilots:
            username_with_slot = str(eligible_pilots[0].get('character_name') or '').strip() or None
        server_address, server_port = self._server_address_port(server)

        return MurmurPanelDescriptor(
            key=f'murmur-server-{getattr(server, "pk", "profile")}',
            priority=self.panel_priority,
            template=self.panel_template,
            server=server,
            account=account,
            temp_password=request.session.pop('murmur_temp_password', None),
            username_with_slot=username_with_slot,
            display_name=display_name,
            display_name_is_fallback=display_name_is_fallback,
            server_label=self._server_label(server) if server is not None else 'Mumble Authentication',
            server_hint=self._server_hint(server) if server is not None else 'Profile password panel',
            server_address=server_address,
            server_port=server_port,
            is_admin=bool(getattr(account, 'is_mumble_admin', False)),
            eligible_pilots=tuple(eligible_pilots),
            show_pilot_selector=len(eligible_pilots) > 1,
            password_reset_url=reverse('mumble:profile_reset_password'),
            password_set_url=reverse('mumble:profile_set_password'),
        )

    @staticmethod
    def _display_name(user, *, account, eligible_pilots: list[dict[str, Any]]) -> tuple[str, bool]:
        stored = str(getattr(account, 'display_name', '') or '').strip()
        if stored:
            return stored, False

        try:
            from fg.views import _compute_display_name

            computed = str(_compute_display_name(user) or '').strip()
            if computed:
                return computed, False
        except Exception:  # noqa: BLE001
            pass

        if eligible_pilots:
            return str(eligible_pilots[0].get('character_name') or ''), True
        return '', True

    def build_panels(self, request) -> list[dict[str, Any]]:
        eligible_pilots = self._eligible_pilots(request.user)
        if not eligible_pilots:
            return []

        servers = self._active_servers()
        if not servers:
            return [
                self._panel_descriptor(
                    request=request,
                    server=None,
                    account=None,
                    eligible_pilots=eligible_pilots,
                ).to_panel_context()
            ]

        target_user_id = request.user.id
        try:
            from fg.views import _resolve_bg_pkid_for_mockui

            if eligible_pilots:
                primary_character_id = str(eligible_pilots[0].get('character_id') or '')
                mapped_pkid = _resolve_bg_pkid_for_mockui(request.user, primary_character_id)
                if mapped_pkid is not None:
                    target_user_id = int(mapped_pkid)
        except Exception:  # noqa: BLE001
            # Fall back to host user id when mock-only mapping is unavailable.
            target_user_id = request.user.id

        accounts_by_server = self._accounts_by_server(target_user_id)
        descriptors: list[MurmurPanelDescriptor] = []
        for server in servers:
            account = accounts_by_server.get(server.pk)
            descriptors.append(
                self._panel_descriptor(
                    request=request,
                    server=server,
                    account=account,
                    eligible_pilots=eligible_pilots,
                )
            )

        return [descriptor.to_panel_context() for descriptor in descriptors]


class CubeProfilePanelProvider(GenericProfilePanelProvider):
    """Cube adapter: currently uses generic behavior with dedicated identity."""

    provider_name = 'cube'


class AllianceAuthProfilePanelProvider(GenericProfilePanelProvider):
    """AllianceAuth adapter: currently uses generic behavior with dedicated identity."""

    provider_name = 'allianceauth'
