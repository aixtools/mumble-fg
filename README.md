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

## Pilot Eligibility Rules

FG owns the access-control decision tables and pushes them to BG via the control channel.
BG independently provisions Mumble accounts from these rules.

### Decision Tables (admin-managed in FG)

- **Allowed alliances** — an alliance is either in or out (no partial alliance access)
- **Blocked corps** — corps within an allowed alliance that are denied access
- **Blocked pilots** — individual pilots within an allowed alliance that are denied access
- **Allowed pilots** — individual pilot overrides that rescue access even when their corp is blocked

### Precedence (most specific wins)

1. **Pilot allow/block** overrides everything
2. **Corp block** applies if no pilot-level override exists
3. **Alliance allow** is the baseline

A blocked corp within an allowed alliance denies that corp's members — but an
explicit pilot-level allow for a specific member of that corp restores their access.

### Account-wide enforcement

Block checks apply across the **entire account**, not just the main character.
If the main **or any alt** matches a blocked corp or pilot ID, the whole account
is denied — unless a pilot-level allow overrides it.

Shared fg/bg naming and boundary conventions are documented in [docs/conventions.md](/home/michael/prj/mumble-fg/docs/conventions.md).
Dev deploy/bootstrap guidance is documented in [docs/bootstrap-dev-deploy.md](/home/michael/prj/mumble-fg/docs/bootstrap-dev-deploy.md).
FG/BG smoke-test checklist is documented in [docs/fg-bg-integration-smoke.md](/home/michael/prj/mumble-fg/docs/fg-bg-integration-smoke.md).
Backup and restore verification steps are documented in [docs/pilot-backup-restore-probe.md](/home/michael/prj/mumble-fg/docs/pilot-backup-restore-probe.md).
