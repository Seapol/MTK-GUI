# -*- coding: utf-8 -*-
"""P3-11 open API server & MES adapter tests."""
from __future__ import annotations

import pytest

from mtkgui.engine.api_server import AS, ApiError, ApiServer, MA, \
    MesAdapter
from mtkgui.engine.auth_audit import AuditLog


def _server(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    return ApiServer(audit_log=audit), audit


def test_issue_key_and_scope_enforcement(tmp_path):
    srv, _ = _server(tmp_path)
    ro = srv.issue_key("ro", scopes=("read",))
    rw = srv.issue_key("rw", scopes=("read", "write"))
    assert ro.startswith("mtk-") and rw != ro
    code, _ = srv.request(ro, "GET", "/api/v1/status")
    assert code == 200
    code, body = srv.request(ro, "POST", "/api/v1/tasks",
                             {"task_id": "T1"})
    assert code == 403 and "write" in body["error"]
    code, _ = srv.request(rw, "GET", "/api/v1/status")
    assert code == 200
    code, body = srv.request("bogus-key", "GET", "/api/v1/status")
    assert code == 401
    srv.revoke_key("ro")
    code, body = srv.request(ro, "GET", "/api/v1/status")
    assert code == 403 and "disabled" in body["error"]


def test_route_dispatch_and_404(tmp_path):
    srv, _ = _server(tmp_path)
    key = srv.issue_key("k", scopes=("admin",))
    code, body = srv.request(key, "GET", "/api/v1/nope")
    assert code == 404
    code, body = srv.request(key, "GET", "/api/v1/status")
    assert code == 200 and body["ok"] is True
    assert body["data"]["platform"] == "mtk-gui"


def test_task_enqueue_via_api(tmp_path):
    srv, _ = _server(tmp_path)
    queued: list[dict] = []
    srv.bind(enqueue=lambda body: queued.append(body))
    key = srv.issue_key("line1", scopes=("write",))
    code, body = srv.request(key, "POST", "/api/v1/tasks",
                             {"task_id": "U1", "kind": "burner"})
    assert code == 200 and body["data"]["queued"] is True
    assert queued and queued[0]["task_id"] == "U1"
    code, body = srv.request(key, "POST", "/api/v1/tasks", {})
    assert code == 400, "task_id required"
    code, body = srv.request(key, "POST", "/api/v1/tasks",
                             {"kind": "burner"})
    assert code == 400


def test_device_and_report_endpoints(tmp_path):
    srv, _ = _server(tmp_path)
    srv.bind(devices=lambda: [{"name": "D1", "active": 1}],
             report_fn=lambda: {"yield": 0.98, "units": 50})
    key = srv.issue_key("k")
    code, body = srv.request(key, "GET", "/api/v1/devices")
    assert code == 200 and body["data"]["devices"][0]["name"] == "D1"
    code, body = srv.request(key, "GET", "/api/v1/reports/summary")
    assert code == 200 and body["data"]["yield"] == 0.98


def test_api_calls_audited(tmp_path):
    srv, audit = _server(tmp_path)
    key = srv.issue_key("k")
    srv.request(key, "GET", "/api/v1/status")
    srv.request("bad", "GET", "/api/v1/status")
    rows = audit.query(action="api:")
    assert any(e["detail"] == "OK" for e in rows)
    assert any(e["detail"] == "401" for e in rows)
    code, body = srv.request(key, "GET", "/api/v1/audit")
    assert code == 200
    assert len(body["data"]["api_calls"]) == 2


def test_mes_inbound_order_idempotent(tmp_path):
    srv, _ = _server(tmp_path)
    queued: list[dict] = []
    mes = MesAdapter(enqueue=lambda body: queued.append(body))
    srv.bind(mes=mes)
    key = srv.issue_key("mes", scopes=("write",))
    order = {"order_id": "WO-1", "part_no": "MT6897", "quantity": 3}
    code, body = srv.request(key, "POST", "/api/v1/mes/orders",
                             order)
    assert code == 200 and body["data"]["accepted"] is True
    assert body["data"]["units"] == 3
    assert len(queued) == 3
    assert queued[0]["source"] == "MES"
    assert queued[0]["order_id"] == "WO-1"
    # duplicate delivery -> idempotent, no double enqueue
    code, body = srv.request(key, "POST", "/api/v1/mes/orders",
                             order)
    assert body["data"]["duplicate"] is True
    assert len(queued) == 3
    # invalid order rejected
    code, body = srv.request(key, "POST", "/api/v1/mes/orders",
                             {"order_id": "WO-2", "quantity": -1})
    assert code == 200 and body["data"]["accepted"] is False


def test_mes_outbound_retry_buffer():
    delivered: list[dict] = []
    fail_first = {"n": 0}

    def deliver(entry):
        if fail_first["n"] < 1:
            fail_first["n"] += 1
            raise OSError("MES endpoint down")
        delivered.append(entry)
        return True

    mes = MesAdapter(enqueue=lambda b: None, deliver=deliver)
    assert mes.push_result("WO-1", {"yield": 1.0}) is False
    assert mes.pending_outbox() == 1
    assert mes.retry_outbox() == 1           # endpoint recovered
    assert delivered and delivered[0]["order_id"] == "WO-1"
    assert mes.pending_outbox() == 0


def test_aliases_and_internal_error_guard(tmp_path):
    assert AS is ApiServer and MA is MesAdapter
    srv, _ = _server(tmp_path)
    srv.route("GET", "/api/v1/boom", "read",
              lambda b: (_ for _ in ()).throw(RuntimeError("x")))
    key = srv.issue_key("k", scopes=("admin",))
    code, body = srv.request(key, "GET", "/api/v1/boom")
    assert code == 500 and "internal" in body["error"]
    with pytest.raises(ApiError):
        srv._auth("nope", "read")
