# Bootstrap Dev Deploy (FG)

This document provides a dev-host setup path for `mumble-fg` that mirrors the
`mumble-bg` bootstrap style.

`mumble-fg` is UI/integration code, not a standalone daemon. Deployment means:

- placing this repo on the host
- wiring the host Django app to import `fg`
- wiring templates and sidebar/profile panel extension points
- configuring FG -> BG control transport settings

## Assumptions

- host Django app checkout exists at `/home/cube/Cube`
- FG checkout path is `/home/cube/mumble-fg`
- BG control API is reachable from the host app (same machine or private network)

## One-Time Host Setup

1. Clone or update `mumble-fg`:

```bash
sudo -u cube gh repo clone aixtools/mumble-fg /home/cube/mumble-fg
```

If it already exists:

```bash
sudo -u cube git -C /home/cube/mumble-fg fetch origin
sudo -u cube git -C /home/cube/mumble-fg switch fg-mvp
sudo -u cube git -C /home/cube/mumble-fg pull --ff-only origin fg-mvp
```

2. Ensure the host runtime can import `fg`.

Common options:

- add `/home/cube/mumble-fg` to `PYTHONPATH` in the Django service environment
- or vendor/sync the `fg/` package into the host app source tree

3. Ensure Django can render FG templates.

Add this template path to host settings `TEMPLATES[...]["DIRS"]`:

- `/home/cube/mumble-fg/templates`

4. Wire host integration points:

- include FG URLs under desired route prefix
- load sidebar entries from `fg.sidebar.SIDEBAR_ITEMS`
- load profile panels through `fg.integration.CubeMurmurIntegration` (or generic facade)

## Required FG Runtime Settings

Set these in the host environment used by Django:

- `MURMUR_CONTROL_URL` (or `MURMUR_CONTROL_BASE_URL`)
- `MURMUR_CONTROL_PSK` (or `MURMUR_CONTROL_SHARED_SECRET`)
- `MURMUR_PANEL_HOST` (for provider selection; for Cube use `cube`)
- `MURMUR_MODEL_APP_LABEL` (Django app label providing `MumbleServer/MumbleUser/MumbleSession`; typically `mumble`)

Optional:

- `MURMUR_MODEL_FALLBACK_APP_LABEL`
- `MURMUR_CONTROL_TIMEOUT_SECONDS`

## Post-Deploy Verification

After deploying FG updates and restarting Django:

1. Open profile page and confirm Murmur panel renders.
2. Trigger a password reset and confirm a temporary password appears once.
3. Open Murmur manage page as:
   - regular staff/alliance-leader role (read/admin actions per permission)
   - superuser (contract metadata sync panel visible)
4. Confirm FG action results using BG probe/control endpoints (see
   [fg-bg-integration-smoke.md](/home/michael/prj/mumble-fg/docs/fg-bg-integration-smoke.md)).
