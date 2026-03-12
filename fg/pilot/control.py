"""Pilot-facing control seam for fg/bg runtime actions.

The foreground should not call bg internals directly. This module keeps the
current extraction-compatible call sites while making it explicit that these
helpers are the control boundary.
"""

try:
    from modules.mumble.ice_sync import (
        MumbleSyncError,
        _open_target_server,
        sync_live_admin_membership,
        sync_mumble_registration,
        unregister_mumble_registration,
    )
except ImportError as exc:
    raise ImportError(
        'fg.pilot.control expects the host application to provide '
        'modules.mumble.ice_sync during this extraction phase.'
    ) from exc


__all__ = [
    'MumbleSyncError',
    '_open_target_server',
    'sync_live_admin_membership',
    'sync_mumble_registration',
    'unregister_mumble_registration',
]
