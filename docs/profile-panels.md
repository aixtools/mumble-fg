# Profile Panel Providers

`mumble-fg` now exposes OO profile panel providers so host apps can render Murmur account panels without hard-coding host-specific logic in views.

## Entry Points

- `fg.panels.ProfilePanelService`
- `fg.panels.build_profile_panels(request, host=None)`
- `fg.integration.MurmurHostIntegration` (host facade)
- `fg.integration.CubeMurmurIntegration`
- `fg.integration.AllianceAuthMurmurIntegration`

Both resolve a provider object via the registry and return panel dicts compatible with host profile panel extension seams.

## Provider Model

Providers implement `ProfilePanelProvider` from `fg.panels.providers`.

Built-in providers:

- `GenericProfilePanelProvider`
- `CubeProfilePanelProvider`
- `AllianceAuthProfilePanelProvider`

Current host adapters inherit generic behavior and differ by provider identity, so host specialization can be added without in-line host checks.

## Registry

Default registry mapping in `fg.panels.registry`:

- `generic` -> `GenericProfilePanelProvider`
- `cube` -> `CubeProfilePanelProvider`
- `allianceauth` -> `AllianceAuthProfilePanelProvider`

Resolution order:

1. explicit `host` argument
2. Django setting `MURMUR_PANEL_HOST`
3. `generic`

Custom providers can be registered with:

- `register_profile_panel_provider(host, factory)`

## Multi-Server Username Slotting

When one pilot has multiple active Murmur registrations with the same username, providers append an ordinal suffix in panel context:

- `username:1`
- `username:2`

This gives a stable visual disambiguator without exposing server internals directly in the username field.

Server identity remains available via panel metadata (`server_label`, `server_hint`) for tooltips or advanced UI affordances.
