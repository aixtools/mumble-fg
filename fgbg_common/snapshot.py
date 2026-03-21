"""Shared account-oriented pilot snapshot contract for FG/BG transport."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping


def _coerce_int(value: Any, *, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field_name} must be an integer') from exc


def _coerce_optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _coerce_int(value, field_name=field_name)


def _coerce_text(value: Any, *, field_name: str) -> str:
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError(f'{field_name} must be a string')
    return value


def _coerce_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f'{field_name} must be a boolean')


@dataclass(frozen=True)
class PilotCharacter:
    character_id: int
    character_name: str
    corporation_id: int | None = None
    corporation_name: str = ''
    alliance_id: int | None = None
    alliance_name: str = ''
    is_main: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> 'PilotCharacter':
        return cls(
            character_id=_coerce_int(payload.get('character_id'), field_name='character_id'),
            character_name=_coerce_text(payload.get('character_name'), field_name='character_name'),
            corporation_id=_coerce_optional_int(payload.get('corporation_id'), field_name='corporation_id'),
            corporation_name=_coerce_text(payload.get('corporation_name', ''), field_name='corporation_name'),
            alliance_id=_coerce_optional_int(payload.get('alliance_id'), field_name='alliance_id'),
            alliance_name=_coerce_text(payload.get('alliance_name', ''), field_name='alliance_name'),
            is_main=_coerce_bool(payload.get('is_main', False), field_name='is_main'),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            'character_id': self.character_id,
            'character_name': self.character_name,
            'corporation_id': self.corporation_id,
            'corporation_name': self.corporation_name,
            'alliance_id': self.alliance_id,
            'alliance_name': self.alliance_name,
            'is_main': self.is_main,
        }


@dataclass(frozen=True)
class PilotAccount:
    pkid: int
    characters: tuple[PilotCharacter, ...]
    display_name: str = ''

    def __post_init__(self):
        if not self.characters:
            raise ValueError('PilotAccount.characters must not be empty')

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> 'PilotAccount':
        pkid = _coerce_int(payload.get('pkid', payload.get('user_id')), field_name='pkid')
        display_name = _coerce_text(payload.get('display_name', ''), field_name='display_name')
        raw_characters = payload.get('characters')
        if not isinstance(raw_characters, (list, tuple)):
            raise ValueError('characters must be a list')
        characters = tuple(_normalize_characters(PilotCharacter.from_mapping(item) for item in raw_characters))
        return cls(pkid=pkid, display_name=display_name, characters=characters)

    @property
    def main_character(self) -> PilotCharacter:
        for character in self.characters:
            if character.is_main:
                return character
        return self.characters[0]

    def as_dict(self) -> dict[str, Any]:
        return {
            'pkid': self.pkid,
            'display_name': self.display_name,
            'characters': [character.as_dict() for character in self.characters],
        }


def _character_sort_key(character: PilotCharacter) -> tuple[int, str, int]:
    return (0 if character.is_main else 1, character.character_name.lower(), character.character_id)


def _normalize_characters(characters: Iterable[PilotCharacter]) -> list[PilotCharacter]:
    by_character_id: dict[int, PilotCharacter] = {}
    for character in characters:
        existing = by_character_id.get(character.character_id)
        if existing is None:
            by_character_id[character.character_id] = character
            continue
        if not existing.is_main and character.is_main:
            by_character_id[character.character_id] = character
    ordered = sorted(by_character_id.values(), key=_character_sort_key)
    if not ordered:
        return []
    if not any(character.is_main for character in ordered):
        first = ordered[0]
        ordered[0] = PilotCharacter(
            character_id=first.character_id,
            character_name=first.character_name,
            corporation_id=first.corporation_id,
            corporation_name=first.corporation_name,
            alliance_id=first.alliance_id,
            alliance_name=first.alliance_name,
            is_main=True,
        )
    return ordered


@dataclass(frozen=True)
class PilotSnapshot:
    accounts: tuple[PilotAccount, ...]
    generated_at: str = ''

    @classmethod
    def empty(cls) -> 'PilotSnapshot':
        return cls(accounts=(), generated_at='')

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> 'PilotSnapshot':
        raw_accounts = payload.get('accounts')
        if not isinstance(raw_accounts, (list, tuple)):
            raise ValueError('accounts must be a list')
        accounts = tuple(
            sorted(
                (PilotAccount.from_mapping(account) for account in raw_accounts),
                key=lambda account: account.pkid,
            )
        )
        generated_at = payload.get('generated_at', '')
        if generated_at is None:
            generated_at = ''
        if not isinstance(generated_at, str):
            raise ValueError('generated_at must be a string')
        return cls(accounts=accounts, generated_at=generated_at)

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[Mapping[str, Any]],
        *,
        generated_at: str = '',
    ) -> 'PilotSnapshot':
        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            pkid = _coerce_int(row.get('pkid', row.get('user_id')), field_name='pkid')
            bucket = grouped.setdefault(
                pkid,
                {
                    'display_name': _coerce_text(row.get('display_name', ''), field_name='display_name'),
                    'characters': [],
                },
            )
            if not bucket['display_name']:
                bucket['display_name'] = _coerce_text(row.get('display_name', ''), field_name='display_name')
            bucket['characters'].append(
                PilotCharacter(
                    character_id=_coerce_int(row.get('character_id'), field_name='character_id'),
                    character_name=_coerce_text(row.get('character_name', ''), field_name='character_name'),
                    corporation_id=_coerce_optional_int(row.get('corporation_id'), field_name='corporation_id'),
                    corporation_name=_coerce_text(row.get('corporation_name', ''), field_name='corporation_name'),
                    alliance_id=_coerce_optional_int(row.get('alliance_id'), field_name='alliance_id'),
                    alliance_name=_coerce_text(row.get('alliance_name', ''), field_name='alliance_name'),
                    is_main=bool(row.get('is_main', False)),
                )
            )
        accounts = tuple(
            PilotAccount(
                pkid=pkid,
                display_name=str(bucket['display_name'] or ''),
                characters=tuple(_normalize_characters(bucket['characters'])),
            )
            for pkid, bucket in sorted(grouped.items())
        )
        return cls(accounts=accounts, generated_at=generated_at)

    @property
    def account_count(self) -> int:
        return len(self.accounts)

    @property
    def character_count(self) -> int:
        return sum(len(account.characters) for account in self.accounts)

    def as_dict(self) -> dict[str, Any]:
        return {
            'generated_at': self.generated_at,
            'accounts': [account.as_dict() for account in self.accounts],
        }

    def fingerprint(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def summary(self) -> dict[str, Any]:
        summary = {
            'account_count': self.account_count,
            'character_count': self.character_count,
            'fingerprint': self.fingerprint(),
        }
        if self.generated_at:
            summary['generated_at'] = self.generated_at
        return summary
