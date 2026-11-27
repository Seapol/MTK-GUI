# -*- coding: utf-8 -*-
"""v2-15 F / M160 C: FCT panel editor — common Timeout/Retries block,
BT_Tone range slider."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mtkgui.gui.yamlbuild.FCTTestConfigWidget import _ToneRangeSlider
from mtkgui.gui.yamlbuild.fct_sequence_v2_panel import BuildFctSequencePanel


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_panel_editor_has_the_common_timeout_and_retries(qapp):
    """M160 C: Timeout / Retries live in the common editor block."""
    from mtkgui.gui.yamlbuild.fct_build import FctStep

    panel = BuildFctSequencePanel()
    try:
        assert hasattr(panel, "edit_retries")
        assert hasattr(panel, "edit_timeout")
        panel.set_sequence(_sequence_with(
            FctStep(name="step", category="Console", type="serial",
                    timeout_s=12.5, retries=2)))
        panel.table.setCurrentCell(0, 0)
        assert panel.edit_timeout.value() == 12.5
        assert panel.edit_retries.value() == 2
    finally:
        panel.deleteLater()


def _sequence_with(*steps):
    from mtkgui.gui.yamlbuild.fct_build import FctSequence
    return FctSequence(name="FCT", steps=list(steps))


def test_tone_slider_set_total_resets_segment(qapp):
    slider = _ToneRangeSlider(6.0)
    slider.set_values(1.0, 4.0)
    slider.set_total(12.0)
    assert slider.total() == 12.0
    assert slider.start_s() == 0.0
    assert slider.end_s() == 12.0
