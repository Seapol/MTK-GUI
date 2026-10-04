# -*- coding: utf-8 -*-
"""P3-10 audit middle platform & compliance report demo
(headless-safe, rc=0).

Closed loop: categorized full-chain logging (login/config/case/
task/device) -> config change with before/after diff -> stats ->
integrity verify (incl. tampered ledger detection) -> ISO compliance
report CSV+JSON export -> CompliancePage GUI board.  Exit 0 = all
checkpoints passed.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mtkgui.engine.audit_hub import AuditHub, diff_of
from mtkgui.engine.auth_audit import AuditLog


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="audit_hub_demo_"))
    hub = AuditHub(AuditLog(tmp / "audit.jsonl"))

    # 1. full-chain categorized trail
    hub.track("op1", "login", "login", "op1")
    hub.track("eng1", "case", "edit", "CASE-1")
    hub.track("eng1", "task", "submit", "T1")
    hub.track("op1", "device", "disable", "BURNER-1")
    assert hub.query(category="task")[0]["action"] == "task:submit"

    # 2. config change with before/after comparison (前后对比)
    hub.change("eng1", "config", "edit", "config.yaml",
               before={"voltage": 3.3, "retries": 2},
               after={"voltage": 3.5, "retries": 2})
    hist = hub.changes_of("config.yaml")
    assert hist and hist[0]["diff"] == [
        {"field": "voltage", "old": 3.3, "new": 3.5}]
    assert diff_of(None, {"x": 1}) == [
        {"field": "x", "old": None, "new": 1}]

    # 3. stats + integrity
    st = hub.stats()
    assert st["total"] == 5 and st["changes"] == 1
    assert st["by_category"]["config"] == 1
    assert hub.verify()["ok"] is True

    # 4. tampered ledger detected
    hub.track("ghost", "security", "login:DENY", "ghost")
    with open(hub.audit.path, "a", encoding="utf-8") as fh:
        fh.write("TAMPERED\n")
    v = hub.verify()
    assert v["ok"] is False and v["malformed"] == 1
    assert hub.stats()["denied"] == 1

    # 5. ISO compliance report (CSV + JSON)
    out = tmp / "reports" / "iso_audit"
    summary = hub.compliance_report(out)
    assert summary["total_entries"] == 6
    assert summary["change_records"] == 1
    assert summary["denied_attempts"] == 1
    assert summary["integrity"] is False      # tampered above
    assert out.with_suffix(".csv").is_file()
    assert out.with_suffix(".json").is_file()

    # 6. CompliancePage GUI board (headless offscreen)
    from PySide6.QtWidgets import QApplication
    from mtkgui.gui.compliance_page import CompliancePage

    app = QApplication.instance() or QApplication([])
    page = CompliancePage(hub)
    page.interactive = False
    assert page.refresh() >= 5, "coverage table shows categories"
    page.path_edit.setText(str(tmp / "rep_gui"))
    summ = page.on_export()
    assert summ["total_entries"] >= 6
    assert "完整性" in page.stats_label.text()

    print("[P3-10 audit hub demo] full-chain audit + compliance OK — "
          "categorized trail, before/after change diffs, stats, "
          "integrity verification with tamper detection, ISO report "
          "CSV+JSON export, CompliancePage board all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
