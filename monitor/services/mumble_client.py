from __future__ import annotations

from datetime import datetime
from pathlib import Path
import logging
import time
import ssl
import socket

from django.conf import settings


logger = logging.getLogger(__name__)


def _ensure_ssl_wrap_socket() -> None:
    """
    Provide ssl.wrap_socket for Python 3.12+ compatibility.
    """
    if hasattr(ssl, "wrap_socket"):
        return

    def wrap_socket(
        sock,
        keyfile=None,
        certfile=None,
        server_side=False,
        cert_reqs=ssl.CERT_NONE,
        ssl_version=None,
        ca_certs=None,
        do_handshake_on_connect=True,
        suppress_ragged_eofs=True,
        ciphers=None,
    ):
        context = ssl.SSLContext(
            ssl.PROTOCOL_TLS_CLIENT if not server_side else ssl.PROTOCOL_TLS_SERVER
        )
        context.check_hostname = False
        context.verify_mode = cert_reqs
        if certfile and keyfile:
            context.load_cert_chain(certfile, keyfile)
        elif certfile:
            context.load_cert_chain(certfile)
        if ca_certs:
            context.load_verify_locations(ca_certs)
        if ciphers:
            context.set_ciphers(ciphers)
        return context.wrap_socket(
            sock,
            server_side=server_side,
            do_handshake_on_connect=do_handshake_on_connect,
            suppress_ragged_eofs=suppress_ragged_eofs,
        )

    ssl.wrap_socket = wrap_socket  # type: ignore[attr-defined]


def fetch_online_users(*, host: str | None = None, timeout: float | None = None) -> list[dict[str, str]]:
    """
    Connect to a Mumble server as a client and return online users.
    """
    _ensure_cert_files()
    try:
        import pymumble_py3 as pymumble
    except Exception as exc:
        raise RuntimeError("pymumble_py3 is required for Mumble client access") from exc

    _ensure_ssl_wrap_socket()

    server = host or getattr(settings, "PYMUMBLE_SERVER", "127.0.0.1")
    port = int(getattr(settings, "PYMUMBLE_PORT", 64738))
    user = getattr(settings, "PYMUMBLE_USER", "monitor")
    password = getattr(settings, "PYMUMBLE_PASSWD", "")
    cert_file = getattr(settings, "PYMUMBLE_CERT_FILE", None)
    key_file = getattr(settings, "PYMUMBLE_KEY_FILE", None)

    cert_path = None
    key_path = None
    if cert_file:
        candidate = Path(cert_file)
        if candidate.is_file():
            cert_path = str(candidate)
    if key_file:
        candidate = Path(key_file)
        if candidate.is_file():
            key_path = str(candidate)

    def _connect(cert_override: tuple[str | None, str | None] | None = None):
        cert_use, key_use = cert_override if cert_override else (cert_path, key_path)
        mumble = pymumble.Mumble(
            server,
            user=user,
            port=port,
            password=password,
            certfile=cert_use,
            keyfile=key_use,
            debug=False,
        )
        mumble.start()
        mumble.is_ready()
        try:
            from pymumble_py3.constants import (
                PYMUMBLE_CONN_STATE_CONNECTED,
            )
        except Exception:
            PYMUMBLE_CONN_STATE_CONNECTED = 2  # fallback
        if getattr(mumble, "connected", None) != PYMUMBLE_CONN_STATE_CONNECTED:
            raise RuntimeError("Mumble client not connected")
        return mumble

    retries = 3
    last_exc: Exception | None = None
    mumble = None
    default_timeout = socket.getdefaulttimeout()
    if timeout is not None:
        socket.setdefaulttimeout(timeout)
    for _ in range(retries):
        try:
            mumble = _connect()
            break
        except Exception as exc:  # pragma: no cover - connection-dependent
            last_exc = exc
            time.sleep(1)

    if mumble is None:
        # Try alternate certs if configured
        alt_cert = Path("..") / "murmur_tools" / "ni_cert.pem"
        alt_key = Path("..") / "murmur_tools" / "ni_key.pem"
        if alt_cert.is_file() and alt_key.is_file():
            try:
                mumble = _connect((str(alt_cert), str(alt_key)))
            except Exception as exc:
                last_exc = exc
    if timeout is not None:
        socket.setdefaulttimeout(default_timeout)

    if mumble is None:
        raise RuntimeError(f"Mumble client connection failed: {last_exc}")

    # wait briefly for the user list to populate (up to 5s)
    deadline = time.time() + (min(5.0, timeout) if timeout else 5.0)
    last_count = -1
    while time.time() < deadline:
        current = len(mumble.users)
        if current > 0 and current == last_count:
            break
        last_count = current
        time.sleep(0.5)

    seen_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users: list[dict[str, str]] = []
    try:
        for session_id, user_info in mumble.users.items():
            name = user_info.get("name", "")
            role = ""
            clean_name = str(name).strip()
            if clean_name.startswith("["):
                role = ""
            elif "[" in clean_name:
                prefix = clean_name.split("[", 1)[0].strip()
                role = prefix
                clean_name = clean_name[len(prefix):].lstrip()
            cert_hash = user_info.get("hash", "")
            channel_id = user_info.get("channel_id")
            texture_hash = user_info.get("texture_hash")
            user_id = user_info.get("user_id")
            users.append(
                {
                    "user": clean_name,
                    "roles": role,
                    "session": str(session_id),
                    "lastseen": seen_at,
                    "cert_hash": str(cert_hash),
                    "channel_id": str(channel_id) if channel_id is not None else "",
                    "texture_hash": str(texture_hash) if texture_hash is not None else "",
                    "user_id": str(user_id) if user_id is not None else "",
                }
            )
    finally:
        try:
            mumble.stop()
        except Exception:
            pass

    return users


def log_online_users(*, host: str | None = None) -> list[dict[str, str]]:
    """
    Fetch and log online users using the Mumble client connection.
    """
    server = host or getattr(settings, "PYMUMBLE_SERVER", "127.0.0.1")
    port = int(getattr(settings, "PYMUMBLE_PORT", 64738))
    logger.info("Mumble client connecting to %s:%s", server, port)
    users = fetch_online_users(host=server)
    logger.info("Mumble users: %s", len(users))
    for row in users:
        logger.info(
            "Mumble user: session=%s name=%s roles=%s cert=%s lastseen=%s",
            row.get("session"),
            row.get("user"),
            row.get("roles"),
            row.get("cert_hash"),
            row.get("lastseen"),
        )
    return users


def _ensure_cert_files() -> None:
    """
    Create Mumble client cert/key files if missing.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from datetime import datetime, timedelta

    cert_file = getattr(settings, "PYMUMBLE_CERT_FILE", None)
    key_file = getattr(settings, "PYMUMBLE_KEY_FILE", None)
    user = getattr(settings, "PYMUMBLE_USER", "monitor")
    if not cert_file or not key_file:
        return

    cert_path = Path(cert_file)
    key_path = Path(key_file)
    if cert_path.exists() and key_path.exists():
        return

    cert_path.parent.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, user)]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=3650))
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
