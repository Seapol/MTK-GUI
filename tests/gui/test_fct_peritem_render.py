# -*- coding: utf-8 -*-
"""M107b: the GUI FCT table renders fat.py per-item rows (display-only)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

ITEMS = [
    {"label": "1. Memory (memtester)", "status": "PASS",
     "duration_s": 12.34},
    {"label": "2. USB U-disk read/write speed", "status": "FAIL",
     "duration_s": 99.5},
    {"label": "3. Wi-Fi scan", "status": "WARN", "duration_s": 1.0},
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    from mtkgui.test_workflow_page import TestWorkFlowPage
    w = TestWorkFlowPage()
    yield w
    w.deleteLater()


def test_render_fct_sub_items_lists_each_item(page):
    row_count = page.fct.rowCount()
    results_before = dict(page._runner._results)
    page._render_fct_sub_items(0, ITEMS)
    widget = page.fct.cellWidget(0, 1)
    assert widget is not None
    labels = [label.text() for label in
              widget.findChildren(QLabel, "fct_sub_item_label")]
    assert labels == [item["label"] for item in ITEMS]
    statuses = [label.text() for label in
                widget.findChildren(QLabel, "fct_sub_item_status")]
    assert statuses == ["PASS", "FAIL", "WARN"]
    # display-only: no row inserted, no runner key, step name intact
    assert page.fct.rowCount() == row_count
    assert page._runner._results == results_before
    assert page.fct.item(0, 1).text() == page.fct_rows[0]


def test_rerender_replaces_previous_items(page):
    page._render_fct_sub_items(0, ITEMS[:1])
    page._render_fct_sub_items(0, ITEMS[1:])
    widget = page.fct.cellWidget(0, 1)
    statuses = [label.text() for label in
                widget.findChildren(QLabel, "fct_sub_item_status")]
    assert statuses == ["FAIL", "WARN"]


def test_clear_results_drops_the_per_item_block(page):
    page._render_fct_sub_items(0, ITEMS)
    assert page.fct.cellWidget(0, 1) is not None
    page.clear_results(keep_log=True)
    assert page.fct.cellWidget(0, 1) is None
