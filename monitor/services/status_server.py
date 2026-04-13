from __future__ import annotations

import socket
import sys
import signal
import threading
import logging
from pathlib import Path
from wsgiref.simple_server import make_server

from django.test import RequestFactory
import django

from monitor.services.local_settings import configure_django_from_local_settings
from monitor.services.logging_config import configure_logging
from monitor.services.item_pricing import flush_item_price_caches
from monitor.services.roster_cache import refresh_roster_cache
from monitor.views import (
    status_ice_users_json,
    status_main_alts_json,
    status_mains_json,
    status_mains_with_alts_json,
    status_orphans_json,
    status_pilot_wealth_json,
    status_pilots_json,
    status_spies_json,
    status_view,
)


ROOT = Path(__file__).resolve().parents[2]
LOGGER = logging.getLogger(__name__)


def _bind_port(preferred: int) -> int:
    last_exc: OSError | None = None
    for port in (preferred,):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
            return port
        except OSError as exc:
            last_exc = exc
            continue
    detail = f": {last_exc}" if last_exc else ""
    raise RuntimeError(
        f"Unable to bind port {preferred} for status server{detail}"
    )


def main() -> int:
    configure_django_from_local_settings()
    # Foreground is default unless background mode is explicitly requested.
    fg = "--bg" not in sys.argv
    configure_logging(fg=fg)
    try:
        port = _bind_port(38450)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        print("Status server not started (port already in use).", file=sys.stderr)
        return 0
    host = "0.0.0.0"

    django.setup()
    factory = RequestFactory()
    try:
        refresh_roster_cache()
    except Exception:
        LOGGER.exception("Roster cache preload failed during startup")

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "/")
        clean_path = path.rstrip("/")
        if clean_path == "/monitor/status":
            query = environ.get("QUERY_STRING", "")
            full_path = f"{path}?{query}" if query else path
            request = factory.get(full_path)
            response = status_view(request)
            status = f"{response.status_code} OK"
            headers = [
                ("Content-Type", response["Content-Type"]),
                ("Content-Length", str(len(response.content))),
            ]
            start_response(status, headers)
            return [response.content]
        if clean_path == "/monitor/status/mains":
            query = environ.get("QUERY_STRING", "")
            full_path = f"{path}?{query}" if query else path
            request = factory.get(full_path)
            response = status_mains_json(request)
            status = f"{response.status_code} OK"
            headers = [
                ("Content-Type", response["Content-Type"]),
                ("Content-Length", str(len(response.content))),
            ]
            start_response(status, headers)
            return [response.content]
        if clean_path == "/monitor/status/mains-with-alts":
            query = environ.get("QUERY_STRING", "")
            full_path = f"{path}?{query}" if query else path
            request = factory.get(full_path)
            response = status_mains_with_alts_json(request)
            status = f"{response.status_code} OK"
            headers = [
                ("Content-Type", response["Content-Type"]),
                (
                    "Content-Length",
                    str(len(response.content)),
                ),
            ]
            start_response(status, headers)
            return [response.content]
        if clean_path == "/monitor/status/main-alts":
            query = environ.get("QUERY_STRING", "")
            full_path = f"{path}?{query}" if query else path
            request = factory.get(full_path)
            response = status_main_alts_json(request)
            status = f"{response.status_code} OK"
            headers = [
                ("Content-Type", response["Content-Type"]),
                (
                    "Content-Length",
                    str(len(response.content)),
                ),
            ]
            start_response(status, headers)
            return [response.content]
        if clean_path == "/monitor/status/orphans":
            query = environ.get("QUERY_STRING", "")
            full_path = f"{path}?{query}" if query else path
            request = factory.get(full_path)
            response = status_orphans_json(request)
            status = f"{response.status_code} OK"
            headers = [
                ("Content-Type", response["Content-Type"]),
                (
                    "Content-Length",
                    str(len(response.content)),
                ),
            ]
            start_response(status, headers)
            return [response.content]
        if clean_path == "/monitor/status/pilots":
            query = environ.get("QUERY_STRING", "")
            full_path = f"{path}?{query}" if query else path
            request = factory.get(full_path)
            response = status_pilots_json(request)
            status = f"{response.status_code} OK"
            headers = [
                ("Content-Type", response["Content-Type"]),
                (
                    "Content-Length",
                    str(len(response.content)),
                ),
            ]
            start_response(status, headers)
            return [response.content]
        if clean_path == "/monitor/status/spies":
            query = environ.get("QUERY_STRING", "")
            full_path = f"{path}?{query}" if query else path
            request = factory.get(full_path)
            response = status_spies_json(request)
            status = f"{response.status_code} OK"
            headers = [
                ("Content-Type", response["Content-Type"]),
                (
                    "Content-Length",
                    str(len(response.content)),
                ),
            ]
            start_response(status, headers)
            return [response.content]
        if clean_path == "/monitor/status/pilot-wealth":
            query = environ.get("QUERY_STRING", "")
            full_path = f"{path}?{query}" if query else path
            request = factory.get(full_path)
            response = status_pilot_wealth_json(request)
            status = f"{response.status_code} OK"
            headers = [
                ("Content-Type", response["Content-Type"]),
                (
                    "Content-Length",
                    str(len(response.content)),
                ),
            ]
            start_response(status, headers)
            return [response.content]
        if clean_path == "/monitor/status/ice-users":
            query = environ.get("QUERY_STRING", "")
            full_path = f"{path}?{query}" if query else path
            request = factory.get(full_path)
            response = status_ice_users_json(request)
            status = f"{response.status_code} OK"
            headers = [
                ("Content-Type", response["Content-Type"]),
                ("Content-Length", str(len(response.content))),
            ]
            start_response(status, headers)
            return [response.content]
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Not Found"]

    with make_server(host, port, app) as server:
        stop_event = threading.Event()

        def _shutdown(*_):
            if stop_event.is_set():
                return
            stop_event.set()
            flush_item_price_caches()
            print("Shutting down monitor.", flush=True)
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
        print(f"Serving http://{host}:{port}/monitor/status/", flush=True)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            _shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
