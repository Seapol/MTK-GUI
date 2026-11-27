# -*- coding: utf-8 -*-
"""M159d: node 06 imports the console capture + the dut_type hint."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from mtkgui.gui.yamlbuild.fct_authoring import (  # noqa: E402
    annotations_to_step,
)
from mtkgui.engine.step_types import CATEGORY_CONSOLE  # noqa: E402
from mtkgui.gui.yamlbuild.fct_build import (  # noqa: E402
    FctSequence,
    FctStep,
)
from mtkgui.gui.yamlbuild.fct_capture import (  # noqa: E402
    ANNOTATION_EXPECT_PASS,
    CaptureAnnotation,
    CaptureBuffer,
)
from mtkgui.gui.yamlbuild.fct_sequence_v2_panel import (  # noqa: E402
    BuildFctSequencePanel,
)


@pytest.fixture
def panel():
    widget = BuildFctSequencePanel()
    yield widget
    widget.deleteLater()


def _draft(name, word):
    return annotations_to_step(
        [CaptureAnnotation(text=word, kind=ANNOTATION_EXPECT_PASS,
                           channel="dut")], "dut", name=name)


def test_import_appends_buffered_steps_and_clears_the_buffer(panel):
    panel.set_sequence(FctSequence(name="FCT Sequence"))
    buffer = CaptureBuffer()
    panel.set_capture_buffer(buffer)
    assert panel.btn_import.isEnabled() is False
    buffer.add_step(_draft("cap 1", "READY"))
    buffer.add_step(_draft("cap 2", "DONE"))
    # the buffer change refreshed the button
    assert panel.btn_import.isEnabled() is True
    changed = []
    panel.content_changed.connect(lambda: changed.append(True))
    panel.btn_import.click()
    steps = panel.sequence().steps
    assert [step.name for step in steps] == ["cap 1", "cap 2"]
    assert steps[0].expect_pass == ["READY"]
    assert buffer.is_empty() is True
    assert panel.btn_import.isEnabled() is False
    assert changed == [True]
    assert panel.table.rowCount() == 2


def test_import_with_empty_buffer_is_a_noop(panel):
    panel.set_sequence(FctSequence(name="FCT Sequence", steps=[
        FctStep(name="Existing", category=CATEGORY_CONSOLE, type="serial",
                channel="dut")]))
    buffer = CaptureBuffer()
    panel.set_capture_buffer(buffer)
    assert panel.btn_import.isEnabled() is False
    changed = []
    panel.content_changed.connect(lambda: changed.append(True))
    panel._import_capture()
    assert [s.name for s in panel.sequence().steps] == ["Existing"]
    assert changed == []
    assert buffer.is_empty() is True


def test_recommendation_line_follows_dut_type(panel):
    panel.set_dut_type("linux")
    assert panel.lbl_recommend.text() == \
        "Recommended: Record (auto-split on TX)"
    panel.set_dut_type("bare_metal")
    assert panel.lbl_recommend.text() == \
        "Recommended: Annotate (listen only)"
    # default (no explicit call) is the linux wording
    fresh = BuildFctSequencePanel()
    try:
        assert fresh.lbl_recommend.text() == \
            "Recommended: Record (auto-split on TX)"
    finally:
        fresh.deleteLater()
