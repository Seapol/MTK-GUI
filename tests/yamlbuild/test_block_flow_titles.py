# -*- coding: utf-8 -*-
"""M10-FIX4 F4: block-flow card titles stay fully readable inside the
real Yaml Build splitter (verified bug: a ~490 px left pane squeezed
the five cards to ~80 px and titles 04 / 05 clipped)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.theme import StyleSpec, build_stylesheet  # noqa: E402
from mtkgui.gui.yamlbuild.block_flow import MIN_FLOW_WIDTH  # noqa: E402
from mtkgui.gui.yamlbuild.stages import (  # noqa: E402
    WORKFLOW_DISPLAY_STAGES,
)
from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402

#: realistic left-pane widths requested through the splitter (the bug
#: report measured ~490 px in the real GUI)
LEFT_PANE_WIDTHS = (460, 490, 520)


@pytest.fixture
def page(tmp_path, monkeypatch):
    from mtkgui.gui.yamlbuild import store
    monkeypatch.setattr(store, "STATE_DIR", tmp_path)
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "state.json")
    widget = YamlBuildPage()
    # render with the REAL app font + stylesheet (the title fit depends
    # on the font metrics, so the test must not measure a default font)
    widget.setFont(StyleSpec().font())
    widget.setStyleSheet(build_stylesheet())
    widget.resize(MIN_FLOW_WIDTH + 720, 640)
    widget.show()
    QApplication.processEvents()
    yield widget
    widget.close()


def _splitter(page):
    return next(child for child in page.children()
                if type(child).__name__ == "QSplitter")


@pytest.mark.parametrize("left_pane", LEFT_PANE_WIDTHS)
def test_card_titles_fit_real_splitter_widths(page, left_pane):
    """The splitter cannot compress the flow below its minimum, and
    every card shows its FULL title on at most two wrapped lines."""
    split = _splitter(page)
    split.setSizes([left_pane, 900])
    QApplication.processEvents()
    assert split.sizes()[0] >= MIN_FLOW_WIDTH
    assert page.block_flow.minimumWidth() == MIN_FLOW_WIDTH
    assert page.block_flow.width() >= MIN_FLOW_WIDTH

    for index, stage in enumerate(WORKFLOW_DISPLAY_STAGES):
        card = page.block_flow._cards[stage.key]
        label = card.title_label
        # full, unshortened title text (no elide / no rename)
        assert label.text() == f"{index + 1:02d} · {stage.title}"
        assert card.width() >= 120
        metrics = label.fontMetrics()
        needed = metrics.boundingRect(
            0, 0, label.width(), 0,
            Qt.TextFlag.TextWordWrap, label.text()).height()
        # the label has room for the wrapped text (nothing clipped)
        assert needed <= label.height() + 1
        # and the wrapping stays at two lines at most
        lines = -(-needed // max(1, metrics.lineSpacing()))
        assert lines <= 2, f"{stage.title} wraps to {lines} lines"
