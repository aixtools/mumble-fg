"""OO panel providers for host profile integration."""

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


def __getattr__(name):
    if name in {'ProfilePanelService', 'build_profile_panels'}:
        from .service import ProfilePanelService, build_profile_panels

        return {
            'ProfilePanelService': ProfilePanelService,
            'build_profile_panels': build_profile_panels,
        }[name]

    if name in {'get_profile_panel_provider', 'register_profile_panel_provider'}:
        from .registry import get_profile_panel_provider, register_profile_panel_provider

        return {
            'get_profile_panel_provider': get_profile_panel_provider,
            'register_profile_panel_provider': register_profile_panel_provider,
        }[name]

    if name in {
        'AllianceAuthProfilePanelProvider',
        'CubeProfilePanelProvider',
        'GenericProfilePanelProvider',
        'MurmurPanelDescriptor',
        'ProfilePanelProvider',
    }:
        from .providers import (
            AllianceAuthProfilePanelProvider,
            CubeProfilePanelProvider,
            GenericProfilePanelProvider,
            MurmurPanelDescriptor,
            ProfilePanelProvider,
        )

        return {
            'AllianceAuthProfilePanelProvider': AllianceAuthProfilePanelProvider,
            'CubeProfilePanelProvider': CubeProfilePanelProvider,
            'GenericProfilePanelProvider': GenericProfilePanelProvider,
            'MurmurPanelDescriptor': MurmurPanelDescriptor,
            'ProfilePanelProvider': ProfilePanelProvider,
        }[name]

    raise AttributeError(name)
