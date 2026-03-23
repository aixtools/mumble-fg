# FG/BG Integration Smoke Test

Use this checklist after deploying or changing either repo on the
`fgbg-db-isolation` branch.

It validates:

- FG -> BG control transport
- BG probe visibility used by FG verification flows
- ACL + pilot-snapshot sync behavior
- profile/manage panel rendering in FG

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

## 4. Manage Page Flow

From FG UI:

1. open Murmur manage page
2. confirm expected pilot/server/registration information renders
3. exercise admin-only actions with a privileged account

Verify with BG probe responses that the expected registration/admin state moved.

## 5. Failure-Mode Check

Temporarily misconfigure the control secret in FG and retry a mutating action.

Expected:

- FG shows a BG/auth failure instead of a false success
- BG rejects the request
- no persisted mutation occurs
