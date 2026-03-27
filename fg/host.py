"""Settings-driven host adapter helpers for mumble-fg."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string

_BUILTIN_HOST_ADAPTERS = {
    'generic': 'fg.host.GenericMurmurHostAdapter',
    'cube': 'fg.host.CubeMurmurHostAdapter',
    'allianceauth': 'fg.host.AllianceAuthMurmurHostAdapter',
}


class GenericMurmurHostAdapter:
    """Host adapter with no product-specific account or permission assumptions."""

    adapter_name = 'generic'

    def get_main_character(self, user) -> Any | None:
        return None

    def get_approved_group_memberships(self, user) -> list[Any]:
        return []

    def list_groups(self) -> list[Any]:
        return []

    def user_is_alliance_leader(self, user) -> bool:
        return False

    def user_is_member(self, user) -> bool:
        return False

    def has_alliance_leader_membership(self, user) -> bool:
        return False

    def get_alliance_ticker(self, alliance_id: int | None) -> str:
        return ''

    def get_corporation_ticker(self, corporation_id: int | None) -> str:
        return ''


class CubeMurmurHostAdapter(GenericMurmurHostAdapter):
    """Cube-style adapter that resolves optional host integrations lazily."""

    adapter_name = 'cube'

    def _accounts_models_module(self):
        import accounts.models as accounts_models

        return accounts_models

    def user_is_member(self, user) -> bool:
        try:
            accounts_models = self._accounts_models_module()
        except ImportError:
            return False
        UserProfile = getattr(accounts_models, 'UserProfile', None)
        if UserProfile is None:
            return False
        return UserProfile.objects.filter(user=user, is_member=True).exists()

    def get_main_character(self, user) -> Any | None:
        try:
            accounts_models = self._accounts_models_module()
        except ImportError:
            return None
        EveCharacter = getattr(accounts_models, 'EveCharacter', None)
        if EveCharacter is None:
            return None
        return EveCharacter.objects.filter(user=user, is_main=True).first()

    def get_approved_group_memberships(self, user) -> list[Any]:
        try:
            accounts_models = self._accounts_models_module()
        except ImportError:
            return []
        GroupMembership = getattr(accounts_models, 'GroupMembership', None)
        if GroupMembership is None:
            return []
        return list(
            GroupMembership.objects.filter(user=user, status='approved').select_related('group')
        )

    def list_groups(self) -> list[Any]:
        try:
            accounts_models = self._accounts_models_module()
        except ImportError:
            return []
        Group = getattr(accounts_models, 'Group', None)
        if Group is None:
            return []
        return list(Group.objects.order_by('name'))

    def user_is_alliance_leader(self, user) -> bool:
        try:
            from modules.corporation.core import _user_is_alliance_leader
        except ImportError:
            return False
        return bool(_user_is_alliance_leader(user))

    def has_alliance_leader_membership(self, user) -> bool:
        if not getattr(user, 'is_authenticated', False):
            return False

        try:
            accounts_models = self._accounts_models_module()
            from modules.corporation.models import CorporationSettings
        except ImportError:
            return False
        GroupMembership = getattr(accounts_models, 'GroupMembership', None)
        if GroupMembership is None:
            return False

        alliance_groups = CorporationSettings.load().alliance_leader_groups.all()
        if not alliance_groups:
            return False

        return GroupMembership.objects.filter(
            user=user,
            status='approved',
            group__in=alliance_groups,
        ).exists()

    def get_alliance_ticker(self, alliance_id: int | None) -> str:
        if not alliance_id:
            return ''
        try:
            accounts_models = self._accounts_models_module()
        except ImportError:
            return ''
        EveAllianceInfo = getattr(accounts_models, 'EveAllianceInfo', None)
        if EveAllianceInfo is None:
            return ''
        row = EveAllianceInfo.objects.filter(alliance_id=alliance_id).only('alliance_ticker').first()
        return str(getattr(row, 'alliance_ticker', '') or '')

    def get_corporation_ticker(self, corporation_id: int | None) -> str:
        if not corporation_id:
            return ''
        try:
            accounts_models = self._accounts_models_module()
        except ImportError:
            return ''
        EveCorporationInfo = getattr(accounts_models, 'EveCorporationInfo', None)
        if EveCorporationInfo is None:
            return ''
        row = EveCorporationInfo.objects.filter(corporation_id=corporation_id).only('corporation_ticker').first()
        return str(getattr(row, 'corporation_ticker', '') or '')


class AllianceAuthMurmurHostAdapter(GenericMurmurHostAdapter):
    """Placeholder adapter for AllianceAuth-style hosts."""

    adapter_name = 'allianceauth'


def _configured_host_adapter_path() -> str:
    explicit_adapter = str(getattr(settings, 'MURMUR_HOST_ADAPTER', '') or '').strip()
    if explicit_adapter:
        return explicit_adapter

    host = str(getattr(settings, 'MURMUR_PANEL_HOST', '') or 'cube').strip().lower() or 'cube'
    return _BUILTIN_HOST_ADAPTERS.get(host, _BUILTIN_HOST_ADAPTERS['cube'])


@lru_cache(maxsize=None)
def _build_host_adapter(adapter_path: str):
    adapter_class = import_string(adapter_path)
    return adapter_class()


def get_host_adapter():
    return _build_host_adapter(_configured_host_adapter_path())


__all__ = [
    'AllianceAuthMurmurHostAdapter',
    'CubeMurmurHostAdapter',
    'GenericMurmurHostAdapter',
    'get_host_adapter',
]
