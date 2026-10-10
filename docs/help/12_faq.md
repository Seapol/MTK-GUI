# FAQ / Troubleshooting

Every entry follows the same structure: **Symptom** → possible
**Cause** → **Fix** (step by step).  Quick index of covered keywords:
`no nets found`, `Address`, `CSV log`, `keyring`, `Run blocked`,
`Overall IGNORE`, login, ports, reports.

## Q1: "no nets found" when parsing a netlist

- **Symptom:** the YAML build reports `no nets found` and produces an
  empty design.
- **Possible cause:** the loaded file has no recognizable netlist
  content — most often the wrong file was picked (the SPF instead of
  the NET).
- **Fix:**
  1. Re-open the file picker in the YAML build page.
  2. Load the **NET** file, not the SPF file.
  3. Re-run the parse; the net count should now be non-zero.

## Q2: "no 'Address' field in the project YAML"

- **Symptom:** an instrument entry is rejected with `no 'Address'
  field in the project YAML`.
- **Possible cause:** the instrument entry has no Address configured.
- **Fix:**
  1. Open the Equipment page.
  2. Configure the Address for that instrument entry.
  3. Save the project YAML and re-run.
- **Note:** Virtual mode Tools batch does not need an Address — the
  virtual instruments are addressed internally.

## Q3: "power rail CSV log missing"

- **Symptom:** the rails capture produced no CSV log (rare, Virtual
  mode).
- **Possible cause:** the rails capture window did not overlap the
  sequence (timing race between capture and test delays).
- **Fix:**
  1. Re-run the sequence once — the race usually resolves itself.
  2. If it repeats: check the rails capture window against the
     sequence delays and widen the capture window.
  3. Re-run and verify the CSV appears under `reports/<date>/`.

## Q4: "Connect failed" on a console port

- **Symptom:** the console link refuses to open.
- **Possible cause:** port busy (another session holds it) or wrong
  baud rate.
- **Fix:**
  1. Close any other terminal that uses the port.
  2. Verify the baud rate matches the DUT console setting.
  3. Reconnect.
- **Note:** Virtual mode needs no hardware — the fake DUT port
  appears without a device attached.

## Q5: "keyring unavailable" warning

- **Symptom:** a warning at startup or when opening a channel.
- **Possible cause:** the OS keyring backend is unavailable (headless
  box, missing service).
- **Fix:**
  1. Set the environment variables `MTK_CRED_<REF>` for every
     credential reference.
  2. Or repair the OS keyring (macOS Keychain / Windows Credential
     Manager) and restart the app.
- **Warning:** the fallback is the environment variable — plaintext
  storage is never used, do not look for a "save password in file"
  option.

## Q6: "Run blocked: no YAML loaded"

- **Symptom:** the Run button refuses to start.
- **Possible cause:** no project YAML is loaded in this session.
- **Fix:**
  1. Use `File > Load Yaml` and pick the project YAML.
  2. Verify the status line shows the loaded project.
  3. Press Run again.

## Q7: Overall verdict shows IGNORE

- **Symptom:** the DUT overall shows `Ignore` although items ran.
- **Possible cause:** this is the designed rule — only a Stop with NO
  failed item shows Ignore.
- **Fix:** no action needed; but remember: any FAIL (even one that
  happened after Stop) reports FAIL overall.  If you expected PASS,
  inspect the item list for the failing step.

## Q8: Login fails with a correct-looking password

- **Symptom:** `登录失败` although the credentials seem right.
- **Possible cause:** role/password mismatch (Operator accounts may
  have been reset), or the account store was re-bootstrapped.
- **Fix:**
  1. Confirm the account exists (ask the Supervisor).
  2. Supervisor: re-create or reset the account in the RBAC page.
  3. Re-login; failed attempts are audited (see `10_audit_security.md`).

## Q9: Operator cannot export a report

- **Symptom:** export is denied for the Operator role.
- **Possible cause:** permissions are default-deny; export must be
  granted explicitly.
- **Fix:**
  1. Supervisor opens Settings > Operator Permissions.
  2. Grant the export permission.
  3. Operator re-logs-in and retries the export.

## Q10: Config save blocked

- **Symptom:** `校验失败，保存被拦截` on the Config page.
- **Possible cause:** one or more fields fail schema validation.
- **Fix:**
  1. Press `全量校验` to list every issue.
  2. Fix the red-marked fields.
  3. Save again — the snapshot is taken automatically on success.

## Q11: A case refuses to be edited

- **Symptom:** saving a case reports it is locked.
- **Possible cause:** the case is version-locked (freeze workflow).
- **Fix:**
  1. Select the case in the tree.
  2. Press `解锁用例`.
  3. Edit and save; re-lock afterwards if needed.

## Q12: Import of the review Excel is blocked

- **Symptom:** `导入被拦截` / `锁定冲突` on the case I/O page.
- **Possible cause:** missing file, corrupt workbook, or the import
  would overwrite version-locked cases.
- **Fix:**
  1. Check the file path exists.
  2. Re-export the review workbook and re-apply edits on the fresh
     copy.
  3. Unlock the listed cases, then import again.

## Q13: Cluster tasks stay QUEUED forever

- **Symptom:** tasks never leave the queue on the Cluster page.
- **Possible cause:** no idle device of the matching kind; all
  matching devices are in `ERROR`.
- **Fix:**
  1. Compare task 类型 with the device 类型 column.
  2. `恢复选中设备` for any device in `ERROR`.
  3. Press `派发下一任务` again.

## Q14: Report CSV is missing in reports/<date>/

- **Symptom:** no new CSV after running a batch.
- **Possible cause:** export requires Supervisor; the Operator
  preview is read-only and writes nothing.
- **Fix:**
  1. Log in as Supervisor.
  2. `Report > Generate Report...` again.
  3. Verify the file appears and the publish history shows in
     `audit_log`.

## Q15: The event log shows nothing during a run

- **Symptom:** the bottom log panel stays empty.
- **Possible cause:** level filter set to a level nobody logs (e.g.
  `ERROR` during an all-PASS run), or a leftover keyword filter.
- **Fix:**
  1. Set the level combo back to `ALL`.
  2. Clear the keyword box.
  3. If lines are still missing, press `Clear` and re-run — the
     buffer re-renders under the active filters.

## Q16: The app forgot a stored credential after a reset

- **Symptom:** channels ask for credentials again after a Supervisor
  password reset.
- **Possible cause:** by design — a password reset clears stored
  credential refs.
- **Fix:**
  1. Re-enter the credentials (they are stored in the OS keyring, the
     YAML only keeps `credential_ref`).
  2. Operator accounts must re-enter them after the reset (see
     docs/fct/B3 spec section 7.2).

## Still stuck?

- Check `08_reports_logs.md` for the exact log/CSV locations.
- Check `10_audit_security.md` for role and credential questions.
- Collect the event log lines around the failure (filter by `ERROR`)
  and attach them — with the `reports/<date>/` CSV — to your support
  request.
