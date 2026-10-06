# -*- coding: utf-8 -*-
"""M0 Overall-Flow stage table layout tests: column widths on the
0-1000 grid, Status >= "Pending..." text width, centered headers,
right-edge auto-fit (mock, offscreen)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QHeaderView,
)

from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = TestWorkFlowPage()
    w.resize(760, 900)
    yield w
    w.deleteLater()


def test_resize_modes_auto_content_last_stretches(page):
    """Item 20: every column auto-resizes to its content; the last
    column (Duration) stretches so the table right edge auto-fits
    and stays responsive when the window resizes."""
    header = page.overall.horizontalHeader()
    for col in range(5):
        assert header.sectionResizeMode(col) \
            == QHeaderView.ResizeMode.ResizeToContents, col
    assert header.stretchLastSection() is True


def test_columns_fit_header_and_cell_text(page, qapp):
    """No truncation: every column is at least as wide as its header
    text (e.g. 'Duration (s)' must not clip to 'atior'); the Status
    column auto-grows when a cell shows longer text ('Pending...')."""
    page.show()
    qapp.processEvents()
    t = page.overall
    fm = QFontMetrics(t.font())
    for col, header_text in enumerate(
            ["#", "Stage", "EN", "Status", "Duration (s)"]):
        text_w = fm.horizontalAdvance(header_text)
        assert t.columnWidth(col) >= text_w, header_text
    # content-driven adaptation: the longer status text widens the
    # column automatically (ResizeToContents)
    before = t.columnWidth(3)
    t.item(0, 3).setText("Pending...")
    qapp.processEvents()
    assert t.columnWidth(3) >= before
    assert t.columnWidth(3) >= fm.horizontalAdvance("Pending...")
    t.item(0, 3).setText("Pending")
    t.hide()


def test_duration_column_grows_on_window_resize(qapp):
    """Responsive layout: widening the host window widens the
    stretched Duration column (auto-fit, no dead space).  The
    Overall Flow group is hosted by the main window top area, so the
    test mounts it into a resizable container like the real shell."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    page = TestWorkFlowPage()
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(page.overall_group)
    host.resize(700, 500)
    host.show()
    qapp.processEvents()
    narrow = page.overall.columnWidth(4)
    host.resize(1400, 500)
    qapp.processEvents()
    wide = page.overall.columnWidth(4)
    assert wide > narrow
    host.hide()
    page.deleteLater()
    host.deleteLater()


def test_headers_centered(page):
    header = page.overall.horizontalHeader()
    assert header.defaultAlignment() == Qt.AlignmentFlag.AlignCenter


# ------------------------------------------- item 20: stop policy YAML
def test_stop_policy_yaml_round_trip(page, qapp, tmp_path):
    """'Stop if failure' / 'Stop if any short' persist into the
    project YAML on save and are restored on load; defaults are
    unchecked / checked; runtime behavior untouched."""
    import yaml

    from mtkgui.project_config import apply_config, build_config

    # documented defaults
    assert page.stop_if_fail_cb.isChecked() is False
    assert page.stop_if_short_cb.isChecked() is True

    page.stop_if_fail_cb.setChecked(True)
    page.stop_if_short_cb.setChecked(False)
    equipment = type("E", (), {"configs": {}})()
    config = build_config(page, equipment)
    assert config["test_workflow"]["stop_if_failure"] is True
    assert config["test_workflow"]["stop_if_any_short"] is False
    yaml_file = tmp_path / "plan.yaml"
    yaml_file.write_text(yaml.safe_dump(config), encoding="utf-8")

    fresh = TestWorkFlowPage()
    try:
        apply_config(yaml.safe_load(yaml_file.read_text(
            encoding="utf-8")), fresh, equipment)
        assert fresh.stop_if_fail_cb.isChecked() is True
        assert fresh.stop_if_short_cb.isChecked() is False
    finally:
        fresh.deleteLater()


def test_row_content_unchanged(page):
    """EN checkmark + '--' placeholder + row count keep the original
    design (no business/visual change beyond widths)."""
    t = page.overall
    assert t.rowCount() == 2
    assert t.columnCount() == 5
    for r in range(2):
        assert t.item(r, 2).checkState() == Qt.CheckState.Checked
        assert t.item(r, 4).text() == "--"
        assert t.item(r, 3).text() == "Pending"
    assert [t.horizontalHeaderItem(c).text()
            for c in range(5)] == \
        ["#", "Stage", "EN", "Status", "Duration (s)"]
