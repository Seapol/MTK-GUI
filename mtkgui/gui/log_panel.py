# -*- coding: utf-8 -*-
"""P2-1 global log panel (pure incremental).

Real-time scrolling log view with level coloring, level filter and
keyword filter.  Emits nothing back to the engine — pure sink, so zero
coupling with P1 core links.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLineEdit, QPushButton,
                               QTextEdit, QVBoxLayout, QWidget)

from .theme import StyleSpec

MAX_LINES = 5000


class LogPanelWidget(QWidget):
    """Bottom log area: live append + level filter + keyword filter."""

    def __init__(self, spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self._entries: list[tuple[str, str, str]] = []  # (ts, level, msg)

        self.view = QTextEdit(self)
        self.view.setReadOnly(True)

        self.level_combo = QComboBox(self)
        self.level_combo.addItems(["ALL", *spec.LOG_LEVELS])

        self.keyword_edit = QLineEdit(self)
        self.keyword_edit.setPlaceholderText("keyword filter...")

        self.clear_btn = QPushButton("Clear", self)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self.level_combo)
        bar.addWidget(self.keyword_edit, 1)
        bar.addWidget(self.clear_btn)

        bar_host = QWidget(self)
        bar_host.setLayout(bar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(bar_host)
        layout.addWidget(self.view, 1)

        self.level_combo.currentTextChanged.connect(lambda _t: self._rerender())
        self.keyword_edit.textChanged.connect(lambda _t: self._rerender())
        self.clear_btn.clicked.connect(self.clear)

    # public API -------------------------------------------------------
    def append(self, level: str, message: str) -> None:
        level = level.upper()
        if level not in self._spec.LOG_LEVELS:
            level = "INFO"
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._entries.append((ts, level, message))
        if self._visible(level, message):
            self._render_line(ts, level, message)

    def clear(self) -> None:
        self.view.clear()

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def visible_count(self) -> int:
        return len(self.view.toPlainText().splitlines())

    # internals --------------------------------------------------------
    def _visible(self, level: str, message: str) -> bool:
        picked = self.level_combo.currentText()
        if picked != "ALL" and level != picked:
            return False
        kw = self.keyword_edit.text()
        return (not kw) or (kw.lower() in message.lower())

    def _render_line(self, ts: str, level: str, message: str) -> None:
        color = {"DEBUG": self._spec.TEXT_DIM, "INFO": self._spec.TEXT_MAIN,
                 "WARN": self._spec.WARN, "ERROR": self._spec.ERROR}[level]
        self.view.setTextColor(QColor(color))
        self.view.append(f"[{ts}] [{level:<5}] {message}")
        self.view.moveCursor(QTextCursor.MoveOperation.End)

    def _rerender(self) -> None:
        self.view.clear()
        for ts, level, msg in self._entries:
            if self._visible(level, msg):
                self._render_line(ts, level, msg)
