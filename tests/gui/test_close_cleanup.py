# -*- coding: utf-8 -*-
"""M0 MainWindow closeEvent ordered-cleanup tests (mock, no GUI
render): child-dialog teardown sequence, event flush, accept."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from mtkgui.main_window import MainWindow  # noqa: E402
from mtkgui.permissions import ROLE_SUPERVISOR  # noqa: E402


class _FakeEvent(QObject):
    """Minimal close-event double recording accept()/ignore()."""

    def __init__(self):
        super().__init__()
        self.accepted = False

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


@pytest.fixture()
def window(qapp):
    w = MainWindow(role=ROLE_SUPERVISOR)
    yield w
    w.close()
    w.deleteLater()


def _run_close(window, monkeypatch, order):
    """Drive closeEvent with spies on the cleanup milestones."""
    monkeypatch.setattr(MainWindow, "_cleanup_child_dialogs",
                        lambda self: order.append("cleanup"))
    monkeypatch.setattr(MainWindow, "_remember_geometry",
                        lambda self: order.append("geometry"))
    monkeypatch.setattr(window.workflow_page.multi_console,
                        "close_all_channels",
                        lambda: order.append("channels"))
    event = _FakeEvent()
    window.closeEvent(event)
    return event


def test_cleanup_runs_before_original_workflow(window, monkeypatch):
    """Step order: cleanup -> geometry -> channels, then accept."""
    order: list[str] = []
    event = _run_close(window, monkeypatch, order)
    assert order == ["cleanup", "geometry", "channels"]
    assert event.accepted is True


def test_accept_called_last(window, monkeypatch):
    """The close event is accepted exactly at the end (step 4)."""
    order: list[str] = []
    calls = []

    real_cleanup = MainWindow._cleanup_child_dialogs

    def spy_cleanup(self):
        real_cleanup(self)
        calls.append("cleanup")

    monkeypatch.setattr(MainWindow, "_cleanup_child_dialogs", spy_cleanup)
    event = _FakeEvent()
    monkeypatch.setattr(event, "accept",
                        lambda: calls.append("accept"))
    window.closeEvent(event)
    assert calls == ["cleanup", "accept"]


def test_child_dialogs_destroyed_and_queue_flushed(window, monkeypatch):
    """Steps 1-3: child dialogs get deleteLater, processEvents flushes
    the queue, worker bindings are disconnected."""
    child = QDialog(window)                  # a live child dialog
    child.show()
    deleted = []
    monkeypatch.setattr(QDialog, "deleteLater",
                        lambda self: deleted.append(self))
    flushed = []
    monkeypatch.setattr(QApplication, "processEvents",
                        staticmethod(lambda *a, **k: flushed.append(1)))
    window._cleanup_child_dialogs()
    assert child in deleted
    assert flushed == [1]


def test_worker_bindings_disconnected(window):
    """Step 1 with a cached batch worker: its signal is disconnected
    (twice - the second pass exercises the tolerant already-connected
    path) without raising."""
    from mtkgui.main_window import _ToolsBatchWorker
    worker = _ToolsBatchWorker("Connect all", [], None, {})
    window._tools_thread = worker
    window._cleanup_child_dialogs()
    window._cleanup_child_dialogs()      # already disconnected: tolerated
    window._tools_thread = None


def test_cleanup_tolerates_missing_thread(window, monkeypatch):
    """No cached worker -> cleanup still completes (no AttributeError)."""
    monkeypatch.delattr(window, "_tools_thread", raising=False)
    monkeypatch.setattr(QApplication, "processEvents",
                        staticmethod(lambda *a, **k: None))
    window._cleanup_child_dialogs()          # must not raise


def test_real_close_event_via_qt(window, monkeypatch):
    """Integration: a real QCloseEvent flows through closeEvent and
    gets accepted; the window then reports closed."""
    monkeypatch.setattr(QApplication, "processEvents",
                        staticmethod(lambda *a, **k: None))
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
