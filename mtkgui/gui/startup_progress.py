# -*- coding: utf-8 -*-
"""Startup progress window (M14 F4).

After the login dialog closes the MainWindow construction used to run
for tens of seconds on Windows with no visible feedback.  This small
frameless, always-on-top widget shows "MTK-GUI - Loading…" plus a
progress bar and the current construction stage while ``MainWindow`` is
built.

It is purely visual: no modality, no input grab, no business logic.  It
receives stages from :func:`mtkgui.startup_timing.mark` through the
progress handler hook.
"""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import (QApplication, QLabel, QProgressBar,
                               QVBoxLayout, QWidget)

#: stage name (as passed to startup_timing.mark) -> bar percentage.
#: M14 F1 applies the theme BEFORE the UI is built, so "theme applied"
#: is an early stage now and carries a low value.
_STAGE_PERCENT = {
    "ui: theme applied": 10,
    "twf: init start": 15,
    "twf: header groups built": 25,
    "twf: fct + console built": 35,
    "twf: page layout done": 45,
    "ui: TestWorkFlowPage built": 50,
    "ui: EquipmentPage built": 60,
    "ui: YamlBuildPage built": 70,
    "ui: _build_ui done": 80,
    "ui: _build_menus done": 90,
    "ui: permissions applied": 100,
}

#: stage name -> text shown under the bar.
_STAGE_TEXT = {
    "ui: theme applied": "Applying the GUI theme…",
    "twf: init start": "Building Test Work Flow page…",
    "twf: header groups built": "Building the project header…",
    "twf: fct + console built": "Building FCT table and console…",
    "twf: page layout done": "Laying out the Test Work Flow page…",
    "ui: TestWorkFlowPage built": "Test Work Flow page ready",
    "ui: EquipmentPage built": "Building the Equipment page…",
    "ui: YamlBuildPage built": "Building the Yaml Build page…",
    "ui: _build_ui done": "Building menus…",
    "ui: _build_menus done": "Applying permissions…",
    "ui: permissions applied": "Ready",
}

_LOGIN_PREFIX = "login done"


class StartupProgress(QWidget):
    """Frameless "Loading…" window shown during MainWindow construction."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool)
        # visible feedback only: never activate or steal focus
        self.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(420, 130)
        self._value = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        title = QLabel("MTK-GUI - Loading…")
        title.setObjectName("strong")
        title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        layout.addWidget(self.bar)

        self.stage_label = QLabel("Starting…")
        self.stage_label.setObjectName("muted")
        layout.addWidget(self.stage_label)
        layout.addStretch(1)

        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.x() + (geo.width() - self.width()) // 2,
                      geo.y() + (geo.height() - self.height()) // 2)

    def handle_stage(self, stage: str, _elapsed_s: float = 0.0) -> None:
        """Advance the bar / stage text for one startup stage.

        Unknown stages advance by a small step and clamp at 95 %; the
        value never regresses.  A paint pass is forced so the window
        stays responsive while MainWindow is still being built (the
        event loop is not running yet).
        """
        percent = _STAGE_PERCENT.get(stage)
        text = _STAGE_TEXT.get(stage)
        if percent is None and stage.startswith(_LOGIN_PREFIX):
            percent = 5
            text = "Sign-in complete"
        if percent is None:
            percent = min(95, self._value + 5)
        if text is None:
            text = stage.split(":", 1)[-1].strip() or stage
        self._value = max(self._value, percent)
        self.bar.setValue(self._value)
        self.stage_label.setText(text)
        QApplication.processEvents(
            QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
