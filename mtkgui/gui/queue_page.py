# -*- coding: utf-8 -*-
"""P3-5 task queue monitor page (pure incremental).

Route key ``queue``: live board of the TaskQueue (tid / priority /
status / attempts / payload), submit box (priority + retries), stats
bar, refresh + TTL-less drain helpers.  Headless-safe via interactive.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from mtkgui.engine.task_queue import TaskQueue

from .theme import StyleSpec


class QueuePage(QWidget):
    """Visualized queue state (route ``queue``)."""

    def __init__(self, queue: TaskQueue,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.queue = queue
        self.interactive = True

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.payload_edit = QLineEdit(self)
        self.payload_edit.setPlaceholderText("Task payload (any text)")
        self.prio_spin = QSpinBox(self)
        self.prio_spin.setRange(-9, 9)
        self.prio_spin.setValue(0)
        self.retry_spin = QSpinBox(self)
        self.retry_spin.setRange(0, 9)
        self.retry_spin.setValue(2)
        self.submit_btn = QPushButton("Enqueue", self)
        self.submit_btn.clicked.connect(self.on_submit)
        self.refresh_btn = QPushButton("Refresh", self)
        self.refresh_btn.clicked.connect(self.refresh)
        self.stats_label = QLabel("", self)
        for w in (self.payload_edit, QLabel("Priority", self),
                  self.prio_spin, QLabel("Retries", self),
                  self.retry_spin, self.submit_btn,
                  self.refresh_btn, self.stats_label):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["Task ID", "Priority", "State", "Attempts", "Payload"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self.refresh()

    # ---------------------------------------------------------- actions
    def on_submit(self) -> object:
        text = self.payload_edit.text().strip()
        if not text:
            return None
        task = self.queue.submit(text,
                                 priority=self.prio_spin.value(),
                                 max_retries=self.retry_spin.value())
        self.refresh()
        return task

    def refresh(self) -> dict:
        rows = self.queue.snapshot()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(("tid", "priority", "status",
                                     "attempts", "payload")):
                self.table.setItem(r, c,
                                   QTableWidgetItem(str(row[key])))
        stats = self.queue.stats()
        self.stats_label.setText(
            f"Total {stats['total']} | pending {stats['PENDING']} | "
            f"running {stats['RUNNING']} | done {stats['DONE']} | "
            f"failed {stats['FAILED']}")
        return stats
