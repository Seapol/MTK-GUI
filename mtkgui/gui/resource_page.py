# -*- coding: utf-8 -*-
"""P3-3 resource & path monitor page (pure incremental).

Route key ``resources``: live snapshot of the global ResourceManager
(held exclusive resources: type/name/owner/tenant/token/age) plus the
tenant PathHub canonical directories.  Buttons: refresh, release
selected (token-checked), TTL sweep.  Headless-safe via interactive.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from mtkgui.engine.resource_hub import (PathHub, ResourceManager,
                                        ResourceBusy)

from .theme import StyleSpec


class ResourcePage(QWidget):
    """Global resource & path monitor (route ``resources``)."""

    def __init__(self, manager: ResourceManager,
                 hub: PathHub | None = None,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.manager = manager
        self.hub = hub or PathHub()
        self.interactive = True

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新", self)
        self.refresh_btn.clicked.connect(self.refresh)
        self.sweep_btn = QPushButton("TTL 清理", self)
        self.sweep_btn.clicked.connect(self.on_sweep)
        self.release_btn = QPushButton("释放选中", self)
        self.release_btn.clicked.connect(self.on_release)
        self.status_label = QLabel("", self)
        for w in (self.refresh_btn, self.sweep_btn,
                  self.release_btn, self.status_label):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["类型", "资源", "持有者", "租户", "持有时长s"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 2)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["路径中台", "位置"])
        root.addWidget(self.tree, 1)
        self.refresh()

    # ------------------------------------------------------------ view
    def refresh(self) -> int:
        rows = self.manager.snapshot()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate((row["type"], row["name"],
                                   row["owner"], row["tenant"],
                                   row["age_s"])):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))
        self.tree.clear()
        for cat, loc in self.hub.snapshot().items():
            QTreeWidgetItem(self.tree, [cat, loc])
        self.status_label.setText(f"持锁 {len(rows)} 项")
        return len(rows)

    # ---------------------------------------------------------- action
    def on_sweep(self) -> int:
        n = self.manager.sweep()
        self.refresh()
        if self.interactive:
            QMessageBox.information(self, "TTL 清理",
                                    f"自动释放 {n} 项过期锁")
        return n

    def on_release(self):
        r = self.table.currentRow()
        if r < 0:
            if self.interactive:
                QMessageBox.warning(self, "释放", "请先选择资源行")
            return None
        rtype = self.table.item(r, 0).text()
        name = self.table.item(r, 1).text()
        try:
            lock = next(lk for lk in self.manager.locks_view()
                        if lk.rtype == rtype and lk.name == name)
        except StopIteration:
            return None
        ok = self.manager.release(lock)
        self.refresh()
        if self.interactive:
            QMessageBox.information(
                self, "释放", "已释放" if ok else "token 不匹配")
        return ok
