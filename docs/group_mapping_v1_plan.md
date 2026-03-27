# FG/BG Murmur Group Mapping UI v1

## Summary

Build an FG operator UI for global `Cube group -> Murmur group` mapping with per-server Murmur inventory visibility. BG remains a per-server Murmur bridge and never merges server state. FG stores mapping intent, ignore state, and imported per-server inventory snapshots; it renders divergence and suppressed mappings when either a Cube group or a Murmur group is ignored. Naming should be explicit: use `is_mumble_admin` / `_is_mumble_admin`, not generic `is_admin`.

## Key Changes

- BG exposes a per-server Murmur inventory API keyed by `server_id`.
- BG buffers per-server ICE inventory with timestamps.
- Inventory freshness is configurable; default is 10 minutes.
- FG stores:
  - Cube-group ignore state
  - Murmur-group ignore state keyed globally by group name
  - Cube-group to Murmur-group mappings
  - imported per-server Murmur inventory snapshots
- Effective mappings are derived:
  - active only if neither side is ignored
  - otherwise preserved and rendered as suppressed
- FG adds global custom permissions:
  - `view_group_mapping`
  - `change_group_mapping`
  - `add_group_mapping`
  - `delete_group_mapping`
- `is_mumble_admin` on any eligible Murmur account grants full mapping access.
- `/profile/` and the new mapping UI share server-label behavior:
  - multiple servers: selector
  - one server: fixed text
  - zero servers: unavailable state

## UI v1

- New mapping screen with:
  - Server selector or fixed text
  - Cube-group selector
  - dual-list Murmur-group mapper
  - Refresh button
  - freshness indicator
  - suppressed mappings shown in grey with reason
  - read-only divergence panel for group/channel/ACL differences
- Operator actions:
  - Refresh selected server
  - Import from selected server
  - Export selected server to all servers
  - Overwrite all servers from selected server
  - Cleanup ignored mappings

## Assumptions

- Mapping intent is global across all BG-managed servers.
- BG never merges inventories; FG computes divergence.
- Murmur-group ignore is keyed globally by group name.
- Selected server is the editable/read source in v1.
- Channels and ACLs remain read-only context in v1.
