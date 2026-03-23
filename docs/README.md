# mumble-fg Documentation

This directory is the canonical documentation location for this repository.

Primary reference:

- [consolidated.md](./consolidated.md) — current intent, architecture, and operational notes.
- [conventions.md](./conventions.md) — shared FG/BG naming and boundary conventions.
- [workflow-deploy.md](./workflow-deploy.md) — current FG deploy workflow and host wiring assumptions.
- [fg-bg-integration-smoke.md](./fg-bg-integration-smoke.md) — FG/BG smoke checklist after deploy or integration changes.
- [pilot-backup-restore-probe.md](./pilot-backup-restore-probe.md) — generic restoreability probe for host-side `PILOT_DBMS` backups.
- [fg-bg-contracts.md](./fg-bg-contracts.md) — explicit and implicit integration contracts.
- [profile-panel-wireframe.md](./profile-panel-wireframe.md) — best-effort markdown sketch of the `/profile/` Mumble panel.

Historical documents are archived in:

- [history/mumble-fg](../../repository/history/mumble-fg)

Keep `consolidated.md` current, use the topic docs above for stable detail, and
treat all files under `history/` as read-only history.
