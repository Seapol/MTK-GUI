# Audit & Security

This chapter merges the security model into the GUI workflow: who may
do what, where every operation is recorded, and how credentials are
stored.  The two roles from the security spec — **Supervisor** (full
access) and **Operator** (restricted) — are enforced by an RBAC gate;
every guarded call is written to the append-only audit ledger.

- **Supervisor**: full access; may switch to Virtual; grants Operator
  permissions (Settings > Operator Permissions).
- **Operator**: no password; permissions default-deny; Product Info
  read-only; Real mode only.

## AuditPage (审计记录, route `audit`)

The audit page is the human window onto the `AuditLog` ledger:

- **Login box** — username/password log in through the access control
  object; after login the session badge shows the role
  (`管理员(全权限)` / `操作员(受限权限)`) or `未登录`.
  - Failed logins are audited too (`login:DENY` entries) — the badge
    shows 未登录 and the attempt stays on record.
- **Guarded demo action** — the `修改配置(受权限管控)` button calls the
  permission gate with action `edit_config`:
  - denied → the session line shows `| 无权限（已留痕）` and a `DENY`
    entry is recorded; nothing changes;
  - granted (admin) → the change is logged with before/after values
    and the detail note.
- **Audit board** — ledger table with 7 columns:
  时间 / 操作员 / 动作 / 对象 / 变更前 / 变更后 / 备注.
- **Filters** — action combo (`全部动作`, plus login / edit_config /
  edit_case / import / export / upload / report_delete /
  audit_export), operator text filter, free-text search, `查询`
  button.  All criteria are AND-combined.
- **Export** — `导出 CSV` and `导出 JSON` one-click exports of the
  filtered ledger; each export is itself logged as `audit_export`.

**Note:** the ledger is append-only.  Nothing in the GUI edits or
deletes audit entries; the only way to reduce noise is to filter the
view or export and archive the file.

### Step-by-step: review today's audit trail

1. Open the `audit` route.
2. Leave 动作 at `全部动作` and clear the operator filter for a full
   sweep, or narrow it (e.g. 动作 `export`, 操作员 your account).
3. Press `查询` — the table re-renders from the filtered entries.
4. Use the free-text box to hunt for one target (a case name, a config
   path) across all actions.
5. Export the result to CSV/JSON and attach it to the release record;
   the export action itself appears as the newest row.

### What gets recorded

- Every login attempt: `login:GRANT` / `login:DENY`.
- Every guarded action attempt: `edit_config`, `edit_case`,
  `export_report`, `report_delete`, `upload`, ... with
  `GRANT`/`DENY`.
- Data changes: before/after snapshots so a diff is always available.
- Import/export/report flows, device failover (`[CLUSTER]` lines) and
  credential operations.

## RBAC & the audit hub

- The RBAC gate is the single permission source: an action is allowed
  only if the session's role grants it; `*` grants everything
  (Supervisor/ADMIN).
- `require(session, action, target)` raises `PermissionError` on
  denial **and** records the attempt — a denial is never silent.
- Operator permissions are **default-deny**: only explicitly granted
  actions (run / view / export / upload) pass; configuration editing
  and case editing always require Supervisor.
- Page access levels map route keys to minimum roles, so the same
  matrix drives both the menus and the backend gate.
- The audit hub sits on top of the append-only `AuditLog` store and
  adds categorized queries (`category:action`), per-user/per-category
  statistics, deny counters and integrity verification of the JSONL
  ledger.

### Step-by-step: grant an Operator a permission

1. Log in as Supervisor.
2. Open Settings > Operator Permissions (the permission matrix view).
3. Tick the action you want to grant (e.g. `export_report`).
4. Save — the matrix is persisted and takes effect for new sessions.
5. Have the Operator re-log-in; verify the allowed action now passes
   and check the audit board for the `GRANT` entry.

**Warning:** permissions are loaded at login.  A running Operator
session keeps its old matrix until re-login — do not expect live
downgrades to kick in mid-run.

## Credentials & the keyring

- **Credentials** (SSH / DUT login) are stored in the OS keyring
  (macOS Keychain / Windows Credential Manager) — the YAML only keeps
  a `credential_ref`, never the secret.
- Lookup order for one credential reference:
  1. OS keyring, service `mtk-gui`;
  2. environment variable `MTK_CRED_<REF>` (uppercased reference) —
     used only as a fallback, **with an explicit warning** the caller
     must surface (Event Log + UI banner);
  3. neither → the channel open fails with a clear reason and nothing
     is guessed.
- Plaintext storage is never used; if the keyring backend is
  unavailable the app says so instead of silently degrading.
- `set_credential` writes through the keyring; if the keyring refuses
  the write, you are told to use the environment fallback.
- **Supervisor password reset** clears stored credential refs; the
  operator re-enters them (see docs/fct/B3 spec section 7.2).

### Step-by-step: store a DUT login credential

1. Open the equipment entry that needs SSH/DUT login and set its
   `credential_ref` name (the YAML keeps only this reference).
2. Enter the secret once in the credential dialog — it goes into the
   OS keyring under service `mtk-gui`.
3. Connect; if a banner mentions the environment fallback, either fix
   the keyring or `export MTK_CRED_<REF>=...` before the next start.
4. Rotate the secret by re-entering it (the keyring value is
   overwritten; the YAML reference stays unchanged).
5. After a Supervisor password reset, re-enter the refs as prompted —
   the stored credential list was cleared on purpose.

### Symptom → Cause → Fix

- **Symptom:** `keyring unavailable` warning at startup.
  - **Cause:** no usable OS keyring backend (headless box, missing
    service).
  - **Fix:** set `MTK_CRED_<REF>` for every referenced credential, or
    restore the keyring service; plaintext storage is never used as a
    fallback.
- **Symptom:** Operator cannot export a report.
  - **Cause:** `export_report` is not in the Operator's granted set
    (default-deny).
  - **Fix:** Supervisor grants `export_report` in Settings > Operator
    Permissions; Operator re-logs-in.
- **Symptom:** a guarded button shows `无权限（已留痕）`.
  - **Cause:** the gate denied the action for your role — this is the
    designed behavior, and the attempt is on the audit ledger.
  - **Fix:** request the permission from a Supervisor; verify the
    `DENY` entry under 动作 on the audit page.
- **Symptom:** audit table empty after login.
  - **Cause:** filters are too narrow (action combo or operator box).
  - **Fix:** reset 动作 to `全部动作`, clear both text filters, press
    `查询`.
- **Symptom:** credential ref resolves but login still fails.
  - **Cause:** stale keyring value after a password rotation on the
    DUT side.
  - **Fix:** re-enter the secret via the credential dialog (step 4
    above) and retry.

## Related pages

- `08_reports_logs.md` — how audit-exported CSVs relate to the report
  exports under `reports/<date>/`.
- `11_case_editor_config.md` — the config-edit permission that the
  guarded demo action mirrors.
- `12_faq.md` — the keyring and Run blocked quick fixes.
