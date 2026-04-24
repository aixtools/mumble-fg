# FG/BG Design Specification

Verified: `mumble-fg` `main` version `0.3.7.dev1` on `2026-04-24`.

This document is written as the design contract the FG/BG split is expected to satisfy.

## 1. Purpose

The Mumble integration is split into two components:

- `mumble-fg` SHALL be the host/UI/admin side.
- `mumble-bg` SHALL be the runtime/state side.

The split exists so host application data access, operator UI, and end-user UI remain in FG,
while Murmur runtime state, ICE integration, authd behavior, and background reconciliation remain in BG.

## 2. Boundary Rules

- FG SHALL be the only side that reads host pilot data.
- BG SHALL own its own runtime database and SHALL NOT read host pilot/core tables directly.
- FG SHALL NOT read BG tables directly.
- BG SHALL NOT write host-owned tables.
- FG and BG SHALL communicate over explicit HTTP control/probe APIs only.
- Long-term shared ORM/model coupling across repos SHALL be treated as a defect.

## 3. Identity Model

- Stable account identity SHALL be `pkid`.
- FG SHALL build and send pilot snapshot data keyed by `pkid`.
- A snapshot account SHALL contain:
  - the account username
  - the resolved display name
  - the main character
  - the character list for that account
  - corporation and alliance identifiers for those characters
- Human-visible Mumble naming SHALL be derived from pilot and organization data, not from the internal `pkid` key.

## 4. ACL Model

FG SHALL own the ACL policy surface.

Supported rule types:

- alliance allow
- corporation deny
- pilot deny
- pilot allow
- pilot `acl_admin`

ACL precedence SHALL be:

1. pilot allow/deny
2. corporation deny
3. alliance allow

Additional rules:

- Unlisted alliances SHALL be implicitly denied.
- Deny evaluation SHALL apply across the entire account, not only the main character.
- A deny hit on any alt SHALL block the account unless overridden by a more-specific allow.
- `acl_admin` SHALL be valid only on pilot rules.
- `acl_admin` SHALL NOT imply allow.
- A pilot SHALL NOT remain `acl_admin` when a corporation or alliance deny applies.

## 5. FG Responsibilities

FG SHALL provide:

- ACL CRUD and audit UI
- `Mumble Controls` operator surfaces (`Accessibility`, `Groups`, `Links`) as implemented and permissioned
- sync actions that push ACL and pilot snapshot state to BG
- the `/profile/` Mumble panel
- host integration hooks for Cube or Cube-like hosts

FG SHALL expose the following operator behaviors:

- manual `Sync BG`
- periodic sync via management command
- explicit permission-gated ACL actions
- append-only audit visibility

## 6. Control Operations

FG SHALL use BG control endpoints for runtime-affecting actions.

Minimum operations:

- ACL sync
- pilot snapshot sync
- reconcile/provision request
- password reset / password set
- live admin membership sync
- runtime server query for profile panel display

Control authentication:

- FG SHALL authenticate to BG with the shared control secret.
- The preferred runtime name for that secret is `BG_PSK`.
- If BG is unreachable, FG SHALL present the operation as unavailable rather than attempting fallback DB behavior.

## 7. Profile Panel Contract

The panel SHALL be visible only when the pilot account is eligible.

Current implementation behavior:

- FG renders one panel per available BG server.
- Each panel shows a fixed-text `Server` field derived from the BG server label/name.
- If more than one eligible pilot is available, FG shows a `Mumble Authentication` selector for pilot choice.

The panel SHALL display:

- `Server`
- `Display Name`
- `Username`
- `Address`
- `Port`
- `IsAdmin` only when true

The displayed Mumble identity SHALL be the resolved human-facing name, not the internal `pkid`.

Target layout:

```text
+------------------------------------------------------------------+
| MUMBLE                                                           |
|------------------------------------------------------------------|
| Server      Finland                                              |
| Display Name [ALLY CORP] Pilot Main                              |
| Username    pilot_main                                           |
| Address    voice.example.org                                     |
| Port       64738                                                 |
| IsAdmin    Yes                                                   |
|                                                                  |
| [Reset Password]                                                 |
| [Custom password __________________________] [Set Password]      |
+------------------------------------------------------------------+
```

## 8. Password and Admin Semantics

- FG SHALL validate password actions before calling BG.
- BG SHALL remain the source of truth for runtime password state.
- FG SHALL expose admin toggles only to appropriately permissioned users.
- `is_staff` alone SHALL NOT grant FG management access.

Failure semantics:

- BG unreachable -> unavailable
- BG reachable but account inactive/not ready -> inactive/try later

## 9. Audit and Safety

- ACL audit SHALL be append-only.
- Pilot-visible actions that mutate runtime state SHALL be traceable through FG and/or BG audit rows.
- Contract drift between FG docs and BG docs SHALL be treated as a documentation bug.
