# Bootstrap Dev Deploy (FG)

This document covers `mumble-fg` deployment to a dev host using GitHub Actions.

`mumble-fg` is UI/integration code (not a standalone daemon). Deploy means:

- syncing this repository to a configured target directory
- ensuring host Django imports `fg` and can load `templates/`
- configuring FG -> BG control transport in the host Django runtime

## What The Workflow Does

The workflow in `.github/workflows/deploy-dev.yml`:

- resolves deploy target from a single JSON secret (default `DEV_DEPLOY_TARGET`)
- rsyncs this repository to `project_dir` (defaults to `/home/<user>/mumble-fg`)
- optionally restarts units listed in `service_units`
- verifies expected FG files exist on the host

It does not create host Django settings, manage Python packages, or write FG
runtime secrets.

## GitHub Actions Configuration

Required:

- deploy target JSON secret (default secret name: `DEV_DEPLOY_TARGET`)

Optional:

- `workflow_dispatch` input `deploy_target_name` to select a different target secret

No additional FG-specific GitHub secret is required by this workflow.

Target JSON shape:

```json
{
  "host": "dev-host.example.net",
  "user": "deploy",
  "key": "-----BEGIN OPENSSH PRIVATE KEY-----\\n...\\n-----END OPENSSH PRIVATE KEY-----",
  "home_dir": "/home/deploy",
  "project_dir": "/home/deploy/mumble-fg",
  "service_units": ["web.service", "worker.service", "scheduler.service"]
}
```

Required fields:

- `host`
- `user`
- `key`

Optional fields:

- `home_dir` (default `/home/<user>`)
- `project_dir` (default `<home_dir>/mumble-fg`)
- `service_units` (array of systemd unit names; when omitted, restart step is skipped)

## Host Runtime Settings (Not GitHub Secrets)

Set these in the host environment used by Django:

- `MURMUR_CONTROL_URL` (or `MURMUR_CONTROL_BASE_URL`)
- `MURMUR_CONTROL_PSK` (or `MURMUR_CONTROL_SHARED_SECRET`)
- `MURMUR_PANEL_HOST` (provider selection key for your host integration)
- `MURMUR_MODEL_APP_LABEL` (usually `mumble`)

Optional:

- `MURMUR_MODEL_FALLBACK_APP_LABEL`
- `MURMUR_CONTROL_TIMEOUT_SECONDS`

## One-Time Host Wiring Checklist

1. Ensure Django can import FG package code (for example via `PYTHONPATH=<project_dir>`).
2. Add `<project_dir>/templates` to Django `TEMPLATES[...]["DIRS"]`.
3. Mount FG URLs in host URLconf.
4. Register sidebar and profile panel integration from FG integration classes.

## Post-Deploy Verification

After deploy and Django restart:

1. Open a profile page and confirm the Murmur profile panel renders.
2. Trigger password reset and verify temporary password is shown once.
3. Open Murmur manage page with non-super and superuser test accounts.
4. Validate FG actions via BG control/probe paths (see [fg-bg-integration-smoke.md](/home/michael/prj/mumble-fg/docs/fg-bg-integration-smoke.md)).
