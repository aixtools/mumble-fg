# FG/BG Integration Smoke Test

This checklist validates:

- FG -> BG control transport
- BG probe visibility used by FG verification flows
- profile/manage panel rendering in FG

Use this after deploying both repos.

## Prerequisites

- `mumble-bg` reachable at configured `MURMUR_CONTROL_URL`
- FG host app has valid control PSK in environment
- at least one active Murmur server row exists in bg state
- one pilot account already linked to that server

## 1) BG API Reachability

From the FG host:

```bash
curl -sS "${MURMUR_CONTROL_URL%/}/v1/health"
```

Expected:

- `"status": "ok"`
- `"control_mode"` is one of `db`, `env`, or `open`

## 2) Control Write Path (Password Reset)

From FG UI:

1. Open profile page.
2. Click `Reset Password` on one Murmur panel.
3. Confirm success/warning message in UI.

Then verify with BG probe:

```bash
curl -sS "${MURMUR_CONTROL_URL%/}/v1/pilots/<pkid>"
```

Check:

- registration row for the target server exists
- `pw_lastchanged` changed after reset request

## 3) Manage Page Presence + Admin Flow

From FG UI:

1. Open Murmur manage page.
2. Verify columns show:
   - pilot account
   - server
   - Murmur ID
   - session/presence columns
3. Toggle admin for a pilot account with permissioned user.

Verify with BG probe response:

- `is_murmur_admin` and `admin_membership_state` reflect expected value.

## 4) Superuser Contract Metadata Sync (FG-102)

As superuser on Murmur manage page:

1. Enter `evepilot_id`, `corporation_id`, `alliance_id`, `kdf_iterations`.
2. Submit `Sync Contract Metadata`.
3. Confirm success message appears only when probe values match requested values.

Probe verification:

```bash
curl -sS "${MURMUR_CONTROL_URL%/}/v1/pilots/<pkid>"
```

Check target registration row includes:

- `evepilot_id`
- `corporation_id`
- `alliance_id`
- `kdf_iterations`

## 5) Panel UX Spot Check

Validate in profile panels:

- duplicate username slot suffixes (for multi-server same username): `:1`, `:2`
- one-time temporary password rendering and session pop behavior
- server label and tooltip/hint rendering for disambiguation

## 6) Failure-Mode Check

Temporarily set wrong PSK in FG environment and retry a mutating action.

Expected:

- FG shows failed control request warning
- BG returns auth rejection (`401`/`rejected`)
- no persisted mutation for attempted action
