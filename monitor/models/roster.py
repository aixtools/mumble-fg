"""Roster state dataclass produced by roster.build_roster()."""

from __future__ import annotations

from dataclasses import dataclass, field

from .eve import EveAlliance, EvePilot


@dataclass(frozen=True)
class RosterSet:
    """
    Snapshot of the three roster partition sets.

    main0 — mains present in AUTH/CUBE but absent from Mumble.
    main1 — mains present in both AUTH/CUBE and Mumble.
    mumble1 — Mumble usernames with no matching main in AUTH/CUBE.
    focus — the alliance that defines membership.
    """

    focus: EveAlliance
    main0: tuple[EvePilot, ...] = field(default_factory=tuple)
    main1: tuple[EvePilot, ...] = field(default_factory=tuple)
    mumble1: tuple[str, ...] = field(default_factory=tuple)
