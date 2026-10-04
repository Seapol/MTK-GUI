# -*- coding: utf-8 -*-
"""P2-10 cluster overview board (pure incremental).

Route key ``cluster`` — visualizes the :class:`ClusterScheduler`
snapshot (read-only; dispatch / failover actions drive the scheduler
API, zero P1 intrusion):

  * device board    — 设备 / 类型 / 状态 / 活跃任务 / 完成 / 失败 / 负载
  * task board      — queue + running progress, per-task status
  * actions         — 派发下一任务 / 提交演示任务 / 摘除选中设备
                      (tasks auto-migrate) / 恢复设备 / 刷新

Headless-safe via the usual ``interactive`` flag.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout,
                               QWidget)

from mtkgui.engine.cluster_scheduler import ClusterScheduler, Task

from .theme import StyleSpec


class ClusterPage(QWidget):
    """Device cluster overview (route ``cluster``)."""

    #: emitted after each dispatch sweep with the running-task count
    dispatched = Signal(int)

    def __init__(self, scheduler: ClusterScheduler,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.scheduler = scheduler
        self.interactive = True

        root = QVBoxLayout(self)
        self.status_label = QLabel("", self)
        root.addWidget(self.status_label)

        bar = QHBoxLayout()
        self.assign_btn = QPushButton("派发下一任务", self)
        self.assign_btn.clicked.connect(self.on_assign)
        self.remove_btn = QPushButton("摘除选中设备", self)
        self.remove_btn.clicked.connect(self.on_remove)
        self.restore_btn = QPushButton("恢复选中设备", self)
        self.restore_btn.clicked.connect(self.on_restore)
        self.refresh_btn = QPushButton("刷新看板", self)
        self.refresh_btn.clicked.connect(self.refresh)
        for w in (self.assign_btn, self.remove_btn, self.restore_btn,
                  self.refresh_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

        self.device_table = QTableWidget(0, 7, self)
        self.device_table.setHorizontalHeaderLabels(
            ["设备", "类型", "状态", "活跃", "完成", "失败", "负载"])
        root.addWidget(self.device_table, 1)

        self.task_table = QTableWidget(0, 4, self)
        self.task_table.setHorizontalHeaderLabels(
            ["任务", "类型", "状态", "设备"])
        root.addWidget(self.task_table, 1)

        self.refresh()

    # ------------------------------------------------------------ view
    def refresh(self) -> None:
        snap = self.scheduler.snapshot()
        devs = snap["devices"]
        self.device_table.setRowCount(len(devs))
        for r, d in enumerate(devs):
            name = d["name"]
            vals = [name, d["kind"], snap["states"].get(name, "-"),
                    str(d["active"]), str(d["completed"]),
                    str(d["failed"]), f"{d['busy_s']:.1f}s"]
            for c, v in enumerate(vals):
                self.device_table.setItem(r, c, QTableWidgetItem(v))
        tasks = snap["queue"] + snap["running"]
        self.task_table.setRowCount(len(tasks))
        for r, t in enumerate(tasks):
            vals = [t["task_id"], t.get("kind", "-"), t["status"],
                    t.get("device", "-") or "-"]
            for c, v in enumerate(vals):
                self.task_table.setItem(r, c, QTableWidgetItem(v))
        n_run = len(snap["running"])
        self.status_label.setText(
            f"集群设备 {len(devs)} 台 | 排队 {len(snap['queue'])} | "
            f"运行中 {n_run}")

    def _selected_device(self) -> str | None:
        row = self.device_table.currentRow()
        if row < 0:
            return None
        item = self.device_table.item(row, 0)
        return item.text() if item else None

    # ----------------------------------------------------------- slots
    def on_assign(self) -> None:
        nxt = self.scheduler.assign_next()
        self.refresh()
        self.dispatched.emit(len(self.scheduler.snapshot()["running"]))
        if nxt is not None and self.interactive:
            QMessageBox.information(
                self, "已派发",
                f"{nxt[0].task_id} -> {nxt[1]}")

    def on_remove(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        migrated = self.scheduler.report_fault(device, "operator")
        self.refresh()
        if self.interactive:
            QMessageBox.warning(
                self, "设备已摘除",
                f"{device} 故障摘除，迁移任务 {len(migrated)} 个")

    def on_restore(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        self.scheduler.restore_device(device)
        self.refresh()
