# FG/BG Conventions

This document records the current naming and boundary conventions shared by
`mumble-fg` and `mumble-bg` on the `fgbg-db-isolation` branch.

## Roles

- `mumble-fg` is the host/UI/admin side
- `mumble-bg` is the runtime/state daemon side

FG and BG are intentionally separate repos with an API boundary between them.

## Database Terms

- `PILOT_DBMS` means the host-side pilot data source that FG reads from
- `BG_DBMS` means the BG-owned runtime database

Current branch rules:

- FG is the only side that reads `PILOT_DBMS`
- BG never reads `PILOT_DBMS` directly
- FG does not read `BG_DBMS` directly
- BG caches FG pilot snapshot data inside `BG_DBMS`

## Integration Terms

Preferred shared terms:

- FG = foreground/UI/integration side
- BG = background/runtime side
- pilot snapshot = the FG-exported account-oriented payload sent to BG
- control channel = the explicit FG -> BG HTTP API

Current control settings are:

- `MURMUR_CONTROL_URL`
- `FGBG_PSK`

## Boundary Rules

Locked rules:

- no shared DB coupling across repos
- no BG writes into host-owned pilot/core tables
- no FG reads from BG runtime tables
- mutating FG -> BG flows go through control endpoints

## Murmur Integration Rules

- normal runtime communication with Murmur is through BG
- FG verifies outcomes through BG control/probe responses
- direct Murmur DB access is optional and debug-only

## Branch Direction

This branch replaces the older shared-DB idea with snapshot sync:

1. FG reads `PILOT_DBMS`
2. FG sends ACL rules and pilot snapshot to BG
3. BG stores that snapshot in `BG_DBMS`
4. BG provisions and reconciles Murmur state from its own cache plus rules
