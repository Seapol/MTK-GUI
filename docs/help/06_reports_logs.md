# Reports & Logs

- **Event Log** (bottom): every step start / verdict / operator answer,
  each line stamped with Station ID + User; PASS/FAIL/Error colored.
- **Report > Generate Report...**: DUT detail report (all judged items)
  + batch summary (counts, yield %, failed-item ranking); CSV export
  (MES-importable) under `reports/<date>/`; Supervisor exports,
  Operator sees a read-only preview of the current session.
- Automatic trigger: every counted product appends to the session
  batch; `audit_log` / `archive` keep the publish history.
