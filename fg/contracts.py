"""Local contract helpers shared within mumble-fg."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _coerce_optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


@dataclass(frozen=True)
class MurmurContract:
    """Focused contract payload shared by fg/bg control endpoints."""

    evepilot_id: int | None = None
    corporation_id: int | None = None
    alliance_id: int | None = None
    kdf_iterations: int | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MurmurContract":
        return cls(
            evepilot_id=_coerce_optional_int(payload.get("evepilot_id"), field_name="evepilot_id"),
            corporation_id=_coerce_optional_int(payload.get("corporation_id"), field_name="corporation_id"),
            alliance_id=_coerce_optional_int(payload.get("alliance_id"), field_name="alliance_id"),
            kdf_iterations=_coerce_optional_int(payload.get("kdf_iterations"), field_name="kdf_iterations"),
        )

    def as_payload(self) -> dict[str, int | None]:
        return {
            "evepilot_id": self.evepilot_id,
            "corporation_id": self.corporation_id,
            "alliance_id": self.alliance_id,
            "kdf_iterations": self.kdf_iterations,
        }
