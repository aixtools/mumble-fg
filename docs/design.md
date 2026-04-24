# mumble-fg Design

Verified: `mumble-fg` `main` version `0.3.7.dev1` on `2026-04-24`.

## Purpose

The Mumble integration is split into two services:

- `mumble-fg`: host-facing UI, operator flows, profile-panel integration, and host data reads
- `mumble-bg`: runtime state, Murmur/ICE integration, authd behavior, reconciliation, and runtime audit

FG reads host data. BG reads runtime data. FG and BG communicate only through explicit HTTP control/probe APIs.

## Ownership Boundary

FG owns:

- ACL CRUD and ACL audit UI
- `Mumble Controls` operator surfaces:
  - `Accessibility`
  - `Groups`
  - `Links`
- profile-panel rendering and pilot self-service password actions
- host-side pilot/account reads
- pilot snapshot export and FG-side cache state
- control client calls into BG
- host integration hooks for Cube-like apps

BG owns:

- cached ACL rules and pilot snapshot data received from FG
- Murmur server inventory and registration state
- password hashing state and generated plaintext password lifecycle during reset/set flows
- ICE integration, authenticator behavior, reconciliation, and live runtime state
- BG-side audit rows
- control-key bootstrap, export, and rotation

Explicitly not allowed:

- FG does not read BG tables directly
- BG does not read host pilot/core tables directly
- BG does not write host-owned tables
- long-lived cross-repo ORM coupling is a defect

## Identity Model

- stable cross-system account identity is `pkid`
- FG builds and sends pilot snapshot data keyed by `pkid`
- snapshot accounts include:
  - `account_username`
  - `display_name`
  - one main character
  - the full character list
  - corporation and alliance identifiers and names
- human-visible Mumble naming is derived from pilot and organization data, not from `pkid`
- runtime login username is FG `account_username`

## ACL Model

FG owns ACL policy and copies it to BG.

Supported rule types:

- alliance allow
- corporation deny
- pilot deny
- pilot allow
- pilot `acl_admin`

Precedence:

1. pilot allow/deny
2. corporation deny
3. alliance allow

Additional semantics:

- unlisted alliances are implicitly denied
- deny evaluation applies across the whole account, not just the main character
- a deny on any alt blocks the account unless a more-specific allow exists
- `acl_admin` is valid only on pilot rules
- `acl_admin` does not imply allow
- denied pilots cannot remain effective admin

## FG Application Permissions

Key FG permission families:

- ACL admin permissions
- group-mapping permissions:
  - `view_group_mapping`
  - `change_group_mapping`
  - `add_group_mapping`
  - `delete_group_mapping`
- temp-link permissions:
  - `view_temp_links`
  - `change_temp_links`
  - `add_temp_links`
  - `delete_temp_links`
- temp-link editor-group membership, which can grant `Links` access and mutation without the explicit Django temp-link permissions

Important rule:

- `is_staff` alone is not the authorization model for Mumble operations
- `is_superuser` is still an operator bypass in some FG/BG surfaces

## Control Contract

FG uses BG control endpoints for runtime-affecting actions.

Core operations:

- ACL sync
- pilot snapshot sync
- reconcile/provision request
- password reset / password set
- live admin membership sync
- runtime server query for profile-panel display
- group-mapping inventory reads
- temp-link redemption/management calls

Control authentication:

- FG authenticates to BG with the shared control secret
- preferred runtime secret name is `BG_PSK`
- FG prefers the rotating keyring and falls back to `BG_PSK` for bootstrap or break-glass behavior
- if BG is unreachable, FG surfaces unavailable behavior rather than falling back to direct DB mutation

## Profile Panel Contract

The `/profile/` Mumble panel is visible only when the account is ACL-eligible.

Current implementation:

- FG renders one panel per available BG server
- each panel shows a fixed-text `Server` field from the BG server label/name
- if more than one eligible pilot is available, FG shows a `Mumble Authentication` selector for pilot choice

The panel displays:

- `Server`
- `Display Name`
- `Username`
- `Address`
- `Port`
- `IsAdmin` only when true

If BG is unavailable:

- `Address` shows `BG unavailable`
- password actions are disabled

Target layout:

```text
+------------------------------------------------------------------+
| MUMBLE                                                           |
|------------------------------------------------------------------|
| Server      Finland                                              |
| Display Name [ALLY CORP] Pilot Main                              |
| Username    pilot_main                                           |
| Address     voice.example.org                                    |
| Port        64738                                                |
| IsAdmin     Yes                                                  |
|                                                                  |
| [Reset Password]                                                 |
| [Custom password __________________________] [Set Password]      |
+------------------------------------------------------------------+
```

## Runtime and Process Topology

FG runs as a Django optional app inside the host application.

Primary FG surfaces:

- profile panel and pilot self-service password actions
- operator controls for ACL, group mapping, temp links, password actions, and sync actions
- periodic tasks:
  - ACL sync every 10 minutes
  - group sync every 3 minutes

BG runs as separate Django-backed services:

- HTTP control service
- ICE authenticator daemon
- pulse/presence collector
- reconciler
- provisioning logic

## Current Direction

The current architecture replaces older shared-DB ideas with snapshot sync:

1. FG reads `PILOT_DBMS`
2. FG sends ACL rules and pilot snapshot to BG
3. BG stores that snapshot in `BG_DBMS`
4. BG provisions and reconciles Murmur state from its own cache plus rules

## Documentation Rule

Contract drift between docs and current code is a documentation bug.
