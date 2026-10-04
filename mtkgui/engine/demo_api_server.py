# -*- coding: utf-8 -*-
"""P3-11 open API & MES adapter demo (headless-safe, rc=0).

Closed loop: key issuance -> scope-enforced RESTful dispatch (status/
devices/tasks/reports/audit) -> audited calls -> MES inbound work
order (idempotent, one task per unit) -> outbound result with retry
buffer -> ApiPage GUI board.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mtkgui.engine.api_server import ApiServer, MesAdapter
from mtkgui.engine.auth_audit import AuditLog


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="api_demo_"))
    audit = AuditLog(tmp / "audit.jsonl")
    srv = ApiServer(audit_log=audit)

    # 1. platform providers bound (engines stay untouched)
    devices = [{"name": "B1", "kind": "burner", "active": 1}]
    queued: list[dict] = []
    srv.bind(devices=lambda: devices,
             report_fn=lambda: {"yield": 0.97, "units": 33},
             enqueue=lambda body: queued.append(body))

    # 2. key issuance + scope enforcement
    ro = srv.issue_key("readonly", scopes=("read",))
    rw = srv.issue_key("line1", scopes=("read", "write"))
    code, _ = srv.request(ro, "GET", "/api/v1/status")
    assert code == 200
    code, body = srv.request(ro, "POST", "/api/v1/tasks",
                             {"task_id": "X"})
    assert code == 403, "read-only key cannot write"
    code, body = srv.request("bad", "GET", "/api/v1/status")
    assert code == 401

    # 3. RESTful read endpoints
    code, body = srv.request(rw, "GET", "/api/v1/devices")
    assert code == 200 and body["data"]["devices"][0]["name"] == "B1"
    code, body = srv.request(rw, "GET", "/api/v1/reports/summary")
    assert body["data"]["yield"] == 0.97

    # 4. task enqueue via API
    code, body = srv.request(rw, "POST", "/api/v1/tasks",
                             {"task_id": "U1", "kind": "burner"})
    assert code == 200 and queued[0]["task_id"] == "U1"

    # 5. MES inbound: work order -> 3 units, idempotent
    mes = MesAdapter(enqueue=lambda body: queued.append(body))
    srv.bind(mes=mes)
    code, body = srv.request(rw, "POST", "/api/v1/mes/orders",
                             {"order_id": "WO-1", "part_no": "MT6897",
                              "quantity": 3})
    assert body["data"]["accepted"] and body["data"]["units"] == 3
    n_before = len(queued)
    code, body = srv.request(rw, "POST", "/api/v1/mes/orders",
                             {"order_id": "WO-1", "part_no": "MT6897",
                              "quantity": 3})
    assert body["data"]["duplicate"] is True
    assert len(queued) == n_before, "no double enqueue"

    # 6. MES outbound: retry buffer on endpoint failure
    fails = {"n": 0}

    def deliver(entry):
        if fails["n"] < 1:
            fails["n"] += 1
            raise OSError("MES down")
        return True

    mes2 = MesAdapter(enqueue=lambda b: None, deliver=deliver)
    assert mes2.push_result("WO-1", {"yield": 1.0}) is False
    assert mes2.pending_outbox() == 1
    assert mes2.retry_outbox() == 1
    assert mes2.pending_outbox() == 0

    # 7. all API calls audited (incl. denials)
    rows = audit.query(action="api:")
    assert any(e["detail"] == "401" for e in rows)
    assert any(e["detail"] == "OK" for e in rows)

    # 8. ApiPage GUI board (headless offscreen)
    from PySide6.QtWidgets import QApplication
    from mtkgui.gui.api_page import ApiPage

    app = QApplication.instance() or QApplication([])
    page = ApiPage(srv, mes)
    page.interactive = False
    page.kid_edit.setText("gui-key")
    issued = page.on_issue()
    assert issued and issued[0] == "gui-key"
    assert page.refresh() == 1
    page.path_edit.setText("/api/v1/status")
    code, _ = page.on_send()
    assert code == 200
    page.order_edit.setText("WO-9,MT6891,2")
    result = page.on_order()
    assert result["accepted"] is True and result["units"] == 2
    assert "接受" in page.mes_label.text()

    print("[P3-11 open API demo] RESTful + MES OK — key scopes, "
          "audited dispatch, device/task/report endpoints, MES "
          "idempotent inbound orders, outbound retry buffer, "
          "ApiPage board all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
