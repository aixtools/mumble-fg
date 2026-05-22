# Cube-Admin Moderator Endpoints (FG/BG companion spec)

**Status: NOT IMPLEMENTED**

Companion to [Cube spec 34 — Cube Admin User Editor](../../Cube/tasks/34-cube-admin-user-editor.md). That spec adds a Cube-side "Edit User" page that surfaces every per-user `MumbleUser` field and exposes two action buttons — *Force password reset* and *Clear certhash* — on a target user's behalf. Today, both actions only exist as **self-service** flows (`mumble:profile_reset_password`, `mumble:profile_set_password`); there is no FG/BG endpoint for a moderator to take the action against another user's `MumbleUser` row.

This spec adds those moderator endpoints and the BG control surface they need.

## What exists today (keep as-is)

- **FG self-service password flows**: `mumble:profile_reset_password`, `mumble:profile_set_password` referenced from the pilot panel provider (`fg/panels/providers.py:36-58, 197-198`). These act on `request.user` only.
- **FG control client**: `fg/control.py:563-587` already has `reset_murmur_password()` and `reset_password_for_user()` which marshal a request to BG's `password_reset` endpoint. The `_for_user` variant is the right entrypoint for the moderator flow — it just needs an HTTP view in front of it that an external (Cube) caller can hit.
- **BG password reset endpoint**: `bg/control.py:922 password_reset` accepts a payload, regenerates `pwhash`/`pw_salt`/`kdf_iterations`, persists to `MumbleUser`, returns the new password to the FG caller. Audited via `BgAudit`.
- **BG `MumbleUser` model**: `bg/state/models.py:102-190`. `certhash` field at line 131 is plain (not encrypted) — already cleared by Murmur reconnect logic on cert change.
- **`manage_mumble_admin` permission**: declared on `MumbleUser.Meta.permissions` (`bg/state/models.py:177-179`). Reuse — do not invent a new permission for the privilege-escalation path.

## Tasks

### 1. FG view: `mumble:admin_reset_password_for_user`

- [ ] Add `admin_reset_password_for_user(request, user_id, server_id)` view in `fg/views.py` (or wherever the FG admin views live — match existing convention).
- [ ] Permission gate: requires the caller to either (a) be in the Django `cube-admin` group, or (b) hold `mumble_fg.manage_mumble_admin` permission. Staff/superuser bypass as usual.
- [ ] Resolves `MumbleUser` for `(user_id, server_id)` via `fg.models.resolve_murmur_models()`. 404 if not found.
- [ ] Calls existing `fg.control.reset_password_for_user(user_id, server_id)` (`fg/control.py:587`).
- [ ] Returns JSON `{password: "...", server_id, username}` so the Cube caller can display it once. Caller is responsible for not persisting.
- [ ] URL pattern in `fg/urls.py` (or `mumble_ui/urls.py`): `path('admin/users/<int:user_id>/servers/<int:server_id>/password-reset/', views.admin_reset_password_for_user, name='admin_reset_password_for_user')`.
- **Priority**: HIGH

### 2. FG view: `mumble:admin_clear_certhash`

- [ ] Add `admin_clear_certhash(request, user_id, server_id)` view alongside the password-reset view.
- [ ] Same permission gate as Task 1.
- [ ] Calls a new FG control client method `clear_certhash_for_user(user_id, server_id)` that POSTs to a new BG control endpoint (Task 3).
- [ ] Returns JSON `{ok: true}`.
- [ ] URL pattern: `path('admin/users/<int:user_id>/servers/<int:server_id>/clear-certhash/', views.admin_clear_certhash, name='admin_clear_certhash')`.
- **Priority**: HIGH

### 3. FG control client: `clear_certhash_for_user`

- [ ] Add `clear_certhash_for_user(user_id, server_id)` to the FG control client class in `fg/control.py` near `reset_password_for_user()` (around line 587). Same auth/error-handling pattern.
- [ ] Hits new BG endpoint `POST /control/users/{user_id}/servers/{server_id}/clear-certhash/`. Raises `BgSyncError` on failure.
- **Priority**: HIGH

### 4. BG control endpoint: clear certhash

- [ ] Add view in `bg/control.py` near `password_reset` (`bg/control.py:922`). Mirror its admin-key auth, payload validation, and audit pattern.
- [ ] Resolves `MumbleUser` for `(user_id, server_id)`. 404 if not found.
- [ ] Sets `mumble_user.certhash = ''` and saves with `update_fields=['certhash', 'updated_at']`.
- [ ] Records a `BgAudit` entry with a new action constant `BG_AUDIT_ACTION_PILOT_CERTHASH_CLEAR = 'pilot_certhash_clear'` (add alongside the existing constants at `bg/state/models.py:551`).
- [ ] Returns `{ok: true, mumble_userid: int, username: str}`.
- [ ] No Murmur runtime call needed — Murmur reads `certhash` lazily on next reconnect.
- **Priority**: HIGH

### 5. Documentation

- [ ] Add a "Moderator endpoints" section to `docs/design_spec.md` listing the two FG views, the BG endpoint, the permission contract (`cube-admin` group cross-recognized + existing `manage_mumble_admin` permission), and the audit trail.
- [ ] Add a worked example to `docs/deploy_workflow.md` of granting the `cube-admin` group to a Cube moderator and verifying the two endpoints work end-to-end.
- **Priority**: MEDIUM

## Out of scope (explicitly)

- Surfacing these endpoints in the FG admin UI itself. The only consumer is the Cube edit-user page (Cube spec 34, Task 6). FG admin already has `MumbleUserAdmin` if a deploy needs to reach the same fields directly.
- Bulk versions of either endpoint. Per-user only — moderators act one user at a time.
- Editing `pwhash`/`hashfn`/`pw_salt`/`kdf_iterations` directly. Password reset is the only supported mutation path; raw hash editing stays out.
- Surfacing `MumbleSession` rows. Read-only audit / runtime data; not a moderator-fix surface.

## Permission model note

The `cube-admin` group is created and managed in the Cube repo (Cube spec 34, Task 1). FG must accept membership in that group as one of two acceptable credentials for these endpoints, **alongside** the existing `mumble_fg.manage_mumble_admin` permission — not as a replacement. Rationale: a Cube moderator who is not a Mumble admin can fix everyday user linkage; a Mumble admin who is not a Cube moderator can still do everything via FG admin. Either credential is sufficient.
