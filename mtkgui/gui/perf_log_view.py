# -*- coding: utf-8 -*-
"""M125: the in-app performance timing log window.

The probe in :mod:`mtkgui.startup_timing` always keeps its last lines in
memory, so ``Tools > Show Performance Timing Log`` can show them live -
no restart, no hunting for the file.  The window is non-modal: it stays
open beside the GUI while the operator reproduces a slow or frozen
action, and the STALL lines land in it as they happen.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog,
                               QDialogButtonBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

#: lines kept on screen (the probe ring holds more)
_VIEW_LINES = 600
#: how often the window picks up new lines (ms)
_REFRESH_MS = 250
#: substrings that make a line "interesting" for the freeze hunt
_INTERESTING = ("[STALL", "[SLOW", "[EXCEPTION")


class PerfLogDialog(QDialog):
    """Live view of the performance timing log (M125)."""

    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        from mtkgui import startup_timing as st
        self._st = st
        self.setWindowTitle("Performance Timing Log")
        from mtkgui.gui.dialog_sizing import fit_dialog
        fit_dialog(self, 900, 620)
        # a log window is read-only - a size grip is enough, no need to
        # fight the layout with a maximize on a text view
        self._last_count = -1

        root = QVBoxLayout(self)
        head = QLabel()
        head.setWordWrap(True)
        head.setProperty("tone", "muted")
        root.addWidget(head)
        self.head = head

        row = QHBoxLayout()
        self.lbl_file = QLabel()
        self.lbl_file.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.lbl_file, 1)
        self.btn_open_file = QPushButton("Open log file")
        self.btn_open_file.setToolTip(
            "Open this session's log in the system editor")
        self.btn_open_file.clicked.connect(self._open_file)
        row.addWidget(self.btn_open_file)
        self.btn_open_dir = QPushButton("Open log folder")
        self.btn_open_dir.clicked.connect(self._open_folder)
        row.addWidget(self.btn_open_dir)
        root.addLayout(row)

        self.chk_stalls = QCheckBox("Only stalls / slow / exceptions")
        self.chk_stalls.setToolTip(
            "Hide the ordinary lines and keep [STALL] / [SLOW] / "
            "[EXCEPTION] - the freeze hunt")
        self.chk_stalls.toggled.connect(lambda _v: self._refresh(force=True))
        root.addWidget(self.chk_stalls)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = self.view.font()
        font.setFamily("Courier New")
        font.setStyleHint(font.StyleHint.Monospace)
        self.view.setFont(font)
        root.addWidget(self.view, 1)

        foot = QHBoxLayout()
        self.chk_record = QCheckBox("Recording (applies now)")
        self.chk_record.setToolTip(
            "Switch the probe on / off for THIS session; the setting is "
            "also saved for the next start")
        self.chk_record.toggled.connect(self._on_record_toggled)
        foot.addWidget(self.chk_record)
        foot.addStretch(1)
        self.btn_clear = QPushButton("Clear view")
        self.btn_clear.clicked.connect(self.view.clear)
        foot.addWidget(self.btn_clear)
        self.btn_copy = QPushButton("Copy all")
        self.btn_copy.clicked.connect(self._copy_all)
        foot.addWidget(self.btn_copy)
        root.addLayout(foot)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._sync_head()
        self._refresh(force=True)

    # ------------------------------------------------------------ helpers
    def _sync_head(self) -> None:
        st = self._st
        state = "ON" if st.is_enabled() else "OFF"
        file_path = st.log_file_path()
        try:
            limit = st.stall_threshold()
        except Exception:                                   # pragma: no cover
            limit = 0.4
        self.head.setText(
            f"Recording: {state}  |  a freeze is logged when the 100 ms "
            f"heartbeat is late by more than {limit:.2f} s  |  "
            f"last {_VIEW_LINES} lines, newest at the bottom")
        self.lbl_file.setText(
            f"Log file: {file_path}" if file_path is not None
            else "Log file: not available (memory view only)")
        self.lbl_file.setToolTip(str(file_path or ""))
        self.chk_record.blockSignals(True)
        self.chk_record.setChecked(bool(st.is_enabled()))
        self.chk_record.blockSignals(False)

    def _refresh(self, force: bool = False) -> None:
        st = self._st
        count = st.recent_count()
        if not force and count == self._last_count:
            return
        self._last_count = count
        lines = st.recent_lines(_VIEW_LINES)
        if self.chk_stalls.isChecked():
            lines = [ln for ln in lines
                     if any(tag in ln for tag in _INTERESTING)]
        at_bottom = self.view.verticalScrollBar().value() >= \
            self.view.verticalScrollBar().maximum() - 4
        self.view.setPlainText("".join(lines))
        if at_bottom:
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())
        self._sync_head()

    def _on_record_toggled(self, checked: bool) -> None:
        st = self._st
        st.set_runtime_enabled(bool(checked))
        try:
            st.save_enabled(bool(checked))
        except Exception:                                   # pragma: no cover
            pass
        self._last_count = -1
        self._refresh(force=True)

    def _copy_all(self) -> None:
        QApplication.clipboard().setText(self.view.toPlainText())
        self.btn_copy.setText("Copied")
        QTimer.singleShot(1200, lambda: self.btn_copy.setText("Copy all"))

    def _open_file(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = self._st.log_file_path()
        if path is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = self._st.log_file_path()
        if path is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def show_log(parent=None) -> PerfLogDialog:
    """Open (or raise) the single timing-log window."""
    dlg = PerfLogDialog._instance
    if dlg is not None:
        try:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            dlg._sync_head()
            dlg._refresh(force=True)
            return dlg
        except RuntimeError:                    # wrapped C++ object deleted
            PerfLogDialog._instance = None
    dlg = PerfLogDialog(parent)
    PerfLogDialog._instance = dlg
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    dlg.show()
    return dlg
