# -*- coding: utf-8 -*-
"""User direction: every new run clears the last power-rails capture -
the waveform is blank until the DAQ AI step captures and redraws."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = TestWorkFlowPage()
    yield w
    w.deleteLater()


def test_clear_results_resets_rail_capture(page):
    """clear_results (cycle reset at every Run) drops the previous
    capture: samples / plot cache / CSV path / AI review are cleared
    and the waveform widget receives empty data."""
    # simulate a stored capture from the previous run (rail set first:
    # the filter only shows ticked rails)
    page.set_rails([("DCDC_1V0", "#facc15", 1.8, 0.0)])
    cache = [("DCDC_1V0", "#facc15", 1.8, [0.0, 1.8, 1.8])]
    page._store_rail_capture([0.0, 1.0], [0.0, 1.8], cache,
                             "/tmp/rails.csv", "Good")
    assert page._rail_plot_cache == cache
    assert page.rail_widget.data == cache
    # a new run begins -> the capture must be gone
    page.clear_results()
    assert page.rail_samples is None
    assert page.rail_volts is None
    assert page._rail_plot_cache == []
    assert page.rail_csv_path is None
    assert page._ai_review_text is None
    assert page.rail_widget.data == []
