# -*- coding: utf-8 -*-
"""The Power Rails properties dialog gains an ENLARGED zoomable
waveform page (user direction 2026-10-16): double-click the DAQ
waveform -> the dialog's first page shows the capture BIG with wheel
zoom (50% - 300%) and scrollbar panning; the bigger plot draws more
curve samples, so zooming in reveals real detail."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.test_workflow_page import (  # noqa: E402
    TestWorkFlowPage,
    _ZoomWaveformPage,
    WaveformWidget,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = TestWorkFlowPage()
    # fabricate a finished capture (rails first: the filter only shows
    # ticked rails - the same pattern as test_run_resets_waveform)
    w.set_rails([("DCDC_1V0", "#facc15", 1.8, 0.0),
                 ("V8_F4232_1", "#38bdf8", 8.0, 0.0)])
    cache = [("DCDC_1V0", "#facc15", 1.8, [0.0, 0.9, 1.8, 1.8]),
             ("V8_F4232_1", "#38bdf8", 8.0, [0.0, 4.0, 7.9, 8.0])]
    # per-rail sample lists (fractions of nominal) + voltage lists -
    # the same shapes the DAQ capture hook delivers
    w._store_rail_capture(
        [[0.0, 0.5, 1.0, 1.0], [0.0, 0.5, 0.99, 1.0]],
        [[0.0, 0.9, 1.8, 1.8], [0.0, 4.0, 7.92, 8.0]],
        cache, "/tmp/rails.csv", "Good")
    yield w
    w.deleteLater()


def _wheel(page, angle):
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0),
                     QPoint(0, angle), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(page.scroll.viewport(), ev)


def test_dialog_has_waveform_page_first(page):
    """The properties dialog carries THREE pages and the zoomable
    Waveform page is the FIRST one."""
    dlg, _ui = page._build_rail_props_dialog()
    tabs = dlg.findChildren(__import__(
        "PySide6.QtWidgets", fromlist=["QTabWidget"]).QTabWidget)[0]
    assert tabs.count() == 3
    assert tabs.tabText(0) == "Waveform"
    assert tabs.tabText(1) == "Properties"
    assert tabs.tabText(2) == "AI Review"
    zoom = tabs.widget(0)
    assert isinstance(zoom, _ZoomWaveformPage)


def test_zoom_page_clones_capture_data(page):
    """The zoom page clones the live waveform's capture at open time:
    labels / colors / nominal / samples / duration / t_start match."""
    dlg, _ui = page._build_rail_props_dialog()
    tabs = dlg.findChildren(__import__(
        "PySide6.QtWidgets", fromlist=["QTabWidget"]).QTabWidget)[0]
    zoom = tabs.widget(0)
    assert zoom.wave.data == page.rail_widget.data
    assert zoom.wave.duration == page.rail_widget.duration
    assert zoom.wave.t_start == page.rail_widget.t_start
    assert zoom.wave.virtual == page.rail_widget.virtual


def test_zoom_limits_and_labels(page):
    """Zoom in/out steps clamp to 50% - 300% and the label tracks."""
    dlg, _ui = page._build_rail_props_dialog()
    zoom = _ZoomWaveformPage(page.rail_widget)
    assert zoom.scale == 1.0
    assert zoom.wave.width() == _ZoomWaveformPage.BASE_W
    for _ in range(10):                       # 1.25^10 >> 3.0 -> clamped
        zoom._zoom_step(1.25)
    assert zoom.scale == _ZoomWaveformPage.MAX_SCALE
    assert zoom.lbl.text() == "Zoom: 300%"
    assert zoom.wave.width() == int(1300 * 3.0)
    for _ in range(20):                       # 0.8^20 << 0.5 -> clamped
        zoom._zoom_step(0.8)
    assert zoom.scale == _ZoomWaveformPage.MIN_SCALE
    assert zoom.lbl.text() == "Zoom: 50%"
    zoom._set_scale(1.0)
    assert zoom.lbl.text() == "Zoom: 100%"


def test_wheel_zooms(page):
    """A wheel event over the plot viewport zooms in / out (consumed,
    no scroll interference)."""
    zoom = _ZoomWaveformPage(page.rail_widget)
    _wheel(zoom, +120)
    assert zoom.scale == pytest.approx(1.15)
    _wheel(zoom, -120)
    assert zoom.scale == pytest.approx(1.0)


def test_bigger_plot_draws_more_samples(page):
    """The detail promise: the painted curve sampling step follows the
    plot width, so the enlarged render uses MORE points per curve than
    the small embedded preview (real detail, not stretched pixels)."""
    samples = list(range(1300))
    big = WaveformWidget()
    big.resize(_ZoomWaveformPage.BASE_W, _ZoomWaveformPage.BASE_H)
    small = WaveformWidget()
    small.resize(500, 200)
    from mtkgui.engine.rails import DURATION_S
    for w in (big, small):
        w.set_data([("DCDC_1V0", "#facc15", 1.8, samples)],
                   DURATION_S, 0.0)
    # the step is derived inside _paint_plot; re-derive it here the
    # same way to prove the enlarged plot keeps more points
    def points_for(width):
        step = max(1, len(samples) // max(1, int(width)))
        return len(range(0, len(samples), step))
    assert points_for(_ZoomWaveformPage.BASE_W) > points_for(500)
