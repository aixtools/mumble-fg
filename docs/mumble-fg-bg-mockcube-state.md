# Mockcube / mumble-fg / mumble-bg State

Date: 2026-03-15

This document is a compact handoff for the current `mockcube`, `mumble-fg`,
and `mumble-bg` direction. It focuses on the intended architecture, the
contract rules already documented elsewhere, and the current implementation
state.

## Target Direction

- `mockcube` is the host-side Django environment used to emulate Cube.
- `mumble-fg` is the host/UI/admin integration layer.
- `mumble-bg` is a separate service with its own virtualenv, runtime, and DB.
- `mumble-bg` should own Murmur/ICE state, control secrets, server inventory,
  registration state, and daemon-side data hidden from Cube/Mockcube.
- `mockcube` should still offer an operator/admin surface for bg, but that
  should be done through `fg` calling bg APIs, not by importing bg ORM models
  into the host app.

## Locked Rules

These points are repeated consistently across `mumble-fg/docs/conventions.md`,
`mumble-bg/docs/system-boundary.md`, and `mumble-bg/docs/mumble-control.md`.

- FG is the foreground/UI/operator side.
- BG is the background/daemon/ICE/private-state side.
- FG and BG should not share a direct database.
- The host app must not read BG's private DB directly.
- BG must not write into host-owned pilot/core tables.
- Cross-system mutations should go through explicit control interfaces.
- FG should verify BG mutations using BG read/probe endpoints, not local DB
  assumptions.
- `monitor` was only an example/reference source, not the long-term ownership
  location for shared contracts.

## Documented Contract Model

- Preferred host-facing term is `pilot`, not a product-specific name.
- BG reads pilot identity from a read-only `DATABASES.pilot` contract.
- BG owns its own runtime DB through `DATABASES.bg`.
- Murmur runtime configuration is split into structured JSON env/secret
  contracts:
  - `ICE`
  - `MURMUR_PROBE`
- BG exposes a narrow HTTP+JSON control/probe API.
- Current documented BG endpoints include:
  - `GET /v1/health`
  - `GET /v1/servers`
  - `GET /v1/pilots/{pkid}`
  - `GET /v1/control-key/status`
  - `POST /v1/password-reset`
  - `POST /v1/registrations/sync`
  - `POST /v1/registrations/contract-sync`
  - `POST /v1/registrations/disable`
  - `POST /v1/admin-membership/sync`
  - `POST /v1/control-key/bootstrap`
  - `POST /v1/control-key/rotate`
- The long-term interface is explicit API transport, not shared imports between
  repos.

## Current Mockcube State

- `mockcube` is now pinned to Django `4.2.29`.
- The admin page was aligned back to Django 4.2 stock admin structure.
- The admin rendering issue was a deployment/static problem, not an HTML
  mismatch:
  - nginx had been serving `/static/` from `mockcube/static/`
  - Django admin CSS actually lives under `mockcube/staticfiles/`
  - once nginx served `staticfiles/`, the stock Django blue header/module
    backgrounds returned
- `mockcube` now has its own local Git repo and tag:
  - version in `pyproject.toml`: `0.1.0.alpha0`
  - tag: `0.1.0.alpha0`
- `mockcube` currently works as the host-side test bed, but it does not yet
  provide the host concepts that `mumble-fg` still expects.

## Current mumble-fg State

- `mumble-fg` still reflects a transitional extraction, not the final contract
  shape.
- It still contains host-side/UI concerns:
  - profile/manage views
  - sidebar registration
  - operator/admin workflows
- It still has host-coupled assumptions that block clean installation into
  `mockcube`:
  - imports from `accounts`
  - imports from `modules.corporation`
  - expectations about host-side models like `GroupMembership`
- Local packaging work has now started:
  - `pyproject.toml` added locally
  - local contract helper added in `fg/contracts.py`
  - wheel build now succeeds
- Local `monitor` coupling was removed from `fg/control.py` by moving the needed
  contract object into `fg/contracts.py`.

## Current mumble-bg State

- `mumble-bg` is already documented as the separate-service target.
- BG owns:
  - `authd`
  - `pulse`
  - ICE interaction
  - control endpoints
  - private runtime/auth state
  - `bg.state` ORM models and migrations
- Local packaging work has now started:
  - setuptools-style `pyproject.toml` added locally
  - local contract helpers added in `bg/contracts.py`
  - wheel build now succeeds
- Local `monitor` coupling was removed from:
  - `bg/authd/service.py`
  - `bg/control.py`
- BG still assumes a Django app install context for `bg.state`, which is fine
  for the BG service itself but not the right direction for `mockcube` if BG is
  meant to stay separate.

## Current Wheel / Install Result

- A local wheelhouse was staged in `/home/michael/dist`.
- Useful wheels were copied there from `/home/monitor/dist`.
- Added there as well:
  - `django-4.2.29`
  - `bcrypt-4.0.1`
  - `passlib-1.7.4`
  - `mysqlclient-2.2.8`
  - `zeroc-ice-3.7.11`
  - local `mumble-fg` wheel
  - local `mumble-bg` wheel
- Installing both wheels into the `mockcube` venv now works from the local
  wheelhouse.
- The remaining failures are integration seams, not packaging failures.

## Current Import / Integration Failures In Mockcube

After wheel install into the `mockcube` venv:

- `fg.contracts` and `fg.control` import successfully.
- `fg.models`, `fg.sidebar`, `fg.views`, and `fg.admin` now import
  successfully after moving host-specific account/permission assumptions behind
  a settings-driven FG host adapter and making Murmur model resolution lazy.
- `bg.contracts` and `bg.authd.service` import successfully.
- `fg` profile panel reads now degrade cleanly to an empty panel list when the
  host does not provide a Murmur model app.
- FG action views still require a host Murmur model app for live runtime use,
  so `mockcube` still needs an explicit host-side Murmur contract or a further
  FG read-model refactor before those URLs are useful there.
- `bg.state.models` and `bg.control` fail in `mockcube` because `bg.state` is
  not in `INSTALLED_APPS`.

## Interpretation

- Packaging is no longer the main problem.
- Installing BG into `mockcube` was useful as a diagnostic, but it is probably
  the wrong runtime target if BG is meant to remain a separate service.
- The desired steady state is:
  - `mockcube` installs `mumble-fg`
  - `mumble-bg` runs separately in its own venv/service
  - `mockcube` admins/operators manage BG through FG-admin or FG-staff pages
  - those pages call BG control/probe APIs
- If that direction is accepted, `mockcube` should not install or mount
  `bg.state` as a host app.

## Recommended Next Steps

- Keep BG separate:
  - its own venv
  - its own runtime DB
  - its own service/processes
- Make FG the only package intended to install into `mockcube`.
- Remove remaining host-coupled assumptions from FG or isolate them behind host
  adapters:
  - `modules.corporation`
  - `GroupMembership`
  - host permission/group checks
- Make FG admin/staff surfaces talk to BG only through explicit APIs.
- Do not use BG ORM models in `mockcube` for operator/admin UX.
- Treat BG probe responses as the source of truth for post-action verification.

## Context Spine

Use this to start a new session quickly:

- `mockcube` is the host-side Cube emulator on Django `4.2.29`.
- `mockcube` admin now matches Cube closely after fixing nginx to serve
  `staticfiles/` instead of `static/`.
- `mumble-fg` is supposed to be the host/UI/admin layer.
- `mumble-bg` is supposed to be the separate daemon/runtime layer with hidden
  state.
- Locked rule: no direct host reads of BG DB, no BG writes into host tables,
  and no long-term shared-import boundary between repos.
- Correct integration model is FG admin/staff UI in `mockcube` calling BG
  control/probe APIs.
- Local packaging work is in progress for FG and BG; both wheels now build.
- Both wheels can be installed into the `mockcube` venv from `/home/michael/dist`.
- Remaining blockers are host integration seams in FG, not package build issues.
- The likely next move is to stop treating BG as a host-installed Django app and
  refactor FG to be API-only toward BG.
