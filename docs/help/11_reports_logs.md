# Reports & Logs

- **Event Log** (bottom panel): every step start / verdict / operator
  answer, each line stamped with Station ID + User; PASS/FAIL/Error
  colored.
- **Report > Generate Report...**: certificate-style DUT report
  (Style A: double-ring frame, big PASS / FAIL seal, "Authorized by
  MTK" sign-off row) + batch summary (counts, yield %, failed-item
  ranking); the full console transcript is attached as an appendix.
  CSV export (MES-importable) and the fixed-name PDF
  (`DUT_[PASS/FAIL]_[Serial#]_[Core ID]_[Project Part#]_[Batch#]_
  [Date]_[Time].pdf`) land under `reports/<date>/`; Supervisor
  exports, Operator sees a read-only preview of the current session.
- Automatic trigger: every counted product appends to the session
  batch; `audit_log` / `archive` keep the publish history.

## ReportPage (route `reports`)

The **ReportPage** is a read-only dashboard: it recomputes every chart
from the metrics engine on demand and never mutates engine state.

- Data source: the `MetricsEngine` record list — zero metric logic is
  duplicated in the page.
- Filter bar:
  - `批次:` — one batch or `全部` (rebuilt automatically from records).
  - `当班:` — `全部` / `day` / `night`.
- Action buttons: `刷新`, `重置`, `数据明细`, `自动刷新: 开/关`.
- Charts:
  - 良率趋势 — real product yield bucketed into 6 equal time slices
    (invalid records excluded from the real-yield line).
  - CpK 制程能力趋势 — per-batch CpK of one configurable parameter
    (empty until `cpk_case` + limits are set).
  - CycleTime 工时对比 — per-case mean, top 8, bottleneck highlighted.
  - 不良项 TOP — top defect ranking.
  - 失败分类占比 — real FAILs vs each invalid kind.
- 批次对比表 — one row per batch: 良率 / 平均工时s / 测试数.
- 数据明细 — first 200 in-scope records as text lines:
  `ts batch station name status measured=… dur=…s`; a modal dialog
  shows the same text when the page runs interactive.
- 自动刷新 — a 5 s timer re-runs `refresh()`; the toggle text switches
  between `自动刷新: 开` and `自动刷新: 关`.
- Signal `report_refreshed(count)` fires after every refresh — tests
  and status widgets may subscribe; the engine never polls this page.

**Note:** the batch combo keeps your current selection when new batches
appear; `重置` returns both filters to `全部`.

### Step-by-step: read the dashboard

1. Open the `reports` route.
2. Pick a batch (or keep `全部`) and a shift.
3. Press `刷新` — the detail line shows
   `refresh: N record(s) in scope`.
4. Press `数据明细` to inspect individual records.
5. Enable `自动刷新: 开` during a running session.

## Session batch & export (Supervisor)

- Every counted product appends to the **session batch**; the batch
  summary carries counts, yield % and the failed-item ranking.
- **Report > Generate Report...** produces:
  - the certificate-style DUT report (all judged items + the
    PASS / FAIL seal bound to the data by a sha256 trace hash),
  - the batch summary,
  - CSV export (MES-importable) + the fixed-name DUT PDF
    (`dut_pdf.py` renders the same markup to A4 via QPrinter).
- **Supervisor** exports; **Operator** gets a read-only preview of the
  current session only.
- The P2-9 exporter renders the commercial deliverable:
  - `build_html_report(...)` — header (part/batch/station/version/
    revision/timestamp/trace hash), KPI summary, anomaly statistics,
    trend thumbnails, batch comparison, full test detail, footer.
  - `export_pdf(html, path)` — the same HTML printed to A4 PDF.
  - `doc_hash(payload)` — SHA-256 provenance digest embedded in header
    and footer (stable for identical source data).
- `audit_log` / `archive` keep the publish history of every export.

**Warning:** the exporter is strictly read-only — it never mutates
engine state; do not try to "fix" data by editing exported CSVs.

### Step-by-step: export a batch report

1. Finish (or pause) the running session so counts are stable.
2. Open `Report > Generate Report...` (Supervisor login required).
3. Review the DUT detail + batch summary preview.
4. Export CSV — the file lands under the date folder (below).
5. Optional: export PDF for archiving; verify the trace hash matches
   the one shown in the report header.

### reports/ directory layout

Exports are organized by calendar day; MES import picks files from the
date folder of the run:

```text
reports/
  2026-10-10/
    summary_<batch>.csv      # batch summary: counts, yield, ranking
    <dut_id>.csv             # per-DUT detail: all judged items
    DUT_PASS_<SN>_<core>_<part#>_<batch#>_<date>_<time>.pdf
                             # certificate report (FAIL named alike)
    report_<batch>.html      # commercial HTML deliverable
    report_<batch>.pdf       # A4 print/archive copy
```

- `summary_<batch>.csv` — one row per batch: total / PASS / FAIL /
  invalid / real yield / mean cycle time.
- `<dut_id>.csv` — one row per judged item: case, verdict, measured,
  limits, duration, timestamp, batch.
- Older folders are never rewritten; re-running the same DUT appends a
  new timestamped file set.

**Note:** keep `reports/` inside the project directory so the archive
and audit trail can reference the same paths.

## SharePoint Upload (Report menu)

> **TEMPORARILY DISABLED** (2026-10-27): the menu item is greyed out
> for the general operator - the browser-session sign-in flow is too
> involved for the shop floor. The dialog, engine and this guide stay
> intact; re-enable `sp_upload_action.setEnabled(True)` in
> `main_window.py` when a simpler path is approved by IT.

`Report > SharePoint Upload...` moves a local folder (reports, logs,
archives) to the project SharePoint folder - either as a real-time
mirror (new / changed files only) or as a timestamped zip once per
period (day / week / bi-weekly / month / quarter / half-year / year).
Virtual mode uses the built-in `FakeSharePoint` transport and marks
every result `(virtual)`; the site is never contacted.

Real mode talks to the NXP tenant over the SharePoint REST API with
the operator's own browser session. The sign-in paths, fastest first:

1. Paste the folder share link (modern `.../:f:/r/teams/...` or the
   classic `.../:f:/teams/...` form; a link to a project sub-folder is
   accepted - it simply becomes the upload root) into **Site link**.
2. **Open in System Browser…** - one click opens the site in your own
   browser AND the import dialog: sign in there if needed (MFA /
   organizational policy all handled by the browser), then press
   F12 > Application > Cookies, copy the `FedAuth` and `rtFa` cookie
   lines for the site and paste them into the import dialog.
3. **Import Browser Session…** - the same paste path when you are
   already signed in (browser still open): the dialog validates the
   cookies against the site host, runs **Test Connection**
   automatically and confirms
   `Signed in as <name> - SharePoint test-data upload ready`.
4. **Connect & Sign in...** - an embedded login window opens; sign in
   with your corporate account (MFA included). Some corporate tenants
   reject the embedded window (e.g. AD account validation failures).

Why is there no fully automatic handover? An automatic Edge debug-port
import was researched and implemented, then verified against this
company Edge (v156): the browser **ignores** `--remote-debugging-port`
on the real profile (2025 anti-debug protection), the cookie values
are app-bound encrypted (a copied profile cannot decrypt them), and
the `RemoteDebuggingAllowed` policies are locked by the company. The
browser-session paste path above is the working one on managed hosts.

MTK GUI stores no password - only the resulting `FedAuth` / `rtFa`
session cookies, under `mtkgui/config/sharepoint_state/` on this OS
user's profile. Test Connection reports OK only when the folder is
reachable and writable; a 401/403 means the session expired (sign in
again or import a fresh browser session), a 404 means the link is
wrong. Until a session is present the dialog shows
`not signed in - sign in in your own browser, then Import Browser
Session (no password, no embedded login)` and never uploads with a
stale session.

Then pick the local folder and the mode and press **Sync Now** /
**Pack & Upload Now** (or let the 30 s driver work while the dialog is
open). Uploads use `Files/add(overwrite=true)`; failures stay in the
local outbox and are retried on the next sweep.

The **Token** field stays for legacy token-based sites.

## Event Log (LogPanelWidget)

The bottom **log panel** is a pure sink — it emits nothing back to the
engine, so there is zero coupling with the core links.

- Line format (fixed):

```text
[HH:MM:SS.mmm] [LEVEL] message
```

- Timestamp resolution: milliseconds (`%H:%M:%S.%f` trimmed to ms).
- Levels: `DEBUG`, `INFO`, `WARN`, `ERROR` — unknown levels are
  recorded as `INFO`.
- Colors: DEBUG dim, INFO normal, WARN warning color, ERROR red —
  verdicts PASS/FAIL/Error are visually separated at a glance.
- Every step start / verdict / operator answer is appended live; each
  line carries the Station ID + User context from the session.
- In-memory buffer: up to 5000 entries; the view keeps scrolling and
  trims the oldest rendered lines.
- Filters:
  - level combo — `ALL` or one exact level;
  - keyword box — case-insensitive substring match on the message.
- `Clear` empties the view only; the entry buffer keeps collecting
  (change the filter and older lines reappear).

### Step-by-step: find a failure in the log

1. Set the level combo to `ERROR` (or `WARN` to catch flaky steps).
2. Type the case name or DUT id into the keyword box.
3. Read the matching lines; timestamps link the log line to the CSV
   row exported under `reports/<date>/`.
4. Reset the keyword box to empty when done — the view re-renders the
   whole buffer under the current level filter.

### Symptom → Cause → Fix: log & report issues

- **Symptom:** the log shows nothing during a run.
  - **Cause:** level filter set to a level nobody logs (e.g. `ERROR`
    during an all-PASS run).
  - **Fix:** set the level combo back to `ALL`, clear the keyword box.
- **Symptom:** old log lines disappeared.
  - **Cause:** the 5000-entry view limit — the oldest lines were
    trimmed, or `Clear` was pressed (view only).
  - **Fix:** switch filters to re-render the buffer; export the batch
    CSV from `reports/<date>/` for a durable copy.
- **Symptom:** report KPIs look wrong (yield too high).
  - **Cause:** invalid records are excluded from the *real* yield by
    design; check the 失败分类占比 pie for invalid kinds.
  - **Fix:** read the 异常统计 section of the HTML/PDF report; verify
    the invalid classification of the affected DUTs.
- **Symptom:** CSV missing in `reports/<date>/`.
  - **Cause:** export requires Supervisor; Operator preview is
    read-only and writes nothing.
  - **Fix:** log in as Supervisor and repeat `Generate Report...`;
    the publish history appears in `audit_log`.
- **Symptom:** CpK chart is empty.
  - **Cause:** `cpk_case` unset or `cpk_usl` not greater than
    `cpk_lsl`.
  - **Fix:** configure the CpK parameter (case + LSL/USL) and press
    `刷新`.
- **Symptom:** auto-refresh does not stop.
  - **Cause:** the toggle stays checked; the 5 s timer keeps firing.
  - **Fix:** press `自动刷新: 开` once to switch it to `关`.

## Related pages

- `12_audit_security.md` — who may export, and where the audit trail
  of every export lives.
- `13_case_editor_config.md` — configuration parameters that feed the
  KPI computations (limits, shifts, station id).
- `14_faq.md` — quick fixes for CSV log and Run blocked problems.
