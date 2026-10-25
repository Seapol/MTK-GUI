# -*- coding: utf-8 -*-
"""Foreground progress feedback for slow GUI actions (M10-FIX3).

The slow design actions (Parse Nets for ICT, Load current yaml, the
Test Plan sync / export) stay SYNCHRONOUS because they mutate the GUI
models and widgets directly; this module only drives a modal
:class:`QProgressDialog` on top of them and pumps the event loop after
each stage, so the window repaints instead of freezing.

The dialog is shown only after ``SHOW_DELAY_S`` seconds, so a fast run
never flashes a window.  There is deliberately no cancel button: the
actions are short and not safely interruptible, and a button that
cannot stop the work would mislead the operator.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QProgressDialog,
    QWidget,
)

#: seconds a run may take before the dialog is actually shown
SHOW_DELAY_S = 0.3


class ProgressDialog(QProgressDialog):
    """Delayed, modal, input-blocking progress dialog.

    ``set_stage`` is the slot the panels connect their
    ``task_progress`` signal to; it stores the latest value / label and
    only pushes them into the widget once the delayed show triggered.
    """

    def __init__(self, owner: QWidget | None, title: str = "Working…",
                 minimum: int = 0, maximum: int = 100,
                 delay: float = SHOW_DELAY_S) -> None:
        super().__init__(title, None, minimum, maximum, owner)
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle(title)
        # no cancel button: the operation cannot be interrupted safely
        self.setCancelButton(None)
        self.setAutoClose(False)
        self.setAutoReset(False)
        self._started = time.monotonic()
        self._delay = max(0.0, float(delay))
        self._value = minimum
        self._label = title
        self._shown = False

    # ------------------------------------------------------------ timing
    def show_delayed(self) -> bool:
        """Show the dialog only once the run passed the delay.

        Returns True when the dialog is (now) visible."""
        if self._shown:
            return True
        if time.monotonic() - self._started < self._delay:
            return False
        self.force_show()
        return True

    def force_show(self) -> None:
        """Show the dialog unconditionally (M17 delivery guarantee:
        any operation lasting past the delay MUST show the bar)."""
        if self._shown:
            return
        self._shown = True
        # push the buffered stage BEFORE showing: with minimumDuration
        # at 0 Qt would otherwise pop the empty dialog on the first
        # setValue
        super().setValue(self._value)
        super().setLabelText(self._label)
        super().setMinimumDuration(0)
        super().show()
        QApplication.processEvents()

    # ------------------------------------------------------------ stages
    def set_stage(self, value: int, label: str) -> None:
        """Record a stage and repaint (the task_progress signal slot)."""
        self._value = int(value)
        self._label = str(label)
        if self._shown:
            super().setValue(self._value)
            super().setLabelText(self._label)
        else:
            self.show_delayed()
        QApplication.processEvents()

    def close_done(self) -> None:
        """Hide and dispose - safe to call on every exit path."""
        self._shown = False
        self.reset()
        self.hide()
        self.deleteLater()
        QApplication.processEvents()


@contextmanager
def busy_progress(owner: QWidget | None, title: str,
                  delay: float = SHOW_DELAY_S):
    """Indeterminate delayed progress around a synchronous action.

    Yields a ``stage(value, label)`` callback for optional coarse
    stages; the finally block always hides the dialog, so a failure
    can never leave a window stranded.  M17: a one-shot timer
    force-shows the dialog once the run passed the delay, so a task
    that emits no stages still gets a foreground bar (user direction:
    any operation lasting > 300 ms must show one)."""
    dlg = ProgressDialog(owner, title, 0, 0, delay=delay)
    dlg.show_delayed()
    show_timer = QTimer(dlg)
    show_timer.setSingleShot(True)
    show_timer.timeout.connect(dlg.force_show)
    show_timer.start(int(delay * 1000))
    try:
        yield dlg.set_stage
    finally:
        show_timer.stop()
        dlg.close_done()


def guarded_run(owner: QWidget | None, button, title: str, fn) -> object:
    """Run ``fn(stage)`` under the busy dialog with the trigger button
    disabled.

    The button is restored to its PREVIOUS enabled state on success and
    on every failure / exception; an exception surfaces as a critical
    message (never crashes the window) and yields None."""
    was_enabled = button.isEnabled() if button is not None else True
    if button is not None:
        button.setEnabled(False)
    try:
        with busy_progress(owner, title) as stage:
            return fn(stage)
    except Exception as exc:                     # noqa: BLE001
        QMessageBox.critical(
            owner, title, str(exc) or exc.__class__.__name__)
        return None
    finally:
        if button is not None:
            button.setEnabled(was_enabled)


class ProgressBridge(QObject):
    """Route a ``task_progress`` signal stream to a FOREGROUND modal
    dialog instead of the status bar (M15, user direction 2026-10-25:
    "front progress bar, no status-bar progress bar, no frozen main
    window").

    Pages connect their ``task_progress`` signal to
    ``bridge.stage``; the bridge owns one delayed, application-modal
    :class:`ProgressDialog` for the duration of a task:

    * ``percent <= 0`` starts a new task (closes any stale dialog);
    * ``percent >= 100`` ends it (dialog closed immediately);
    * a task that emits stages but no terminal event self-closes
      after :attr:`STALE_S` of silence, so an exception path can
      never leave a modal dialog stranded.

    Every stage pumps the event loop, so the main window repaints
    instead of freezing during the synchronous page actions.
    """

    #: seconds without any stage before a still-open dialog self-closes
    STALE_S = 30.0

    def __init__(self, owner: QWidget | None, title: str = "Working…",
                 delay: float = SHOW_DELAY_S) -> None:
        super().__init__(owner)
        self._title = str(title)
        self._delay = max(0.0, float(delay))
        self._dlg: ProgressDialog | None = None
        self._timer: QTimer | None = None
        self._show_timer: QTimer | None = None

    # ------------------------------------------------------------ slot
    def stage(self, percent: int, label: str) -> None:
        """Drive the modal dialog from one progress event."""
        value = int(percent)
        text = str(label) or self._title
        if value <= 0:
            self._close()
            self._ensure_dlg()
            self._arm_show_timer()
            self._dlg.set_stage(0, text)
        elif value >= 100:
            if self._dlg is not None:
                self._dlg.set_stage(100, text)
            self._close()
        else:
            self._ensure_dlg()
            self._arm_show_timer()
            self._dlg.set_stage(value, text)

    # ---------------------------------------------------------- helpers
    def _ensure_dlg(self) -> None:
        if self._dlg is not None:
            self._arm_timer()
            return
        self._dlg = ProgressDialog(self.parent(), self._title,
                                   0, 100, delay=self._delay)
        self._arm_timer()

    def _arm_show_timer(self) -> None:
        """Arm the one-shot force-show (M17): a task that emits no
        further stages (e.g. the threaded SPF extraction) still gets
        the foreground bar once the delay elapsed."""
        if self._show_timer is None:
            self._show_timer = QTimer(self)
            self._show_timer.setSingleShot(True)
            self._show_timer.timeout.connect(self._show_now)
        self._show_timer.start(int(self._delay * 1000))

    def _show_now(self) -> None:
        self._show_timer = None      # one-shot (already fired)
        if self._dlg is not None:
            self._dlg.force_show()

    def _arm_timer(self) -> None:
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._close)
        self._timer.start(int(self.STALE_S * 1000))

    def _close(self) -> None:
        if self._show_timer is not None:
            self._show_timer.stop()
            self._show_timer = None
        if self._timer is not None:
            self._timer.stop()
        if self._dlg is not None:
            self._dlg.close_done()
            self._dlg = None
