# mumble-fg / mumble-bg Conventions

This document records the current naming and boundary conventions shared by `mumble-fg` and `mumble-bg`.

The two repositories are co-dependent:

- `mumble-fg` is the foreground/UI/integration side
- `mumble-bg` is the background/daemon side

Neither one should be treated as a complete standalone Mumble solution without the other.

## Repo Names

- foreground repo: `mumble-fg`
- background repo: `mumble-bg`

Local convention:

- code repos live under `~/git/<repo>`
- `~/git` and `~/prj` are treated as equivalent workspace roots
- session venvs for testing use `~/.venv/codex` when available; otherwise use `~/.venv/<repo-name>`

Project-history convention:

- non-code history and archival material live under `~/git/repository/<repo>/...`
- handoffs and blocker notes should go there, not in the code repo

Agent-material convention:

- agent-specific project material should live under `~/git/ai_agents/<repo>/...`

## Runtime Roles

- `mumble-fg`
  - views
  - admin
  - templates
  - host-app integration
  - operator workflows

- `mumble-bg`
  - `authd`
  - `pulse`
  - ICE interaction
  - background reconciliation
  - private runtime state

## Host-App Naming

The upstream host application is referred to by contract role, not by product name.

Preferred term:

- `pilot`

This is used because the foreground/background pair depends on a pilot-oriented contract rather than on one specific host product such as Cube or AllianceAuth.

## Database / Contract Names

Foreground and background do not share a direct database.

Current intended split:

- pilot source DB
  - read-only from `mumble-bg`
  - nested under env secret: `DATABASES.pilot`
  - used for pilot identity and policy inputs

- `mumble-bg` DB
  - owned by `mumble-bg`
  - nested under env secret: `DATABASES.bg`
  - used for `mumble-bg` runtime and auth state

- Murmur DB
  - optional
  - read-only
  - debug/verification only
  - not part of normal operation

## Naming Surface

Preferred shared names:

- foreground repo: `mumble-fg`
- background repo: `mumble-bg`
- pilot contract object: `PilotIdentity`
- pilot adapter name: `PilotDBA`
- pilot read function: `list_pilot_identities()`
- background DB adapter: `MmblBgDBA`
- explicit fg/bg control channel name: `mumble_control`

The current transport and endpoint shape for `mumble_control` is documented in
`mumble-bg` at `docs/mumble-control.md`.

## Boundary Rules

Locked rules:

- no direct DB coupling from the host app into `mumble-bg`
- no writes from `mumble-bg` into host-owned pilot/core tables
- all fg/bg or host/bg actions should go through explicit interfaces or messages
- password reset requests must go through an explicit control path, not shared table writes

Practical consequence:

- `mumble-fg` must not assume direct access to the `mumble-bg` private DB
- `mumble-bg` must not assume it can mutate host-app tables directly
- `mumble-fg` should send control actions through `mumble_control`, not through
  shared imports or direct DB writes

## FG `mumble_` Naming Audit

Current fg usage of `mumble_` is mostly interface/product-level and should be
treated separately from bg model contracts:

- `mumble` runtime control and UX routes: `mumble_manage`, `toggle-admin`,
  `mumble_control`.
- permission and session keys: `manage_mumble_admin`, `view_mumble_presence`,
  `murmur_temp_password_*`.
- helper entry points and command utilities: `update_mumble_groups`,
  `update_all_mumble_groups`, `sync_murmur_registration`, etc.
- data objects/fields that already map to existing Murmur db tables:
  `murmur_userid`, `MumbleUser`, `mumble_control` DB fields.

For bg-facing reverse-relations, the current synced surface is intentionally
`murmur_registrations` and `murmur_sessions`; fg references should align to those
and the legacy relation names are no longer used for runtime model coupling.

## ICE / Murmur Rules

Normal operation:

- communication with Murmur is via ICE only

Optional debug mode:

- Murmur's own backing DB may be read to verify expected effects
- that probe must be non-blocking
- if unavailable, the result should be “did not operate”, not a startup failure

## Murmur Contract

Shared fg/bg Murmur configuration is split into two structured JSON secrets:

- `ICE`
- `MURMUR_PROBE`

`ICE` is the required ICE/runtime contract.

Shape:

```json
[
  {
    "name": "optional label",
    "host": "127.0.0.1",
    "virtual_server_id": 1,
    "icewrite": "write-secret",
    "iceport": 6502,
    "iceread": "read-secret"
  }
]
```

Required per server:

- `host`
- `virtual_server_id`
- `icewrite`

Optional per server:

- `name`
- `iceport`
- `iceread`

Rules:

- `name` defaults to `host:virtual_server_id` when omitted.
- `icewrite` is the required control path for `authd`.
- `iceread` is optional and is intended for `pulse` or other read-only ICE use.
- If `iceread` is omitted, `icewrite` may be reused.
- `iceport` may be supplied, but bg should discover it when absent.

`MURMUR_PROBE` is the optional Murmur DB probe/debug contract.

Shape:

```json
[
  {
    "name": "optional label",
    "host": "127.0.0.1",
    "username": "mumble",
    "database": "mumble_db",
    "password": "secret",
    "dbport": 5432,
    "dbengine": "postgres"
  }
]
```

Required per probe target:

- `host`
- `username`
- `database`
- `password`

Optional per probe target:

- `name`
- `dbport`
- `dbengine`

Rules:

- `name` defaults to `host` when omitted.
- `MURMUR_PROBE` is optional and debug-only.
- If `MURMUR_PROBE` is absent, normal operation still proceeds over ICE only.
- `dbengine` and `dbport` may be supplied, but bg should discover them when absent.

## Packaging / Layout

Background package layout:

- `bg/authd/...`
- `bg/pulse/...`
- bundled Murmur slice under `bg/ice/...`

Foreground package layout:

- `fg/...` for foreground-owned Django/UI code
- `fg/models.py` for host-contract model resolution
- `fg/control.py` for fg/bg control transport
- `templates/fg/...` for extracted foreground templates

Foreground repo still remains partially transitional around host identity/policy inputs.

## Current Status

The split is still in progress, but these names are the current target and should be used in new work instead of the older `cube-mumble`, `cube-monitor`, or `cube-core` names.
