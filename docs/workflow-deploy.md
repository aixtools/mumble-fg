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
- resolves a deploy target from `TARGETHOST` and `TARGETUSER` secrets
- rsyncs this repository to `project_dir`
- optionally syncs `BG_PSK` into a host FG env file
- optionally restarts systemd units listed in `service_units`
- verifies expected FG files exist on the host after sync

It does not:

- install Python packages
- create Django settings
- write full FG runtime secrets or `PILOT_DBMS`
- configure the host-side `PILOT_DBMS`
- configure BG runtime or BG deploy state

## Deploy Target Secrets

The workflow expects:
Use single-value secret notation in documentation as `NAME = value`.

- `TARGETHOST = <hostname>`
- `TARGETUSER = <json>`

`TARGETHOST` example:

```text
cube-dev.example.net
```

`TARGETUSER` example:

```json
{
  "user": "deploy",
  "key": "-----BEGIN OPENSSH PRIVATE KEY-----\\n...\\n-----END OPENSSH PRIVATE KEY-----",
  "home_dir": "~deploy",
  "project_dir": "~deploy/mumble-fg",
  "env_file": "~deploy/Cube/.env",
  "service_units": ["cube-django"]
}
```

Required fields:

- `user`
- `key`

Optional fields:

- `home_dir`
- `project_dir`
- `env_file`
- `service_units`

Defaults:

- `home_dir`: `/home/<user>`
- `project_dir`: `<home_dir>/mumble-fg`
- `env_file`: blank, which skips host env updates
- `service_units`: empty list, which skips restarts

## Host Runtime Settings

The workflow syncs code only. The host Django environment still needs:

- `MURMUR_CONTROL_URL` or `MURMUR_CONTROL_BASE_URL`
- `BG_PSK`
- `MURMUR_PANEL_HOST`
- `MURMUR_HOST_ADAPTER` when custom host adapters are needed
- `MURMUR_MODEL_APP_LABEL` when a legacy host Murmur model app is still present

Optional:

- `MURMUR_MODEL_FALLBACK_APP_LABEL`
- `MURMUR_CONTROL_TIMEOUT_SECONDS`

`PILOT_DBMS` is a host-side concern. This workflow does not define or migrate it;
it assumes the host app already has access to the pilot data it needs.

## Accessing `BG_PSK` From BG During FG Deploy

GitHub Actions in `mumble-fg` cannot directly read repository secrets that exist
only in `mumble-bg`.

Current supported path:

- define `BG_PSK` as an org or environment secret visible to both repos, then FG deploy reads `${{ secrets.BG_PSK }}`

If `env_file` is unset, FG deploy remains code-sync only and skips env syncing.

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
