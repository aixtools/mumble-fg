# mumble-fg

Foreground/UI Murmur integration paired with `mumble-bg`.

This repository now holds the Django/UI code that remains coupled to the host application side:

- profile and admin views for Murmur account management
- pilot-side sidebar registration
- helpers for display-name and group refresh
- the display-name backfill management command
- the legacy Django test module for those flows

The runtime service, ICE authenticator, Murmur pulse loop, and standalone deployment logic now live in `mumble-bg`.

Current extracted paths:

- `fg/views.py`
- `fg/urls.py`
- `fg/sidebar.py`
- `fg/tasks.py`
- `fg/tests.py`
- `fg/passwords.py`
- `fg/models.py`
- `fg/host.py`
- `fg/control.py`
- `fg/integration.py`
- `fg/cube_extension.py`
- `fg/panels/`
- `fg/management/commands/backfill_mumble_display_names.py`
- `templates/fg/manage.html`
- `templates/fg/panels/profile_panel.html`

This split is intentionally incomplete. The Django code here still expects broader host-application context, including:

- `accounts`
- `modules.corporation`
- `modules.esi_queue`
- Murmur contract models resolved through `fg.models`
- host account/permission adapters resolved through `fg.host`
- fg/bg control transport through `fg.control`
- Cube extension hooks resolved through `fg.cube_extension`

At runtime, FG now treats host Murmur ORM models as optional. When `MURMUR_MODEL_APP_LABEL`
does not resolve, profile panels and Murmur management views fall back to BG control/probe APIs.

Those seams should be redesigned explicitly rather than left shared implicitly.

Shared fg/bg naming and boundary conventions are documented in [docs/conventions.md](/home/michael/prj/mumble-fg/docs/conventions.md).
Dev deploy/bootstrap guidance is documented in [docs/bootstrap-dev-deploy.md](/home/michael/prj/mumble-fg/docs/bootstrap-dev-deploy.md).
FG/BG smoke-test checklist is documented in [docs/fg-bg-integration-smoke.md](/home/michael/prj/mumble-fg/docs/fg-bg-integration-smoke.md).
Backup and restore verification steps are documented in [docs/pilot-backup-restore-probe.md](/home/michael/prj/mumble-fg/docs/pilot-backup-restore-probe.md).
