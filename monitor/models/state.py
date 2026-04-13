from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MonitorState:
    """
    Persisted monitor state for comparing runs.
    """
    environment: str | None = None
    known_users: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        """
        Serialize the state to a JSON-compatible dict.
        """
        return {
            "environment": self.environment,
            "known_users": sorted(self.known_users),
        }

    @classmethod
    def from_dict(cls, payload: dict | None) -> "MonitorState":
        """
        Load a state instance from a dict payload.
        """
        if not payload:
            return cls()
        environment = payload.get("environment")
        known_users = set(payload.get("known_users") or [])
        return cls(environment=environment, known_users=known_users)
