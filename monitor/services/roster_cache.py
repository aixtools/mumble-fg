from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any

from ..services.eve_repository import get_repository
from ..services.env import resolve_database_alias

_CACHE_LOCK = Lock()
_ROSTER_CACHE: dict[str, dict[str, Any]] = {}


def _alt_payload(alt: Any) -> dict[str, Any]:
    return {
        "name": alt.name,
        "character_id": alt.character_id,
        "alliance_name": alt.alliance_name or "",
        "alliance_id": alt.alliance_id or 0,
        "corporation_name": alt.corporation_name or "",
    }


def _build_roster_payload(app: str) -> dict[str, Any]:
    from ..cli import _attach_alts_to_mains, _find_spies, get_configured_alliance_ids

    alias = resolve_database_alias(env=app)
    repo = get_repository(app, using=alias)
    mains = list(repo.list_mains())
    pilots = list(repo.list_pilots())
    mains_with_alts, orphans = _attach_alts_to_mains(mains, pilots)
    alliance_ids = get_configured_alliance_ids()
    spy_ids = {
        pilot.character_id
        for pilot in _find_spies(mains_with_alts, alliance_ids)
    }

    payload: list[dict[str, Any]] = []
    for pilot in mains_with_alts:
        isa = "spy" if pilot.character_id in spy_ids else "main"
        payload.append(
            {
                "name": pilot.name,
                "character_id": pilot.character_id,
                "alliance_name": pilot.alliance_name or "",
                "alliance_id": pilot.alliance_id or 0,
                "corporation_name": pilot.corporation_name or "",
                "isa": isa,
                "hasa": sorted(
                    [_alt_payload(alt) for alt in (pilot.alts or [])],
                    key=lambda alt: alt["name"].lower(),
                ),
            }
        )
    for pilot in orphans:
        payload.append(
            {
                "name": pilot.name,
                "character_id": pilot.character_id,
                "alliance_name": pilot.alliance_name or "",
                "alliance_id": pilot.alliance_id or 0,
                "corporation_name": pilot.corporation_name or "",
                "isa": "orphan",
                "hasa": [],
            }
        )

    counts = {"main": 0, "spy": 0, "orphan": 0}
    for row in payload:
        role = str(row.get("isa") or "")
        if role in counts:
            counts[role] += 1

    return {
        "ok": True,
        "app": app,
        "pilots": payload,
        "counts": counts,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "error": None,
    }


def refresh_roster_cache(app: str | None = None) -> dict[str, dict[str, Any]]:
    apps = [app] if app else ["AUTH", "CUBE"]
    updated: dict[str, dict[str, Any]] = {}
    for app_name in apps:
        try:
            payload = _build_roster_payload(app_name)
        except Exception as exc:
            payload = {
                "ok": False,
                "app": app_name,
                "pilots": [],
                "counts": {"main": 0, "spy": 0, "orphan": 0},
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "error": str(exc),
            }
        with _CACHE_LOCK:
            _ROSTER_CACHE[app_name] = payload
        updated[app_name] = payload
    return updated


def get_roster_payload(
    app: str,
    *,
    build_if_missing: bool = True,
) -> dict[str, Any]:
    with _CACHE_LOCK:
        cached = _ROSTER_CACHE.get(app)
    if cached is not None and bool(cached.get("ok")):
        return cached
    if cached is not None and not build_if_missing:
        return cached
    if not build_if_missing:
        return {
            "ok": False,
            "app": app,
            "pilots": [],
            "counts": {"main": 0, "spy": 0, "orphan": 0},
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "error": "cache not initialized",
        }
    return refresh_roster_cache(app=app)[app]
