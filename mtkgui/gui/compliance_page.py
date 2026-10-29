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

from .dialog_sizing import wrap_page
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
        self.path_edit.setPlaceholderText("Report output path (no suffix)")
        self.export_btn = QPushButton("Export ISO compliance report", self)
        self.export_btn.clicked.connect(self.on_export)
        self.refresh_btn = QPushButton("Refresh", self)
        self.refresh_btn.clicked.connect(self.refresh)
        self.stats_label = QLabel("", self)
        for w in (self.path_edit, self.export_btn, self.refresh_btn,
                  self.stats_label):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Audit category", "Entries"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 2)
        # M34: scroll-protect the page on very small windows
        wrap_page(self)
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
            f"Total entries {st['total']} | denied {st['denied']} | "
            f"changes {st['changes']} | integrity "
            f"{'OK' if v['ok'] else 'BAD'}")
        return len(cats)

    # ----------------------------------------------------------- ops
    def on_export(self):
        path = self.path_edit.text().strip() or "compliance_report"
        summary = self.hub.compliance_report(path)
        self.refresh()
        if self.interactive:
            QMessageBox.information(
                self, "ISO compliance report",
                f"Exported {summary['total_entries']} entries "
                f"(denied {summary['denied_attempts']} / "
                f"changes {summary['change_records']})")
        return summary
