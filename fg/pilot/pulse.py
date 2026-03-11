"""Transitional access to host-app pulse helpers kept only for legacy tests."""

try:
    from modules.mumble.pulse import (
        mark_server_sessions_disconnected,
        mark_session_disconnected,
        reconcile_server_snapshot,
        record_successful_authentication,
        upsert_session_from_state,
    )
except ImportError as exc:
    raise ImportError(
        'fg.pilot.pulse expects the host application to provide '
        'modules.mumble.pulse during the current extraction phase.'
    ) from exc

__all__ = [
    'mark_server_sessions_disconnected',
    'mark_session_disconnected',
    'reconcile_server_snapshot',
    'record_successful_authentication',
    'upsert_session_from_state',
]
