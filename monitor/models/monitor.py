from __future__ import annotations

from dataclasses import dataclass, field

import logging

from django.conf import settings

from ..services.env import detect_environment, resolve_database_alias
from ..services.eve_repository import get_repository


@dataclass
class Monitor:
    """
    Monitor AUTH or CUBE for changes in Eve pilots and use ICE to update
    MUMBLE as required.

    The monitor connects to a single application environment (AUTH or
    CUBE) while managing one or more Murmur server connections.
    """

    mumble_servers: tuple[int, ...] = field(default_factory=tuple)
    using: str = "default"
    app_type: str | None = None
    application: str = field(init=False)
    pilot_names: tuple[str, ...] = field(init=False, default_factory=tuple)
    pilot_count: int = field(init=False, default=0)
    db_host: str | None = field(init=False, default=None)
    db_port: int | None = field(init=False, default=None)
    dbms: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        """
        Normalize application name and validate constraints.
        """
        using = self.using
        application = None
        label = None

        if self.app_type is not None:
            expected = self.app_type.upper()
            if expected not in {"AUTH", "CUBE"}:
                raise ValueError("app_type must be AUTH or CUBE")
            if using == "default":
                using = resolve_database_alias(env=expected)
            application = detect_environment(using=using, log=False)
            if application != expected:
                raise ValueError(
                    f"Expected app_type {expected} but detected {application}"
                )
            label = expected
        elif using == "default":
            last_error: Exception | None = None
            for candidate in ("AUTH", "CUBE"):
                try:
                    candidate_using = resolve_database_alias(env=candidate)
                    candidate_app = detect_environment(
                        using=candidate_using, log=False
                    )
                    if candidate_app != candidate:
                        continue
                    using = candidate_using
                    application = candidate_app
                    label = candidate
                    break
                except Exception as exc:
                    last_error = exc
                    continue
            if application is None:
                raise ValueError(
                    "Unable to resolve application type from available "
                    "connections."
                ) from last_error
        else:
            application = detect_environment(using=using, log=False)
            label = application

        logger = logging.getLogger(__name__)
        if application:
            logger.info("Detected %s environment from DB schema", application)

        object.__setattr__(self, "using", using)
        object.__setattr__(self, "application", application)

        config = settings.DATABASES.get(using, {})
        host = config.get("HOST")
        raw_port = config.get("PORT")
        port = None
        if raw_port is not None:
            try:
                port = int(raw_port)
            except (TypeError, ValueError):
                port = None
        engine = str(config.get("ENGINE", "")).lower()

        dbms = None
        if "mysql" in engine:
            dbms = "MYSQL"
        elif "postgres" in engine:
            dbms = "PSQL"
        elif port == 3306:
            dbms = "MYSQL"
        elif port == 5432:
            dbms = "PSQL"

        object.__setattr__(self, "db_host", str(host) if host else None)
        object.__setattr__(self, "db_port", port)
        object.__setattr__(self, "dbms", dbms)

        identifier = (
            getattr(settings, "ALLIANCE_ID", None)
            or getattr(settings, "ALLIANCE_TICKER", None)
        )
        repo = get_repository(application, using=using)
        alliance = repo.resolve_alliance(identifier)
        if alliance is None:
            raise ValueError("Unable to resolve alliance")
        names = tuple(pilot.name for pilot in repo.list_mains(alliance_id=alliance.id))
        object.__setattr__(self, "pilot_names", names)
        object.__setattr__(self, "pilot_count", len(names))
        logger.info("%s: %s pilots", label, self.pilot_count)
        for name in self.pilot_names:
            logger.debug("%s pilot: %s", label, name)
