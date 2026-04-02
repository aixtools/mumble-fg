from __future__ import annotations

import logging
import os
import socket
from datetime import datetime
from ipaddress import ip_address

from django.conf import settings
from django.db import connections

from .services.eve_repository import get_repository
from .services.env import detect_environment
from .services.ice_client import normalize_server_id


def _classify_db_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "access denied" in message or "password" in message or "authentication" in message:
        return "authentication failed (check user/password)"
    if "could not connect" in message or "connection refused" in message:
        return "connection refused (check host/port/firewall)"
    if "no such file or directory" in message or "could not translate host name" in message:
        return "host not reachable or invalid hostname"
    if "unknown database" in message:
        return "database not found (check name)"
    return "connection failed"


def _classify_ice_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "connection refused" in message:
        return "connection refused (check host/port/firewall)"
    if "no such file or directory" in message:
        return "host not reachable or invalid hostname"
    if "ice" in message and "missing" in message:
        return "ICE dependencies missing"
    return "connection failed"


def _db_configured(
    config: dict[str, object],
) -> tuple[bool, list[str], list[str]]:
    required = ["ENGINE", "NAME", "USER", "PASSWORD", "HOST"]
    missing: list[str] = []
    placeholders: list[str] = []
    for key in required:
        value = str(config.get(key) or "").strip()
        if not value:
            missing.append(key)
            continue
        if value == "fill-with-valid-password":
            placeholders.append(key)
    ok = len(missing) == 0
    return ok, missing, placeholders


def _alias_label(alias: str) -> str:
    _ = alias
    return "Database"


def _is_mumble_db_config(config: dict[str, object]) -> bool:
    name = str(config.get("NAME") or "").strip()
    user = str(config.get("USER") or "").strip()
    expected_name = str(getattr(settings, "MUMBLE_DB_NAME", "") or "").strip()
    expected_user = str(getattr(settings, "MUMBLE_DB_USER", "") or "").strip()
    if not name or not expected_name:
        return False
    if name != expected_name:
        return False
    if expected_user and user and user != expected_user:
        return False
    return True


def _password_state(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "<empty>"
    if text == "fill-with-valid-password":
        return "<placeholder>"
    return "<set>"


def _format_attempted_settings(settings_map: dict[str, object]) -> str:
    lines = ["Attempted settings:"]
    for key, value in settings_map.items():
        if "PASSWORD" in key:
            shown = _password_state(value)
        else:
            shown = str(value if value not in (None, "") else "-")
        lines.append(f"  {key}={shown}")
    return "\n".join(lines)


def _configured_dbprefix_hint() -> str:
    auth_prefix = str(getattr(settings, "AUTH_DBPREFIX", "") or "")
    cube_prefix = str(getattr(settings, "CUBE_DBPREFIX", "") or "")
    if auth_prefix or cube_prefix:
        return (
            "configured DBPREFIX values "
            f"(AUTH_DBPREFIX={auth_prefix!r}, CUBE_DBPREFIX={cube_prefix!r})"
        )
    return "configured DBPREFIX values"


_LAST_VERIFY_MESSAGES: list[str] = []
_LAST_STATUS: dict[str, object] = {}


def _format_startup_log(level: str, logger_name: str, message: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    return f"{timestamp} {level} {logger_name} {message}"


def append_startup_message(level: str, logger_name: str, message: str) -> None:
    _LAST_VERIFY_MESSAGES.append(_format_startup_log(level, logger_name, message))


def get_last_verify_messages() -> list[str]:
    return list(_LAST_VERIFY_MESSAGES)


def get_last_status() -> dict[str, object]:
    return dict(_LAST_STATUS)


class _VerifyLogHandler(logging.Handler):
    def __init__(self, verbose: bool = False) -> None:
        super().__init__()
        self.verbose = verbose
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            if not self.verbose or record.levelno < logging.WARNING:
                return
        self.messages.append(self.format(record))


def _apply_connect_timeout(connection, seconds: int = 3) -> None:
    """
    Ensure DB connection attempts do not block indefinitely.
    """
    cfg = connection.settings_dict
    options = cfg.get("OPTIONS") or {}
    if "connect_timeout" in options:
        return
    cfg["OPTIONS"] = {**options, "connect_timeout": seconds}


def _is_postgresql_config(config: dict[str, object]) -> bool:
    engine = str(config.get("ENGINE") or "").strip().lower()
    return engine == "django.db.backends.postgresql"


def _is_mysql_config(config: dict[str, object]) -> bool:
    engine = str(config.get("ENGINE") or "").strip().lower()
    return engine == "django.db.backends.mysql"


def _host_resolves_to_loopback(host: str) -> bool:
    text = host.strip().lower()
    if not text or text == "localhost":
        return True
    try:
        return ip_address(text).is_loopback
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(text, None)
    except OSError:
        return False
    for info in infos:
        address = info[4][0]
        try:
            if ip_address(address).is_loopback:
                return True
        except ValueError:
            continue
    return False


def _db_ssl_connectors(config: dict[str, object]) -> list[dict[str, str]]:
    raw_connectors = config.get("MONITOR_DB_SSL_CONNECTORS")
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


def _postgres_ssl_attempts(config: dict[str, object]) -> list[tuple[dict[str, object], str, int | None]]:
    host = str(config.get("HOST") or "").strip()
    options = dict(config.get("OPTIONS") or {})
    if not host or _host_resolves_to_loopback(host):
        return [(options, "plain", None)]

    base_options = {
        key: value
        for key, value in options.items()
        if key not in {"sslmode", "sslrootcert", "sslcert", "sslkey"}
    }
    attempts: list[tuple[dict[str, object], str, int | None]] = []
    connectors = _db_ssl_connectors(config)
    if not connectors:
        sslrootcert = str(config.get("MONITOR_SSLROOTCERT") or "").strip()
        if sslrootcert:
            connectors = [{"ca": sslrootcert}]
    for connector in connectors:
        sslrootcert = str(connector.get("ca") or "").strip()
        if not sslrootcert:
            continue
        verify_options = {
            **base_options,
            "sslmode": "verify-full",
            "sslrootcert": sslrootcert,
        }
        sslcert = str(connector.get("cert") or "").strip()
        sslkey = str(connector.get("key") or "").strip()
        if sslcert:
            verify_options["sslcert"] = sslcert
        if sslkey:
            verify_options["sslkey"] = sslkey
        attempts.append((verify_options, "verify-full", None))
    attempts.append(
        (
            {
                **base_options,
                "sslmode": "require",
            },
            "require",
            logging.INFO,
        )
    )
    attempts.append((base_options, "plain", logging.WARNING))
    return attempts


def _mysql_ssl_attempts(
    config: dict[str, object],
) -> list[tuple[dict[str, object], str, int | None]]:
    host = str(config.get("HOST") or "").strip()
    options = dict(config.get("OPTIONS") or {})
    if not host or _host_resolves_to_loopback(host):
        return [(options, "plain", None)]

    base_options = {
        key: value
        for key, value in options.items()
        if key != "ssl"
    }
    connectors = _db_ssl_connectors(config)
    raw_ssl = options.get("ssl")
    if isinstance(raw_ssl, dict):
        legacy_connector = {
            key: str(value).strip()
            for key, value in raw_ssl.items()
            if key in {"ca", "cert", "key"} and str(value or "").strip()
        }
        if legacy_connector:
            connectors.append(legacy_connector)

    attempts: list[tuple[dict[str, object], str, int | None]] = []
    for connector in connectors:
        ssl_ca = str(connector.get("ca") or "").strip()
        ssl_cert = str(connector.get("cert") or "").strip()
        ssl_key = str(connector.get("key") or "").strip()
        if ssl_ca and ssl_cert and ssl_key:
            attempts.append(
                (
                    {
                        **base_options,
                        "ssl": {
                            "ca": ssl_ca,
                            "cert": ssl_cert,
                            "key": ssl_key,
                        },
                    },
                    "full",
                    None,
                )
            )
    for connector in connectors:
        ssl_ca = str(connector.get("ca") or "").strip()
        if ssl_ca:
            attempts.append(
                (
                    {
                        **base_options,
                        "ssl": {
                            "ca": ssl_ca,
                        },
                    },
                    "ca-only",
                    logging.INFO,
                )
            )
    attempts.append((base_options, "plain", logging.WARNING))
    return attempts


def _ensure_database_connection(connection) -> tuple[int | None, str | None, str | None]:
    config = connection.settings_dict
    if not _is_postgresql_config(config) and not _is_mysql_config(config):
        connection.ensure_connection()
        connection.close()
        return None, None, None

    original_options = dict(config.get("OPTIONS") or {})
    if _is_postgresql_config(config):
        attempts = _postgres_ssl_attempts(config)
        ssl_kind = "postgresql"
    else:
        attempts = _mysql_ssl_attempts(config)
        ssl_kind = "mysql"
    last_exc: Exception | None = None
    for options, mode, level in attempts:
        config["OPTIONS"] = options
        try:
            connection.ensure_connection()
            connection.close()
            return level, mode, ssl_kind
        except Exception as exc:
            last_exc = exc
            connection.close()
            continue
    config["OPTIONS"] = original_options
    if last_exc is not None:
        raise last_exc
    connection.ensure_connection()
    connection.close()
    return None, None, None


def verify_connections(verbose: bool = False) -> None:
    """
    Verify configured Murmur ICE and database connections at startup.

    This attempts each configured connection, logs errors, and terminates
    the process if any connection checks fail.
    """
    logger = logging.getLogger(__name__)
    handler = _VerifyLogHandler(verbose=verbose)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s,%(msecs)03d %(levelname)s %(name)s %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    errors: list[str] = []
    had_failures = False
    connection_result: dict[str, bool] = {}
    eve_ok_any = False
    mumble_raw_ok_any = False
    eve_failures: list[str] = []
    mumble_raw_failures: list[str] = []
    status: dict[str, object] = {
        "ice": [],
        "databases": [],
        "mumble_client": {"ok": False, "error": None, "host": None, "port": None},
        "janice": {"ok": False, "error": "not checked", "market": None},
    }
    ice_ok_any = False

    try:
        db_ok = False
        db_errors: list[str] = []
        ice_errors: list[str] = []
        mumble_raw_infos: list[str] = []
        mumble_raw_warnings: list[str] = []
        all_aliases = list(connections.databases.keys())
        ordered_aliases = all_aliases
        eve_detected_aliases: dict[str, list[str]] = {"AUTH": [], "CUBE": []}

        # 1) EVE + DB connectivity checks.
        for alias in ordered_aliases:
            placeholders: list[str] = []
            cfg = connections.databases.get(alias, {})
            is_mumble_db = _is_mumble_db_config(cfg)
            try:
                connection = connections[alias]
                ok_config, missing, placeholders = _db_configured(
                    cfg
                )
                label = _alias_label(alias)
                if not ok_config:
                    attempt = _format_attempted_settings(
                        {
                            "ENGINE": cfg.get("ENGINE", ""),
                            "HOST": cfg.get("HOST", ""),
                            "PORT": cfg.get("PORT", ""),
                            "NAME": cfg.get("NAME", ""),
                            "USER": cfg.get("USER", ""),
                            "PASSWORD": cfg.get("PASSWORD", ""),
                        }
                    )
                    message = (
                        f"{label} connection: skipped (missing "
                        f"{', '.join(missing) if missing else 'values'})"
                    )
                    if verbose:
                        message = f"{message}\n{attempt}"
                    connection_result[alias] = False
                    status["databases"].append(
                        {"alias": alias, "ok": False, "error": "missing settings"}
                    )
                    if not is_mumble_db:
                        eve_failures.append(message)
                    else:
                        mumble_raw_failures.append(message)
                    continue
                _apply_connect_timeout(connection, seconds=3)
                ssl_level, ssl_mode, ssl_kind = _ensure_database_connection(connection)
                if placeholders:
                    if is_mumble_db:
                        placeholder_msg = (
                            f"{label} connection: ok "
                            "(PASSWORD is placeholder value)"
                        )
                        mumble_raw_warnings.append(placeholder_msg)
                    elif verbose:
                        logger.warning(
                            "%s connection: ok (alias=%s engine=%s PASSWORD is placeholder value)",
                            label,
                            alias,
                            cfg.get("ENGINE", "unknown"),
                        )
                else:
                    if is_mumble_db:
                        mumble_raw_infos.append(f"{label} connection: ok")
                    elif verbose:
                        logger.info("%s connection: ok", label)
                if ssl_level is not None and ssl_mode is not None and ssl_kind is not None:
                    if ssl_kind == "postgresql":
                        ssl_message = (
                            f"{label} connection: PostgreSQL SSL fallback succeeded "
                            f"(sslmode={ssl_mode})"
                        )
                    else:
                        ssl_message = (
                            f"{label} connection: MySQL SSL fallback succeeded "
                            f"(ssl={ssl_mode})"
                        )
                    if is_mumble_db:
                        if ssl_level >= logging.WARNING:
                            mumble_raw_warnings.append(ssl_message)
                        else:
                            mumble_raw_infos.append(ssl_message)
                    elif ssl_level >= logging.WARNING:
                        logger.warning("%s", ssl_message)
                    else:
                        logger.info("%s", ssl_message)
                connection_result[alias] = True
                db_ok = True
                status["databases"].append(
                    {"alias": alias, "ok": True, "error": None}
                )
                if not is_mumble_db:
                    try:
                        env = detect_environment(using=alias, log=False)
                    except Exception:
                        env = None
                    if env in {"AUTH", "CUBE"}:
                        eve_detected_aliases[env].append(alias)
                        eve_ok_any = True
                    elif verbose:
                        eve_failures.append(
                            (
                                "Database connection: unknown app schema "
                                "(alias={alias} engine={engine})".format(
                                    alias=alias,
                                    engine=cfg.get("ENGINE", "unknown"),
                                )
                            )
                        )
                        eve_failures.append(
                            (
                                "Hint: database connected but schema hints were not found. "
                                f"Check {_configured_dbprefix_hint()}."
                            )
                        )
                if is_mumble_db:
                    mumble_raw_ok_any = True
            except Exception as exc:  # pragma: no cover - startup logging
                engine = cfg.get("ENGINE", "unknown")
                host = cfg.get("HOST", "")
                port = cfg.get("PORT", "")
                name = cfg.get("NAME", "")
                user = cfg.get("USER", "")
                reason = _classify_db_error(exc)
                placeholder_note = ""
                if placeholders:
                    placeholder_note = " (PASSWORD is placeholder value)"
                attempt = _format_attempted_settings(
                    {
                        "ENGINE": engine,
                        "HOST": host,
                        "PORT": port,
                        "NAME": name,
                        "USER": user,
                        "PASSWORD": cfg.get("PASSWORD", ""),
                    }
                )
                if verbose:
                    message = (
                        "{label} connection: failed ({reason}){placeholder}\n"
                        "  [engine={engine} host={host} port={port} "
                        "name={name} user={user}] ({exc})\n{attempt}".format(
                            label=_alias_label(alias),
                            reason=reason,
                            placeholder=placeholder_note,
                            engine=engine,
                            host=host or "-",
                            port=port or "-",
                            name=name or "-",
                            user=user or "-",
                            exc=exc,
                            attempt=attempt,
                        )
                    )
                else:
                    message = (
                        "{label} connection: failed ({reason}){placeholder} "
                        "(alias={alias} engine={engine})".format(
                            label=label,
                            reason=reason,
                            placeholder=placeholder_note,
                            alias=alias,
                            engine=engine,
                        )
                    )
                connection_result[alias] = False
                status["databases"].append(
                    {"alias": alias, "ok": False, "error": reason}
                )
                if not is_mumble_db:
                    eve_failures.append(message)
                else:
                    mumble_raw_failures.append(message)

        if eve_failures and not eve_ok_any:
            had_failures = True
            if verbose:
                for message in eve_failures:
                    logger.error(message)
            else:
                logger.error(
                    "Database connection succeeded but no AUTH/CUBE schema could be verified. "
                    "Check %s.",
                    _configured_dbprefix_hint(),
                )
        for env, label in (("AUTH", "EVE.auth"), ("CUBE", "EVE.cube")):
            if eve_detected_aliases[env]:
                logger.info("%s status: available", label)
            else:
                logger.warning("%s status: unavailable", label)
        if db_errors:
            for message in db_errors:
                logger.error(message)

        # 2) EVE alliance ticker/id resolution follows EVE connection checks.
        resolved_alias = None
        resolved_type = "UNKNOWN"
        if eve_detected_aliases["CUBE"]:
            resolved_type = "CUBE"
            resolved_alias = eve_detected_aliases["CUBE"][0]
        elif eve_detected_aliases["AUTH"]:
            resolved_type = "AUTH"
            resolved_alias = eve_detected_aliases["AUTH"][0]
        if resolved_alias:
            ticker = str(getattr(settings, "ALLIANCE_TICKER", "")).strip()
            raw_alliance_id = getattr(settings, "ALLIANCE_ID", None)
            alliance_id: int | str | None = None
            if raw_alliance_id is not None:
                text = str(raw_alliance_id).strip()
                if text:
                    alliance_id = text
            identifier = (
                alliance_id
                if alliance_id
                else ticker
                if ticker
                else None
            )
            if identifier:
                try:
                    repo = get_repository(resolved_type, using=resolved_alias)
                    resolved = repo.resolve_alliance(identifier)
                    if resolved is not None:
                        resolved_ticker = resolved.ticker or "UNKNOWN"
                        logger.info(
                            "EVE.%s alliance resolved: [%s]:%s",
                            resolved_type.lower(),
                            resolved_ticker,
                            resolved.id,
                        )
                    else:
                        logger.error(
                            "EVE.%s alliance resolve failed: %s",
                            resolved_type.lower(),
                            identifier,
                        )
                except Exception as exc:
                    logger.error(
                        "EVE.%s alliance resolve failed: %s (%s)",
                        resolved_type.lower(),
                        identifier,
                        exc,
                    )
            else:
                logger.warning(
                    "EVE.%s ticker/id not set; skipping alliance resolution",
                    resolved_type.lower(),
                )
        else:
            if verbose:
                logger.warning(
                    "EVE connection not successful; skipping alliance ticker "
                    "resolution",
                )

        # 3) ICE connectivity checks.
        try:
            from .services.ice_client import ICEClient, resolve_ice_connections

            connections = resolve_ice_connections()
            if not connections:
                default_host = getattr(settings, "ICE_HOST", "127.0.0.1")
                connections = [
                    {
                        "HOST": default_host,
                        "PORT": getattr(settings, "ICE_PORT", 6502),
                        "SECRET": getattr(settings, "ICE_SECRET", None),
                        "INI_PATH": getattr(settings, "ICE_INI_PATH", None),
                        "SERVER_ID": normalize_server_id(
                            getattr(settings, "PYMUMBLE_SERVER_ID", 1)
                        ),
                    }
                ]
            for connection_cfg in connections:
                host = str(connection_cfg.get("HOST") or "127.0.0.1")
                server_id = int(connection_cfg.get("SERVER_ID") or 1)
                try:
                    with ICEClient(
                        server_id=server_id,
                        host=host,
                        port=connection_cfg.get("PORT"),
                        secret=connection_cfg.get("SECRET"),
                        ini_path=connection_cfg.get("INI_PATH"),
                        timeout_ms=3000,
                    ) as ice:
                        list(ice.get_channels())
                    logger.info("Mumble.ice ok: host=%s", host)
                    connection_result["mumble.ice"] = True
                    ice_ok_any = True
                    status["ice"].append({"host": host, "ok": True, "error": None})
                except Exception as exc:  # pragma: no cover - startup logging
                    reason = _classify_ice_error(exc)
                    connection_result["mumble.ice"] = False
                    had_failures = True
                    attempt = _format_attempted_settings(
                        {
                            "ICE_HOST": host,
                            "ICE_PORT": connection_cfg.get("PORT", 6502),
                            "ICE_SECRET": connection_cfg.get("SECRET"),
                            "PYMUMBLE_SERVER_ID": server_id,
                        }
                    )
                    if verbose:
                        ice_errors.append(
                            f"Mumble.ice failed (host={host}): "
                            f"{reason} ({exc})\n{attempt}"
                        )
                    else:
                        ice_errors.append(
                            f"Mumble.ice failed (host={host}): {reason}"
                        )
                    status["ice"].append(
                        {"host": host, "ok": False, "error": reason}
                    )
        except Exception as exc:  # pragma: no cover - startup logging
            reason = _classify_ice_error(exc)
            connection_result["mumble.ice"] = False
            had_failures = True
            attempt = _format_attempted_settings(
                {
                    "ICE_HOST": getattr(settings, "ICE_HOST", None),
                    "ICE_PORT": getattr(settings, "ICE_PORT", 6502),
                    "ICE_SECRET": getattr(
                        settings,
                        "ICE_SECRET",
                        None,
                    ),
                    "PYMUMBLE_SERVER_ID": getattr(settings, "PYMUMBLE_SERVER_ID", 1),
                }
            )
            if verbose:
                ice_errors.append(f"Mumble.ice failed: {reason} ({exc})\n{attempt}")
            else:
                ice_errors.append(f"Mumble.ice failed: {reason}")
            status["ice"].append({"host": None, "ok": False, "error": reason})
        for message in ice_errors:
            logger.error(message)

        # 4) Mumble checks (raw DB + client socket).
        if mumble_raw_failures and not mumble_raw_ok_any:
            had_failures = True
            if verbose:
                for message in mumble_raw_failures:
                    logger.error(message)
        for message in mumble_raw_infos:
            logger.info(message)
        for message in mumble_raw_warnings:
            logger.warning(message)

        try:
            import socket

            host = str(getattr(settings, "PYMUMBLE_SERVER", "127.0.0.1"))
            port = int(getattr(settings, "PYMUMBLE_PORT", 64738))
            with socket.create_connection((host, port), timeout=3):
                logger.info(
                    "Mumble.client connection: ok (host=%s port=%s)",
                    host,
                    port,
                )
                connection_result["mumble.client"] = True
                status["mumble_client"] = {
                    "ok": True,
                    "error": None,
                    "host": host,
                    "port": port,
                }
        except Exception as exc:  # pragma: no cover - startup logging
            attempt = _format_attempted_settings(
                {
                    "PYMUMBLE_SERVER": getattr(settings, "PYMUMBLE_SERVER", None),
                    "PYMUMBLE_PORT": getattr(settings, "PYMUMBLE_PORT", None),
                    "PYMUMBLE_USER": getattr(settings, "PYMUMBLE_USER", None),
                    "PYMUMBLE_PASSWD": getattr(settings, "PYMUMBLE_PASSWD", None),
                    "PYMUMBLE_CERT_FILE": getattr(settings, "PYMUMBLE_CERT_FILE", None),
                    "PYMUMBLE_KEY_FILE": getattr(settings, "PYMUMBLE_KEY_FILE", None),
                }
            )
            if verbose:
                logger.error(
                    "Mumble.client connection: failed (%s)\n%s",
                    exc,
                    attempt,
                )
            else:
                logger.error("Mumble.client connection: failed")
            connection_result["mumble.client"] = False
            had_failures = True
            status["mumble_client"] = {
                "ok": False,
                "error": str(exc),
                "host": getattr(settings, "PYMUMBLE_SERVER", None),
                "port": getattr(settings, "PYMUMBLE_PORT", None),
            }

        # 5) Janice pricing API key/connectivity check (informational).
        janice_key = (
            str(getattr(settings, "JANICE_API_KEY", "") or "").strip()
            or str(os.environ.get("JANICE_API_KEY", "") or "").strip()
        )
        janice_market = str(getattr(settings, "JANICE_MARKET", "2") or "2")
        janice_pricing = str(getattr(settings, "JANICE_PRICING", "sell") or "sell")
        janice_variant = str(
            getattr(settings, "JANICE_VARIANT", "immediate") or "immediate"
        )
        janice_days = str(getattr(settings, "JANICE_DAYS", "0") or "0")
        from .services.item_pricing import JanicePricingMethod

        janice_ok, janice_error = JanicePricingMethod.verify(
            api_key=janice_key,
            market=janice_market,
            pricing=janice_pricing,
            variant=janice_variant,
            days=janice_days,
        )
        if janice_ok:
            logger.info(
                "Janice pricing: ok (market=%s pricing=%s variant=%s days=%s)",
                janice_market,
                janice_pricing,
                janice_variant,
                janice_days,
            )
        elif janice_error == "no key configured":
            logger.warning("Janice pricing: no key configured (JANICE_API_KEY)")
        else:
            logger.warning(
                "Janice pricing: failed (%s). Check Janice API docs: "
                "https://github.com/E-351/janice?tab=readme-ov-file#api",
                janice_error,
            )
        status["janice"] = {
            "ok": janice_ok,
            "error": None if janice_ok else janice_error,
            "market": janice_market,
            "pricing": janice_pricing,
            "variant": janice_variant,
            "days": janice_days,
        }

        if not db_ok:
            errors.append("No app connections succeeded.")
        elif len(all_aliases) == 1:
            sole_db = connections.databases.get(all_aliases[0], {})
            if sole_db.get("ENGINE") == "django.db.backends.dummy":
                logger.warning(
                    "No real database configured. "
                    "Set EVE_HOST/EVE_USER/EVE_DB to check real apps."
                )

        operational = eve_ok_any and mumble_raw_ok_any
        if errors:
            for message in errors:
                logger.error(message)
            raise SystemExit(1)
        if ice_errors:
            raise SystemExit(1)
        if had_failures and not operational:
            raise SystemExit(1)
    finally:
        if handler.messages:
            _LAST_VERIFY_MESSAGES[:] = handler.messages[-200:]
        status["ice_ok"] = ice_ok_any
        status["timestamp"] = datetime.now().isoformat(timespec="seconds")
        _LAST_STATUS.clear()
        _LAST_STATUS.update(status)
        logger.removeHandler(handler)


def collect_connection_status() -> dict[str, list[dict[str, object]]]:
    """
    Return status info for ICE hosts and configured databases.

    This does not raise on failures; callers decide how to report errors.
    """
    cached = get_last_status()
    if cached.get("ice") or cached.get("databases") or cached.get("mumble_client") or cached.get("janice"):
        return cached
    return {"ice": [], "databases": [], "mumble_client": {}, "janice": {}}


def validate_settings() -> list[str]:
    """
    Return a list of configuration errors.

    This is a lightweight validation pass for settings needed by the app.
    """
    errors: list[str] = []
    raw_server_id = getattr(settings, "PYMUMBLE_SERVER_ID", None)
    if raw_server_id is None:
        errors.append("PYMUMBLE_SERVER_ID is not configured.")
    else:
        try:
            normalize_server_id(raw_server_id)
        except (TypeError, ValueError):
            errors.append("PYMUMBLE_SERVER_ID must be an integer.")
    return errors
