# -*- coding: utf-8 -*-
"""P3-10 compliance report board (pure incremental).

Route key ``compliance``: audit coverage stats (category counts /
denials / change records), integrity verdict, ISO report export
(CSV + JSON).  Headless-safe via interactive.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from mtkgui.engine.audit_hub import AuditHub

from .theme import StyleSpec


class CompliancePage(QWidget):
    """Audit & compliance middle-platform board (route
    ``compliance``)."""

    def __init__(self, hub: AuditHub,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.hub = hub
        self.interactive = True

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.path_edit = QLineEdit(self)
        self.path_edit.setPlaceholderText("报表输出路径 (无需后缀)")
        self.export_btn = QPushButton("导出ISO合规报表", self)
        self.export_btn.clicked.connect(self.on_export)
        self.refresh_btn = QPushButton("刷新", self)
        self.refresh_btn.clicked.connect(self.refresh)
        self.stats_label = QLabel("", self)
        for w in (self.path_edit, self.export_btn, self.refresh_btn,
                  self.stats_label):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["审计类别", "条目数"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 2)
        self.refresh()

    # ------------------------------------------------------------ view
    def refresh(self) -> int:
        st = self.hub.stats()
        v = self.hub.verify()
        cats = sorted(st["by_category"].items())
        self.table.setRowCount(len(cats))
        for r, (cat, n) in enumerate(cats):
            self.table.setItem(r, 0, QTableWidgetItem(cat))
            self.table.setItem(r, 1, QTableWidgetItem(str(n)))
        self.stats_label.setText(
            f"总条目 {st['total']} | 拒绝 {st['denied']} | "
            f"变更 {st['changes']} | 完整性 "
            f"{'OK' if v['ok'] else 'BAD'}")
        return len(cats)

    # ----------------------------------------------------------- ops
    def on_export(self):
        path = self.path_edit.text().strip() or "compliance_report"
        summary = self.hub.compliance_report(path)
        self.refresh()
        if self.interactive:
            QMessageBox.information(
                self, "ISO合规报表",
                f"已导出 {summary['total_entries']} 条 "
                f"(拒绝 {summary['denied_attempts']} / "
                f"变更 {summary['change_records']})")
        return summary
