# -*- coding: utf-8 -*-
"""M101: Test Work Flow page review (2x2 body, float/dock tables, Console
tabs + Command Helper, status-bar progress width)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    p = TestWorkFlowPage()
    yield p
    p.deleteLater()


def test_fct_default_rows_drop_flash_gui_suffix(page):
    names = list(page.fct_rows)
    assert "MessageGoStop: Flash FAT Firmware" in names
    assert "MessageGoStop: Flash OOBE Firmware" in names
    assert not any("(3rd-party GUI)" in n for n in names)


def test_body_is_two_stages_vertical_1_1(page, qapp):
    page.resize(1200, 900)
    page.show()
    qapp.processEvents()
    vertical = page._vertical_splitter
    assert vertical.orientation() == Qt.Orientation.Vertical
    assert vertical.count() == 2
    for splitter in (page._ict_splitter, page._fct_splitter):
        assert splitter.orientation() == Qt.Orientation.Horizontal
        assert splitter.count() == 3


def test_chevron_collapses_right_pane_and_restores(page, qapp):
    page.resize(1200, 900)
    page.show()
    qapp.processEvents()
    splitter = page._ict_splitter
    chevron = page._ict_chevron
    right = page._ict_right
    assert right.isVisible()
    assert chevron.arrowType() == Qt.ArrowType.RightArrow
    chevron.click()
    qapp.processEvents()
    assert not right.isVisible()
    assert chevron.arrowType() == Qt.ArrowType.LeftArrow
    chevron.click()
    qapp.processEvents()
    assert right.isVisible()
    assert chevron.arrowType() == Qt.ArrowType.RightArrow
    left, _chevron, right_w = splitter.sizes()
    assert abs(left - right_w) <= 26


def test_splitter_sizes_persist_qsettings(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    store = QSettings(str(tmp_path / "settings.ini"),
                      QSettings.Format.IniFormat)
    monkeypatch.setattr("mtkgui.test_workflow_page.QSettings",
                        lambda *a, **k: store)
    first = TestWorkFlowPage()
    first.resize(1200, 900)
    first.show()
    qapp.processEvents()
    first._ict_chevron.click()
    qapp.processEvents()
    assert store.value("workflow_page/ict_collapsed", type=bool) is True
    second = TestWorkFlowPage()
    second.show()
    qapp.processEvents()
    assert not second._ict_right.isVisible()
    first.deleteLater()
    second.deleteLater()


def test_double_click_ict_floats_readonly_and_docks_back(page, qapp):
    page.resize(1200, 900)
    page.show()
    qapp.processEvents()
    page.ict.cellDoubleClicked.emit(0, 0)
    qapp.processEvents()
    assert page._ict_float_win is not None
    assert page.ict.parent() is page._ict_float_win
    assert page._ict_placeholder is not None
    assert page._ict_float_win.isVisible()
    page._dock_table("ict")
    qapp.processEvents()
    assert page._ict_float_win is None
    assert page.ict.parent() is page._ict_pane
    assert page._ict_placeholder is None


def test_double_click_fct_floats_readonly_and_docks_back(page, qapp):
    page.resize(1200, 900)
    page.show()
    qapp.processEvents()
    page.fct.cellDoubleClicked.emit(0, 0)
    qapp.processEvents()
    assert page._fct_float_win is not None
    assert page.fct.parent() is page._fct_float_win
    assert page._fct_placeholder is not None
    page._dock_table("fct")
    qapp.processEvents()
    assert page._fct_float_win is None
    assert page.fct.parent() is page._fct_pane
    assert page._fct_placeholder is None


def test_context_menu_has_edit_sequence_gated(page):
    import inspect
    src = inspect.getsource(page._ict_context_menu)
    assert "Edit sequence..." in src
    assert "_can_edit_ict" in src
    src = inspect.getsource(page._fct_context_menu)
    assert "Edit sequence..." in src
    assert "_can_edit_fct" in src


def test_edit_sequence_emits_build_requested(page):
    emitted_ict = []
    emitted_fct = []
    page.ict_build_requested.connect(lambda: emitted_ict.append(True))
    page.fct_build_requested.connect(lambda: emitted_fct.append(True))
    page._emit_edit_sequence("ict")
    page._emit_edit_sequence("fct")
    assert emitted_ict == [True]
    assert emitted_fct == [True]


def test_console_uses_tabs_one_per_channel(page):
    from PySide6.QtWidgets import QTabWidget
    mc = page.multi_console
    assert isinstance(mc._tabs, QTabWidget)
    assert mc._tabs.count() == len(mc.channels)
    labels = [mc._tabs.tabText(i) for i in range(mc._tabs.count())]
    assert labels == ["SER1"]
    for key, channel in mc.channels.items():
        assert channel["label"] in labels


def test_add_remove_controls_absent(page):
    mc = page.multi_console
    assert getattr(mc, "btn_add_serial", None) is None
    assert getattr(mc, "btn_add_ssh", None) is None
    assert getattr(mc, "btn_remove", None) is None


def test_console_float_and_dock_back(page, qapp):
    mc = page.multi_console
    key = "ser1"
    console_window = mc.channels[key]["console_window"]
    tab_page = mc.channels[key]["tab_page"]
    assert console_window.parent() is tab_page
    assert mc._float_win[key] is None
    mc._float_console(key)
    qapp.processEvents()
    assert mc._float_win[key] is not None
    assert console_window.parent() is mc._float_win[key]
    assert mc.channels[key]["placeholder"] is not None
    mc._dock_console(key)
    qapp.processEvents()
    assert mc._float_win[key] is None
    assert console_window.parent() is tab_page
    assert mc.channels[key]["placeholder"] is None


def test_command_helper_shows_linux_only_and_fills_send(page):
    from mtkgui.command_library import load_command_library
    mc = page.multi_console
    console_window = mc.channels["ser1"]["console_window"]
    helper = console_window._cmd_helper
    send_panel = console_window.send_panel

    assert "Cmd Helper: Linux" in helper.btn_toggle.text()
    assert all(e["category"] == "linux" for e in helper.entries)
    assert any(b.text() == "Insert" for b in helper._insert_btns)

    library = load_command_library()
    non_linux = [e for e in library if e["category"] != "linux"]
    assert non_linux  # sanity: the shared library carries other categories
    shown = {e["name"] for e in helper.entries}
    assert not any(e["name"] in shown for e in non_linux)

    sent = []
    console_window.send_requested.connect(lambda *a: sent.append(a))
    helper.fill_send("uname -a")
    assert send_panel.edit.text() == "uname -a"
    assert sent == []



