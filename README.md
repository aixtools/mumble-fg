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
- Murmur contract models resolved through `fg.models`
- host account/permission adapters resolved through `fg.host`
- fg/bg control transport through `fg.control`
- Cube extension hooks resolved through `fg.cube_extension`

At runtime, FG now treats host Murmur ORM models as optional. When `MURMUR_MODEL_APP_LABEL`
does not resolve, profile panels and Murmur management views fall back to BG control/probe APIs.

Those seams should be redesigned explicitly rather than left shared implicitly.

## Pilot Eligibility Rules

FG owns the access-control list (ACL) and is the only side that reads host-side
`PILOT_DBMS` data. FG pushes both ACL rules and a full account-oriented pilot snapshot to BG
via the control channel. BG provisions Mumble accounts from that cached snapshot
plus the synced ACL rules.

### Decision Tables (admin-managed in FG)

- **Allowed alliances** — an alliance is either in or out (no partial alliance access). Alliances not listed are **implicitly denied**.
- **Denied corps** — corps within an allowed alliance that are denied access.
- **Denied pilots** — individual pilots denied access regardless of alliance/corp status.
- **Allowed pilots** — individual pilot overrides that rescue access even when their corp or alliance is denied.

### Precedence (most specific wins)

1. **Pilot allow/deny** overrides everything
2. **Corp deny** applies if no pilot-level override exists
3. **Alliance allow** is the baseline (unlisted alliances are implicitly denied)

A denied corp within an allowed alliance blocks that corp's members — but an
explicit pilot-level allow for a specific member of that corp restores their access.

### Account-wide enforcement

Deny checks apply across the **entire account**, not just the main character.
If the main **or any alt** matches a deny rule (alliance, corp, or pilot), the
whole account is denied — unless a pilot-level allow overrides it.

### Eligible / Blocked pilot lists

The ACL panel provides two on-demand pilot lists:

- **Eligible Pilots** — one row per eligible account, showing the main
  character first and any explicitly allowed non-main alts underneath. Alliance
  or corp allowance by itself does not list every alt on the account.
- **Blocked Pilots** — only characters **explicitly** hit by a deny rule
  (denied alliance, denied corp, or individually denied pilot). Characters in
  unlisted alliances are implicitly denied but do **not** appear on this list —
  the implicitly-denied set is effectively the entire EVE universe minus the
  eligible set.

ACL changes now trigger an immediate full-table FG→BG sync, and the ACL page
also exposes a manual `Sync BG` action for users with `change_accessrule`.
For host-side scheduling, `manage.py sync_mumble_acl` runs the same full-table
sync and appends a `sync` audit entry. The sync sequence is:

1. send ACL rules to `/v1/access-rules/sync`
2. send pilot snapshot to `/v1/pilot-snapshot/sync`
3. optionally request reconcile via `/v1/provision`

Shared fg/bg naming and boundary conventions are documented in [docs/conventions.md](./docs/conventions.md).
Dev deploy/bootstrap guidance is documented in [docs/workflow-deploy.md](./docs/workflow-deploy.md).
FG/BG smoke-test checklist is documented in [docs/fg-bg-integration-smoke.md](./docs/fg-bg-integration-smoke.md).
Backup and restore verification steps are documented in [docs/pilot-backup-restore-probe.md](./docs/pilot-backup-restore-probe.md).

## Commit Message Pre-check

Conventional Commits are enforced for new commits.

Validate a message explicitly:

```bash
make precheck COMMIT_MSG="feat(fg): add acl hash transport"
```

Enable the git hook once per clone:

```bash
git config core.hooksPath .githooks
```
