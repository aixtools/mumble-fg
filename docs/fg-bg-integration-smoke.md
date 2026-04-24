# FG/BG Integration Smoke Test

Verified: `mumble-fg` `main` version `0.3.7.dev1` on `2026-04-24`.

Use this checklist after deploying or changing either repo.

It validates:

- FG -> BG control transport
- BG probe visibility used by FG verification flows
- ACL + pilot-snapshot sync behavior
- profile panel rendering in FG
- `Mumble Controls` rendering in FG

## Prerequisites

- FG host app is up
- BG control API is reachable at `MURMUR_CONTROL_URL`
- FG and BG share the same control secret
- BG has at least one active server row

## 1. BG API Reachability

From the FG host:

```bash
curl -sS "${MURMUR_CONTROL_URL%/}/v1/health"
```

Expected:

- BG reports healthy status
- control auth mode is sensible for the environment

## 2. ACL + Pilot Snapshot Sync

From FG:

1. open the ACL page
2. trigger `Sync BG`

Expected FG sequence:

1. ACL rules sent to `/v1/access-rules/sync`
2. pilot snapshot sent to `/v1/pilot-snapshot/sync`
3. reconcile optionally requested through `/v1/provision`

If BG reports missing pilot snapshot data, the snapshot sync step is not landing.

## 3. Profile Password Flow

From FG UI:

1. open a profile page
2. trigger `Reset Password` or `Set Password`
3. confirm FG surfaces BG success/failure correctly

Then verify with BG probe:

```bash
curl -sS "${MURMUR_CONTROL_URL%/}/v1/pilots/<pkid>"
```

Check that the target registration state changed as expected.

## 4. Mumble Controls Flow

From FG UI:

1. open `Mumble Controls`
2. confirm the expected tabs render for the current account permissions
3. exercise admin-only actions with a privileged account
4. if group mapping is enabled for the account, confirm `Groups` can load BG-backed server inventory
5. if temp links are enabled for the account, confirm `Links` renders and BG-unavailable states surface correctly

Verify with BG probe responses that the expected registration/admin state moved.

## 5. Failure-Mode Check

Temporarily misconfigure the control secret in FG and retry a mutating action.

Expected:

- FG shows a BG/auth failure instead of a false success
- BG rejects the request
- no persisted mutation occurs
