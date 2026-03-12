# Implementation Matrix

## Must-Have Issues (MVP)

1. `FG-101` [fg-models] Remove FG direct action coupling from `fg/pilot` control shim. Owner: `fg-models`. Files: `fg/pilot/control.py`, `fg/views.py`, `fg/tests.py`. Done when `fg.views` no longer performs registration/de-registration/admin-membership control calls directly against local contract assumptions and all outbound control calls are through bg contract endpoints; tests asserting those local calls are migrated or removed.

2. `BG-201` [bg-models] Expose control endpoints for registration sync, unregister, admin-membership sync, and password operations. Owner: `bg-models`. Files: `/home/michael/prj/mumble-bg` control router, handlers, serializers. Done when endpoints exist, validate permissions, and all FG action paths resolve to these endpoints with documented request/response contracts.

3. `BG-202` [bg-models] Add read-only probe APIs used for FG verification (`pw_lastchanged`, registration status, admin membership state). Owner: `bg-models`. Files: `/home/michael/prj/mumble-bg` probe handlers/services. Done when FG can confirm outcomes via read path only and never reads mutable bg internals from host DB tables.

4. `BG-203` [bg-models] Implement control key bootstrap + rotation lifecycle and PSK reset command. Owner: `bg-models`. Files: `/home/michael/prj/mumble-bg` ICE/auth/control config, migrations/models. Done when first connect can use env PSK and follow-up sessions use DB key if present; reset command sets DB key to `NULL`.

5. `FG-102` [fg-models] Build admin panels for superuser-only `kdf_interactions` and Murmur contract IDs (`alliance_id`, `corporation_id`, `evepilot_id`) with control-driven persistence and probe reads. Owner: `fg-models`. Files: `fg/admin.py`, `fg/views.py`, `fg/urls.py`, `templates/fg/manage.html`, `fg/pilot/models.py`. Done when UI updates are blocked by permission checks and only show success after read verification.

6. `FG-103` [fg-models] Remove legacy naming/tests not aligned to bg contract (`mumble_session*`, legacy registration naming, old DB-field assumptions). Owner: `fg-models`. Files: `fg/*`, `templates/fg/*`, `fg/tests.py`. Done when no legacy naming or semantics remain for user-facing FG-facing contracts, and tests cover the renamed API/contracts.

## Should-Have Issues (next)

7. `FG-104` [fg-models] Add/keep group permission-driven pulse/watch views and data displays against bg read contract. Owner: `fg-models`. Files: `fg/views.py`, `fg/urls.py`, `templates/fg/*`. Done when FG group/pulse UI reflects bg-sourced permissions and data without direct host mutations.

8. `BG-204` [bg-models] Finalize OO-model naming contract (`murmur_*`) and migration compatibility with bg ownership. Owner: `bg-models`. Files: `/home/michael/prj/mumble-bg` OO models, migrations, docs. Done when names, table contracts, and JSON payloads are consistent with fg consumers.

9. `FG-105` [fg-models] Collapse `fg/pilot` layer to thin adapters only (no host DB coupling assumptions). Owner: `fg-models`. Files: `fg/pilot/models.py`, `fg/pilot/control.py`, `fg/tasks.py`, `fg/tests.py`. Done when every operation that affects Murmur state passes through contract adapters and is validated by read probes.

10. `FG-110` [fg-models] Remove legacy cube/pilot integration code path once FG is contract-driven. Owner: `fg-models`. Files: `fg/pilot/`, `fg/tests.py`, `fg/views.py`. Done when no runtime imports target `fg.pilot.models` or `fg.pilot.control`, no direct calls to host `modules.mumble.*` are made, and all previously tested FG paths use bg control/probe or admin-read-only BG-owned endpoints.

## Later Issues

11. `FG-106` [fg-models] Remove or defer Celery surface if no FG runtime path uses it for bg-facing work. Files: `fg/tasks.py`, app config, dependency wiring. Done when task entrypoints are removed or explicitly marked deprecated and deployment docs updated.

12. `BG-205` [bg-models] Add end-to-end integration tests for control/probe contracts. Files: `/home/michael/prj/mumble-bg` tests. Done when happy-path and failure-path contracts are covered with permission and schema assertions.

13. `FG-107` [fg-models] Final documentation alignment for permissions, permissions matrix, and contract ownership. Files: `docs/conventions.md`, `docs/implementation-matrix.md`. Done when doc states exactly who owns each action and what FG can only read versus request.

## Branch Plan

Plan for execution order: implement `BG-201`/`BG-202`/`BG-203`/`BG-204` on `bg-models` first, then apply `FG-101`/`FG-102`/`FG-103`/`FG-105` on `fg-models`, then run `FG-110`, then validate `FG-104` and stage the later items.

## One-Page Run Order

1. `git checkout bg-models`  
   1. `git pull --ff-only origin bg-models`  
   2. Implement `BG-203`, `BG-201`, `BG-202`, `BG-204` in commit order.  
   3. Run bg control/probe tests and export signatures for each endpoint.

2. `git checkout fg-models`  
   1. `git merge bg-models` (or rebase bg changes if preferred).  
   2. Implement `FG-101` then `FG-105` in one or more atomic commits.  
   3. Validate mutating action paths only route through bg control/probe.

3. Same branch (`fg-models`)  
   1. Apply `FG-110` only after read/write contract verification is green.  
   2. Delete legacy `fg/pilot` path and confirm `rg \"fg\\.pilot|modules\\.mumble\\.models|murmur_userid\" fg` returns expected contract names only.

4. Same branch (`fg-models`)  
   1. Implement `FG-102` then `FG-103`.  
   2. Confirm permission gates (`is_super`) and verification reads are enforced.

5. Same branch (`fg-models`) + `bg-models`  
   1. Run `FG-104` and `FG-107` with docs aligned to final ownership.  
   2. Finish `BG-205`, then optional `FG-106`.  
   3. Run end-to-end verification pass before release.

## Concrete Execution Schedule

Phase 1 (week 1): `BG-203` -> `BG-201` -> `BG-202`. Goal is to deliver control and probe contract first so fg can be switched to read-then-verify behavior. Exit checks: contract endpoints respond with stable JSON schemas, non-super users cannot invoke mutating control routes, probe queries return required fields for password and registration state.

Phase 2 (week 1): `FG-101` -> `FG-105`. Goal is to remove direct fg legacy control and refactor pilot adapters into thin readers/wrappers. Exit checks: fg tests no longer rely on local control-side implementation details; all mutating paths route through bg control/probe contracts.

Phase 3 (week 2): `FG-110` (legacy cube/pilot removal checkpoint). Goal is to cut legacy code and coupling from FG after critical paths are contractized. Actions: delete `fg/pilot/` shims, replace import points in `fg/views.py`/`fg/tests.py`/templates, and remove legacy test expectations tied to local side effects. Exit checks: no runtime dependency on `modules.mumble.*` or `fg.pilot.*`; registration/admin/password paths work only through bg interfaces.

Phase 4 (week 2): `FG-102` -> `FG-103`. Goal is to ship admin action UI and finish naming migration to `murmur_*` contract terms. Exit checks: `is_super` gates enforced; UI shows success only after read verification; contract-facing names are consistent across fg docs and UI.

Phase 5 (week 2-3): `FG-104` -> `BG-205` -> `FG-107` -> `FG-106`. Goal is to complete permissions/pulse UX, then harden tests/docs and optionally trim remaining Celery surfaces. Exit checks: group/pulse view renders only with expected permissions; integration tests cover control/probe contracts; docs and runtime dependencies match final architecture.

Cutover Rule: Do not start `FG-110` until `BG-201` control endpoints, `BG-202` probes, and `FG-101`/`FG-105` adaptation are stable in staging.
