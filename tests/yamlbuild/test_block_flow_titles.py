# -*- coding: utf-8 -*-
"""M10-FIX4 F4: block-flow card titles stay fully readable no matter
how far the page is squeezed (verified bug: a ~490 px pane squeezed the
five cards to ~80 px and titles 04 / 05 clipped).

v2-3c: the M19d rebuild made the page a single vertical flow (block strip
on top, Channel Allocation below) - there is no QSplitter left to size,
so the test now drives the whole page width instead of a splitter pane
and keeps the same contract: the strip never goes below MIN_FLOW_WIDTH
and every card still shows its full title on at most two wrapped lines."""

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

#: page widths around the width that produced the clipping bug, plus the
#: two sizes the GUI actually opens at
PAGE_WIDTHS = (860, 1024, 1200, 1440)


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


@pytest.mark.parametrize("page_width", PAGE_WIDTHS)
def test_card_titles_fit_real_page_widths(page, page_width):
    """The strip cannot compress below its minimum, and every card shows
    its FULL title on at most two wrapped lines."""
    page.resize(page_width, 640)
    QApplication.processEvents()
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
