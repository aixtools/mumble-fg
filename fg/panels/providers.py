"""Host-agnostic and host-specific profile panel providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fg.models import MumbleServer, MumbleUser


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
    server_label: str
    server_hint: str

    def to_panel_context(self) -> dict[str, Any]:
        return {
            'key': self.key,
            'priority': self.priority,
            'template': self.template,
            'server': self.server,
            'account': self.account,
            'temp_password': self.temp_password,
            'username_with_slot': self.username_with_slot,
            'server_label': self.server_label,
            'server_hint': self.server_hint,
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

    def _active_servers(self):
        return list(MumbleServer.objects.filter(is_active=True).order_by('display_order', 'name'))

    def _accounts_by_server(self, user_id: int) -> dict[int, Any]:
        return {
            mumble_user.server_id: mumble_user
            for mumble_user in MumbleUser.objects.filter(user_id=user_id).select_related('server')
        }

    def _slot_labels(self, accounts_by_server: dict[int, Any]) -> dict[int, str | None]:
        usernames: dict[str, list[int]] = defaultdict(list)
        for server_id, account in accounts_by_server.items():
            username = str(getattr(account, 'username', '') or '').strip()
            if username:
                usernames[username].append(server_id)

        labels: dict[int, str | None] = {server_id: None for server_id in accounts_by_server}
        for server_ids in usernames.values():
            if len(server_ids) <= 1:
                continue
            for slot, server_id in enumerate(sorted(server_ids), start=1):
                labels[server_id] = f':{slot}'
        return labels

    @staticmethod
    def _server_label(server) -> str:
        return str(getattr(server, 'name', '') or '').strip() or str(getattr(server, 'address', '') or '').strip() or f'server-{server.pk}'

    @staticmethod
    def _server_hint(server) -> str:
        explicit_name = str(getattr(server, 'name', '') or '').strip()
        if explicit_name:
            return explicit_name
        return str(getattr(server, 'address', '') or '').strip()

    def build_panels(self, request) -> list[dict[str, Any]]:
        servers = self._active_servers()
        if not servers:
            return []

        accounts_by_server = self._accounts_by_server(request.user.id)
        slot_labels = self._slot_labels(accounts_by_server)

        descriptors: list[MurmurPanelDescriptor] = []
        for server in servers:
            account = accounts_by_server.get(server.pk)
            slot_suffix = slot_labels.get(server.pk)
            username_with_slot = None
            if account is not None:
                username = str(getattr(account, 'username', '') or '').strip()
                if username:
                    username_with_slot = f'{username}{slot_suffix or ""}'
            descriptors.append(
                MurmurPanelDescriptor(
                    key=f'murmur-server-{server.pk}',
                    priority=self.panel_priority,
                    template=self.panel_template,
                    server=server,
                    account=account,
                    temp_password=request.session.pop(f'murmur_temp_password_{server.pk}', None),
                    username_with_slot=username_with_slot,
                    server_label=self._server_label(server),
                    server_hint=self._server_hint(server),
                )
            )

        return [descriptor.to_panel_context() for descriptor in descriptors]


class CubeProfilePanelProvider(GenericProfilePanelProvider):
    """Cube adapter: currently uses generic behavior with dedicated identity."""

    provider_name = 'cube'


class AllianceAuthProfilePanelProvider(GenericProfilePanelProvider):
    """AllianceAuth adapter: currently uses generic behavior with dedicated identity."""

    provider_name = 'allianceauth'
