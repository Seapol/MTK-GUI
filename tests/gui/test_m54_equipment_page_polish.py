# -*- coding: utf-8 -*-
"""M54: Equipment page UI polish.

Locks the M54 contract:
* §1 the row-level Test buttons are gone - Test / self-test live INSIDE
  the Config dialogs (instrument actions + "Test Connection" for the
  _TESTABLE_FORM_KEYS entries, PASSED / FAILED in the dialog);
* §2 the "Hide" push button became a flat arrow QToolButton (Event Log
  style) that collapses / expands the left column;
* §3 the left column defaults to 25 % of the width and the zoom range is
  50 % .. 300 % (the M49a drag clamp stays);
* §4 the hint text under the title is removed;
* §5 zoom scales the diagram items only - the viewport background never
  scales with the transform.
"""
from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog,  # noqa: E402
                               QGraphicsScene, QLabel, QPushButton,
                               QToolButton)

from mtkgui.equipment_page import (BlockDiagramView,  # noqa: E402
                                   EquipmentPage, LEFT_ENTRIES,
                                   _GroupConfigDialog)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    p = EquipmentPage()
    yield p
    p.deleteLater()


# ---------------------------------------------------------------------------
# §1 - every row keeps Config only; the test actions live in the dialog
# ---------------------------------------------------------------------------
def test_no_entry_row_has_a_test_button(page):
    for _group, entries in LEFT_ENTRIES:
        for key, _label, _kind, _source in entries:
            buttons = page.entry_buttons[key]
            assert set(buttons) == {"config"}, key
            assert "Test" not in buttons["config"].text()
    assert not hasattr(page, "_test_entry")
    assert not hasattr(page, "_run_instrument_self_test")


def test_instrument_dialog_still_offers_the_test_actions(page, monkeypatch):
    captured = {}

    def fake_exec(dlg):
        captured["dlg"] = dlg
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    page._instrument_connections["daq973a"] = True
    page.open_entry("daq973a")
    dlg = captured["dlg"]
    try:
        assert dlg.btn_connect.text() == "Connect"
        assert dlg.btn_disconnect.text() == "Disconnect"
        assert dlg.btn_test.text() == "Test Connection"
        labels = [btn.text() for btn in dlg.findChildren(QPushButton)]
        assert "Self Test" in labels
    finally:
        dlg.deleteLater()


def test_dialog_self_test_still_drives_the_lamp(page, monkeypatch, qapp):
    captured = {}
    seen = []
    page.instrument_selftest_changed.connect(
        lambda key, passed: seen.append((key, passed)))

    def fake_exec(dlg):
        captured["dlg"] = dlg
        dlg._connected = True
        dlg.self_test_changed.emit("daq973a", True)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    page.open_entry("daq973a")
    assert seen == [("daq973a", True)]
    assert page.instrument_state("daq973a") == "green"
    captured["dlg"].deleteLater()


def test_testable_group_config_shows_test_connection(qapp):
    dlg = _GroupConfigDialog(
        None, "SSH Login", [("ip", "IP address", "")], {"ip": "1.2.3.4"},
        test_probe=lambda values: (True, "ok"))
    try:
        assert dlg.test_button.text() == "Test Connection"
        assert dlg.test_result is not None
    finally:
        dlg.deleteLater()


def test_plain_group_config_has_no_test_connection(qapp):
    dlg = _GroupConfigDialog(
        None, "DIO signals", [("press", "Press", "")], {"press": "DIO09"})
    try:
        assert not hasattr(dlg, "test_button")
        assert not hasattr(dlg, "test_result")
    finally:
        dlg.deleteLater()


def test_control_board_dialog_has_no_test_connection(page, monkeypatch):
    captured = {}

    def fake_exec(dlg):
        captured["dlg"] = dlg
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    page.open_entry("control_board")
    dlg = captured["dlg"]
    try:
        assert not hasattr(dlg, "test_button")
    finally:
        dlg.deleteLater()


def test_dialog_test_connection_reports_passed_text(page, qapp):
    seen = []

    def probe(values):
        seen.append(dict(values))
        return True, "Test Connection PASSED: the link is available."

    dlg = _GroupConfigDialog(
        page, "SSH Login", [("ip", "IP address", "")], {"ip": "1.2.3.4"},
        test_probe=probe)
    try:
        dlg.test_button.click()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            qapp.processEvents()
            text = dlg.test_result.text()
            if text and text != "Testing ...":
                break
            time.sleep(0.01)
        assert "Test Connection PASSED" in dlg.test_result.text()
        assert seen and seen[0]["ip"] == "1.2.3.4"
        assert "#15803d" in dlg.test_result.styleSheet()
    finally:
        dlg.deleteLater()


def test_probe_with_span_keeps_the_m51_span(page, monkeypatch):
    from mtkgui.engine import host_platform
    monkeypatch.setattr(host_platform, "ping_host", lambda host: False)
    ok, message = page._probe_with_span(
        "dut_ssh", {"ip": "10.1.2.3", "username": "root"})
    assert ok is False
    assert "Test Connection FAILED" in message


# ---------------------------------------------------------------------------
# §2 - flat arrow collapse control
# ---------------------------------------------------------------------------
def test_collapse_control_is_a_flat_arrow_tool_button(page):
    btn = page.btn_collapse
    assert isinstance(btn, QToolButton)
    assert btn.autoRaise() is True
    assert btn.arrowType() == Qt.ArrowType.LeftArrow
    assert btn.toolTip() == "Collapse Hardware Configuration"
    assert not page.left_list.isHidden()


def test_collapse_swaps_the_arrow_and_the_tooltip(page):
    page.btn_collapse.click()
    assert page.left_list.isHidden()
    assert page.btn_collapse.arrowType() == Qt.ArrowType.RightArrow
    assert page.btn_collapse.toolTip() == "Show Hardware Configuration"
    page.btn_collapse.click()
    assert not page.left_list.isHidden()
    assert page.btn_collapse.arrowType() == Qt.ArrowType.LeftArrow
    assert page.btn_collapse.toolTip() == "Collapse Hardware Configuration"


# ---------------------------------------------------------------------------
# §3 - left column 25 % + zoom 50 - 300 %
# ---------------------------------------------------------------------------
def test_splitter_defaults_to_a_quarter(page, qapp):
    page.resize(1600, 900)
    page.show()
    qapp.processEvents()
    left, right = page.splitter.sizes()
    assert left + right > 0
    assert left <= (left + right) * 0.30


def test_splitter_drag_clamp_still_caps_at_half(page):
    page.splitter.setSizes([1000, 100])
    page.splitter.splitterMoved.emit(1000, 1)
    left, right = page.splitter.sizes()
    assert left <= right


def _view(qapp):
    view = BlockDiagramView(QGraphicsScene(0, 0, 200, 150),
                            lambda _item: None)
    view.resize(400, 300)
    return view


def test_zoom_range_is_50_to_300_percent(qapp):
    view = _view(qapp)
    try:
        view.zoom_reset()
        for _ in range(20):
            view.zoom_in()
        assert view.transform().m11() <= BlockDiagramView.MAX_ZOOM
        assert view.transform().m11() == pytest.approx(1.25 ** 4)
        view.zoom_reset()
        for _ in range(20):
            view.zoom_out()
        assert view.transform().m11() >= BlockDiagramView.MIN_ZOOM
        assert view.transform().m11() == pytest.approx(0.8 ** 3)
        view.zoom_reset()
        assert view.transform().m11() == pytest.approx(1.0)
    finally:
        view.deleteLater()


def test_view_stylesheet_has_no_background(page):
    assert "background" not in page.view.styleSheet()


# ---------------------------------------------------------------------------
# §4 - the hint text is gone
# ---------------------------------------------------------------------------
def test_hint_text_is_removed(page):
    texts = [label.text() for label in page.findChildren(QLabel)]
    assert not any("configurable hardware (Config)" in text
                   for text in texts)


# ---------------------------------------------------------------------------
# §5 - zoom scales the items, never the background
# ---------------------------------------------------------------------------
def test_background_rect_is_the_viewport_not_the_scene(qapp):
    view = _view(qapp)
    try:
        view.zoom_reset()
        before = QRectF(view.viewport().rect())
        view.zoom_in()
        after = view._background_rect()
        assert after == before
        assert after.width() == view.viewport().width()
    finally:
        view.deleteLater()


def test_background_is_painted_at_viewport_size_after_zoom(qapp):
    """drawBackground resets the painter transform, so the fill covers
    the whole viewport at any zoom while the foreground keeps scaling."""
    view = _view(qapp)
    view.zoom_in()
    view.zoom_in()
    try:
        image = QImage(view.viewport().size(),
                       QImage.Format.Format_ARGB32)
        image.fill(QColor("#000000"))
        painter = QPainter(image)
        painter.setTransform(view.transform())      # simulate the zoom
        view.drawBackground(painter, view.sceneRect())
        painter.end()
        assert image.pixelColor(1, 1) == BlockDiagramView.BACKGROUND
        assert image.pixelColor(image.width() - 2,
                                image.height() - 2) == \
            BlockDiagramView.BACKGROUND
        assert view.transform().m11() > 1.0
    finally:
        view.deleteLater()
