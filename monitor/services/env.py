import logging

from django.conf import settings
from django.db import connections


AUTH_TABLE_HINTS = ("authentication_userprofile", "eveonline_evecharacter")
CUBE_TABLE_HINTS = ("accounts_evecharacter",)


def _prefixed(table: str, prefix: str) -> str:
    return f"{prefix}{table}" if prefix else table


def get_db_prefix(env: str, *, using: str | None = None) -> str:
    if using:
        cfg = connections.databases.get(using, {})
        alias_prefix = str(cfg.get("MONITOR_DBPREFIX", "") or "")
        if alias_prefix:
            return alias_prefix
    env_name = env.upper()
    if env_name == "AUTH":
        return str(getattr(settings, "AUTH_DBPREFIX", "") or "")
    if env_name == "CUBE":
        return str(getattr(settings, "CUBE_DBPREFIX", "") or "")
    raise ValueError(f"Unsupported environment: {env}")


def resolve_database_alias(
    preferred: str | None = None, *, env: str | None = None
) -> str:
    """
    Select a database alias that matches the requested environment.
    """
    dbs = settings.DATABASES.keys()
    if preferred and preferred in dbs:
        return preferred

    env_value = (env or "").upper()
    for alias in dbs:
        try:
            detected = detect_environment(using=alias, log=False)
        except Exception:
            continue
        if env_value:
            if detected == env_value:
                return alias
        else:
            return alias

    if env_value:
        raise RuntimeError(
            f"No database alias matched environment {env_value}"
        )

    for alias in dbs:
        if alias != "default":
            return alias
    return "default"


def detect_environment(using: str = "default", *, log: bool = True) -> str:
    """
    Detect whether the database schema matches AUTH or CUBE.

    Returns the environment label, or raises if the schema is unknown.
    """
    logger = logging.getLogger(__name__)
    connection = connections[using]
    tables = set(connection.introspection.table_names())
    auth_prefix = get_db_prefix("AUTH", using=using)
    cube_prefix = get_db_prefix("CUBE", using=using)
    auth_hints = {_prefixed(name, auth_prefix) for name in AUTH_TABLE_HINTS}
    cube_hints = {_prefixed(name, cube_prefix) for name in CUBE_TABLE_HINTS}

    if auth_hints & tables:
        if log:
            logger.info("Detected AUTH environment from DB schema")
        return "AUTH"
    if cube_hints & tables:
        if log:
            logger.info("Detected CUBE environment from DB schema")
        return "CUBE"

    raise RuntimeError(
        "Unable to detect AUTH vs CUBE environment from DB schema "
        f"(AUTH_DBPREFIX={auth_prefix!r}, CUBE_DBPREFIX={cube_prefix!r})"
    )
