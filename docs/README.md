# mumble-fg Documentation

Verified: `mumble-fg` `main` version `0.3.7.dev1` on `2026-04-24`.

This directory is the canonical documentation location for this repository.

Primary reference:

- [consolidated.md](./consolidated.md) — current intent, architecture, and operational notes.
- [conventions.md](./conventions.md) — shared FG/BG naming and boundary conventions.
- [deploy_manual.md](./deploy_manual.md) — manual installation into a host application.
- [deploy_workflow.md](./deploy_workflow.md) — current GitHub Actions deployment behavior.
- [fg-bg-contracts.md](./fg-bg-contracts.md) — explicit and implicit FG/BG integration contracts.
- [fg-bg-integration-smoke.md](./fg-bg-integration-smoke.md) — smoke checklist after deploy or integration changes.
- [profile-panel-wireframe.md](./profile-panel-wireframe.md) — markdown sketch of the current `/profile/` Mumble panel.
- [pilot-backup-restore-probe.md](./pilot-backup-restore-probe.md) — restoreability probe for host-side `PILOT_DBMS` backups.
- [design_spec.md](./design_spec.md) — implementation contract and intended steady-state design.
- [mumble-fg-bg-system-design.md](./mumble-fg-bg-system-design.md) — after-the-fact architecture summary.

Feature-specific planning docs retained in this directory:

- [group_mapping_v1_plan.md](./group_mapping_v1_plan.md)
- [group_mapping_v1_plan.json](./group_mapping_v1_plan.json)

Historical documents are archived in:

- [history/mumble-fg](../../repository/history/mumble-fg)

Keep the files above aligned with current code and workflows, and treat files under
`history/` as read-only history.
