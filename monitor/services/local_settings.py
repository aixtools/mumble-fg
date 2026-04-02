from __future__ import annotations

import os
from pathlib import Path
import re
import runpy

from django.conf import settings


def configure_django_from_local_settings(path: str | None = None) -> None:
    """
    Configure Django settings.

    Default behavior is environment-first: if no explicit path is passed and
    SETTINGS_FILE is unset, settings are built from environment
    variables only. If a path is provided (argument or SETTINGS_FILE),
    it is parsed as either key/value text or Python module settings.
    """
    if settings.configured:
        return

    if path is None:
        path = os.environ.get("SETTINGS_FILE")

    if not path:
        django_settings = _build_django_settings({})
        settings.configure(**django_settings)
        return

    config_path = Path(path)
    if not config_path.is_file():
        django_settings = _build_django_settings({})
        settings.configure(**django_settings)
        return

    if config_path.suffix == ".py" or _looks_like_python_settings_file(config_path):
        values = _parse_python_settings(config_path)
    else:
        values = _parse_settings_file(config_path)
    django_settings = _build_django_settings(values)
    settings.configure(**django_settings)


def _build_django_settings(values: dict[str, object]) -> dict[str, object]:
    """
    Translate parsed settings values into Django settings dict.
    """
    django_settings: dict[str, object] = {
        "INSTALLED_APPS": ["monitor"],
        "ROOT_URLCONF": "monitor.urls",
        "SECRET_KEY": "monitor-dev-key",
        "ALLOWED_HOSTS": ["*"],
        "JANICE_API_KEY": os.environ.get(
            "JANICE_API_KEY", "FAKE-JANICE-API-KEY-EXAMPLE-0000"
        ),
        "DATABASES": {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": os.environ.get(
                    "CUBE_DB",
                    os.environ.get("EVE_DB", "cube_db"),
                ),
                "USER": os.environ.get(
                    "CUBE_USER",
                    os.environ.get("EVE_USER", "cube_user"),
                ),
                "PASSWORD": os.environ.get(
                    "CUBE_PASSWORD",
                    os.environ.get("EVE_PASSWORD", "fill-with-valid-password"),
                ),
                "HOST": os.environ.get(
                    "CUBE_HOST",
                    os.environ.get("EVE_HOST", "127.0.0.1"),
                ),
                "PORT": os.environ.get(
                    "CUBE_PORT",
                    os.environ.get("EVE_PORT", "5432"),
                ),
                "OPTIONS": {
                    "connect_timeout": 10,
                    "options": "-c statement_timeout=30000",
                },
                "MONITOR_SSLROOTCERT": os.environ.get("PSQL_SSLROOTCERT", ""),
            },
            "mysql": {
                "ENGINE": "django.db.backends.mysql",
                "NAME": os.environ.get(
                    "AUTH_DB",
                    os.environ.get("EVE_DB", "aa_db"),
                ),
                "USER": os.environ.get(
                    "AUTH_USER",
                    os.environ.get("EVE_USER", "aa_user"),
                ),
                "PASSWORD": os.environ.get(
                    "AUTH_PASSWORD",
                    os.environ.get("EVE_PASSWORD", "fill-with-valid-password"),
                ),
                "HOST": os.environ.get(
                    "AUTH_HOST",
                    os.environ.get("EVE_HOST", "127.0.0.1"),
                ),
                "PORT": os.environ.get(
                    "AUTH_PORT",
                    os.environ.get("EVE_PORT", "3306"),
                ),
                "OPTIONS": {
                    **_database_default_options("mysql"),
                    **_mysql_ssl_options_from_env(),
                },
            },
            "mumble_mysql": {
                "ENGINE": "django.db.backends.mysql",
                "NAME": os.environ.get("MUMBLE_DB_NAME", "mumble_db"),
                "USER": os.environ.get("MUMBLE_DB_USER", "mumble"),
                "PASSWORD": os.environ.get(
                    "MUMBLE_DB_PASSWORD", "yourPW"
                ),
                "HOST": os.environ.get("MUMBLE_DB_HOST", "127.0.0.1"),
                "PORT": os.environ.get("MYSQL_PORT", "3306"),
                "OPTIONS": {
                    **_database_default_options("mysql"),
                    **_mysql_ssl_options_from_env(),
                },
            },
            "mumble_psql": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": os.environ.get("MUMBLE_DB_NAME", "mumble_db"),
                "USER": os.environ.get("MUMBLE_DB_USER", "mumble"),
                "PASSWORD": os.environ.get(
                    "MUMBLE_DB_PASSWORD", "yourPW"
                ),
                "HOST": os.environ.get("MUMBLE_DB_HOST", "127.0.0.1"),
                "PORT": os.environ.get("PSQL_PORT", "5432"),
                "OPTIONS": {
                    "connect_timeout": 10,
                    "options": "-c statement_timeout=30000",
                },
                "MONITOR_SSLROOTCERT": os.environ.get("PSQL_SSLROOTCERT", ""),
            },
        },
    }

    if isinstance(values.get("DATABASES"), dict):
        django_settings["DATABASES"] = values["DATABASES"]
    else:
        grouped_databases = _extract_grouped_database_settings(values)
        if grouped_databases:
            merged_databases = dict(django_settings["DATABASES"])
            merged_databases.update(grouped_databases)
            django_settings["DATABASES"] = merged_databases
        else:
            database_settings = _extract_database_settings(values)
            if database_settings is not None:
                django_settings["DATABASES"] = {"default": database_settings}
            elif "DB_SCHEMA" in values or "DB_NAME" in values:
                database = {
                    "ENGINE": values.get("DB_SCHEMA", "django.db.backends.sqlite3"),
                    "NAME": values.get("DB_NAME", ":memory:"),
                    "USER": values.get("DB_USER", ""),
                    "PASSWORD": values.get("DB_PASSWORD", ""),
                    "HOST": values.get("DB_HOST", ""),
                    "PORT": values.get("DB_PORT", ""),
                }
                django_settings["DATABASES"] = {"default": database}

    _apply_grouped_monitor_settings(values, django_settings)

    for key, value in values.items():
        if (
            key.startswith("ICE_")
            or key.startswith("PYMUMBLE_")
            or key.startswith("MUMBLE_DB_")
        ):
            django_settings[key] = value
        elif key in {"LOG_LEVEL", "LOG_FILE", "ALLIANCE_ID", "ALLIANCE_TICKER", "AUTH_DBPREFIX", "CUBE_DBPREFIX", "JANICE_API_KEY", "JANICE_MARKET", "JANICE_PRICING", "JANICE_VARIANT", "JANICE_DAYS", "ITEM_PRICE_CACHE_BACKEND", "ITEM_PRICE_CACHE_FILE", "ITEM_PRICE_CACHE_TTL_SECONDS"}:
            django_settings[key] = value

    # Allow ICE_/PYMUMBLE_/MUMBLE_DB_ plus core monitor settings from environment.
    for key, value in os.environ.items():
        if (
            key.startswith("ICE_")
            or key.startswith("PYMUMBLE_")
            or key.startswith("MUMBLE_DB_")
        ):
            django_settings.setdefault(key, value)
        elif key in {"LOG_LEVEL", "LOG_FILE", "ALLIANCE_ID", "ALLIANCE_TICKER", "AUTH_DBPREFIX", "CUBE_DBPREFIX", "JANICE_API_KEY", "JANICE_MARKET", "JANICE_PRICING", "JANICE_VARIANT", "JANICE_DAYS", "ITEM_PRICE_CACHE_BACKEND", "ITEM_PRICE_CACHE_FILE", "ITEM_PRICE_CACHE_TTL_SECONDS"}:
            django_settings.setdefault(key, value)

    _apply_database_derived_settings(django_settings)

    return django_settings


def _parse_settings_file(path: Path) -> dict[str, object]:
    """
    Parse a simple key=value settings file into a dict.
    """
    values: dict[str, object] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        raw_value = _strip_inline_comment(raw_value.strip())
        if not key:
            continue
        values[key] = _coerce_value(raw_value)
    return values


def _parse_python_settings(path: Path) -> dict[str, object]:
    """
    Load a Python settings file and return its variables.
    """
    data = runpy.run_path(str(path))
    return {key: value for key, value in data.items() if not key.startswith("__")}


def _looks_like_python_settings_file(path: Path) -> bool:
    """
    Detect Python-style settings blocks in non-.py files.
    """
    assignment_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s+=\s+")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if assignment_re.match(line):
            return True
    return False


def _extract_database_settings(values: dict[str, object]) -> dict[str, object] | None:
    """
    Extract a database config from parsed settings.
    """
    databases = values.get("DATABASES")
    if not isinstance(databases, dict):
        return None
    if "default" in databases and isinstance(databases["default"], dict):
        return databases["default"]
    if "MYSQL" in databases and isinstance(databases["MYSQL"], dict):
        return databases["MYSQL"]
    return None


def _extract_grouped_database_settings(
    values: dict[str, object],
) -> dict[str, dict[str, object]]:
    """
    Extract grouped DB settings and map them to Django aliases.

    Neutral monitor config blocks expand into Django database candidates:
    each EVE_APPS entry becomes both MySQL and PostgreSQL candidates, and
    MUMBLE_DB does the same for the Mumble database connection.
    """
    aliases: dict[str, dict[str, object]] = {}
    db_ssl_connectors = _extract_db_ssl_connectors(values)
    raw_eve_apps = values.get("EVE_APPS")
    if isinstance(raw_eve_apps, (list, tuple)):
        aliases.update(
            _expand_eve_app_candidates(
                raw_eve_apps,
                db_ssl_connectors=db_ssl_connectors,
            )
        )

    grouped_keys = (
        ("CUBE_DATABASE", "default"),
        ("AUTH_DATABASE", "mysql"),
        ("MUMBLE_MYSQL_DATABASE", "mumble_mysql"),
        ("MUMBLE_PSQL_DATABASE", "mumble_psql"),
    )
    for source_key, alias in grouped_keys:
        raw = values.get(source_key)
        if isinstance(raw, dict):
            aliases[alias] = dict(raw)

    raw_mumble = values.get("MUMBLE_DATABASE")
    if isinstance(raw_mumble, dict):
        engine = str(raw_mumble.get("ENGINE") or "").lower()
        if "mysql" in engine:
            aliases.setdefault("mumble_mysql", dict(raw_mumble))
        elif "postgres" in engine:
            aliases.setdefault("mumble_psql", dict(raw_mumble))

    raw_mumble = values.get("MUMBLE_DB")
    if isinstance(raw_mumble, dict):
        aliases.update(
            _expand_mumble_db_candidates(
                raw_mumble,
                db_ssl_connectors=db_ssl_connectors,
            )
        )

    return aliases


def _apply_grouped_monitor_settings(
    values: dict[str, object],
    django_settings: dict[str, object],
) -> None:
    """
    Map grouped monitor config blocks onto flat runtime settings.
    """
    raw_ice = values.get("MUMBLE_ICE")
    if isinstance(raw_ice, (list, tuple)):
        connections = [
            dict(entry)
            for entry in raw_ice
            if isinstance(entry, dict)
        ]
        if connections:
            django_settings["ICE_CONNECTIONS"] = connections
            _apply_primary_ice_connection(connections[0], django_settings)
    elif isinstance(raw_ice, dict):
        django_settings["ICE_CONNECTIONS"] = [dict(raw_ice)]
        _apply_primary_ice_connection(raw_ice, django_settings)

    db_ssl_connectors = _extract_db_ssl_connectors(values)
    if db_ssl_connectors:
        django_settings["DB_SSL_CONNECTORS"] = [
            dict(entry) for entry in db_ssl_connectors
        ]

    raw_pymumble = values.get("PYMUMBLE")
    if isinstance(raw_pymumble, dict):
        mapping = {
            "SERVER": "PYMUMBLE_SERVER",
            "PORT": "PYMUMBLE_PORT",
            "USER": "PYMUMBLE_USER",
            "PASSWD": "PYMUMBLE_PASSWD",
            "CERT_FILE": "PYMUMBLE_CERT_FILE",
            "KEY_FILE": "PYMUMBLE_KEY_FILE",
            "SERVER_ID": "PYMUMBLE_SERVER_ID",
        }
        for source_key, target_key in mapping.items():
            if source_key in raw_pymumble:
                django_settings[target_key] = raw_pymumble.get(source_key)


def _apply_primary_ice_connection(
    raw_ice: dict[str, object],
    django_settings: dict[str, object],
) -> None:
    if "HOST" in raw_ice:
        django_settings["ICE_HOST"] = raw_ice.get("HOST")
    if "HOSTS" in raw_ice:
        django_settings["ICE_HOSTS"] = raw_ice.get("HOSTS")
    if "PORT" in raw_ice:
        django_settings["ICE_PORT"] = raw_ice.get("PORT")
    if "SECRET" in raw_ice:
        django_settings["ICE_SECRET"] = raw_ice.get("SECRET")
    if "INI_PATH" in raw_ice:
        django_settings["ICE_INI_PATH"] = raw_ice.get("INI_PATH")
    if "SERVER_ID" in raw_ice:
        django_settings["PYMUMBLE_SERVER_ID"] = raw_ice.get("SERVER_ID")


def _expand_eve_app_candidates(
    raw_entries: list[object] | tuple[object, ...],
    *,
    db_ssl_connectors: list[dict[str, str]] | None = None,
) -> dict[str, dict[str, object]]:
    aliases: dict[str, dict[str, object]] = {}
    for idx, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            continue
        suffix = "" if idx == 1 else f"_{idx}"
        aliases[f"mysql{suffix}"] = _build_candidate_database(
            raw_entry,
            engine="mysql",
            db_ssl_connectors=db_ssl_connectors,
        )
        aliases["default" if idx == 1 else f"default{suffix}"] = (
            _build_candidate_database(
                raw_entry,
                engine="postgresql",
                db_ssl_connectors=db_ssl_connectors,
            )
        )
    return aliases


def _expand_mumble_db_candidates(
    raw_entry: dict[str, object],
    *,
    db_ssl_connectors: list[dict[str, str]] | None = None,
) -> dict[str, dict[str, object]]:
    return {
        "mumble_mysql": _build_candidate_database(
            raw_entry,
            engine="mysql",
            db_ssl_connectors=db_ssl_connectors,
        ),
        "mumble_psql": _build_candidate_database(
            raw_entry,
            engine="postgresql",
            db_ssl_connectors=db_ssl_connectors,
        ),
    }


def _build_candidate_database(
    raw_entry: dict[str, object],
    *,
    engine: str,
    db_ssl_connectors: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    engine_name = _database_engine_name(engine)
    database_name = raw_entry.get("NAME_DB", raw_entry.get("NAME", ""))
    database = {
        "ENGINE": engine_name,
        "NAME": database_name,
        "USER": raw_entry.get("USER", ""),
        "PASSWORD": raw_entry.get("PASSWORD", ""),
        "HOST": raw_entry.get("HOST", "127.0.0.1"),
        "PORT": _database_default_port(engine),
        "MONITOR_DBPREFIX": raw_entry.get("DBPREFIX", ""),
    }
    database["OPTIONS"] = _database_default_options(engine)
    if engine == "postgresql":
        database["MONITOR_SSLROOTCERT"] = raw_entry.get("SSLROOTCERT", "")
    database["MONITOR_DB_SSL_CONNECTORS"] = [
        dict(entry)
        for entry in (db_ssl_connectors or [])
    ]
    return database


def _database_engine_name(engine: str) -> str:
    if engine == "mysql":
        return "django.db.backends.mysql"
    return "django.db.backends.postgresql"


def _database_default_port(engine: str) -> str:
    if engine == "mysql":
        return "3306"
    return "5432"


def _database_default_options(engine: str) -> dict[str, object]:
    if engine == "mysql":
        return {"charset": "utf8mb4", "connect_timeout": 5}
    return {
        "connect_timeout": 10,
        "options": "-c statement_timeout=30000",
    }


def _mysql_ssl_options_from_env() -> dict[str, object]:
    ssl_options = {
        "ca": os.environ.get("MYSQL_SSL_CA", ""),
        "cert": os.environ.get("MYSQL_SSL_CERT", ""),
        "key": os.environ.get("MYSQL_SSL_KEY", ""),
    }
    normalized = {
        key: value
        for key, value in ssl_options.items()
        if str(value or "").strip()
    }
    if not normalized:
        return {}
    return {"ssl": normalized}


def _extract_db_ssl_connectors(values: dict[str, object]) -> list[dict[str, str]]:
    raw_connectors = values.get("DB_SSL")
    connectors: list[dict[str, str]] = []
    if isinstance(raw_connectors, dict):
        raw_connectors = [raw_connectors]
    if isinstance(raw_connectors, (list, tuple)):
        for raw_entry in raw_connectors:
            if not isinstance(raw_entry, dict):
                continue
            connector = {
                key: str(value).strip()
                for key, value in raw_entry.items()
                if key in {"ca", "cert", "key"} and str(value or "").strip()
            }
            if connector:
                connectors.append(connector)
    return connectors


def _apply_database_derived_settings(django_settings: dict[str, object]) -> None:
    """
    Derive monitor convenience settings from DATABASES when not set explicitly.
    """
    databases = django_settings.get("DATABASES")
    if not isinstance(databases, dict):
        return

    mumble_mysql = databases.get("mumble_mysql")
    mumble_psql = databases.get("mumble_psql")
    primary_mumble = (
        mumble_mysql
        if isinstance(mumble_mysql, dict)
        else mumble_psql
        if isinstance(mumble_psql, dict)
        else None
    )
    if isinstance(primary_mumble, dict):
        django_settings.setdefault("MUMBLE_DB_NAME", primary_mumble.get("NAME"))
        django_settings.setdefault("MUMBLE_DB_HOST", primary_mumble.get("HOST"))
        django_settings.setdefault("MUMBLE_DB_USER", primary_mumble.get("USER"))
        django_settings.setdefault(
            "MUMBLE_DB_PASSWORD",
            primary_mumble.get("PASSWORD"),
        )


def _strip_inline_comment(value: str) -> str:
    """
    Remove inline comments while preserving quoted values.
    """
    if "#" not in value:
        return value
    quote: str | None = None
    for idx, ch in enumerate(value):
        if ch in ("'", '"'):
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
        elif ch == "#" and quote is None:
            return value[:idx].strip()
    return value.strip()


def _coerce_value(value: str) -> object:
    """
    Coerce a string value to bool/int where appropriate.
    """
    if value == "":
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]
        return value
    upper = value.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    if value.isdigit():
        return int(value)
    return value
