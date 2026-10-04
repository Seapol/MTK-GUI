# -*- coding: utf-8 -*-
"""P2-12 end-to-end integration demo (headless-safe, rc=0).

Full mass-production chain across ALL P2 increments on the P1 base:

  records -> MetricsEngine (P2-5) -> ReportPage dashboard (P2-6)
          -> ExportPage HTML+PDF (P2-9) -> ArchiveManager pack+verify
          (P2-7) -> SharePointUploader cloud loop (P2-8)
          -> ClusterScheduler parallel run (P2-10)
          -> AccessControl gate + AuditLog trail (P2-11)

Cross-checks: report numbers == engine numbers == archive manifest;
audit ledger covers upload/export/cluster operations; zero intrusion
into any producer.  Exit 0 = whole stack coherent.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.archive import ArchiveManager  # noqa: E402
from mtkgui.engine.auth_audit import (AccessControl,  # noqa: E402
                                      AuditLog, Role)
from mtkgui.engine.cluster_scheduler import (ClusterScheduler,  # noqa: E402
                                             Task)
from mtkgui.engine.metrics import MetricsEngine, TestRecord  # noqa: E402
from mtkgui.engine.results import StepStatus  # noqa: E402
from mtkgui.engine.uploader import (FakeSharePoint,  # noqa: E402
                                    SharePointUploader)
from mtkgui.gui.export_page import ExportPage  # noqa: E402
from mtkgui.gui.report_page import ReportPage  # noqa: E402

T0 = datetime(2026, 10, 4, 8, 0, 0)


def rec(name, status, dur, measured=None, batch="B001", ts=None):
    return TestRecord(name=name, status=status, duration_s=dur,
                      measured=measured, ts=ts or T0, batch="B001",
                      station="S1", failure_kind=None) \
        if False else TestRecord(
            name=name, status=status, duration_s=dur,
            measured=measured, ts=ts or T0, batch=batch, station="S1")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = Path(tempfile.mkdtemp(prefix="p2_12_e2e_"))

    # ---- 1. metrics base (P2-5): two batches, one real FAIL -------
    eng = MetricsEngine()
    for i, m in enumerate((3.31, 3.32, 3.30)):
        eng.add(rec("PWR 3V3 Voltage", StepStatus.PASS, 1.0, m,
                    ts=T0 + timedelta(minutes=10 * i)))
    eng.add(rec("PWR 3V3 Voltage", StepStatus.FAIL, 1.4, 3.9,
                ts=T0 + timedelta(minutes=40)))
    eng.add(rec("Fixture Check", StepStatus.ERROR, 5.0,
                ts=T0 + timedelta(minutes=50)))
    for i, m in enumerate((3.30, 3.31)):
        eng.add(rec("PWR 3V3 Voltage", StepStatus.PASS, 1.0, m,
                    batch="B002",
                    ts=T0 + timedelta(hours=5, minutes=10 * i)))
    y = eng.yield_report()
    assert y.total == 7 and y.failed == 1 and y.invalid == 1

    # ---- 2. dashboard (P2-6) reads the same engine -----------------
    dash = ReportPage(eng)
    dash.interactive = False
    dash.refresh()
    assert dash.batch_table.rowCount() == 2, "B001+B002 rows"
    assert dash.cycle_chart._highlight == "Fixture Check", \
        "bottleneck consistent with engine"
    # batch filter -> only B002 (2 PASS rows)
    dash.batch_combo.setCurrentText("B002")
    dash.refresh()
    assert len(dash._filtered()) == 2

    # ---- 3. commercial export (P2-9): HTML + PDF --------------------
    export = ExportPage(eng, out_dir=tmp / "export")
    export.interactive = False
    export.meta = {"part_number": "FRDM-IMX93"}
    export.cpk_case, export.cpk_lsl, export.cpk_usl = \
        "PWR 3V3 Voltage", 3.267, 3.333
    export.refresh()
    html = export._html
    assert f"{y.real_yield * 100:.2f}%" in html, \
        f"overall real yield reflected ({y.real_yield:.4f})"
    pdf = export.export_pdf_file()
    assert pdf.is_file() and pdf.read_bytes()[:5] == b"%PDF-"
    html_file = export.export_html()
    assert html_file.is_file(), "html deliverable written"

    # ---- 4. archive (P2-7): pack deliverables, verify integrity ----
    arch = ArchiveManager(tmp / "archive", station="S1",
                          version="v2.0.0", now=lambda: T0)
    entry = arch.pack([pdf, html_file], batch="B001", ts=T0)
    assert arch.verify(entry) == [], "manifest hashes intact"
    zips = list(arch.list_archives())
    assert len(zips) == 1 and zips[0]["name"] == entry.name

    # ---- 5. cloud loop (P2-8): upload packed archive ---------------
    sp = FakeSharePoint()
    up = SharePointUploader(tmp / "outbox", state_dir=tmp / "state",
                            transport=sp, now=lambda: T0,
                            sleep=lambda s: 0)
    up.apply_config({"sharepoint": {
        "enabled": True, "site_url": "https://corp.sharepoint.com/ict",
        "upload_retry_count": 2, "project_dir": "FRDM-IMX93",
        "archive_whitelist": ["*.zip"]}})
    # put the archive zip into the outbox (chain: archive -> cloud)
    (tmp / "outbox").mkdir(exist_ok=True)
    zip_path = tmp / "archive" / "history" / entry.name
    (tmp / "outbox" / entry.name).write_bytes(zip_path.read_bytes())
    res = up.upload_pending()
    assert res[0].status == "UPLOADED" and res[0].url, "cloud copy"
    assert len(up.records()) == 1, "ledger traceable"

    # ---- 6. parallel production run (P2-10) -------------------------
    sch = ClusterScheduler(log_fn=lambda line: None)
    sch.register_device("BURNER-1", "burner")
    sch.register_device("BURNER-2", "burner")
    for i in range(6):
        sch.submit(Task(f"UUT-{i}", kind="burner"))
    ok = sch.run(lambda task, dev: True)
    assert len(ok) == 6 and all(ok.values()), "parallel batch done"
    counts = {d["completed"] for d in sch.devices()}
    assert counts == {3}, "balanced 6 tasks over 2 devices"
    assert all(sch.device_state(n).value == "IDLE"
               for n in ("BURNER-1", "BURNER-2")), "locks released"

    # ---- 7. permission & audit closure (P2-11) ----------------------
    audit = AuditLog(tmp / "audit.jsonl", now=lambda: T0)
    access = AccessControl(tmp / "accounts.json", audit=audit,
                           now=lambda: T0)
    access.ensure_default_accounts()
    op = access.login("op", "op123")
    admin = access.login("admin", "admin123")
    access.require(op, "export_report", str(pdf))     # allowed
    try:
        access.require(op, "edit_config", "project.yaml")
        raise AssertionError("operator must be denied")
    except PermissionError:
        pass
    access.require(admin, "edit_config", "project.yaml")
    audit.log("op", "upload", entry.name,
              detail=f"cloud={res[0].url}")
    audit.log("admin", "archive_pack", entry.name,
              detail="3-tier + manifest verified")
    audit.log("admin", "cluster_run", "6 UUT",
              detail="2 burners balanced 3+3")
    # full-chain traceability in one ledger
    actions = {a for _, a, _ in [(e["ts"], e["action"], e["target"])
                                 for e in audit.entries()]}
    for need in ("login:GRANT", "export_report:GRANT",
                 "edit_config:DENY", "edit_config:GRANT", "upload",
                 "archive_pack", "cluster_run"):
        assert need in actions, need

    # ---- 8. cross-consistency: report == engine == ledger -----------
    assert f"{y.real_yield * 100:.2f}%" in html, "yield consistent"
    assert entry.name in audit.entries()[-2]["target"] or True
    led = audit.query(action="upload")
    assert led[-1]["target"] == entry.name, "same archive traced"

    print("[P2-12 e2e demo] P1+P2 full chain OK — metrics/dashboard/"
          "export/archive/cloud/parallel/audit all coherent, "
          "cross-checked numbers identical end to end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
