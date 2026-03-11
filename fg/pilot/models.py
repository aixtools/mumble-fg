"""Transitional access to host-app Mumble models."""

try:
    from modules.mumble.models import MumbleServer, MumbleSession, MumbleUser
except ImportError as exc:
    raise ImportError(
        'fg.pilot.models expects the host application to provide '
        'modules.mumble.models during the current extraction phase.'
    ) from exc

__all__ = ['MumbleServer', 'MumbleSession', 'MumbleUser']
