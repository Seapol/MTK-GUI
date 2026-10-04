# -*- coding: utf-8 -*-
"""P2-1 global status bar (pure incremental).

Real-time display chips: engine state / device online count / test
progress / baseline version / session runtime.  Values are pushed in by
callers (shell or future engine bridges) — no engine imports here.
"""
from __future__ import annotations

import time

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .theme import StyleSpec


class StatusBarWidget(QWidget):
    """Bottom status strip: [STATE] [DEVICES] [PROGRESS] [BASELINE] [UPTIME]."""

    def __init__(self, baseline_version: str, spec: StyleSpec = StyleSpec(),
                 parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self._t0 = time.monotonic()

        self.state_label = QLabel("idle", self)
        self.devices_label = QLabel("devices online: 0", self)
        self.progress_label = QLabel("progress: --", self)
        self.baseline_label = QLabel(f"baseline: {baseline_version}", self)
        self.uptime_label = QLabel("uptime: 00:00:00", self)
        for w in (self.state_label, self.devices_label, self.progress_label,
                  self.baseline_label, self.uptime_label):
            w.setObjectName("StatusBarChip")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(18)
        layout.addWidget(self.state_label)
        layout.addWidget(self.devices_label)
        layout.addWidget(self.progress_label)
        layout.addStretch(1)
        layout.addWidget(self.baseline_label)
        layout.addWidget(self.uptime_label)

    # public API -------------------------------------------------------
    def set_engine_state(self, state: str) -> None:
        self.state_label.setText(f"engine: {state}")

    def set_devices_online(self, count: int) -> None:
        self.devices_label.setText(f"devices online: {count}")

    def set_progress(self, done: int, total: int) -> None:
        pct = (done * 100 // total) if total > 0 else 0
        self.progress_label.setText(f"progress: {done}/{total} ({pct}%)")

    def tick(self) -> None:
        el = int(time.monotonic() - self._t0)
        self.uptime_label.setText(
            f"uptime: {el // 3600:02d}:{el % 3600 // 60:02d}:{el % 60:02d}")
