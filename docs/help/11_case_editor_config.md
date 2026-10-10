# Case Editor & Configuration

This chapter merges the use-case editor (用例编辑) with the
configuration page (系统设置): how a case is structured, how to edit
and save one, how to import/export case sets, and what every option on
the Config page does.

## CaseEditorPage (route `cases`)

The visual case editor is a two-pane page:

- **Left: case tree** — groups the YAML cases by their dimension
  (电源网络 / 时钟网络 / 信号网络 / 操作流程), one row per case with
  优先级, 维度 and 状态 (`启用` / `停用`, or `🔒已锁定` for
  version-locked cases).
- **Right: detail form** — the selected case as a read-only identity
  block plus editable fields.
- **Bottom: modification record** — a scrolling audit trail of every
  save, lock and import applied through this page.
- **Dimension toggles** — one checkbox per dimension (e.g.
  `电源网络测试`); toggling enables/disables every case in that group
  and writes the change immediately.

### Case fields

Read-only identity (set by the generator, edited via import):

- `用例名称` (name), `类型` (kind).

Editable fields:

- `测试使能` — enable flag (checkbox).
- `等待ms` (wait_ms), `超时ms` (timeout_ms), `重试次数` (retry).
- `跳过条件` — skip-if expression (free text).
- `阈值下限` / `阈值上限` — threshold_min / threshold_max.
- `优先级(电源树层级)` — priority; `所属电源域` — power domain.
- `仪器分配` — instrument choice combo (DMM / SCOPE / DAQ / ...).
- `备注` — free-text notes.
- Traceability: `上游:` / `下游:` links show the dependency chain of
  the case in the power/topology order.

**Note:** the engine never reads this page — the editor only loads the
YAML through the case store, applies edits through it, and re-renders
from the stored result.

### Step-by-step: edit one case

1. Open the `cases` route; the tree groups all cases by dimension.
2. Click a case — the form fills with its current values and the
   上下游拓扑 line shows its upstream/downstream links.
3. Edit the fields you need (thresholds, timeout, retry, instrument,
   notes...).
4. Press `保存修改 (快照+审计)`:
   - a snapshot of the YAML is taken first,
   - the change is written through the case store,
   - the modification record appends
     `已保存 N 项修改 (用例名)`,
   - the signal `cases_applied(cfg)` fires (hot effect; the engine
     does not poll this page).
5. The tree re-renders and re-selects the edited case so you keep your
   context.

**Warning:** a version-locked case refuses edits — saving raises the
lock guard, the record shows `保存被拦截: <name> 已锁定`, and nothing
is written.  Unlock the case first (see below).

### Lock / unlock a case

- `锁定用例` freezes the selected case against further edits
  (review-freeze workflow).
- `解锁用例` releases it again.
- Both actions are recorded in the audit history shown in the
  modification record.

## Import / export case sets

The case I/O page (route `case_io`) moves cases between YAML and
review Excel:

- **导出** — one-click export of the current cases to a full-field
  review workbook; the path is filled automatically when left empty.
- **导入** — one-click import of the engineer-edited workbook; the
  pipeline is snapshot → pre-flight diff → apply → audit history.
- The **diff report** lists: added / removed cases, per-field
  parameter changes (old -> new), instrument re-assignments, priority
  moves and ignored (dirty) columns.
- Guards:
  - empty path or missing file → import blocked with a message, YAML
    untouched;
  - a version-locked case touched by the workbook → the whole import
    is blocked and the locked names are listed;
  - corrupt workbook / wrong format → import blocked, YAML unchanged.
- After a successful import an automatic snapshot of the new state is
  saved and the change history records the import.

### Step-by-step: round-trip a case set

1. Press the export button — note the generated `.xlsx` path in the
   summary line.
2. Hand the workbook to the case owner; they edit values in place.
3. Put the edited file path into the import field.
4. Press import — read the diff summary (added / removed / changed /
   ignored columns) before accepting the result.
5. Confirm the modification record shows the import entry and the new
   snapshot note.

## ConfigPage (route `config`)

The configuration page is a schema-driven visual YAML editor:

- Sections and fields come from the registered schema; each field
  shows its label, an editor widget and an inline error label.
- Editor types: checkbox (bool), combo (choice), line edit (str /
  number), one-item-per-line for string lists; secret fields render
  as password edits.
- **Real-time validation** — every keystroke / toggle validates the
  field; invalid input gets a red background plus the reason text.
- Top bar:
  - `全量校验` — validates all fields; the summary line lists every
    issue or shows `校验通过 ✔`.
  - `差异对比` — shows pending differences against the saved config.
  - `回滚` + snapshot combo — restore any previous snapshot.
  - `Save (格式化+快照)` — validate, format, snapshot, write.
- **Modification record** — one line per applied change plus rollback
  notes.

### Config options

- **Theme** — appearance selection (light / dark variants provided by
  the style sheet registry); applies through the theme apply guard so
  a failed switch never leaves the UI half-styled.
- **Station settings** — station id, operator-facing labels, log
  levels for the event log panel, report export directory.
- **Engine settings** — retry counts, timeouts, instrument profiles —
  validated against the schema before they can be saved.
- **Credential references** — `credential_ref` names only; secrets
  live in the OS keyring (see `10_audit_security.md`).

### Step-by-step: change a setting safely

1. Open the `config` route; the form loads the current YAML.
2. Edit the field — watch the inline error label clear as the value
   becomes valid.
3. Press `差异对比` to review exactly what will change.
4. Press `Save (格式化+快照)`:
   - validation failures block the save with a modal warning and the
     summary line `校验失败，保存被拦截`;
   - success takes a snapshot (`pre-save` note), writes the formatted
     YAML, and emits `config_applied(cfg)` — hot effect, no engine
     restart.
5. If the result misbehaves, pick an earlier entry in the snapshot
   combo and press `回滚` — the restore is written to disk
   immediately and re-applied hot.

**Note:** unknown YAML keys outside the registered sections are
preserved but not editable here — edit the file directly for exotic
options and re-load.

### Symptom → Cause → Fix

- **Symptom:** save blocked with `校验失败，保存被拦截`.
  - **Cause:** at least one field failed schema validation (bad
    number, empty required value, out-of-range).
  - **Fix:** press `全量校验`, fix every listed field (red background
    marks them), save again.
- **Symptom:** a case cannot be edited.
  - **Cause:** the case is version-locked (row shows `🔒已锁定`).
  - **Fix:** select it and press `解锁用例`, edit, then re-lock.
- **Symptom:** import blocked with `锁定冲突`.
  - **Cause:** the workbook would overwrite a locked case.
  - **Fix:** unlock the listed cases (or remove them from the
    workbook) and import again.
- **Symptom:** dimension toggle changed more cases than expected.
  - **Cause:** the toggle enables/disables the whole dimension group.
  - **Fix:** re-toggle the group, then re-enable the individual cases
    in the form.
- **Symptom:** instrument combo shows the wrong device.
  - **Cause:** the case's stored instrument is not in the current
    choice list; the editor falls back to the first entry.
  - **Fix:** set the instrument explicitly in the form and save.
- **Symptom:** rollback combo is empty.
  - **Cause:** no snapshot exists yet (nothing was saved through this
    page).
  - **Fix:** make one save first; snapshots are created on every
    successful save.

## Related pages

- `08_reports_logs.md` — where the results of these cases end up.
- `10_audit_security.md` — who may edit cases or config (roles).
- `12_faq.md` — quick fixes for YAML load and validation problems.
