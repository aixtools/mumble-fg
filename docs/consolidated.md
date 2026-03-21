# mumble-fg Consolidated Documentation

This document is the active, consolidated operating document for the `mumble-fg` repository. It replaces the old per-topic docs that now live in
[history/mumble-fg](../../repository/history/mumble-fg).

## Purpose and Current Architecture

- `mumble-fg` is the host-facing UI/Admin integration layer.
- `mumble-bg` is the separate runtime daemon/runtime-auth layer.
- `mumble-fg` owns Murmur-facing ACL modeling and UI views.
- Runtime actions that affect Murmur state are expected to flow through BG control/probe contracts when host models are unavailable.
- Legacy host coupling is being reduced in favor of adapter and runtime fallback behavior.

## Repo Scope

- Host/admin pages:
  - Manage/Murmur account lifecycle actions.
  - ACL panel and permission checks.
- Profile-side password reset controls and profile panel entries.
- Contract adapters for BG control/probe communications.
- Django tests that can run in both mocked host and full host-compatible environments.

## Host/Integration Contract

- FG is the only side that reads `PILOT_DBMS`; BG receives pilot snapshot data over control APIs.
- `fg` should be the only package installed in `mockcube`.
- `mockcube` should not import BG ORM models directly for FG admin/operator flows.
- `fg` runtime should prefer:
  - `fg.runtime` + runtime payloads when host Murmur models are unavailable.
  - `MURMUR_MODEL_APP_LABEL` resolved models only when explicitly present.
- Explicit host permissions/caps:
  - Superuser and module perms are now the intended admin gate for ACL UI actions.
  - Non-staff users should not get broader UI surface by default.

## Test Guidance

- For full host-like FG test execution:
  - Set `FG_RUN_HOST_MURMUR_TESTS=1` and run standard Django tests.
- For mockcube-like host shell execution:
  - Leave `FG_RUN_HOST_MURMUR_TESTS` unset/false and run standard FG tests to skip host-bound tests.
- If tests need multi-DB behavior, include both aliases explicitly in test classes (`databases = [...]`).

## Operations Checklist

1. Read this document before modifying any FG integration flow.
2. Verify `mumble-ui` mount and extension wiring are aligned in host.
3. Ensure BG endpoints are reached through explicit control URL and secret settings.
4. Keep mockcube-compatible compatibility shims minimal and explicit.
5. If a test or code path depends on host Murmur tables, mark/guard accordingly.

## Companion Docs

- [conventions.md](./conventions.md)
- [workflow-deploy.md](./workflow-deploy.md)
- [fg-bg-integration-smoke.md](./fg-bg-integration-smoke.md)
- [pilot-backup-restore-probe.md](./pilot-backup-restore-probe.md)

## Archived Documentation Index

- [history/mumble-fg/bootstrap-dev-deploy.md](../../repository/history/mumble-fg/bootstrap-dev-deploy.md)
- [history/mumble-fg/conventions.md](../../repository/history/mumble-fg/conventions.md)
- [history/mumble-fg/fg-bg-integration-smoke.md](../../repository/history/mumble-fg/fg-bg-integration-smoke.md)
- [history/mumble-fg/implementation-matrix.md](../../repository/history/mumble-fg/implementation-matrix.md)
- [history/mumble-fg/mumble-fg-bg-mockcube-state.md](../../repository/history/mumble-fg/mumble-fg-bg-mockcube-state.md)
- [history/mumble-fg/pilot-backup-restore-probe.md](../../repository/history/mumble-fg/pilot-backup-restore-probe.md)
- [history/mumble-fg/profile-panels.md](../../repository/history/mumble-fg/profile-panels.md)
- [repository/mumble-fg/history/HANDOFF-2026-03-11-fg.md](../../repository/mumble-fg/history/HANDOFF-2026-03-11-fg.md)
- [repository/mumble-fg/history/HANDOFF-2026-03-12-done-todo-learned.md](../../repository/mumble-fg/history/HANDOFF-2026-03-12-done-todo-learned.md)
- [repository/mumble-fg/history/HANDOFF-2026-03-12-fg-bg-smoke.md](../../repository/mumble-fg/history/HANDOFF-2026-03-12-fg-bg-smoke.md)
- [repository/mumble-fg/history/HANDOFF-2026-03-12-fg.md](../../repository/mumble-fg/history/HANDOFF-2026-03-12-fg.md)
