# -*- coding: utf-8 -*-
"""M10-FIX3 F6: foreground progress dialog regression tests.

Covers the shared helper contract (modal, delayed show, always-hide
on exception, button restore) and the Parse Nets button wiring
(task_progress -> dialog; button re-enabled on every exit path)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QMessageBox,
    QProgressDialog,
    QPushButton,
)

from mtkgui.gui.progress_dialog import (  # noqa: E402
    ProgressDialog,
    busy_progress,
    guarded_run,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _visible_progress_dialogs():
    return [w for w in QApplication.topLevelWidgets()
            if isinstance(w, QProgressDialog) and w.isVisible()]


# ------------------------------------------------------------- dialog
def test_dialog_is_modal_without_cancel(qapp):
    dlg = ProgressDialog(None, "Working…", 0, 100, delay=0)
    assert dlg.isModal()
    assert dlg.windowModality() == Qt.WindowModality.ApplicationModal
    # setCancelButton(None): no push button lives in the dialog
    assert dlg.findChildren(QPushButton) == []
    assert dlg.windowTitle() == "Working…"
    dlg.deleteLater()


def test_delayed_show_skips_fast_run(qapp):
    """A stage before the delay must NOT pop a window."""
    dlg = ProgressDialog(None, "Fast", 0, 100, delay=10.0)
    dlg.set_stage(50, "parse nets: parsing")
    assert not dlg.isVisible()
    assert dlg.labelText() == "Fast"   # buffered, never pushed yet
    dlg.close_done()


def test_show_after_delay_tracks_stage(qapp):
    dlg = ProgressDialog(None, "Slow", 0, 100, delay=0.0)
    dlg.set_stage(55, "parse nets: classifying nets")
    assert dlg.isVisible()
    assert dlg.value() == 55
    assert dlg.labelText() == "parse nets: classifying nets"
    dlg.close_done()
    assert not dlg.isVisible()


def test_busy_context_always_hides_on_exception(qapp):
    with pytest.raises(RuntimeError):
        with busy_progress(None, "Boom", delay=0.0) as stage:
            stage(10, "working")
            assert _visible_progress_dialogs()
            raise RuntimeError("boom")
    assert _visible_progress_dialogs() == []


# --------------------------------------------------------- guarded_run
def test_guarded_run_re_enables_button_on_success(qapp):
    btn = QPushButton("run")

    def work(stage):
        stage(100, "done")
        return "value"

    assert guarded_run(None, btn, "Task", work) == "value"
    assert btn.isEnabled()


def test_guarded_run_re_enables_button_and_surfaces_error(
        qapp, monkeypatch):
    btn = QPushButton("run")
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a) or 0)

    def boom(stage):
        stage(10, "working")
        raise RuntimeError("write failed")

    assert guarded_run(None, btn, "Task", boom) is None
    assert btn.isEnabled()
    assert shown and "write failed" in str(shown[0][2])


# --------------------------------------------------- Parse Nets wiring
def test_task_progress_reaches_connected_dialog(qapp):
    from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel
    panel = ParseNetsPanel()
    dlg = ProgressDialog(panel, "Parse Nets for ICT", 0, 100, delay=0)
    panel.task_progress.connect(dlg.set_stage)
    panel.task_progress.emit(85, "parse nets: scoring path risk")
    assert dlg.value() == 85
    assert dlg.labelText() == "parse nets: scoring path risk"
    panel.task_progress.disconnect(dlg.set_stage)
    dlg.close_done()
    panel.deleteLater()


def test_parse_button_re_enabled_after_missing_net(qapp, monkeypatch):
    """Forced failure path: no NET file -> warning, no stuck button."""
    from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel
    panel = ParseNetsPanel()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a) or 0)
    panel._on_parse_clicked()
    assert warnings
    assert panel.btn_parse.isEnabled()
    panel.deleteLater()


def test_parse_button_stages_reach_dialog(qapp, monkeypatch):
    """The button path feeds task_progress into its own determinate
    dialog and re-enables the button after a successful stub run."""
    from mtkgui.gui.yamlbuild import parse_nets as pn

    stages = []
    made = []

    class Recording(pn.ProgressDialog):
        def __init__(self, *args, **kwargs):
            kwargs["delay"] = 0.0
            super().__init__(*args, **kwargs)
            made.append(self)

        def set_stage(self, value, label):
            stages.append((value, label))
            super().set_stage(value, label)

    monkeypatch.setattr(pn, "ProgressDialog", Recording)
    panel = pn.ParseNetsPanel()

    def stub_parse():
        panel.task_progress.emit(0, "parse nets: reading raw data")
        panel.task_progress.emit(55, "parse nets: classifying nets")
        panel.task_progress.emit(100, "parse nets: done")

    panel.parse_nets = stub_parse
    panel._on_parse_clicked()

    assert [v for v, _l in stages] == [0, 55, 100]
    assert made and not made[0].isVisible()
    assert panel.btn_parse.isEnabled()
    panel.deleteLater()
