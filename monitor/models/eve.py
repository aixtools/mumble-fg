from __future__ import annotations

"""Domain objects for EVE entities from AUTH, CUBE, or EveUniverse sources."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Iterable, Literal, Mapping, Optional, Protocol

SourceApp = Literal["AUTH", "CUBE", "EVEUNIVERSE"]


def _pick(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return None


def _to_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class EveObject:
    """
    Root object for EVE entities.

    `source_model` stores the source descriptor (table/model/interface).
    """

    source_app: SourceApp
    source_model: str
    source_pk: int | str


@dataclass(frozen=True)
class EveNamed(EveObject):
    """Common identity fields shared across EVE entities."""

    id: int
    name: str


@dataclass(frozen=True)
class EveOrg(EveNamed):
    """Organization base with optional ticker."""

    ticker: Optional[str] = None


@dataclass(frozen=True)
class EveAlliance(EveOrg):
    """Alliance domain object."""

    executor_corp_id: Optional[int] = None
    raw: Any | None = None

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EveAlliance":
        alliance_id = _to_int(_pick(record, "alliance_id", "id"))
        if alliance_id is None:
            raise ValueError("alliance_id or id is required")
        source_pk = _pick(record, "source_pk", "id", "alliance_id")
        if source_pk is None:
            source_pk = alliance_id
        ticker = _pick(record, "alliance_ticker", "ticker")
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            id=alliance_id,
            name=_to_str(_pick(record, "alliance_name", "name")),
            ticker=str(ticker) if ticker is not None else None,
            executor_corp_id=_to_int(_pick(record, "executor_corp_id")),
            raw=raw,
        )


@dataclass(frozen=True)
class EveAllianceRef(EveOrg):
    """Lightweight alliance reference (id, name, ticker only)."""

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        source_pk: int | str,
    ) -> "EveAllianceRef":
        alliance_id = _to_int(_pick(record, "alliance_id", "id"))
        if alliance_id is None:
            raise ValueError("alliance_id or id is required")
        ticker = _pick(record, "alliance_ticker", "ticker")
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            id=alliance_id,
            name=_to_str(_pick(record, "alliance_name", "name")),
            ticker=str(ticker) if ticker is not None else None,
        )


@dataclass(frozen=True)
class EveCorporationRef(EveOrg):
    """Lightweight corporation reference (id, name, ticker only)."""

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        source_pk: int | str,
    ) -> "EveCorporationRef":
        corporation_id = _to_int(_pick(record, "corporation_id", "id"))
        if corporation_id is None:
            raise ValueError("corporation_id or id is required")
        ticker = _pick(record, "corporation_ticker", "ticker")
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            id=corporation_id,
            name=_to_str(_pick(record, "corporation_name", "name")),
            ticker=str(ticker) if ticker is not None else None,
        )


@dataclass(frozen=True)
class EveCorporation(EveOrg):
    """Corporation domain object."""

    member_count: Optional[int] = None
    ceo_id: Optional[int] = None
    alliance: Optional[EveAllianceRef] = None
    raw: Any | None = None

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EveCorporation":
        corporation_id = _to_int(_pick(record, "corporation_id", "id"))
        if corporation_id is None:
            raise ValueError("corporation_id or id is required")
        source_pk = _pick(record, "source_pk", "id", "corporation_id")
        if source_pk is None:
            source_pk = corporation_id
        ticker = _pick(record, "corporation_ticker", "ticker")
        alliance = None
        if _pick(record, "alliance_id") is not None:
            alliance = EveAllianceRef.from_record(
                record,
                source_app=source_app,
                source_model=source_model,
                source_pk=source_pk,
            )
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            id=corporation_id,
            name=_to_str(_pick(record, "corporation_name", "name")),
            ticker=str(ticker) if ticker is not None else None,
            member_count=_to_int(_pick(record, "member_count")),
            ceo_id=_to_int(_pick(record, "ceo_id")),
            alliance=alliance,
            raw=raw,
        )


@dataclass(frozen=True)
class EveItemType(EveNamed):
    """Type-level metadata for an EVE item."""

    group_id: Optional[int] = None
    category_id: Optional[int] = None
    volume: Optional[float] = None
    packaged_volume: Optional[float] = None
    raw: Any | None = None

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EveItemType":
        type_id = _to_int(_pick(record, "type_id", "eve_type_id", "id"))
        if type_id is None:
            raise ValueError("type_id or eve_type_id or id is required")
        source_pk = _pick(record, "source_pk", "id", "eve_type_id", "type_id")
        if source_pk is None:
            source_pk = type_id
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            id=type_id,
            name=_to_str(_pick(record, "type_name", "item_name", "name")),
            group_id=_to_int(_pick(record, "group_id")),
            category_id=_to_int(_pick(record, "category_id")),
            volume=_to_float(_pick(record, "volume")),
            packaged_volume=_to_float(_pick(record, "packaged_volume")),
            raw=raw,
        )


@dataclass(frozen=True)
class EveItemStack(EveObject):
    """A quantity-bearing item row owned by a pilot."""

    character_id: int
    item_type: EveItemType
    quantity: int = 0
    raw: Any | None = None

    @property
    def type_id(self) -> int:
        return self.item_type.id

    @property
    def type_name(self) -> str:
        return self.item_type.name

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EveItemStack":
        character_id = _to_int(_pick(record, "character_id"))
        if character_id is None:
            raise ValueError("character_id is required")
        item_type = EveItemType.from_record(
            record,
            source_app=source_app,
            source_model=source_model,
            raw=raw,
        )
        source_pk = _pick(record, "source_pk", "id")
        if source_pk is None:
            source_pk = f"{character_id}:{item_type.id}"
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            character_id=character_id,
            item_type=item_type,
            quantity=_to_int(_pick(record, "quantity", "qty", "amount"), 0) or 0,
            raw=raw,
        )


@dataclass(frozen=True)
class EveAssetItem(EveItemStack):
    """Asset-level item row with location and blueprint metadata."""

    item_id: Optional[int] = None
    item_name: str = ""
    location_id: Optional[int] = None
    location_name: Optional[str] = None
    location_flag: Optional[str] = None
    is_blueprint_copy: Optional[bool] = None
    is_singleton: Optional[bool] = None

    @property
    def display_name(self) -> str:
        return self.item_name or self.type_name

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EveAssetItem":
        stack = EveItemStack.from_record(
            record,
            source_app=source_app,
            source_model=source_model,
            raw=raw,
        )
        return cls(
            source_app=stack.source_app,
            source_model=stack.source_model,
            source_pk=stack.source_pk,
            character_id=stack.character_id,
            item_type=stack.item_type,
            quantity=stack.quantity,
            item_id=_to_int(_pick(record, "item_id")),
            item_name=_to_str(_pick(record, "item_name", "name"), ""),
            location_id=_to_int(_pick(record, "location_id")),
            location_name=_to_str(_pick(record, "location_name"), "")
            or None,
            location_flag=_to_str(_pick(record, "location_flag"), "")
            or None,
            is_blueprint_copy=(
                bool(_pick(record, "is_blueprint_copy"))
                if _pick(record, "is_blueprint_copy") is not None
                else None
            ),
            is_singleton=(
                bool(_pick(record, "is_singleton"))
                if _pick(record, "is_singleton") is not None
                else None
            ),
            raw=raw,
        )


@dataclass(frozen=True)
class EveItemBasket(EveObject):
    """Collection of item rows for a pilot."""

    character_id: int
    items: tuple[EveItemStack, ...] = ()
    raw: Any | None = None

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def unique_type_count(self) -> int:
        return len({item.type_id for item in self.items})

    def by_type_id(self, type_id: int) -> tuple[EveItemStack, ...]:
        return tuple(item for item in self.items if item.type_id == type_id)


@dataclass(frozen=True)
class EveItemPrice:
    """Per-item-stack valuation entry."""

    item: EveItemStack
    method: str
    unit_price_isk: float
    market: int | str | None = None
    currency: str = "ISK"

    @property
    def type_id(self) -> int:
        return self.item.type_id

    @property
    def quantity(self) -> int:
        return self.item.quantity

    @property
    def total_price_isk(self) -> float:
        quantity = self.item.quantity if self.item.quantity > 0 else 0
        return self.unit_price_isk * quantity


@dataclass(frozen=True)
class EveItemValuation:
    """Valuation output over a set of item rows."""

    prices: tuple[EveItemPrice, ...] = ()
    unpriced_type_ids: tuple[int, ...] = ()
    attempted_methods: tuple[str, ...] = ()

    @property
    def total_estimated_isk(self) -> float:
        return sum(row.total_price_isk for row in self.prices)

    @property
    def priced_type_ids(self) -> tuple[int, ...]:
        return tuple(sorted({row.type_id for row in self.prices}))

    def by_type_id(self, type_id: int) -> tuple[EveItemPrice, ...]:
        return tuple(row for row in self.prices if row.type_id == type_id)


@dataclass(frozen=True)
class EveSkill(EveNamed):
    """Skill definition."""

    group_id: Optional[int] = None
    rank: Optional[int] = None
    raw: Any | None = None

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EveSkill":
        skill_id = _to_int(_pick(record, "skill_id", "eve_type_id", "type_id", "id"))
        if skill_id is None:
            raise ValueError("skill_id or eve_type_id or id is required")
        source_pk = _pick(record, "source_pk", "id", "eve_type_id", "skill_id")
        if source_pk is None:
            source_pk = skill_id
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            id=skill_id,
            name=_to_str(_pick(record, "skill_name", "type_name", "name")),
            group_id=_to_int(_pick(record, "group_id", "skill_group_id")),
            rank=_to_int(_pick(record, "rank")),
            raw=raw,
        )


@dataclass(frozen=True)
class EvePilotSkill(EveObject):
    """Pilot-owned skill with level and allocated SP detail."""

    character_id: int
    skill: EveSkill
    trained_skill_level: int = 0
    active_skill_level: int = 0
    skillpoints_in_skill: int = 0
    raw: Any | None = None

    @property
    def skill_id(self) -> int:
        return self.skill.id

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EvePilotSkill":
        character_id = _to_int(_pick(record, "character_id"))
        if character_id is None:
            raise ValueError("character_id is required")
        skill = EveSkill.from_record(
            record,
            source_app=source_app,
            source_model=source_model,
            raw=raw,
        )
        source_pk = _pick(
            record,
            "source_pk",
            "id",
            "skill_id",
            "eve_type_id",
        )
        if source_pk is None:
            source_pk = f"{character_id}:{skill.id}"
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            character_id=character_id,
            skill=skill,
            trained_skill_level=_to_int(_pick(record, "trained_skill_level"), 0) or 0,
            active_skill_level=_to_int(_pick(record, "active_skill_level"), 0) or 0,
            skillpoints_in_skill=_to_int(
                _pick(record, "skillpoints_in_skill"),
                0,
            )
            or 0,
            raw=raw,
        )


@dataclass(frozen=True)
class EveSkillBasket(EveObject):
    """Collection of pilot-owned skill rows."""

    character_id: int
    skills: tuple[EvePilotSkill, ...] = ()
    raw: Any | None = None

    @property
    def skill_count(self) -> int:
        return len(self.skills)

    @property
    def allocated_sp(self) -> int:
        return sum(skill.skillpoints_in_skill for skill in self.skills)

    def by_skill_id(self, skill_id: int) -> Optional[EvePilotSkill]:
        for skill in self.skills:
            if skill.skill_id == skill_id:
                return skill
        return None

    def has_skill(self, skill_id: int, min_level: Optional[int] = None) -> bool:
        skill = self.by_skill_id(skill_id)
        if skill is None:
            return False
        if min_level is None:
            return True
        return skill.trained_skill_level >= min_level


@dataclass(frozen=True)
class EvePilotSkillSummary(EveObject):
    """Pilot skill summary totals."""

    character_id: int
    total_sp: Optional[int] = None
    unallocated_sp: Optional[int] = None
    allocated_sp: Optional[int] = None
    raw: Any | None = None

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EvePilotSkillSummary":
        character_id = _to_int(_pick(record, "character_id"))
        if character_id is None:
            raise ValueError("character_id is required")
        source_pk = _pick(record, "source_pk", "id", "character_id")
        if source_pk is None:
            source_pk = character_id
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            character_id=character_id,
            total_sp=_to_int(_pick(record, "total_sp", "total")),
            unallocated_sp=_to_int(_pick(record, "unallocated_sp", "unallocated")),
            allocated_sp=_to_int(_pick(record, "allocated_sp")),
            raw=raw,
        )


@dataclass(frozen=True)
class EvePilotSkillbook(EveObject):
    """Pilot skill summary + basket."""

    character_id: int
    summary: EvePilotSkillSummary
    basket: EveSkillBasket
    raw: Any | None = None

    def __post_init__(self) -> None:
        if self.summary.character_id != self.character_id:
            raise ValueError("summary.character_id must match character_id")
        if self.basket.character_id != self.character_id:
            raise ValueError("basket.character_id must match character_id")

    @property
    def total_sp(self) -> Optional[int]:
        return self.summary.total_sp

    @property
    def unallocated_sp(self) -> Optional[int]:
        return self.summary.unallocated_sp

    @property
    def allocated_sp(self) -> int:
        if self.summary.allocated_sp is not None:
            return self.summary.allocated_sp
        return self.basket.allocated_sp


@dataclass(frozen=True)
class EveImplant(EveNamed):
    """Implant definition."""

    slot: Optional[int] = None
    raw: Any | None = None

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EveImplant":
        implant_id = _to_int(
            _pick(record, "implant_id", "eve_type_id", "type_id", "id")
        )
        if implant_id is None:
            raise ValueError("implant_id or eve_type_id or id is required")
        source_pk = _pick(record, "source_pk", "id", "implant_id", "eve_type_id")
        if source_pk is None:
            source_pk = implant_id
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            id=implant_id,
            name=_to_str(_pick(record, "implant_name", "type_name", "name")),
            slot=_to_int(_pick(record, "slot")),
            raw=raw,
        )


@dataclass(frozen=True)
class EveCloneLocation(EveNamed):
    """Location for home clone or jump clone."""

    solar_system_id: Optional[int] = None
    eve_type_id: Optional[int] = None
    owner_id: Optional[int] = None
    raw: Any | None = None

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EveCloneLocation":
        location_id = _to_int(_pick(record, "location_id", "home_location_id", "id"))
        if location_id is None:
            raise ValueError("location_id or home_location_id or id is required")
        source_pk = _pick(record, "source_pk", "id", "location_id", "home_location_id")
        if source_pk is None:
            source_pk = location_id
        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            id=location_id,
            name=_to_str(_pick(record, "location_name", "home_location_name", "name")),
            solar_system_id=_to_int(_pick(record, "solar_system_id")),
            eve_type_id=_to_int(_pick(record, "eve_type_id", "type_id")),
            owner_id=_to_int(_pick(record, "owner_id")),
            raw=raw,
        )


@dataclass(frozen=True)
class EveJumpClone(EveObject):
    """One jump clone row for a pilot."""

    character_id: int
    jump_clone_id: int
    name: str = ""
    location: Optional[EveCloneLocation] = None
    implants: tuple[EveImplant, ...] = ()
    raw: Any | None = None

    @property
    def implant_count(self) -> int:
        return len(self.implants)

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EveJumpClone":
        character_id = _to_int(_pick(record, "character_id"))
        if character_id is None:
            raise ValueError("character_id is required")
        jump_clone_id = _to_int(_pick(record, "jump_clone_id", "clone_id", "id"))
        if jump_clone_id is None:
            raise ValueError("jump_clone_id or clone_id or id is required")
        source_pk = _pick(record, "source_pk", "id", "jump_clone_id", "clone_id")
        if source_pk is None:
            source_pk = f"{character_id}:{jump_clone_id}"

        location = None
        if _pick(record, "location_id", "home_location_id") is not None:
            location = EveCloneLocation.from_record(
                record,
                source_app=source_app,
                source_model=source_model,
                raw=raw,
            )

        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            character_id=character_id,
            jump_clone_id=jump_clone_id,
            name=_to_str(_pick(record, "clone_name", "name")),
            location=location,
            raw=raw,
        )


@dataclass(frozen=True)
class EvePilotCloneSummary(EveObject):
    """Pilot clone summary fields."""

    character_id: int
    home_location: Optional[EveCloneLocation] = None
    last_clone_jump_at: Optional[datetime] = None
    last_station_change_at: Optional[datetime] = None
    raw: Any | None = None

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        raw: Any | None = None,
    ) -> "EvePilotCloneSummary":
        character_id = _to_int(_pick(record, "character_id"))
        if character_id is None:
            raise ValueError("character_id is required")
        source_pk = _pick(record, "source_pk", "id", "character_id")
        if source_pk is None:
            source_pk = character_id

        home_location = None
        if _pick(record, "home_location_id", "location_id") is not None:
            home_location = EveCloneLocation.from_record(
                record,
                source_app=source_app,
                source_model=source_model,
                raw=raw,
            )

        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            character_id=character_id,
            home_location=home_location,
            last_clone_jump_at=_to_datetime(
                _pick(record, "last_clone_jump_at", "last_clone_jump_date")
            ),
            last_station_change_at=_to_datetime(
                _pick(record, "last_station_change_at", "last_station_change_date")
            ),
            raw=raw,
        )


@dataclass(frozen=True)
class EveCloneBay(EveObject):
    """Collection of pilot clone-related rows."""

    character_id: int
    jump_clones: tuple[EveJumpClone, ...] = ()
    current_implants: tuple[EveImplant, ...] = ()
    raw: Any | None = None

    @property
    def clone_count(self) -> int:
        return len(self.jump_clones)

    @property
    def current_implant_count(self) -> int:
        return len(self.current_implants)

    @property
    def total_jump_clone_implants(self) -> int:
        return sum(clone.implant_count for clone in self.jump_clones)

    def by_jump_clone_id(self, jump_clone_id: int) -> Optional[EveJumpClone]:
        for clone in self.jump_clones:
            if clone.jump_clone_id == jump_clone_id:
                return clone
        return None


@dataclass(frozen=True)
class EvePilotClonebook(EveObject):
    """Pilot clone summary + clone bay."""

    character_id: int
    summary: EvePilotCloneSummary
    bay: EveCloneBay
    raw: Any | None = None

    def __post_init__(self) -> None:
        if self.summary.character_id != self.character_id:
            raise ValueError("summary.character_id must match character_id")
        if self.bay.character_id != self.character_id:
            raise ValueError("bay.character_id must match character_id")

    @property
    def clone_count(self) -> int:
        return self.bay.clone_count

    @property
    def current_implant_count(self) -> int:
        return self.bay.current_implant_count


@dataclass(frozen=True)
class EvePilot(EveNamed):
    """Pilot domain object for application-agnostic EVE character rows."""

    corporation: EveCorporationRef
    alliance: Optional[EveAllianceRef] = None
    is_main: Optional[bool] = None
    user_id: Optional[int] = None
    skillbook: Optional[EvePilotSkillbook] = None
    clonebook: Optional[EvePilotClonebook] = None
    # Mains have a list (possibly empty). Alts keep this as None.
    alts: Optional[list["EvePilot"]] = None
    raw: Any | None = None

    @property
    def character_id(self) -> int:
        return self.id

    @property
    def character_name(self) -> str:
        return self.name

    @property
    def corporation_id(self) -> Optional[int]:
        return self.corporation.id if self.corporation else None

    @property
    def corporation_name(self) -> Optional[str]:
        return self.corporation.name if self.corporation else None

    @property
    def corporation_ticker(self) -> Optional[str]:
        return self.corporation.ticker if self.corporation else None

    @property
    def alliance_id(self) -> Optional[int]:
        return self.alliance.id if self.alliance else None

    @property
    def alliance_name(self) -> Optional[str]:
        return self.alliance.name if self.alliance else None

    @property
    def alliance_ticker(self) -> Optional[str]:
        return self.alliance.ticker if self.alliance else None

    @property
    def label(self) -> str:
        """
        Canonical Mumble display name: [alliance_ticker corp_ticker] name.
        Corp ticker is always present for a valid EVE pilot.
        Uses '--' for alliance_ticker when the pilot has no alliance.
        """
        c_ticker = self.corporation.ticker.strip()
        a_ticker = (
            (self.alliance.ticker or "").strip() if self.alliance else "--"
        )
        return f"[{a_ticker} {c_ticker}] {self.name}"

    def with_alts(self, alts: list["EvePilot"]) -> "EvePilot":
        return replace(self, alts=alts)

    def with_skillbook(self, skillbook: EvePilotSkillbook) -> "EvePilot":
        return replace(self, skillbook=skillbook)

    def with_clonebook(self, clonebook: EvePilotClonebook) -> "EvePilot":
        return replace(self, clonebook=clonebook)

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_app: SourceApp,
        source_model: str,
        is_main: bool | None = None,
        raw: Any | None = None,
    ) -> "EvePilot":
        character_id = _to_int(_pick(record, "character_id", "id"))
        if character_id is None:
            raise ValueError("character_id or id is required")
        source_pk = _pick(record, "source_pk", "id", "character_id")
        if source_pk is None:
            source_pk = character_id

        corp = EveCorporationRef.from_record(
            record,
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
        )

        alliance = None
        if _pick(record, "alliance_id") is not None:
            alliance = EveAllianceRef.from_record(
                record,
                source_app=source_app,
                source_model=source_model,
                source_pk=source_pk,
            )

        computed_is_main = is_main
        if computed_is_main is None:
            main_value = _pick(record, "is_main")
            if main_value is not None:
                computed_is_main = bool(main_value)

        return cls(
            source_app=source_app,
            source_model=source_model,
            source_pk=source_pk,
            id=character_id,
            name=_to_str(_pick(record, "character_name", "name")),
            corporation=corp,
            alliance=alliance,
            is_main=computed_is_main,
            user_id=_to_int(_pick(record, "user_id")),
            raw=raw,
        )


class EveRepository(Protocol):
    """Repository interface used by EVE application adapters."""

    app: str

    def resolve_alliance(self, identifier: int | str) -> Optional[EveAlliance]:
        ...

    def resolve_corporation(self, identifier: int | str) -> Optional[EveCorporation]:
        ...

    def list_pilots(
        self,
        *,
        alliance_id: Optional[int] = None,
        corporation_id: Optional[int] = None,
    ) -> Iterable[EvePilot]:
        ...

    def list_mains(
        self,
        *,
        alliance_id: Optional[int] = None,
        corporation_id: Optional[int] = None,
    ) -> Iterable[EvePilot]:
        ...

    def list_pilot_assets(self, character_id: int) -> Iterable[EveAssetItem]:
        ...

    def get_pilot_asset_basket(
        self,
        character_id: int,
    ) -> Optional[EveItemBasket]:
        ...

    def get_pilot_skill_summary(
        self,
        character_id: int,
    ) -> Optional[EvePilotSkillSummary]:
        ...

    def list_pilot_skills(self, character_id: int) -> Iterable[EvePilotSkill]:
        ...

    def get_pilot_skillbook(
        self,
        character_id: int,
    ) -> Optional[EvePilotSkillbook]:
        ...

    def get_pilot_clone_summary(
        self,
        character_id: int,
    ) -> Optional[EvePilotCloneSummary]:
        ...

    def list_pilot_jump_clones(self, character_id: int) -> Iterable[EveJumpClone]:
        ...

    def list_pilot_current_implants(self, character_id: int) -> Iterable[EveImplant]:
        ...

    def get_pilot_clonebook(
        self,
        character_id: int,
    ) -> Optional[EvePilotClonebook]:
        ...
