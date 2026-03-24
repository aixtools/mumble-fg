# Workflow Deployment

This document describes the current GitHub Actions deployment behavior for `mumble-fg`.

## 1. Current Workflow Files

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
  "service_units": ["cube-django"]
}
```

Dev workflow currently:

- resolves `TARGETHOST` and `TARGETUSER`
- rsyncs repository content to `project_dir`
- writes `BG_PSK` into the host env file when `env_file` is configured
- optionally restarts systemd units listed in `service_units`
- verifies that expected FG files exist on the target

It does not:

- install FG into the target venv
- migrate Django
- collect static files
- create host settings

## 3. Prod Workflow

The prod workflow is still on the older secret model.

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
- rsyncs repository content to `project_dir`
- bootstraps an editable install into the configured Cube venv when `mumble-fg` is not already installed
- optionally restarts configured units

It does not:

- define host env values for you
- migrate `mumble_fg`
- run `collectstatic`

Those remain host/operator steps unless the workflow is extended.

## 4. Host Expectations

The target host is expected to already provide:

- the Django application checkout
- a functioning virtualenv
- the host env file
- sudo rights for restarting listed services when `service_units` is used
- host-side pilot data access

For Cube-like hosts, `mumble_ui.apps.MumbleUiConfig` and FG extension discovery must already be supported by the host application.
