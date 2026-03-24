# Manual Deployment

This document covers manual installation of `mumble-fg` into a host application such as Cube.

## 1. Preconditions

- BG is already installed and reachable.
- The host application already has pilot data access.
- The host application has a working Django environment and staticfiles path.

FG manual deployment does not provision BG.

## 2. Install the package

From the host application checkout:

```bash
sudo systemctl stop cube-django
source venv/bin/activate
pip install --upgrade mumble_fg-<version>-py3-none-any.whl
```

If you want a quick package sanity check first:

```bash
pip install --dry-run mumble_fg-<version>-py3-none-any.whl
```

## 3. Configure the host environment

The host env SHALL include:

- `OPTIONAL_APPS=mumble_ui.apps.MumbleUiConfig`
- `MURMUR_CONTROL_URL=<bg-control-url>`
- `BG_PSK=<shared-control-secret>`

Common optional values:

- `BG_PUBLIC_KEY_PATH`
- `MURMUR_PANEL_HOST`
- `MURMUR_CONTROL_TIMEOUT_SECONDS`
- `MURMUR_MODEL_APP_LABEL`
- `MURMUR_MODEL_FALLBACK_APP_LABEL`

`PILOT_DBMS` remains a host concern. FG expects the host application to provide the pilot/account data it needs.

## 4. Apply Django changes

```bash
python manage.py check
python manage.py migrate mumble_fg
python manage.py collectstatic
sudo systemctl start cube-django
```

## 5. Verify the install

Verify these surfaces:

- `/mumble-ui/acl/`
- `/profile/`

Quick runtime checks:

```bash
curl -sS -m 3 "${MURMUR_CONTROL_URL}/v1/health" | python3 -m json.tool
python manage.py sync_mumble_acl --traceback
```

Expected outcome:

- FG can reach BG control.
- ACL sync succeeds.
- `/profile/` renders the Mumble panel for eligible pilots.

## 6. Shared values with BG

Keep these FG and BG values aligned:

- `MURMUR_CONTROL_URL`
- `BG_PSK`
- BG public key path, when FG encrypts password traffic with a BG public key file

The authoritative BG-side operator file is typically `~/.env/mumble-bg`.
