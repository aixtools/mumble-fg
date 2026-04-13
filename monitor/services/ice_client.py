from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Any
from configparser import ConfigParser
from pathlib import Path
import logging
import os
import sys

from django.conf import settings


@dataclass(frozen=True)
class ICEChannel:
    """
    Lightweight ICE channel representation.
    """
    channel_id: int
    name: str
    parent: int | None


@dataclass(frozen=True)
class IceResult:
    """
    Wrapper for ICE operations that return a status code and value.
    """
    code: int = 0
    message: str | None = None
    value: Any | None = None


class ICEClient:
    """
    ICE client wrapper for Murmur operations.
    """

    def __init__(
        self,
        server_id: int = 0,
        *,
        host: str | None = None,
        port: int | str | None = None,
        secret: str | None = None,
        ini_path: str | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        """
        Initialize the client for a given Murmur server id.
        """
        self.server_id = server_id
        self.host = host
        self.port = port
        self.secret = secret
        self.ini_path = ini_path
        self._ic = None
        self._meta = None
        self._server = None
        self._context = None
        self._timeout_ms = timeout_ms

    def get_channels(self) -> Iterable[ICEChannel]:
        """
        Fetch the list of channels from Murmur.
        """
        server = self._get_server()
        channels = server.getChannels()
        results = []
        for channel_id, channel in channels.items():
            results.append(ICEChannel(channel_id=channel_id, name=channel.name, parent=channel.parent))
        return results

    def add_channel(self, name: str, parent: int | None = None) -> IceResult:
        """
        Create a new channel and return the ICE result.
        """
        server = self._get_server()
        try:
            channel_id = server.addChannel(name, parent if parent is not None else 0)
        except Exception as exc:
            return IceResult(code=1, message=str(exc))
        return IceResult(code=0, value=channel_id)

    def delete_channel(self, channel_id: int) -> IceResult:
        """
        Delete a channel by id.
        """
        server = self._get_server()
        try:
            server.removeChannel(channel_id)
        except Exception as exc:
            return IceResult(code=1, message=str(exc))
        return IceResult(code=0)

    def get_users(self) -> Iterable[str]:
        """
        Return registered usernames from Murmur.
        """
        server = self._get_server()
        users = server.getRegisteredUsers("")
        return list(users.values())

    def get_online_users(self) -> list[dict[str, str]]:
        """
        Return online users with session and certificate info, if available.
        """
        from datetime import datetime

        server = self._get_server()
        users = server.getUsers()
        seen_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        results: list[dict[str, str]] = []

        def _field(user_obj, key: str, default: object = "") -> object:
            value = getattr(user_obj, key, None)
            if value is not None:
                return value
            if hasattr(user_obj, "get"):
                try:
                    return user_obj.get(key, default)
                except Exception:
                    return default
            return default

        for session_id, user in users.items():
            name = _field(user, "name", "")
            cert_hash = _field(user, "certhash", None)
            if not cert_hash:
                cert_hash = _field(user, "hash", "")
            channel_id = _field(user, "channel", "")
            results.append(
                {
                    "user": str(name),
                    "session": str(session_id),
                    "online": seen_at,
                    "cert_hash": str(cert_hash),
                    "channel_id": str(channel_id),
                }
            )
        return results

    def create_user(self, name: str, comment: str, password_hash_hex: str, salt_hex: str) -> IceResult:
        """
        Create a new Murmur user with a hashed password.
        """
        server = self._get_server()
        try:
            info = self._build_user_info(name, comment, password_hash_hex, salt_hex)
            server.registerUser(info)
        except Exception as exc:
            return IceResult(code=1, message=str(exc))
        return IceResult(code=0)

    def delete_user(self, name: str) -> IceResult:
        """
        Delete a registered user by name.
        """
        server = self._get_server()
        try:
            users = server.getRegisteredUsers(name)
            for user_id, user_name in users.items():
                if user_name == name:
                    server.unregisterUser(user_id)
                    break
        except Exception as exc:
            return IceResult(code=1, message=str(exc))
        return IceResult(code=0)

    def close(self) -> None:
        """
        Close and destroy the ICE communicator.
        """
        if self._ic is not None:
            try:
                self._ic.destroy()
            except Exception:
                pass
            self._ic = None
            self._meta = None
            self._server = None

    def __enter__(self) -> "ICEClient":
        """
        Context manager entry to ensure connection initialized.
        """
        self._get_server()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """
        Context manager exit to clean up ICE state.
        """
        self.close()

    def _build_user_info(self, name: str, comment: str, password_hash_hex: str, salt_hex: str):
        """
        Build a MumbleServer.UserInfo structure for registration.
        """
        Ice, MumbleServer = _require_ice()
        info = MumbleServer.UserInfo()
        info.name = name
        info.comment = comment
        info.pwHash = bytes.fromhex(password_hash_hex)
        info.pwSalt = bytes.fromhex(salt_hex)
        return info

    def _get_server(self):
        """
        Lazily connect to ICE and return the server proxy.
        """
        if self._server is not None:
            return self._server

        Ice, MumbleServer = _require_ice()
        logger = logging.getLogger(__name__)

        host = self.host or getattr(settings, "ICE_HOST", "127.0.0.1")
        port = self.port or getattr(settings, "ICE_PORT", 6502)
        secret = self.secret if self.secret is not None else getattr(settings, "ICE_SECRET", None)
        ini_path = self.ini_path or getattr(settings, "ICE_INI_PATH", None)
        if not ini_path:
            ini_path = str(Path.home() / "mumble-server/mumble-server.ini")

        if secret is None:
            secret = _read_ice_secret(ini_path)

        try:
            if self._timeout_ms is not None:
                init = Ice.InitializationData()
                init.properties = Ice.createProperties()
                init.properties.setProperty(
                    "Ice.Override.Timeout", str(self._timeout_ms)
                )
                init.properties.setProperty(
                    "Ice.Override.ConnectTimeout", str(self._timeout_ms)
                )
                self._ic = Ice.initialize(init)
            else:
                self._ic = Ice.initialize()
            ctx = self._ic.getImplicitContext()
            if ctx is not None:
                ctx.put("secret", secret)
                self._context = None
            else:
                self._context = {"secret": secret}

            endpoint = f"Meta:tcp -h {host} -p {port}"
            logger.debug(
                "ICE endpoint %s (server_id=%s, ini=%s)",
                endpoint,
                self.server_id,
                ini_path,
            )
            proxy = self._ic.stringToProxy(endpoint)
            self._meta = MumbleServer.MetaPrx.checkedCast(proxy)
            if not self._meta:
                raise RuntimeError("ICE: cannot connect to Meta")

            logger.debug("ICE connected to Meta at %s:%s", host, port)
            meta = self._meta
            if self._context:
                meta = meta.ice_context(self._context)
            self._server = meta.getServer(self.server_id)
            if self._server and self._context:
                self._server = self._server.ice_context(self._context)
            if not self._server:
                raise RuntimeError(
                    f"ICE: unable to get server id {self.server_id}"
                )
            return self._server
        except Exception:
            # Ensure communicator is destroyed if initialization fails.
            if self._ic is not None:
                try:
                    self._ic.destroy()
                except Exception:
                    pass
                self._ic = None
            self._meta = None
            self._server = None
            self._context = None
            raise


def normalize_server_id(value: object, *, default: int = 1) -> int:
    """
    Normalize PYMUMBLE_SERVER_ID to an integer.
    """
    if value is None:
        return default
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return default
    return int(text)


def resolve_ice_connections() -> list[dict[str, object]]:
    """
    Return normalized ICE connection configs from grouped settings or legacy vars.
    """
    raw_connections = getattr(settings, "ICE_CONNECTIONS", None)
    if isinstance(raw_connections, (list, tuple)):
        connections: list[dict[str, object]] = []
        for raw in raw_connections:
            if not isinstance(raw, dict):
                continue
            normalized = _normalize_ice_connection(raw)
            if normalized:
                connections.append(normalized)
        if connections:
            return connections

    raw_hosts = getattr(settings, "ICE_HOSTS", None)
    if raw_hosts is None:
        raw_hosts = os.environ.get("ICEHOST")
    hosts = _parse_legacy_ice_hosts(raw_hosts)
    if hosts:
        return [
            {
                "HOST": host,
                "PORT": getattr(settings, "ICE_PORT", 6502) or 6502,
                "SECRET": getattr(settings, "ICE_SECRET", None),
                "INI_PATH": getattr(settings, "ICE_INI_PATH", None),
                "SERVER_ID": normalize_server_id(
                    getattr(settings, "PYMUMBLE_SERVER_ID", 1)
                ),
            }
            for host in hosts
        ]

    return [
        {
            "HOST": getattr(settings, "ICE_HOST", "127.0.0.1") or "127.0.0.1",
            "PORT": getattr(settings, "ICE_PORT", 6502) or 6502,
            "SECRET": getattr(settings, "ICE_SECRET", None),
            "INI_PATH": getattr(settings, "ICE_INI_PATH", None),
            "SERVER_ID": normalize_server_id(
                getattr(settings, "PYMUMBLE_SERVER_ID", 1)
            ),
        }
    ]


def _normalize_ice_connection(raw: dict[str, object]) -> dict[str, object]:
    host = str(raw.get("HOST") or "").strip()
    if not host:
        return {}
    port = raw.get("PORT", 6502)
    ini_path = raw.get("INI_PATH")
    secret = raw.get("SECRET")
    server_id = normalize_server_id(raw.get("SERVER_ID", 1))
    return {
        "HOST": host,
        "PORT": int(port) if str(port).strip() else 6502,
        "SECRET": secret,
        "INI_PATH": ini_path,
        "SERVER_ID": server_id,
    }


def _parse_legacy_ice_hosts(value: object | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value).strip()
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1].strip()
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    hosts: list[str] = []
    for part in parts:
        if (part.startswith('"') and part.endswith('"')) or (
            part.startswith("'") and part.endswith("'")
        ):
            part = part[1:-1]
        part = part.strip()
        if part:
            hosts.append(part)
    return hosts


def _read_ice_secret(path: str) -> str:
    """
    Read the Ice secret from the murmur ini file.
    """
    cfg = ConfigParser(interpolation=None)
    ini_path = Path(path)
    if not ini_path.exists():
        raise RuntimeError(f"ICE: murmur ini not found at {ini_path}")
    with ini_path.open("r", encoding="utf-8") as handle:
        cfg.read_string("[murmur]\n" + handle.read())
    secret = cfg["murmur"].get("icesecretwrite", fallback=None)
    if not secret:
        raise RuntimeError("ICE: missing icesecretwrite in murmur ini")
    return secret.strip().strip('"')


def _require_ice():
    """
    Import Ice and MumbleServer bindings, adding fallbacks as needed.
    """
    try:
        import Ice  # type: ignore
    except Exception as exc:
        raise RuntimeError("ICE dependencies missing. Install Ice and MumbleServer slice bindings.") from exc

    _ensure_ice_pythonpath()

    if not hasattr(Ice, "openModule"):
        import sys
        import types

        def _open_module(name: str):
            module = sys.modules.get(name)
            if module is None:
                module = types.ModuleType(name)
                sys.modules[name] = module
            return module

        setattr(Ice, "openModule", _open_module)

    if not hasattr(Ice, "updateModule"):
        def _update_module(_: str) -> None:
            return None

        setattr(Ice, "updateModule", _update_module)

    if not hasattr(Ice, "createTempClass"):
        def _create_temp_class():
            class _Temp:  # noqa: N801 - mimic Ice temp class
                pass

            return _Temp

        setattr(Ice, "createTempClass", _create_temp_class)

    if not hasattr(Ice, "EnumBase"):
        class _EnumBase:  # noqa: N801 - mimic Ice enum base
            _enumerators = ()

            def __init__(self, *args, **kwargs):
                if args:
                    self._value = args[-1]
                else:
                    self._value = kwargs.get("value")

            def __int__(self):
                return int(self._value) if self._value is not None else 0

        setattr(Ice, "EnumBase", _EnumBase)

    try:
        import Ice.SliceChecksumDict_ice  # type: ignore
    except Exception:
        import sys
        import types

        sys.modules["Ice.SliceChecksumDict_ice"] = types.ModuleType(
            "Ice.SliceChecksumDict_ice"
        )

    try:
        import MumbleServer  # type: ignore
        return Ice, MumbleServer
    except Exception as first_exc:
        try:
            import importlib
            import importlib.util
            import sys

            try:
                ms_ice = importlib.import_module("MumbleServer_ice")
            except Exception:
                ms_ice = None
                try:
                    ms_ice = importlib.import_module(
                        "monitor.ice.MumbleServer_ice"
                    )
                    sys.modules["MumbleServer_ice"] = ms_ice
                except Exception:
                    ms_ice = None
                for candidate in _candidate_ice_module_paths():
                    ms_file = candidate / "MumbleServer_ice.py"
                    if ms_file.is_file():
                        spec = importlib.util.spec_from_file_location("MumbleServer_ice", ms_file)
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            sys.modules["MumbleServer_ice"] = module
                            spec.loader.exec_module(module)
                            ms_ice = module
                            break
            module = sys.modules.get("MumbleServer")
            if module is None and ms_ice is not None:
                module = getattr(ms_ice, "_M_MumbleServer", None)
                if module is not None:
                    sys.modules["MumbleServer"] = module
            if module is None:
                import MumbleServer  # type: ignore
                module = MumbleServer
            return Ice, module
        except Exception as exc:
            raise RuntimeError(
                f"ICE dependencies missing. Install Ice and MumbleServer slice bindings. "
                f"Import errors: {first_exc}; {exc}"
            ) from exc


def _candidate_ice_module_paths() -> list[Path]:
    """
    Return candidate filesystem paths for MumbleServer_ice modules.
    """
    module_root = Path(__file__).resolve()
    paths = [
        module_root.parents[1] / "ice",
        module_root.parents[2] / "monitor" / "ice",
        module_root.parents[2] / "ice",
        Path.cwd() / "monitor" / "ice",
        Path.cwd() / "ice",
    ]
    try:
        from importlib import resources

        with resources.as_file(
            resources.files("monitor").joinpath("ice")
        ) as ice_dir:
            paths.append(Path(ice_dir))
    except Exception:
        pass

    return paths


def _ensure_ice_pythonpath() -> None:
    """
    Ensure Python can import ICE slice bindings from configured paths.
    """
    try:
        from importlib import resources

        with resources.as_file(
            resources.files("monitor").joinpath("ice")
        ) as ice_dir:
            ice_path = str(ice_dir)
            if ice_path not in sys.path:
                sys.path.insert(0, ice_path)
    except Exception:
        pass

    # NOTE: external ICE_PYTHONPATH override is intentionally disabled.
    # For now we force bundled ICE modules with the package (Mumble 1.5 focus).
    # If switching to Mumble 1.6 bindings later, this block can be restored.
    #
    # configured = getattr(settings, "ICE_PYTHONPATH", None)
    # if configured:
    #     found = False
    #     for raw_path in str(configured).split(os.pathsep):
    #         path = raw_path.strip()
    #         if not path:
    #             continue
    #         candidate = Path(path)
    #         if candidate.is_dir():
    #             if (candidate / "MumbleServer_ice.py").is_file() or (
    #                 candidate / "MumbleServer"
    #             ).is_dir():
    #                 found = True
    #         if path not in sys.path:
    #             sys.path.insert(0, path)
    #     if found:
    #         return

    for candidate in _candidate_ice_module_paths():
        if candidate.is_dir():
            path_str = str(candidate)
            if path_str not in sys.path:
                sys.path.insert(0, path_str)
