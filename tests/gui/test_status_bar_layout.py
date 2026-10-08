# -*- coding: utf-8 -*-
"""M0 status-bar layout tests: Station ID removed, LED-only console
indicators, progress-bar idle/running/complete behavior, version
label intact (mock, offscreen)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QProgressBar  # noqa: E402

from mtkgui.main_window import (  # noqa: E402
    SerialStatusBar,
    StatusLed,
    MainWindow,
)
from mtkgui.permissions import ROLE_SUPERVISOR  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp, monkeypatch):
    monkeypatch.setattr(
        "mtkgui.gui_version.load_gui_version",
        lambda path=None: ("v4.1.1.1287", None))
    w = MainWindow(role=ROLE_SUPERVISOR)
    yield w
    w.close()
    w.deleteLater()


# -------------------------------------------------------- Station ID gone
def test_station_id_removed(window):
    assert not hasattr(window, "status_station")
    labels = window.statusBar().findChildren(QLabel)
    assert not any("Station ID" in l.text() for l in labels)


# ------------------------------------------------- console lights LED-only
def test_console_indicators_led_only(qapp):
    bar = SerialStatusBar()
    bar.sync_channels({"DUT": {"connected": True},
                       "AUX": {"connected": False}})
    children = bar.findChildren(QLabel)
    # the 'Console:' caption + one StatusLed per channel - no other
    # text labels beside the lights
    captions = [w for w in children if not isinstance(w, StatusLed)]
    leds = [w for w in children if isinstance(w, StatusLed)]
    assert len(captions) == 1 and captions[0].text() == "Console:"
    assert len(leds) == 2
    # channel names live on the tooltips
    assert "DUT" in leds[0].toolTip()
    # a resync (channel set change) keeps the caption
    bar.sync_channels({"DUT": {"connected": False}})
    captions = [w for w in bar.findChildren(QLabel)
                if not isinstance(w, StatusLed)]
    assert [c.text() for c in captions] == ["Console:"]
    bar.deleteLater()


# ------------------------------------------------------------ progress bar
def test_progress_idle_gray_empty(window):
    p: QProgressBar = window.status_progress
    assert p.value() == 0 and p.minimum() == 0 and p.maximum() == 1
    assert p.format() == "Idle"


def test_progress_running_updates_percent(window):
    p = window.status_progress
    window._update_run_progress(5, 10)
    assert p.value() == 5 and p.maximum() == 10
    assert "50%" in p.format()
    window._update_run_progress(9, 10)
    assert p.value() == 9 and "90%" in p.format()


def test_progress_complete_fills_then_auto_resets(window):
    p = window.status_progress
    window._finish_run_progress()
    assert p.value() == 100 and p.maximum() == 100
    assert "100%" in p.format()
    assert window._progress_reset_pending is True
    window._reset_run_progress()
    assert window._progress_reset_pending is False
    assert p.value() == 0 and p.format() == "Idle"


def test_running_run_cancels_pending_reset(window):
    """A new run starting inside the reset grace window is never
    clobbered by the stale auto-reset."""
    p = window.status_progress
    window._finish_run_progress()
    assert window._progress_reset_pending
    window._update_run_progress(3, 10)     # new run -> cancels reset
    assert not window._progress_reset_pending
    window._reset_run_progress()           # stale reset: ignored
    assert p.value() == 3                  # running position kept


# ----------------------------------------------------- preserved widgets
def test_version_label_and_neighbors_intact(window):
    assert window.status_version.text() == "GUI version: v4.1.1.1287"
    for attr in ("status_role", "status_mode", "status_user",
                 "instr_status", "status_date"):
        assert getattr(window, attr) is not None, attr


def test_no_widget_overlap_in_status_bar(window):
    """Sanity: every status-bar child got a geometry inside the bar
    after a layout pass (no overflow / overlap crash)."""
    window.resize(900, 700)
    window.show()
    QApplication.processEvents()
    bar = window.statusBar()
    for w in bar.findChildren(QProgressBar) + bar.findChildren(QLabel):
        assert w.width() >= 0 and w.height() >= 0
    window.hide()
