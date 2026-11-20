# -*- coding: utf-8 -*-
"""v2-15 F: FCT panel editor — drop common Retries/Timeout, wire BT_Tone."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mtkgui.gui.yamlbuild.FCTTestConfigWidget import _ToneRangeSlider
from mtkgui.gui.yamlbuild.fct_sequence_v2_panel import BuildFctSequencePanel


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_panel_editor_drops_common_retries_and_timeout(qapp):
    panel = BuildFctSequencePanel()
    assert not hasattr(panel, "edit_retries")
    assert not hasattr(panel, "edit_timeout")
    panel.deleteLater()


def test_tone_slider_set_total_resets_segment(qapp):
    slider = _ToneRangeSlider(6.0)
    slider.set_values(1.0, 4.0)
    slider.set_total(12.0)
    assert slider.total() == 12.0
    assert slider.start_s() == 0.0
    assert slider.end_s() == 12.0
