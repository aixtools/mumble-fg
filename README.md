# mumble-fg

Foreground/UI Mumble integration paired with `mumble-bg`.

This repository now holds the Django/UI code that remains coupled to the host application side:

- profile and admin views for Mumble account management
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
- `fg/pilot/`
- `fg/management/commands/backfill_mumble_display_names.py`
- `templates/fg/manage.html`

This split is intentionally incomplete. The Django code here still expects broader host-application context, including:

- `accounts`
- `modules.corporation`
- `modules.esi_queue`
- pilot-side Mumble models exposed through `fg.pilot.models`
- pilot-side sync helpers exposed through `fg.pilot.control`

Those seams should be redesigned explicitly rather than left shared implicitly.

Shared fg/bg naming and boundary conventions are documented in [docs/conventions.md](/home/michael/prj/mumble-fg/docs/conventions.md).
