# -*- coding: utf-8 -*-
"""P3-12 full-stack E2E integration demo (headless-safe, rc=0).

P1+P2+P3 whole-platform closed loop over PUBLIC contracts only:

  tenant (P3-1) -> resource hub (P3-3) -> service layer (P3-4)
  -> task queue (P3-5) -> cluster hub (P3-6) -> load balancer (P3-7)
  -> batch pipeline (P3-8) -> RBAC (P3-9) -> audit hub (P3-10)
  -> open API / MES (P3-11)

High-concurrency pressure: 3 tenants x parallel queue workers x
cluster scheduling.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mtkgui.engine.api_server import ApiServer, MesAdapter
from mtkgui.engine.audit_hub import AuditHub
from mtkgui.engine.auth_audit import AuditLog
from mtkgui.engine.batch_pipeline import BatchPipeline
from mtkgui.engine.cluster_hub import ClusterHub
from mtkgui.engine.cluster_scheduler import ClusterScheduler, Task
from mtkgui.engine.db_store import DbStore
from mtkgui.engine.load_balancer import LoadBalancer
from mtkgui.engine.project_context import ProjectContext, \
    TenantRegistry
from mtkgui.engine.results import StepStatus
from mtkgui.engine.rbac_hub import RbacHub, Role5
from mtkgui.engine.resource_hub import PathHub, ResourceManager
from mtkgui.engine.service_layer import LAYER, ServiceRegistry
from mtkgui.engine.task_queue import TaskQueue
from mtkgui.engine.metrics import TestRecord


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="p3_e2e_"))

    # ===== 1. multi-tenant kernel (P3-1) =====
    reg = TenantRegistry(base)
    for pid in ("PRJ-A", "PRJ-B", "PRJ-C"):
        reg.register(pid)
    reg.switch("PRJ-A")
    assert ProjectContext.current().project_id == "PRJ-A"

    # ===== 2. per-tenant isolation: path hub + resource + db =====
    path_a = PathHub(reg.get("PRJ-A"))
    res_a = ResourceManager()
    lock_a = res_a.acquire("device", "BURNER-1", "op1",
                           tenant="PRJ-A")
    db_a = DbStore(path_a.path("metrics") / "tenant.db",
                   project_id="PRJ-A")
    db_a.add_record(TestRecord(name="S1", status=StepStatus.PASS,
                               station="PRJ-A"))
    db_b = DbStore(
        PathHub(reg.get("PRJ-B")).path("metrics") / "tenant.db",
        project_id="PRJ-B")
    db_b.add_record(TestRecord(name="S2", status=StepStatus.FAIL,
                               station="PRJ-B"))
    assert [r.name for r in db_a.list_records()] == ["S1"]
    assert [r.name for r in db_b.list_records()] == ["S2"], \
        "tenant data isolated"
    assert res_a.owner_of("device", "BURNER-1") == "op1"
    res_a.release(lock_a)

    # ===== 3. service layer classification (P3-4) =====
    sr = ServiceRegistry()
    sr.wrap("taskq", TaskQueue(), LAYER.STORE)
    svc = sr.resolve("taskq", LAYER.CORE)   # CORE->STORE allowed
    assert svc is not None

    # ===== 4. persistent task queue under load (P3-5) =====
    tq = TaskQueue(journal_path=str(base / "_jq.json"))
    for i in range(30):
        tq.submit({"n": i}, priority=i % 3)
    tq.run(lambda task: True, workers=4)
    st = tq.stats()
    assert st["DONE"] == 30 and st["FAILED"] == 0
    # priority ordering: single-worker drain runs high priority first
    tq2 = TaskQueue()
    order: list[int] = []
    for i in range(6):
        tq2.submit({"n": i}, priority=i % 3)
    tq2.run(lambda task: (order.append(task.payload["n"]), True)[1],
            workers=1)
    assert order == [2, 5, 1, 4, 0, 3], "priority ordering honored"

    # ===== 5. cluster scheduling + hub + balancing (P3-6/7) =====
    hub = ClusterHub()
    hub.register_node("B1", "hostA", "burner")
    hub.register_node("B2", "hostB", "burner")
    sch = ClusterScheduler(log_fn=lambda line: None)
    for d in ("B1", "B2"):
        sch.register_device(d, "burner")
    for i in range(8):
        sch.submit(Task(f"E{i}", kind="burner"))
    t0 = time.monotonic()
    results = sch.run(lambda task, dev: time.sleep(0.01) or True)
    wall = time.monotonic() - t0
    assert all(results.values()) and len(results) == 8
    lb = LoadBalancer()
    hosts = lb.observe(hub, sch)
    assert set(hosts) == {"hostA", "hostB"}
    assert lb.accel_stats(sch, wall)["speedup"] > 0
    hub.set_enabled("B1", False, scheduler=sch)
    assert hub.node("B1").enabled is False
    hub.set_enabled("B1", True, scheduler=sch)

    # ===== 6. batch pipeline unattended (P3-8) =====
    bp = BatchPipeline()
    bp.create_batch("E2E-BATCH", [f"SN{i}" for i in range(10)])
    bp.execute("E2E-BATCH", [
        ("validate", lambda u: None),
        ("test", lambda u: u.unit_id != "SN4" or
            (_ for _ in ()).throw(RuntimeError("jam"))),
        ("report", lambda u: None),
    ])
    summ = bp.summarize("E2E-BATCH")
    assert summ["states"]["DONE"] == 9
    assert summ["stages"]["test"]["FAIL"] == 1

    # ===== 7. RBAC gate (P3-9) =====
    access_log = AuditLog(base / "audit.jsonl")
    rbac = RbacHub()
    assert rbac.can(Role5.ENGINEER, "case_edit")
    try:
        rbac.require(Role5.VIEWER, "account_manage")
        raise SystemExit("rbac gate failed")
    except PermissionError:
        pass

    # ===== 8. audit hub + compliance (P3-10) =====
    ah = AuditHub(access_log)
    ah.track("op1", "task", "submit", "E2E")
    ah.change("eng1", "config", "edit", "cfg.yaml",
              before={"v": 1}, after={"v": 2})
    assert ah.verify()["ok"] is True
    assert ah.compliance_report(base / "iso")["total_entries"] >= 2

    # ===== 9. open API + MES over the live queue (P3-11) =====
    srv = ApiServer(audit_log=access_log)
    mes = MesAdapter(enqueue=lambda body: tq.submit(body))
    srv.bind(status_fn=lambda: {"tenants": 3, "queue": tq.stats()},
             mes=mes)
    key = srv.issue_key("mes-line", scopes=("read", "write"))
    code, _ = srv.request(key, "GET", "/api/v1/status")
    assert code == 200
    code, body = srv.request(key, "POST", "/api/v1/mes/orders",
                             {"order_id": "WO-E2E",
                              "part_no": "MT6897", "quantity": 5})
    assert body["data"]["accepted"] is True
    assert tq.stats()["PENDING"] == 5
    tq.run(lambda task: True, workers=4)
    assert tq.stats()["DONE"] == 35
    assert mes.push_result("WO-E2E", {"yield": 1.0}) is True

    # ===== 10. high-concurrency pressure: 3 tenants in parallel ==
    def tenant_cycle(pid: str) -> str:
        reg.switch(pid)
        db = DbStore(PathHub(reg.get(pid)).path("metrics")
                     / "load.db", project_id=pid)
        for i in range(20):
            db.add_record(TestRecord(name=f"{pid}-{i}",
                                     status=StepStatus.PASS,
                                     station=pid))
        return pid

    with ThreadPoolExecutor(max_workers=3) as pool:
        done = list(pool.map(tenant_cycle, ["PRJ-A", "PRJ-B",
                                            "PRJ-C"]))
    assert sorted(done) == ["PRJ-A", "PRJ-B", "PRJ-C"]
    for pid in ("PRJ-A", "PRJ-B", "PRJ-C"):
        db = DbStore(PathHub(reg.get(pid)).path("metrics")
                     / "load.db", project_id=pid)
        assert len(db.list_records()) == 20, f"{pid} isolated load"

    print("[P3-12 E2E demo] whole-platform integration OK — tenant "
          "isolation, resource/db/service layers, queue priority "
          "under load, cluster scheduling + balancing, batch "
          "pipeline, RBAC gate, audit compliance report, open API "
          "+ MES loop, 3-tenant parallel pressure all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
