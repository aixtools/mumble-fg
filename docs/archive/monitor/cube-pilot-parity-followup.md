# Cube Pilot Parity Follow-Up

This note captures the monitor-side work to do if Cube PR `aixtools/Cube#2` is approved and deployed.

## Goal

Consume Cube's new cached org, clone, and contact data so the Cube path reaches closer parity with AUTH without adding live ESI calls inside monitor.

## Cube Data Added By PR #2

New org metadata tables:
- `accounts_eveallianceinfo`
- `accounts_evecorporationinfo`

New clone tables:
- `character_clone_summary`
- `character_jump_clones`
- `character_jump_clone_implants`
- `character_current_implants`

New contact tables:
- `character_contacts_summary`
- `character_contact_labels`
- `character_contacts`

## Monitor Touch Points

### 1. Add ticker-backed org resolution for Cube

File:
- `monitor/adapters/repositories.py`

Current state:
- `DjangoCubeRepository.resolve_alliance()` resolves from `accounts_evecharacter` only and cannot match alliance ticker.
- `DjangoCubeRepository.resolve_corporation()` resolves from `accounts_evecharacter` only and cannot match corporation ticker.
- `DjangoCubeRepository.list_pilots()` and `list_mains()` do not return `corporation_ticker` or `alliance_ticker`.

Follow-up:
- Query `accounts_eveallianceinfo` in `resolve_alliance()`.
- Query `accounts_evecorporationinfo` in `resolve_corporation()`.
- Join those tables in `list_pilots()` and `list_mains()` so `EvePilot.from_record()` receives:
  - `corporation_ticker`
  - `alliance_ticker`
  - optional future extras such as `member_count`, `ceo_id`, `executor_corp_id`

Why:
- `EvePilot.label` in `monitor/models/eve.py` assumes corp ticker exists and uses alliance ticker when present.
- Today the Cube path works around missing tickers in some places instead of loading canonical pilot labels from DB-backed data.

### 2. Implement clonebook support for Cube

File:
- `monitor/adapters/repositories.py`

Current state:
- `DjangoCubeRepository.get_pilot_clone_summary()` returns `None`.
- `DjangoCubeRepository.list_pilot_jump_clones()` returns `()`.
- `DjangoCubeRepository.list_pilot_current_implants()` returns `()`.
- `DjangoCubeRepository.get_pilot_clonebook()` returns `None`.

Follow-up:
- Build `EvePilotCloneSummary` from `character_clone_summary`.
- Build `EveJumpClone` rows from `character_jump_clones`.
- Build jump-clone implant rows from `character_jump_clone_implants`.
- Build current implant rows from `character_current_implants`.
- Return a normal `EvePilotClonebook` from `get_pilot_clonebook()`.

Suggested joins:
- `character_clone_summary.character_id -> accounts_evecharacter.id`
- `character_jump_clones.character_id -> accounts_evecharacter.id`
- `character_jump_clone_implants.jump_clone_id -> character_jump_clones.id`
- `character_current_implants.character_id -> accounts_evecharacter.id`

Useful fields now cached by Cube:
- home clone location id/name/type
- last clone jump timestamp
- last station change timestamp
- jump clone location id/name/type
- implant ids, names, and slots

### 3. Enable Cube contact counts in the wealth/detail API

File:
- `monitor/views.py`

Current state:
- `status_pilot_wealth_json()` only fills `clones`, `contacts`, and `contacts_total` for AUTH.
- The Cube branch only returns assets, wallet, and SP.

Follow-up:
- In the Cube branch of `status_pilot_wealth_json()`, count jump clones from `character_jump_clones`.
- Fill per-character contacts from `character_contacts_summary.total_contacts`, or from `character_contacts` if agent filtering is needed.
- Fill `contacts_total` from distinct `character_contacts.contact_id` across the requested characters.

Important parity detail:
- AUTH excludes NPC agents by contact id range `3000000-3999999`.
- If monitor wants exact parity, apply that same exclusion when counting from Cube's `character_contacts` table.

### 4. Keep Cube roster queries aligned with soft-delete behavior

File:
- `monitor/adapters/repositories.py`

Current state:
- Monitor reads `accounts_evecharacter` directly, which can include `pending_delete = TRUE` rows.

Follow-up:
- Add `pending_delete = FALSE` filtering to Cube pilot queries where appropriate.

This is not introduced by PR #2, but it is worth folding in while the Cube adapter is already being touched.

### 5. Optional monitor-only parity cleanup

File:
- `monitor/views.py`

Current state:
- Cube asset counts use `character_assets_summary.total_items`.
- AUTH asset counts use summed item quantity.

Follow-up:
- Prefer `character_assets_summary.total_quantity` for Cube asset counts if the goal is AUTH-style quantity parity rather than unique-row parity.

## Minimal Patch Order In Monitor

1. Update `DjangoCubeRepository.resolve_alliance()` and `resolve_corporation()` to use the new org metadata tables.
2. Update `DjangoCubeRepository.list_pilots()` and `list_mains()` to return tickers.
3. Implement the four clone methods in `DjangoCubeRepository`.
4. Update the Cube branch of `status_pilot_wealth_json()` to expose clone and contact counts.
5. Add `pending_delete = FALSE` filtering and, if wanted, switch Cube asset counts to `total_quantity`.

## Sanity Checks After Monitor Follow-Up

- Cube pilot labels render as `[ALLY CORP] Name` without live ESI lookups.
- Cube detail panel shows clone counts and contact counts.
- Cube `contacts_total` matches AUTH-style behavior if NPC-agent filtering is applied.
- Soft-deleted Cube characters no longer appear in pilot lists.
