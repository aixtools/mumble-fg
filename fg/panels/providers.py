"""Host-agnostic and host-specific profile panel providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

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
    server_label: str
    server_hint: str
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
            'server_label': self.server_label,
            'server_hint': self.server_hint,
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

    def _panel_descriptor(
        self,
        *,
        request,
        server,
        account,
        slot_suffix,
        eligible_pilots: list[dict[str, Any]],
    ) -> MurmurPanelDescriptor:
        username_with_slot = None
        if account is not None:
            username = str(getattr(account, 'username', '') or '').strip()
            if username:
                username_with_slot = f'{username}{slot_suffix or ""}'

        return MurmurPanelDescriptor(
            key=f'murmur-server-{getattr(server, "pk", "profile")}',
            priority=self.panel_priority,
            template=self.panel_template,
            server=server,
            account=account,
            temp_password=request.session.pop('murmur_temp_password', None),
            username_with_slot=username_with_slot,
            server_label=self._server_label(server) if server is not None else 'Mumble Authentication',
            server_hint=self._server_hint(server) if server is not None else 'Profile password panel',
            eligible_pilots=tuple(eligible_pilots),
            show_pilot_selector=len(eligible_pilots) > 1,
            password_reset_url=reverse('mumble:profile_reset_password'),
            password_set_url=reverse('mumble:profile_set_password'),
        )

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
                    slot_suffix=None,
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
        slot_labels = self._slot_labels(accounts_by_server)

        descriptors: list[MurmurPanelDescriptor] = []
        for server in servers:
            account = accounts_by_server.get(server.pk)
            descriptors.append(
                self._panel_descriptor(
                    request=request,
                    server=server,
                    account=account,
                    slot_suffix=slot_labels.get(server.pk),
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
