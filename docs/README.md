# mumble-fg Documentation

Verified: `mumble-fg` `main` version `0.3.7.dev1` on `2026-04-24`.

This directory is the canonical documentation location for this repository.

Primary reference:

- [design.md](./design.md) — current architecture, contracts, permissions, and profile-panel behavior.
- [operations.md](./operations.md) — deployment, workflow behavior, smoke checks, and restoreability probe.

## Scope

- `mumble-fg` is the host-facing UI/Admin integration layer.
- `mumble-bg` is the separate runtime daemon/runtime-auth layer.
- `mumble-fg` owns host-facing Mumble operator and pilot UI.
- Runtime actions that affect Murmur state are expected to flow through BG control/probe contracts when host models are unavailable.

- Host/admin pages:
  - `Mumble Controls` surfaces:
    - `Accessibility`
    - `Groups`
    - `Links`
  - ACL panel and permission checks.
- Profile-side password reset controls and profile panel entries.
- Contract adapters for BG control/probe communications.
- Pilot snapshot export and FG-side cache state for BG synchronization.
- Django tests that can run in both mocked host and full host-compatible environments.

## Working assumptions

- FG is the only side that reads `PILOT_DBMS`
- BG receives pilot snapshot data over control APIs
- FG should be the only package installed in `mockcube`
- `mockcube` should not import BG ORM models directly for FG admin/operator flows
- Superuser and FG module permissions are the primary admin gate for control-surface actions
- `Links` can also be granted through configured temp-link editor groups

## Operator checklist

1. Read this document before modifying any FG integration flow.
2. Verify `mumble-ui` mount and extension wiring are aligned in host.
3. Ensure BG endpoints are reached through explicit control URL and secret settings.
4. Keep mockcube-compatible compatibility shims minimal and explicit.
5. If a test or code path depends on host Murmur tables, mark/guard accordingly.

Keep the files above aligned with current code and workflows.
