# -*- coding: utf-8 -*-
"""P3-6 fleet monitor page (pure incremental).

Route key ``fleet``: cluster node board (id/host/kind/status/load/
enabled), transition ledger, remote ops (heartbeat / enable /
disable), alert log.  Headless-safe via interactive.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QMessageBox,
                               QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout,
                               QWidget)

from mtkgui.engine.cluster_hub import ClusterHub

from .theme import StyleSpec


class FleetPage(QWidget):
    """Cluster device middle-platform board (route ``fleet``)."""

    #: emitted on every alert with the detail line
    fleet_alert = Signal(str)

    def __init__(self, hub: ClusterHub, scheduler=None,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.hub = hub
        self.scheduler = scheduler
        self.interactive = True
        hub.on_alert(lambda node, detail: self.fleet_alert.emit(
            f"{node.device_id if node else '?'}: {detail}"))
        self._alerts: list[str] = []

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.beat_edit = QLineEdit(self)
        self.beat_edit.setPlaceholderText("设备ID")
        self.beat_btn = QPushButton("心跳", self)
        self.beat_btn.clicked.connect(self.on_heartbeat)
        self.enable_btn = QPushButton("启用", self)
        self.enable_btn.clicked.connect(lambda: self.on_toggle(True))
        self.disable_btn = QPushButton("禁用", self)
        self.disable_btn.clicked.connect(
            lambda: self.on_toggle(False))
        self.refresh_btn = QPushButton("刷新", self)
        self.refresh_btn.clicked.connect(self.refresh)
        self.stats_label = QLabel("", self)
        for w in (self.beat_edit, self.beat_btn, self.enable_btn,
                  self.disable_btn, self.refresh_btn,
                  self.stats_label):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["设备", "主机", "类型", "状态", "负载", "启用"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 2)

        self.alert_list = QListWidget(self)
        root.addWidget(self.alert_list, 1)
        self.fleet_alert.connect(self._on_alert)
        self.refresh()

    # ------------------------------------------------------------ view
    def refresh(self) -> int:
        self.hub.monitor()
        if self.scheduler is not None:
            self.hub.attach_scheduler(self.scheduler)
        rows = self.hub.snapshot()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(("device_id", "host", "kind",
                                     "status", "load", "enabled")):
                self.table.setItem(r, c,
                                   QTableWidgetItem(str(row[key])))
        online = sum(1 for x in rows if x["status"] == "ONLINE")
        self.stats_label.setText(f"节点 {len(rows)} | 在线 {online}")
        return len(rows)

    def _on_alert(self, line: str) -> None:
        self._alerts.append(line)
        self.alert_list.addItem(line)

    # ----------------------------------------------------------- remote
    def on_heartbeat(self):
        did = self.beat_edit.text().strip()
        if not did:
            return None
        self.hub.heartbeat(did)
        self.refresh()
        return did

    def on_toggle(self, enabled: bool):
        did = self.beat_edit.text().strip()
        if not did:
            if self.interactive:
                QMessageBox.warning(self, "远程管控", "请先输入设备ID")
            return None
        ok = self.hub.set_enabled(did, enabled,
                                  scheduler=self.scheduler)
        self.refresh()
        if self.interactive:
            QMessageBox.information(
                self, "远程管控",
                "成功" if ok else "未知设备")
        return ok
