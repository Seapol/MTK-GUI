# -*- coding: utf-8 -*-
"""P2-12 stability & full-stack integration tests (no new features)."""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mtkgui.engine.auth_audit import AccessControl, AuditLog, Role
from mtkgui.engine.cluster_scheduler import ClusterScheduler, Task
from mtkgui.gui.shell import MainWindow

T0 = datetime(2026, 10, 4, 8, 0, 0)


def test_cluster_stress_3x12_isolated_and_balanced():
    """Parallel soak: 12 tasks on 3 devices, exclusive locks, no
    double-occupation, balanced completion, all locks released."""
    sch = ClusterScheduler(log_fn=lambda line: None)
    for n in ("D1", "D2", "D3"):
        sch.register_device(n, "burner")
    for i in range(12):
        sch.submit(Task(f"S{i}", kind="burner", weight=1 + i % 3))
    held: dict[str, str] = {}
    conflicts: list[str] = []
    guard = threading.Lock()

    def worker(task: Task, device: str) -> bool:
        with guard:
            if device in held:
                conflicts.append(f"{device}:{task.task_id}")
            held[device] = task.task_id
        time.sleep(0.01)
        with guard:
            del held[device]
        return True

    t_start = time.monotonic()
    results = sch.run(worker)
    elapsed = time.monotonic() - t_start
    assert len(results) == 12 and all(results.values())
    assert conflicts == [], "no lock double-occupation under load"
    counts = [d["completed"] for d in sch.devices()]
    assert counts == [4, 4, 4], counts            # balanced
    assert all(sch.device_state(n).value == "IDLE"
               for n in ("D1", "D2", "D3"))
    # parallel speedup sanity: 12x10ms on 3 devices must beat 120ms
    assert elapsed < 0.1, f"soak took {elapsed:.3f}s"


def test_cluster_failover_under_load():
    """Device dies mid-run; its queued tasks still all complete."""
    sch = ClusterScheduler(log_fn=lambda line: None)
    for n in ("A", "B", "C"):
        sch.register_device(n, "burner")
    for i in range(9):
        sch.submit(Task(f"F{i}", kind="burner"))
    done_on: dict[str, str] = {}
    lock = threading.Lock()

    def worker(task: Task, device: str) -> bool:
        time.sleep(0.01)
        if device == "B" and task.task_id == "F1":
            sch.report_fault("B", "mid-run failure")
            return False                       # task on dead device
        with lock:
            done_on[task.task_id] = device
        return True

    results = sch.run(worker)
    assert sum(results.values()) >= 8, "all recoverable tasks done"
    assert not any(d == "B" for d in done_on.values()), \
        "dead device never reused"
    counts = [d["completed"] for d in sch.devices() if d["name"] != "B"]
    assert sum(counts) >= 8, "migrated to survivors"


def test_shell_full_stack_routes_and_shared_stores(tmp_path,
                                                   monkeypatch):
    """Every P2 route mounts with its shared store; audit + accounts
    land in the redirected sandbox dirs (no CWD pollution)."""
    monkeypatch.setenv("MTKGUI_AUDIT_LOG",
                       str(tmp_path / "audit" / "audit.jsonl"))
    monkeypatch.setenv("MTKGUI_ACCOUNTS",
                       str(tmp_path / "audit" / "accounts.json"))
    monkeypatch.setenv("MTKGUI_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("MTKGUI_EXPORT_DIR",
                       str(tmp_path / "reports_export"))
    win = MainWindow()
    win.interactive = False
    win.mount_default_routes()
    assert win.route_keys == ["home", "workflow", "cases", "case_io",
                              "reports", "upload", "export",
                              "cluster", "resources", "queue",
                              "fleet", "balance", "pipeline", "rbac", "compliance", "audit",
                              "config"], \
        "all P2+P3 routes mounted"
    assert win.metrics_engine is not None
    assert win.upload_manager is not None
    assert win.cluster_scheduler is not None
    assert win.audit_log.path == tmp_path / "audit" / "audit.jsonl"
    assert win.access.accounts.get("admin", {}).get("role") == "ADMIN"
    # every page instantiates lazily without error
    for key in win.route_keys:
        win.navigate(key)
        assert win.stack.currentWidget() is not None, key


def test_audit_ledger_grows_across_shared_calls(tmp_path):
    audit = AuditLog(tmp_path / "a.jsonl", now=lambda: T0)
    access = AccessControl(tmp_path / "acc.json", audit=audit,
                           now=lambda: T0)
    access.ensure_default_accounts()
    admin = access.login("admin", "admin123")
    access.require(admin, "edit_case", "case PWR")
    n1 = len(audit.entries())
    access.require(admin, "edit_case", "case PWR_1V8")
    assert len(audit.entries()) == n1 + 1, "append-only ledger"
    rows = audit.query(action="edit_case:GRANT")
    assert len(rows) == 2 and rows[-1]["target"] == "case PWR_1V8"
