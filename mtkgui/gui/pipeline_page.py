# -*- coding: utf-8 -*-
"""P3-8 batch pipeline board (pure incremental).

Route key ``pipeline``: batch create box, unit table (SN / state /
stages / error), stats bar (yield), monitor output.  Headless-safe
via interactive.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from mtkgui.engine.batch_pipeline import BatchPipeline

from .theme import StyleSpec


class PipelinePage(QWidget):
    """Batch pipeline middle-platform board (route ``pipeline``)."""

    def __init__(self, pipeline: BatchPipeline,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.pipeline = pipeline
        self.interactive = True
        self._batch_id = ""

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.batch_edit = QLineEdit(self)
        self.batch_edit.setPlaceholderText("批次ID")
        self.units_edit = QLineEdit(self)
        self.units_edit.setPlaceholderText("SN1,SN2,SN3")
        self.create_btn = QPushButton("批量初始化", self)
        self.create_btn.clicked.connect(self.on_create)
        self.monitor_btn = QPushButton("监控", self)
        self.monitor_btn.clicked.connect(self.on_monitor)
        self.stats_label = QLabel("", self)
        for w in (self.batch_edit, self.units_edit, self.create_btn,
                  self.monitor_btn, self.stats_label):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            ["SN", "状态", "阶段", "错误"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 2)

    # ------------------------------------------------------------ view
    def refresh(self) -> int:
        if not self._batch_id:
            return 0
        rows = self.pipeline.snapshot(self._batch_id)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            stages = ", ".join(f"{k}:{v}"
                               for k, v in row["stages"].items())
            for c, val in enumerate((row["unit_id"], row["state"],
                                     stages, row["error"])):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))
        summ = self.pipeline.summarize(self._batch_id)
        self.stats_label.setText(
            f"批次 {self._batch_id} | 单元 {summ['units']} | "
            f"良率 {summ['yield']:.1%}")
        return len(rows)

    # ----------------------------------------------------------- ops
    def on_create(self):
        bid = self.batch_edit.text().strip()
        units = [u.strip() for u in
                 self.units_edit.text().split(",") if u.strip()]
        if not bid or not units:
            if self.interactive:
                QMessageBox.warning(self, "批量初始化",
                                    "请输入批次ID与SN列表")
            return None
        self.pipeline.create_batch(bid, units)
        self._batch_id = bid
        self.refresh()
        return bid

    def on_monitor(self):
        if not self._batch_id:
            return None
        mon = self.pipeline.monitor(self._batch_id)
        self.refresh()
        if self.interactive:
            QMessageBox.information(
                self, "流水线监控",
                "健康" if mon["healthy"] else
                f"异常: {len(mon['failed'])} 个单元失败")
        return mon
