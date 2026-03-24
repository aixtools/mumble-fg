# Deploy Workflow

This document describes the current `mumble-fg` source-checkout deployment
workflow for the dev host.

It covers:

- the GitHub Actions deploy workflow
- one-time host wiring that the workflow assumes already exists
- FG-specific runtime settings that must be present in the host Django env

## What The Workflow Does

The current `.github/workflows/deploy-dev.yml` workflow:

- triggers on pushes to `main` and `fg-mvp`
- also supports manual `workflow_dispatch`
- resolves a deploy target from one JSON secret identified by a host-user label, default `CUBE_DEV_CUBE`
- rsyncs this repository to `project_dir`
- optionally syncs `FGBG_PSK` into a host FG env file
- optionally restarts systemd units listed in `service_units`
- verifies expected FG files exist on the host after sync

It does not:

- install Python packages
- create Django settings
- write full FG runtime secrets or `PILOT_DBMS`
- configure the host-side `PILOT_DBMS`
- configure BG runtime or BG deploy state

## Deploy Target Secret

The workflow expects a JSON secret shaped like:

```json
{
  "host": "dev-host.example.net",
  "user": "deploy",
  "key": "-----BEGIN OPENSSH PRIVATE KEY-----\\n...\\n-----END OPENSSH PRIVATE KEY-----",
  "home_dir": "/home/deploy",
  "project_dir": "/home/deploy/mumble-fg",
  "env_file": "/home/deploy/.env/cube",
  "bg_env_file": "/home/deploy/.env/mumble-bg",
  "service_units": ["web.service", "worker.service", "scheduler.service"]
}
```

Required fields:

- `host`
- `user`
- `key`

Optional fields:

- `home_dir`
- `project_dir`
- `env_file`
- `bg_env_file`
- `service_units`

Defaults:

- `home_dir`: `/home/<user>`
- `project_dir`: `<home_dir>/mumble-fg`
- `env_file`: blank, which skips host env updates
- `bg_env_file`: blank, which disables BG-host secret import
- `service_units`: empty list, which skips restarts

## Host Runtime Settings

The workflow syncs code only. The host Django environment still needs:

- `MURMUR_CONTROL_URL` or `MURMUR_CONTROL_BASE_URL`
- `FGBG_PSK`
- `MURMUR_PANEL_HOST`
- `MURMUR_HOST_ADAPTER` when custom host adapters are needed
- `MURMUR_MODEL_APP_LABEL` when a legacy host Murmur model app is still present

Optional:

- `MURMUR_CONTROL_PSK` or `MURMUR_CONTROL_SHARED_SECRET` as temporary legacy aliases
- `MURMUR_MODEL_FALLBACK_APP_LABEL`
- `MURMUR_CONTROL_TIMEOUT_SECONDS`

`PILOT_DBMS` is a host-side concern. This workflow does not define or migrate it;
it assumes the host app already has access to the pilot data it needs.

## Environment Settings Reference (Historical and Current)

### Current (preferred)

- `FGBG_PSK`
  - control-channel shared secret FG sends to BG.
- `MURMUR_CONTROL_URL` (or `MURMUR_CONTROL_BASE_URL`)
  - BG control API base URL FG calls.
- `MURMUR_PANEL_HOST`
  - profile panel host/address display source.
- `MURMUR_CONTROL_TIMEOUT_SECONDS`
  - FG control request timeout.
- `MURMUR_HOST_ADAPTER`
  - optional host adapter override.
- `MURMUR_MODEL_APP_LABEL`
  - optional explicit host model app binding when legacy host models exist.
- `MURMUR_MODEL_FALLBACK_APP_LABEL`
  - optional fallback model label for transitional deployments.

### Historical (legacy) and replacement

- `MURMUR_CONTROL_PSK`
  - replaced by: `FGBG_PSK`.
  - status: legacy alias accepted for compatibility.
- `MURMUR_CONTROL_SHARED_SECRET`
  - replaced by: `FGBG_PSK`.
  - status: legacy alias accepted for compatibility.

Notes:

- Keep new deployments on `FGBG_PSK` and avoid introducing new usage of legacy aliases.
- The deploy workflow can import legacy PSK values from BG env and normalize to `FGBG_PSK` in FG env.

## Accessing `FGBG_PSK` From BG During FG Deploy

GitHub Actions in `mumble-fg` cannot directly read repository secrets that exist
only in `mumble-bg`.

Current supported paths are:

- preferred shared-secret path: define `FGBG_PSK` as an org or environment secret visible to both repos, then FG deploy reads `${{ secrets.FGBG_PSK }}`
- host-import path: set both `env_file` and `bg_env_file` in the FG deploy target JSON, ensure the FG deploy user can read `bg_env_file`, and the workflow copies `FGBG_PSK` from the BG host env file into the FG host env file

The host-import path works like this:

1. FG deploy sshes to the target host
2. it reads `FGBG_PSK` from `bg_env_file` on that host
3. it writes or replaces `FGBG_PSK=...` in `env_file`
4. the restarted FG host services then see the same secret BG is already using

Compatibility note:

- if BG still has only legacy `MURMUR_CONTROL_PSK`, the FG workflow will import that and write it back as `FGBG_PSK`
- if `env_file` is unset, FG deploy remains code-sync only and skips all secret syncing

## One-Time Host Wiring

Before relying on the workflow, ensure the host already:

1. can import FG package code
2. can load FG templates
3. mounts FG URLs and extension hooks
4. exposes the expected control URL/PSK settings
5. restarts the desired Django/Celery units when `service_units` is configured

For upstream Cube-like hosts:

- `mumble_ui.apps.MumbleUiConfig` should be enabled
- `fg.cube_extension` should be discoverable
- profile panel and ACL routes should be mounted in the host app

## Post-Deploy Verification

After deploy and host restart:

1. open a profile page and confirm the Murmur panel renders
2. open the ACL page and confirm FG can still reach BG
3. trigger a password-reset flow and verify BG-backed success/failure handling
4. run the FG/BG smoke checklist in `docs/fg-bg-integration-smoke.md`

## Branch Boundary Reminder

On this branch:

- FG reads `PILOT_DBMS`
- FG sends pilot snapshot data to BG
- BG never reads `PILOT_DBMS` directly

That is why FG deploy is mostly code-sync and host wiring, not DB or BG-runtime
bootstrap.
