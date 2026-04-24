# mumble-fg Operations

Verified: `mumble-fg` `main` version `0.3.7.dev1` on `2026-04-24`.

## Scope

This document covers:

- manual installation into a host application
- current GitHub Actions deployment behavior
- post-deploy smoke checks
- a restoreability probe for host-side `PILOT_DBMS` backups

## Manual Deployment

### Preconditions

- BG is already installed and reachable
- the host application already has pilot data access
- the host application has a working Django environment and staticfiles path

FG deployment does not provision BG.

### Install

From the host application checkout:

```bash
sudo systemctl stop cube-django
source venv/bin/activate
pip install --upgrade mumble_fg-<version>-py3-none-any.whl
```

Optional sanity check:

```bash
pip install --dry-run mumble_fg-<version>-py3-none-any.whl
```

### Required host environment

- `OPTIONAL_APPS=mumble_ui.apps.MumbleUiConfig`
- `MURMUR_CONTROL_URL=<bg-control-url>`
- `BG_PSK=<shared-control-secret>`

Common optional values:

- `BG_PUBLIC_KEY_PATH`
- `MURMUR_PANEL_HOST`
- `MURMUR_CONTROL_TIMEOUT_SECONDS`
- `MURMUR_MODEL_APP_LABEL`
- `MURMUR_MODEL_FALLBACK_APP_LABEL`

`PILOT_DBMS` remains a host concern.

### Apply Django changes

```bash
python manage.py check
python manage.py migrate mumble_fg
python manage.py collectstatic
sudo systemctl start cube-django
```

## Workflow Deployment

Current workflow files:

- `.github/workflows/deploy.yml`
- `.github/workflows/deploy-dev.yml`
- `.github/workflows/deploy-prod.yml`

The workflows are code-sync oriented. They do not replace one-time host setup.

### Dev workflow

Required secrets:

- `TARGETHOST`
- `TARGETUSER`
- `BG_PSK`

`TARGETUSER` is JSON and includes user, key, path, and service-unit settings.

The dev workflow currently:

- resolves `TARGETHOST` and `TARGETUSER`
- preflights `/etc/mumble-fg/keys`
- rsyncs repository content to `project_dir`
- installs `mumble-fg` into the configured Cube venv from the synced checkout
- runs `python manage.py migrate mumble_fg --noinput`
- runs `python manage.py collectstatic --noinput`
- writes `BG_PSK` into the host env file when configured
- writes `FG_PKI_PASSPHRASE` into the host env file when configured
- optionally restarts configured systemd units
- verifies expected FG files exist on the target

### Prod workflow

Current prod default secret:

- `CUBE_PROD_CUBE`

`deploy-prod.yml` currently:

- resolves the deploy target JSON secret
- preflights `/etc/mumble-fg/keys`
- rsyncs repository content to `project_dir`
- bootstraps an editable install when needed
- runs `python manage.py migrate mumble_fg --noinput`
- writes `FG_PKI_PASSPHRASE` into the configured FG env file when `env_file` is provided
- optionally restarts configured units

It does not run `collectstatic`; that remains a host/operator step unless the workflow is extended.

### Reusable workflow

`.github/workflows/deploy.yml` is the reusable workflow form.

It currently performs these core actions:

- resolve JSON deploy target
- preflight `/etc/mumble-fg/keys`
- rsync repo checkout
- bootstrap editable install when needed
- run `migrate mumble_fg`
- optionally restart service units

Current limitation:

- the reusable workflow does not populate `DEPLOY_CUBE_PROJECT_DIR`
- because of that, its `FG_PKI_PASSPHRASE` sync step currently skips unless the workflow is corrected
- keypair ensure is also skipped for the same reason

### Host expectations

The target host is expected to already provide:

- the Django application checkout
- a functioning virtualenv
- the host env file
- sudo rights for restarting listed services when `service_units` is used
- host-side pilot data access

For Cube-like hosts, `mumble_ui.apps.MumbleUiConfig` and FG extension discovery must already be supported by the host application.

## Shared Values With BG

Keep these FG and BG values aligned:

- `MURMUR_CONTROL_URL`
- `BG_PSK`
- BG public key path, when FG encrypts password traffic with a BG public key file

The authoritative BG-side operator file is typically `~/.env/mumble-bg`.

## Smoke Checklist

Use this after deploying or changing either repo.

It validates:

- FG -> BG control transport
- BG probe visibility used by FG verification flows
- ACL + pilot-snapshot sync behavior
- profile panel rendering in FG
- `Mumble Controls` rendering in FG

### Prerequisites

- FG host app is up
- BG control API is reachable at `MURMUR_CONTROL_URL`
- FG and BG share the same control secret
- BG has at least one active server row

### BG API reachability

From the FG host:

```bash
curl -sS "${MURMUR_CONTROL_URL%/}/v1/health"
```

Expected:

- BG reports healthy status
- control auth mode is sensible for the environment

### ACL + pilot snapshot sync

From FG:

1. open the ACL page
2. trigger `Sync BG`

Expected FG sequence:

1. ACL rules sent to `/v1/access-rules/sync`
2. pilot snapshot sent to `/v1/pilot-snapshot/sync`
3. reconcile optionally requested through `/v1/provision`

### Profile password flow

From FG UI:

1. open a profile page
2. trigger `Reset Password` or `Set Password`
3. confirm FG surfaces BG success/failure correctly

Then verify with BG probe:

```bash
curl -sS "${MURMUR_CONTROL_URL%/}/v1/pilots/<pkid>"
```

### Mumble Controls flow

From FG UI:

1. open `Mumble Controls`
2. confirm the expected tabs render for the current account permissions
3. exercise admin-only actions with a privileged account
4. if group mapping is enabled, confirm `Groups` can load BG-backed server inventory
5. if temp links are enabled, confirm `Links` renders and BG-unavailable states surface correctly

### Failure-mode check

Temporarily misconfigure the control secret in FG and retry a mutating action.

Expected:

- FG shows a BG/auth failure instead of a false success
- BG rejects the request
- no persisted mutation occurs

## `PILOT_DBMS` Restoreability Probe

Use this to answer one narrow question:

- can a captured pilot-data backup be restored cleanly into a disposable probe DB?

### Preconditions

- you have a recent backup artifact
- you have credentials that can create and drop a disposable probe DB
- you are not pointing at production data

### Local non-destructive restore probe

Replace the placeholders for your environment:

```bash
export PGPASSWORD='<db_password>'
BACKUP_FILE='/path/to/pilot_dump.sql.gz'
PROBE_DB="pilot_dbms_restore_probe_$(date +%Y%m%d_%H%M%S)"

createdb -h 127.0.0.1 -U <db_user> "$PROBE_DB"

gzip -dc "$BACKUP_FILE" \
  | psql -h 127.0.0.1 -U <db_user> -d "$PROBE_DB"

gzip -dc "$BACKUP_FILE" > /tmp/pilot_dbms_restore_probe.sql
wc -l /tmp/pilot_dbms_restore_probe.sql
psql -h 127.0.0.1 -U <db_user> -d "$PROBE_DB" -c '\dt'

dropdb -h 127.0.0.1 -U <db_user> "$PROBE_DB"
rm -f /tmp/pilot_dbms_restore_probe.sql
```

Check:

- backup stream decompresses cleanly
- `psql` import completes without schema/object errors
- expected tables exist in the probe DB
- the probe DB can be dropped cleanly afterward
