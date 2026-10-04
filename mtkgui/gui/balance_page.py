# -*- coding: utf-8 -*-
"""P3-7 cross-host load balance board (pure incremental).

Route key ``balance``: per-host aggregated load table (devices /
active / completed / failed / busy_s / offline / utilization),
cluster imbalance meter, cross-host MIGRATE plan, migration records,
parallel speedup stats.  Read-only over the frozen P2-10 scheduler
and the P3-6 hub; headless-safe via interactive.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QMessageBox,
                               QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout,
                               QWidget)

from mtkgui.engine.load_balancer import LoadBalancer

from .theme import StyleSpec


class BalancePage(QWidget):
    """Cross-host load balancing board (route ``balance``)."""

    def __init__(self, balancer: LoadBalancer, hub, scheduler=None,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.balancer = balancer
        self.hub = hub
        self.scheduler = scheduler
        self.interactive = True

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.task_edit = QLineEdit(self)
        self.task_edit.setPlaceholderText("任务ID")
        self.migrate_btn = QPushButton("记录跨机迁移", self)
        self.migrate_btn.clicked.connect(self.on_record)
        self.refresh_btn = QPushButton("刷新", self)
        self.refresh_btn.clicked.connect(self.refresh)
        self.imbalance_label = QLabel("", self)
        self.speed_label = QLabel("", self)
        for w in (self.task_edit, self.migrate_btn, self.refresh_btn,
                  self.imbalance_label, self.speed_label):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 8, self)
        self.table.setHorizontalHeaderLabels(
            ["主机", "设备数", "运行中", "已完成", "失败", "忙时(s)",
             "离线", "利用率"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 2)

        self.plan_list = QListWidget(self)
        root.addWidget(self.plan_list, 1)
        self.migration_list = QListWidget(self)
        root.addWidget(self.migration_list, 1)
        self.refresh()

    # ------------------------------------------------------------ view
    def refresh(self) -> int:
        self.balancer.observe(self.hub, self.scheduler)
        rows = self.balancer.hosts_view()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(("host", "devices", "active",
                                     "completed", "failed", "busy_s",
                                     "offline", "utilization")):
                self.table.setItem(r, c,
                                   QTableWidgetItem(str(row[key])))
        imb = self.balancer.imbalance()
        self.imbalance_label.setText(f"失衡度 {imb:.2f}")
        self.plan_list.clear()
        for mv in self.balancer.plan(self.hub, self.scheduler):
            self.plan_list.addItem(
                f"MIGRATE {mv['kind']} {mv['from']} -> {mv['to']} "
                f"({mv['reason']})")
        self.migration_list.clear()
        for m in self.balancer.migrations():
            self.migration_list.addItem(
                f"{m['task_id']}: {m['from']} -> {m['to']} "
                f"{m['reason']}".strip())
        return len(rows)

    def set_speedup(self, wall_s: float) -> None:
        if self.scheduler is None:
            return None
        st = self.balancer.accel_stats(self.scheduler, wall_s)
        self.speed_label.setText(
            f"加速比 {st['speedup']:.2f}x / 效率 {st['efficiency']:.2f}")

    # --------------------------------------------------------- record
    def on_record(self):
        tid = self.task_edit.text().strip()
        if not tid:
            if self.interactive:
                QMessageBox.warning(self, "迁移记录", "请先输入任务ID")
            return None
        rows = self.balancer.hosts_view()
        if len(rows) < 2:
            return None
        # record from the hottest to the coldest host
        hot = max(rows, key=lambda r: r["utilization"])["host"]
        cold = min(rows, key=lambda r: r["utilization"])["host"]
        self.balancer.record_migration(tid, hot, cold, "manual")
        self.refresh()
        if self.interactive:
            QMessageBox.information(self, "迁移记录", "成功")
        return (tid, hot, cold)
