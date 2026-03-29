from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.db import transaction
from django.utils.dateparse import parse_datetime

from fg.host import get_host_adapter
from fg.models import (
    CubeGroupMapping,
    IgnoredCubeGroup,
    IgnoredMurmurGroup,
    MurmurInventorySnapshot,
    MumbleUser,
    MurmurModelLookupError,
)
from fg.runtime import safe_pilot_registrations


def normalize_cube_group_name(name: str) -> str:
    return str(name or '').strip()


def all_cube_group_names() -> list[str]:
    adapter = get_host_adapter()
    groups = getattr(adapter, 'list_groups', lambda: [])()
    return sorted(
        {
            normalize_cube_group_name(getattr(group, 'name', '') or '')
            for group in groups
            if normalize_cube_group_name(getattr(group, 'name', '') or '')
        },
        key=str.lower,
    )


def ignored_cube_group_names() -> set[str]:
    return set(IgnoredCubeGroup.objects.values_list('cube_group_name', flat=True))


def ignored_murmur_group_names() -> set[str]:
    return set(IgnoredMurmurGroup.objects.values_list('murmur_group_name', flat=True))


def mapping_rows_by_cube_group() -> dict[str, list[CubeGroupMapping]]:
    rows: dict[str, list[CubeGroupMapping]] = defaultdict(list)
    for row in CubeGroupMapping.objects.all().order_by('cube_group_name', 'murmur_group_name'):
        rows[row.cube_group_name].append(row)
    return rows


def mapped_murmur_groups_for_cube_group(cube_group_name: str) -> list[str]:
    return list(
        CubeGroupMapping.objects.filter(cube_group_name=cube_group_name)
        .order_by('murmur_group_name')
        .values_list('murmur_group_name', flat=True)
    )


def build_group_mapping_config() -> tuple[set[str], set[str], dict[str, list[CubeGroupMapping]]]:
    return (
        ignored_cube_group_names(),
        ignored_murmur_group_names(),
        mapping_rows_by_cube_group(),
    )


def effective_murmur_groups_for_user(user, *, mumble_user=None, _config=None) -> list[str]:
    adapter = get_host_adapter()
    parts: list[str] = []
    main = adapter.get_main_character(user)
    if main:
        if getattr(main, 'alliance_name', None):
            parts.append(str(main.alliance_name).replace(' ', '_'))
        if getattr(main, 'corporation_name', None):
            parts.append(str(main.corporation_name).replace(' ', '_'))

    if adapter.user_is_member(user):
        parts.append('Member')

    if _config is not None:
        ignored_cube, ignored_murmur, mapping_by_group = _config
    else:
        ignored_cube, ignored_murmur, mapping_by_group = build_group_mapping_config()

    for membership in adapter.get_approved_group_memberships(user):
        cube_group_name = normalize_cube_group_name(getattr(getattr(membership, 'group', None), 'name', '') or '')
        if not cube_group_name or cube_group_name in ignored_cube:
            continue

        mappings = mapping_by_group.get(cube_group_name, [])
        if not mappings:
            parts.append(cube_group_name.replace(' ', '-'))
            continue

        for mapping in mappings:
            murmur_group_name = str(mapping.murmur_group_name or '').strip()
            if murmur_group_name and murmur_group_name not in ignored_murmur:
                parts.append(murmur_group_name)

    if mumble_user and getattr(mumble_user, 'is_mumble_admin', False):
        parts.append('admin')

    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part and part not in seen:
            deduped.append(part)
            seen.add(part)
    return deduped


def effective_groups_csv_for_user(user, *, mumble_user=None, _config=None) -> str:
    return ','.join(effective_murmur_groups_for_user(user, mumble_user=mumble_user, _config=_config))


def user_has_mumble_admin_bypass(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    try:
        return MumbleUser.objects.filter(user=user, is_mumble_admin=True).exists()
    except MurmurModelLookupError:
        return any(registration.is_mumble_admin for registration in safe_pilot_registrations(int(user.pk)))


@transaction.atomic
def store_inventory_snapshot(payload: dict[str, Any]) -> MurmurInventorySnapshot:
    fetched_at_raw = payload.get('fetched_at')
    fetched_at = fetched_at_raw if fetched_at_raw is None else parse_datetime(str(fetched_at_raw))
    snapshot, _created = MurmurInventorySnapshot.objects.update_or_create(
        server_id=int(payload.get('server_id')),
        defaults={
            'server_name': str(payload.get('server_label', '') or ''),
            'freshness_seconds': int(payload.get('freshness_seconds') or 600),
            'is_real_time': bool(payload.get('is_real_time')),
            'fetched_at': fetched_at,
            'inventory': payload.get('inventory') or {},
        },
    )
    return snapshot
