"""Transitional access to host-app Mumble sync helpers."""

try:
    from modules.mumble.ice_sync import (
        MumbleSyncError,
        sync_live_admin_membership,
        sync_mumble_registration,
        unregister_mumble_registration,
    )
except ImportError as exc:
    raise ImportError(
        'fg.pilot.ice_sync expects the host application to provide '
        'modules.mumble.ice_sync during the current extraction phase.'
    ) from exc

__all__ = [
    'MumbleSyncError',
    'sync_live_admin_membership',
    'sync_mumble_registration',
    'unregister_mumble_registration',
]
