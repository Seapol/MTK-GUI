# -*- coding: utf-8 -*-
"""P3-B2 tests: console YAML persistence, console window state memory,
log enhancements (filter / keyword highlight / auto-scroll) and the
workflow debug node-comment YAML round trip."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.project_config import (  # noqa: E402
    apply_config,
    build_config,
)
from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402
from mtkgui.widgets.console_widget import (  # noqa: E402
    ERROR_COLOR,
    WARN_COLOR,
    ConsoleWidget,
)
from mtkgui.widgets.multi_console import (  # noqa: E402
    APP_NAME,
    APP_ORG,
    MultiConsoleWidget,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = TestWorkFlowPage()
    yield w
    w.deleteLater()


@pytest.fixture()
def equipment(qapp):
    eq = pytest.importorskip(
        "mtkgui.equipment_page").EquipmentPage()
    yield eq
    eq.deleteLater()


@pytest.fixture()
def console_settings():
    """Isolate the console_window/<key> QSettings keys per test."""
    settings = QSettings(APP_ORG, APP_NAME)
    settings.clear()
    yield settings
    settings.clear()


# ------------------------------------------------------- T1 console YAML
def test_console_section_round_trip(page, equipment):
    """SER/SSH parameters are written into the project 'console'
    section and restored into channel params on load."""
    mc = page.multi_console
    mc.apply_yaml_channels([
        {"kind": "serial",
         "params": {"port": "/dev/ttyUSB0", "baudrate": 921600}},
        {"kind": "ssh",
         "params": {"host": "192.168.1.10", "port": 22,
                    "username": "root", "password": "pw"}},
    ])
    config = build_config(page, equipment)
    assert [c["kind"] for c in config["console"]] == ["serial", "ssh"]
    assert config["console"][0]["params"]["baudrate"] == 921600
    assert config["console"][1]["params"]["host"] == "192.168.1.10"

    fresh = TestWorkFlowPage()
    try:
        apply_config(config, fresh, equipment)
        keys = fresh.multi_console.yaml_channel_keys()
        assert keys == ["ser1", "ssh1"]
        assert fresh.multi_console.channels["ser1"]["params"][
            "port"] == "/dev/ttyUSB0"
        assert fresh.multi_console.channels["ssh1"]["params"][
            "username"] == "root"
    finally:
        fresh.deleteLater()


def test_console_section_absent_keeps_channels(page, equipment):
    """Backward compat: an old YAML without a 'console' section leaves
    the current channel configuration untouched."""
    mc = page.multi_console
    mc.set_channel_params("ser1", {"port": "/dev/ttyUSB9"})
    config = build_config(page, equipment)
    del config["console"]                     # simulate an old project

    fresh = TestWorkFlowPage()
    try:
        apply_config(config, fresh, equipment)
        assert fresh.multi_console.yaml_channel_keys() is None
        assert fresh.multi_console.channels["ser1"]["params"].get(
            "port") != "/dev/ttyUSB9"         # untouched default
    finally:
        fresh.deleteLater()


# --------------------------------------------- T2 console window memory
def test_console_window_state_round_trip(qapp, console_settings):
    """Geometry / font / color scheme persist per channel key in
    QSettings and are restored into a fresh window."""
    mc = MultiConsoleWidget()
    try:
        win = mc.channels["ser1"]["console_window"]
        font = QFont("Courier New", 13)
        win.console.set_font(font)
        saved_font = win.console.font().toString()
        win.set_background("#101820")
        win._save_window_state()

        st = console_settings
        assert st.contains("console_window/ser1/geometry")
        assert st.contains("console_window/ser1/font")
        assert st.value("console_window/ser1/bg") == "#101820"

        mc2 = MultiConsoleWidget()
        try:
            win2 = mc2.channels["ser1"]["console_window"]
            # the persisted font string must come back identically
            # (Qt may resolve the family / pixel size, so compare the
            # serialized form, not pointSize)
            assert win2.console.font().toString() == saved_font
            assert win2.bg_color == "#101820"
        finally:
            mc2.deleteLater()
    finally:
        mc.deleteLater()


def test_console_window_restore_without_saved_state(qapp,
                                                    console_settings):
    """A fresh profile (no saved keys) must not break construction."""
    mc = MultiConsoleWidget()
    try:
        win = mc.channels["ssh1"]["console_window"] \
            if "ssh1" in mc.channels else \
            mc.channels["ser1"]["console_window"]
        assert win.console is not None
    finally:
        mc.deleteLater()


def test_console_window_per_key_isolation(qapp, console_settings):
    """Each console instance restores its own state (key-scoped)."""
    mc = MultiConsoleWidget()
    try:
        mc.add_serial()                      # second instance key ser2
        win1 = mc.channels["ser1"]["console_window"]
        win1.set_background("#223344")
        win1._save_window_state()
        win2 = mc.channels["ser2"]["console_window"]
        win2.set_background("#556677")
        win2._save_window_state()
        st = console_settings
        assert st.value("console_window/ser1/bg") == "#223344"
        assert st.value("console_window/ser2/bg") == "#556677"
    finally:
        mc.deleteLater()


# ------------------------------------------------- T3 log enhancements
def test_log_filter_drops_non_matching_lines(qapp):
    console = ConsoleWidget("k", "T", "f")
    try:
        console.edit_filter.setText("BOOT")
        assert console.filter_text == "BOOT"
        console.append_message("SYS", "unrelated line")
        console.append_message("SYS", "BOOT ok line")
        text = console.view.toPlainText()
        assert "BOOT ok line" in text
        assert "unrelated line" not in text
    finally:
        console.deleteLater()


def test_log_filter_allows_chunk_with_any_matching_line(qapp):
    console = ConsoleWidget("k", "T", "f")
    try:
        console.edit_filter.setText("ready")
        # multi-line chunk with at least one matching line passes the
        # fast gate, then per-line filtering drops the others
        console.append_message("SYS", "noise\nready 100%\nmore noise")
        text = console.view.toPlainText()
        assert "ready 100%" in text
        assert "noise" not in text
    finally:
        console.deleteLater()


def test_keyword_highlight_error_warning(qapp):
    assert ConsoleWidget._line_color("boot error occurred",
                                     "#ffffff") == (ERROR_COLOR, True)
    assert ConsoleWidget._line_color("some warning here",
                                     "#ffffff") == (WARN_COLOR, False)
    assert ConsoleWidget._line_color("all fine", "#ffffff") == \
        ("#ffffff", False)


def test_keyword_highlight_rendered(qapp):
    console = ConsoleWidget("k", "T", "f")
    try:
        console.append_message("SYS", "an error happened")
        doc = console.view.document()
        colors = set()
        for b in range(doc.blockCount()):
            block = doc.findBlockByNumber(b)
            it = block.begin()
            while it != block.end():
                colors.add(it.fragment().charFormat().
                           foreground().color().name())
                it += 1
        assert ERROR_COLOR in colors
    finally:
        console.deleteLater()


def test_autoscroll_toggle_exists(qapp):
    console = ConsoleWidget("k", "T", "f")
    try:
        assert console.check_autoscroll.isChecked()
        console.check_autoscroll.setChecked(False)
        assert not console.check_autoscroll.isChecked()
    finally:
        console.deleteLater()


def test_font_accessor(qapp):
    console = ConsoleWidget("k", "T", "f")
    try:
        f = QFont("Menlo", 11)
        console.set_font(f)
        # Qt may resolve point size into pixel size on the widget font,
        # so compare the serialized form (exact round trip)
        assert console.font().toString() == \
            console.view.font().toString()
        assert console.font().family() in ("Menlo", ".AppleSystemUIFont",
                                           "Menlo-Regular")
    finally:
        console.deleteLater()


# ------------------------------------------ T4 node comment round trip
def test_node_comment_yaml_round_trip(page, equipment):
    """Non-empty comments are archived to the YAML cases and restored
    into a fresh page (tooltip + list)."""
    page.ict_comments = ["", "check R105 short", ""]
    page.fct_comments = ["verify flash log"]

    config = build_config(page, equipment)
    ict = config["test_workflow"]["ict_test_cases"]
    fct = config["test_workflow"]["fct_test_cases"]
    assert ict[0].get("comment") is None
    assert ict[1]["comment"] == "check R105 short"
    assert fct[0]["comment"] == "verify flash log"

    fresh = TestWorkFlowPage()
    try:
        apply_config(config, fresh, equipment)
        assert fresh.ict_comments[1] == "check R105 short"
        assert fresh.fct_comments[0] == "verify flash log"
        assert fresh.ict.item(1, 1).toolTip() == "check R105 short"
        assert fresh.fct.item(0, 1).toolTip() == "verify flash log"
    finally:
        fresh.deleteLater()


def test_node_comment_absent_backwards_compatible(page, equipment):
    """Old YAML cases without 'comment' load with empty comments."""
    config = build_config(page, equipment)
    for c in config["test_workflow"]["ict_test_cases"]:
        c.pop("comment", None)
    fresh = TestWorkFlowPage()
    try:
        apply_config(config, fresh, equipment)
        assert all(not c for c in fresh.ict_comments)
    finally:
        fresh.deleteLater()


def test_breakpoint_yaml_round_trip(page, equipment):
    """Debug breakpoints persist per case ('breakpoint: true'), are
    restored into the sets on load and re-marked with the ● prefix;
    old YAML without the flag loads with empty breakpoint sets."""
    page.ict_breakpoints = {1, 4}
    page.fct_breakpoints = {2}

    config = build_config(page, equipment)
    ict = config["test_workflow"]["ict_test_cases"]
    fct = config["test_workflow"]["fct_test_cases"]
    assert [bool(c.get("breakpoint")) for c in ict] == \
        [False, True, False, False, True] + [False] * (len(ict) - 5)
    assert [bool(c.get("breakpoint")) for c in fct] == \
        [False, False, True] + [False] * (len(fct) - 3)

    fresh = TestWorkFlowPage()
    try:
        apply_config(config, fresh, equipment)
        assert fresh.ict_breakpoints == {1, 4}
        assert fresh.fct_breakpoints == {2}
        # ● marker re-applied by the row fill after the restore
        assert fresh.ict.item(1, 0).text() == "● 2"
        assert fresh.ict.item(0, 0).text() == "1"
        assert fresh.fct.item(2, 0).text() == "● 3"
    finally:
        fresh.deleteLater()


def test_breakpoint_flag_absent_backwards_compatible(page, equipment):
    """Old YAML cases without 'breakpoint' load with no breakpoints."""
    config = build_config(page, equipment)
    for c in config["test_workflow"]["ict_test_cases"]:
        c.pop("breakpoint", None)
    fresh = TestWorkFlowPage()
    try:
        apply_config(config, fresh, equipment)
        assert fresh.ict_breakpoints == set()
    finally:
        fresh.deleteLater()


def test_edit_comment_stores_and_updates_tooltip(qapp, monkeypatch):
    """The context-menu editor stores the text and syncs the tooltip;
    Cancel leaves the comment unchanged."""
    from PySide6.QtWidgets import QInputDialog

    console_page = TestWorkFlowPage()
    try:
        monkeypatch.setattr(
            QInputDialog, "getMultiLineText",
            staticmethod(lambda *a, **k: ("my note", True)))
        console_page._edit_comment(console_page.ict, 2,
                                   console_page.ict_comments)
        assert console_page.ict_comments[2] == "my note"
        assert console_page.ict.item(2, 1).toolTip() == "my note"

        monkeypatch.setattr(
            QInputDialog, "getMultiLineText",
            staticmethod(lambda *a, **k: ("cleared", True)))
        console_page._edit_comment(console_page.ict, 2,
                                   console_page.ict_comments)
        assert console_page.ict_comments[2] == "cleared"

        monkeypatch.setattr(
            QInputDialog, "getMultiLineText",
            staticmethod(lambda *a, **k: ("never shown", False)))
        console_page._edit_comment(console_page.ict, 2,
                                   console_page.ict_comments)
        assert console_page.ict_comments[2] == "cleared"
    finally:
        console_page.deleteLater()


def test_context_menu_offers_comment_action(qapp):
    """Both tables carry the 'Edit comment...' context-menu entry."""
    from PySide6.QtWidgets import QMenu

    console_page = TestWorkFlowPage()
    try:
        # verify wiring exists by checking the handlers reference the
        # comment lists (regression guard for accidental removal)
        import inspect
        src = inspect.getsource(console_page._ict_context_menu)
        assert "Edit comment..." in src
        assert "ict_comments" in src
        src = inspect.getsource(console_page._fct_context_menu)
        assert "Edit comment..." in src
        assert "fct_comments" in src
        assert QMenu is not None
    finally:
        console_page.deleteLater()
