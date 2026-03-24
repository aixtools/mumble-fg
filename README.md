# mumble-fg

`mumble-fg` is the host/UI/admin half of the FG/BG split.

It owns:

- the ACL admin surface
- the pilot `/profile/` Mumble panel
- host-side pilot data reads
- Cube/host integration hooks
- control calls to `mumble-bg`

It does not own runtime state, Murmur reconciliation, or ICE/authd behavior.
Those live in `mumble-bg`.

## Canonical Documents

- [docs/design_spec.md](./docs/design_spec.md)
- [docs/deploy_manual.md](./docs/deploy_manual.md)
- [docs/deploy_workflow.md](./docs/deploy_workflow.md)

Treat the three documents above as authoritative for current FG behavior.

## Runtime Summary

- FG reads host-side pilot data.
- FG sends ACL rules and pilot snapshot data to BG over the control API.
- FG does not read BG tables directly.
- FG is packaged as a Django optional app, typically enabled as `mumble_ui.apps.MumbleUiConfig`.
- FG requires BG control connectivity for live sync, password actions, and runtime server data.

## Commit Message Pre-check

Conventional Commits are enforced for new commits.

```bash
make precheck COMMIT_MSG="feat(fg): add acl hash transport"
git config core.hooksPath .githooks
```
