# FG/BG Contracts

This document captures explicit contracts and implicit conventions between:
- FG and BG services
- FG/BG admins (operators)
- Individual pilots

## 1) Explicit Service Contracts

### 1.1 Boundary
- FG is host/UI/admin.
- BG is runtime/state daemon.
- FG is the only side that reads host/pilot data.
- FG reads `PILOT_DBMS`; BG owns `BG_DBMS`.
- FG does not read BG DB directly.
- BG does not read FG/host DB directly.
- BG does not write FG/host tables.
- BG owns runtime state plus a cached FG pilot snapshot.
- Integration is API-only (control/probe endpoints).

### 1.2 Control Channel Auth
- FG calls BG control endpoints with shared secret auth (`FGBG_PSK`).
- Missing/invalid secret is rejected (`401`).
- If BG is unreachable, FG treats operations as unavailable.

### 1.3 ACL Sync Contract
- FG sends full ACL payload to BG (`/v1/access-rules/sync`).
- BG validates payload shape/types.
- BG computes delta against current state.
- If delta is empty: no state change and no BG ACL audit row.
- If delta exists: BG applies create/update/delete, then writes ACL audit row.
- Sync is full-table replacement on BG (rules not present in payload are removed).

### 1.4 Pilot Snapshot Sync Contract
- FG sends a full account-oriented pilot snapshot to BG (`/v1/pilot-snapshot/sync`).
- Snapshot accounts are keyed by `pkid`.
- Each account includes the main character plus its character list and org data.
- BG validates payload shape/types.
- BG replaces its cached pilot snapshot when the snapshot changes and writes snapshot sync audit metadata.

### 1.5 Provision Contract
- FG can request reconcile/provision after ACL sync (`/v1/provision`).
- BG computes eligible/blocked from rules + cached FG pilot snapshot data.
- Eligible:
  - missing BG user -> create
  - inactive BG user -> reactivate
- Blocked:
  - existing active BG user -> deactivate
  - missing user -> no-op
- FG periodic sync (scheduler/command) uses this same ACL sync path so disconnect windows self-heal.
- Even when ACL sync is `noop`, FG can still push snapshot state and request eligibility/provision and Murmur reconciliation.

### 1.5 Password Reset Contract
- FG reset/set actions target BG by `pkid` (BG-side user identity).
- In mock UI mode, FG maps selected `character_id` to Eve `user_id` before BG call.
- BG updates password hash state and attempts Murmur sync.
- BG audits password change attempts/outcomes.

### 1.6 Murmur Registration Contract
- Registration sync endpoint updates or creates Murmur registration for one BG user.
- Disable endpoint keeps registration present and sets disabled state (does not delete row).
- BG audits Murmur user creation events.
- BG sync/reconcile ensures all active BG users are present in Murmur (except unmanaged Murmur SuperUser).
- Inactive BG users are kept in Murmur but forced into disabled state; disable transitions are audited.

## 2) Explicit Admin Contracts

### 2.1 FG Admin Permissions
- ACL UI visibility and actions are permission-gated by FG module permissions and/or superuser.
- `is_staff` alone is not sufficient for FG ACL CRUD visibility.

### 2.2 Audit Immutability
- FG ACL audit is append-only.
- BG audit is append-only.
- Audit rows are not editable/deletable by normal admin flows.
- Pilot-related BG audit actions are: `pilot_create`, `pilot_disable`, `pilot_enable`, `pilot_pwreset`.

### 2.3 Sync UX
- Sync is non-blocking from UI perspective.
- UI surfaces success/failure state from control responses.
- BG-unavailable and BG-reachable failures are surfaced as distinct user messages.

## 3) Explicit Pilot Contracts

### 3.1 Profile Panel Visibility
- Pilot sees Mumble profile panel only when ACL-eligible.
- If multiple eligible pilot identities are available, selector is shown.

### 3.2 Pilot-Initiated Password Actions
- Pilot reset/set requests are validated in FG (selection and password policy).
- FG forwards operation to BG; BG is source of truth for runtime account state.
- Failure semantics:
  - BG unreachable -> unavailable message
  - BG reachable but account not active/ready -> inactive/try later

## 4) Implicit Contracts and Conventions

### 4.1 Identity Convention
- Runtime key is stable Cube account identity (`pkid`), not display name.
- Character names are presentation values and can drift from stored runtime usernames.

### 4.2 Specificity Convention for ACL
- Precedence is most-specific wins:
  - pilot > corporation > alliance
- Deny-on-alt can block account-level eligibility unless overridden by more-specific allow.
- Baseline is allow-by-rule-presence with alliance allow as the broadest allow path.
- Unlisted alliances are implicitly denied for eligibility (no allow path).

### 4.3 Operational Convention
- `mockbg.sh` is the local operator surface for mock stack lifecycle and sync.
- Status checks are protocol/API based, not filesystem/process-introspection only.

### 4.4 Failure Handling Convention
- Partial progress is acceptable when designed (example: password hash stored even if Murmur sync fails).
- Partial outcomes should be visible in response and audit metadata.

### 4.5 Evolution Convention
- Backward-compatibility shims used during development should be removed once contract stabilizes.
- New behavior changes should land with tests and explicit contract updates in docs.
