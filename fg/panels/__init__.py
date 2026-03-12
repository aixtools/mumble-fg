"""OO panel providers for host profile integration."""

from .providers import (
    AllianceAuthProfilePanelProvider,
    CubeProfilePanelProvider,
    GenericProfilePanelProvider,
    MurmurPanelDescriptor,
    ProfilePanelProvider,
)
from .registry import get_profile_panel_provider, register_profile_panel_provider
from .service import ProfilePanelService, build_profile_panels

__all__ = [
    'AllianceAuthProfilePanelProvider',
    'CubeProfilePanelProvider',
    'GenericProfilePanelProvider',
    'MurmurPanelDescriptor',
    'ProfilePanelProvider',
    'ProfilePanelService',
    'build_profile_panels',
    'get_profile_panel_provider',
    'register_profile_panel_provider',
]
