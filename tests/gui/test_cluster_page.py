# -*- coding: utf-8 -*-
"""P2-10 cluster page tests (headless offscreen)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mtkgui.engine.cluster_scheduler import ClusterScheduler, Task
from mtkgui.gui.cluster_page import ClusterPage
from mtkgui.gui.shell import MainWindow


@pytest.fixture()
def page():
    app = QApplication.instance() or QApplication([])
    sch = ClusterScheduler(log_fn=lambda line: None)
    sch.register_device("B1", "burner")
    sch.register_device("B2", "burner")
    sch.submit(Task("T1", kind="burner"))
    p = ClusterPage(sch)
    p.interactive = False
    return p


def test_device_board_rows(page):
    page.refresh()
    assert page.device_table.rowCount() == 2
    assert page.device_table.item(0, 0).text() == "B1"
    assert page.device_table.item(0, 2).text() == "IDLE"
    assert page.task_table.rowCount() == 1, "queued task visible"
    assert page.task_table.item(0, 2).text() == "QUEUED"


def test_assign_updates_board_and_signal(page):
    fired = []
    page.dispatched.connect(fired.append)
    page.on_assign()
    assert page.task_table.item(0, 2).text() == "RUNNING"
    assert page.task_table.item(0, 3).text() in ("B1", "B2")
    assert fired and fired[-1] == 1, "one running task"
    assert "运行中 1" in page.status_label.text()


def test_remove_selected_device_migrates(page):
    page.on_assign()
    # select the occupied device row and remove it
    for r in range(page.device_table.rowCount()):
        if page.device_table.item(r, 2).text() == "OCCUPIED":
            page.device_table.selectRow(r)
            break
    page.on_remove()
    snap = page.scheduler.snapshot()
    assert snap["queue"] and snap["queue"][0]["task_id"] == "T1"


def test_restore_selected_device(page):
    page.on_assign()
    occupied = next(d["name"] for d in page.scheduler.snapshot()
                    ["devices"] if d["active"])
    for r in range(page.device_table.rowCount()):
        if page.device_table.item(r, 0).text() == occupied:
            page.device_table.selectRow(r)
            break
    page.on_remove()
    page.on_restore()
    assert page.scheduler.device_state(occupied).value == "IDLE"


def test_shell_registers_cluster_route(qapp):
    win = MainWindow()
    win.interactive = False
    win.mount_default_routes()
    assert isinstance(win.cluster_scheduler, ClusterScheduler)
    win.navigate("cluster")
    assert isinstance(win.stack.currentWidget(), ClusterPage)
