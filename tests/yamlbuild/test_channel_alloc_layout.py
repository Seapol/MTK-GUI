# -*- coding: utf-8 -*-
"""Channel Allocation adaptive column layout tests.

Net column bounded (never consumes the viewport), remaining columns
share the leftover space evenly with minimum-width protection, manual
drag widths persist into the model (project YAML channel) and are
restored, window resize triggers the reflow."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QHeaderView  # noqa: E402

from mtkgui.gui.yamlbuild.channel_allocation import (  # noqa: E402
    NET_MAX_WIDTH,
    NET_MIN_WIDTH,
    ChannelAllocationPage,
)

TESTABLE = {
    "3V3": {"category": "Power", "members": ["U1.5"]},
    "CLK_24M": {"category": "Clock", "members": ["U1.10"]},
    "GPIO_LED1": {"category": "GPIO", "members": ["U1.20"]},
}


class ModelStub:
    def __init__(self, allocation=None):
        self.imported = {"net": {"file": "", "raw": ""},
                         "testable_nets": dict(TESTABLE)}
        self.channel_allocation = allocation or {}

    def set_channel_allocation(self, data):
        self.channel_allocation = data


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = ChannelAllocationPage()
    w.set_model(ModelStub())
    yield w
    w.deleteLater()


def _reflow(table_widget, width=1400):
    """Reflow with an explicit viewport width (simulates a window
    resize; the live path goes through the viewport event filter)."""
    table_widget.reflow(width)


# ------------------------------------------------------------- layout rules
def test_all_columns_interactive_with_min_protection(page):
    """Every column is user-draggable (Interactive) and the header
    enforces a minimum section width (no hidden columns)."""
    for table in (page.table_power, page.table_clock,
                  page.table_gpio):
        header = table.table.horizontalHeader()
        for c in range(table.table.columnCount()):
            assert header.sectionResizeMode(c) == \
                QHeaderView.ResizeMode.Interactive
        assert header.minimumSectionSize() >= 60


def test_net_column_bounded_other_columns_share_space(page):
    """Wide viewport: Net grows only to its cap; the other columns
    share the remaining space (all wider than their minimums)."""
    _reflow(page.table_power, width=1600)
    widths = page.table_power.column_widths()
    assert NET_MIN_WIDTH <= widths[0] <= NET_MAX_WIDTH
    others = widths[1:]
    assert all(w >= 70 for w in others)
    assert len(set(others)) == 1      # even distribution


def test_narrow_viewport_keeps_every_column_visible(page):
    """Narrow window: every column collapses to its minimum width but
    never disappears."""
    _reflow(page.table_power, width=300)
    widths = page.table_power.column_widths()
    assert len(widths) == page.table_power.table.columnCount()
    assert all(w > 0 for w in widths)
    assert widths[0] == NET_MIN_WIDTH


def test_window_resize_triggers_reflow(page):
    """A viewport resize event re-distributes the widths (rule 4)."""
    _reflow(page.table_power, width=700)
    narrow = page.table_power.column_widths()
    _reflow(page.table_power, width=1600)
    wide = page.table_power.column_widths()
    assert sum(wide) > sum(narrow)


# ----------------------------------------------------- persistence / restore
def test_user_widths_persist_and_restore(qapp):
    """Manual drag widths land in the model channel_allocation dict
    (project YAML channel) and are restored on reopen."""
    model = ModelStub()
    page = ChannelAllocationPage()
    page.set_model(model)
    # simulate a user drag on the power Net column (not guarded)
    page.table_power.table.horizontalHeader().resizeSection(0, 200)
    page.save_to_model()
    saved = model.channel_allocation["column_widths"]["power"]
    assert saved[0] == 200
    try:
        fresh = ChannelAllocationPage()
        fresh.set_model(model)      # set_model -> refresh_from_model
        assert fresh.table_power.table.columnWidth(0) == 200
        fresh.deleteLater()
    finally:
        page.deleteLater()


def test_collect_includes_widths_without_breaking_rows(page):
    """collect() adds the column_widths key while the row dicts stay
    untouched (zero regression for the existing consumers)."""
    collected = page.collect()
    assert set(collected) == {"power", "clock", "gpio",
                              "column_widths"}
    assert collected["power"][0]["net"] == "3V3"
    assert collected["column_widths"]["clock"][0] > 0


def test_reflow_after_load_rows(page):
    """(Re)population re-applies the layout rules (load_rows)."""
    page.refresh_from_model()
    widths = page.table_clock.column_widths()
    assert NET_MIN_WIDTH <= widths[0] <= NET_MAX_WIDTH
