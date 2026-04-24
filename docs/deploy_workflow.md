# Workflow Deployment

Verified: `mumble-fg` `main` version `0.3.7.dev1` on `2026-04-24`.

This document describes the current GitHub Actions deployment behavior for `mumble-fg`.

## 1. Current Workflow Files

- `.github/workflows/deploy.yml`
- `.github/workflows/deploy-dev.yml`
- `.github/workflows/deploy-prod.yml`

The workflows are code-sync oriented. They do not replace the one-time host application setup.

## 2. Dev Workflow

The dev workflow is the cleaned path.

Required secrets:

- `TARGETHOST`
- `TARGETUSER`
- `BG_PSK`

`TARGETHOST` is a single hostname value.

`TARGETUSER` is JSON:

```json
{
  "user": "${WorkflowUser}",
  "key": "-----BEGIN OPENSSH PRIVATE KEY-----\\n...\\n-----END OPENSSH PRIVATE KEY-----",
  "home_dir": "~${WorkflowUser}",
  "project_dir": "~${WorkflowUser}/mumble-fg",
  "env_file": "~${WorkflowUser}/Cube/.env",
  "cube_project_dir": "~${WorkflowUser}/Cube",
  "cube_venv": "~${WorkflowUser}/Cube/venv",
  "port": "22",
  "service_units": ["cube-django"]
}
```

Dev workflow currently:

- resolves `TARGETHOST` and `TARGETUSER`
- preflights `/etc/mumble-fg/keys`
- rsyncs repository content to `project_dir`
- installs `mumble-fg` into the configured Cube venv from the synced checkout
- runs `python manage.py migrate mumble_fg --noinput`
- runs `python manage.py collectstatic --noinput`
- writes `BG_PSK` into the host env file when `env_file` is configured
- writes `FG_PKI_PASSPHRASE` into the host env file when configured
- optionally restarts systemd units listed in `service_units`
- verifies that expected FG files exist on the target

It does not create host settings.

## 3. Prod Workflow

Current prod default:

- `CUBE_PROD_CUBE`

Expected JSON shape:

```json
{
  "host": "cube-prod.example.net",
  "user": "${WorkflowUser}",
  "key": "-----BEGIN OPENSSH PRIVATE KEY-----\\n...\\n-----END OPENSSH PRIVATE KEY-----",
  "home_dir": "~${WorkflowUser}",
  "project_dir": "~${WorkflowUser}/mumble-fg",
  "service_units": ["cube-django"],
  "port": "22",
  "cube_venv": "~${WorkflowUser}/Cube/venv"
}
```

`deploy-prod.yml` currently:

- resolves the deploy target JSON secret
- preflights `/etc/mumble-fg/keys`
- rsyncs repository content to `project_dir`
- bootstraps an editable install into the configured Cube venv when `mumble-fg` is not already installed
- runs `python manage.py migrate mumble_fg --noinput`
- writes `FG_PKI_PASSPHRASE` into the configured FG env file when `env_file` is provided
- optionally restarts configured units

It does not:

- define host env values for you
- run `collectstatic`

`collectstatic` remains a host/operator step unless the workflow is extended.

## 4. Reusable Workflow

`.github/workflows/deploy.yml` is the reusable workflow form.

It accepts a single `deploy_target_name` input pointing at a JSON secret with:

- `host`
- `user`
- `key`
- optional path and service-unit fields

It performs the same core actions as the current prod workflow:

- resolve JSON deploy target
- preflight `/etc/mumble-fg/keys`
- rsync repo checkout
- bootstrap editable install when needed
- run `migrate mumble_fg`
- sync `FG_PKI_PASSPHRASE` when configured
- optionally restart service units

## 5. Host Expectations

The target host is expected to already provide:

- the Django application checkout
- a functioning virtualenv
- the host env file
- sudo rights for restarting listed services when `service_units` is used
- host-side pilot data access

For Cube-like hosts, `mumble_ui.apps.MumbleUiConfig` and FG extension discovery must already be supported by the host application.
