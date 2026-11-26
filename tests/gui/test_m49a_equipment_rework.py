# -*- coding: utf-8 -*-
"""M49a: two-column Equipment page (configurable hardware list +
read-only block diagram), instrument indicator lamps and the equipment
yaml state model - plus the M48 follow-up that removes the leftover
"Custom Operation" editor option."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,  # noqa: E402
                               QLineEdit, QPushButton)

from mtkgui.equipment_page import (EquipmentPage, LEFT_ENTRIES,  # noqa: E402
                                   _HardwareInfoDialog, _InstrumentDialog)
from mtkgui.gui.steps_editor import OP_STEPS  # noqa: E402
from mtkgui.test_workflow_page import _SequenceEditorDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    p = EquipmentPage()
    yield p
    p.deleteLater()


# ---------------------------------------------------------------------------
# §0 - no "Custom Operation" entry point in the Operation editor
# ---------------------------------------------------------------------------
def _standard_combo(widget):
    combos = [cb for cb in widget.findChildren(QComboBox)
              if cb.count() >= len(OP_STEPS)]
    assert combos, "the Operation editor must offer a standard-step combo"
    return combos[0]


def test_operation_editor_offers_only_standard_steps(qapp, monkeypatch):
    step = ("op", "Fixture Ready", "—", "—", "—", "—",
            {"type": "fixture_ready", "debounce_ms": 200})
    dlg = _SequenceEditorDialog("ict", [step], [True], [100], [5000])
    seen = {}

    def fake_exec(widget):
        combo = _standard_combo(widget)
        seen["items"] = [combo.itemText(i) for i in range(combo.count())]
        seen["text"] = combo.currentText()
        return QDialog.DialogCode.Accepted

    try:
        monkeypatch.setattr(QDialog, "exec", fake_exec)
        assert dlg._edit_op_step(0, dlg._steps[0]) is True
        assert "Custom Operation" not in seen["items"]
        assert set(seen["items"]) == set(OP_STEPS)
        assert seen["text"] == "Fixture Ready"
    finally:
        dlg.deleteLater()


def test_legacy_unknown_operation_keeps_original_name(qapp, monkeypatch):
    step = ("op", "Legacy Vendor Step", "—", "—", "—", "—", None)
    dlg = _SequenceEditorDialog("ict", [step], [True], [100], [5000])
    seen = {}

    def fake_exec(widget):
        combo = _standard_combo(widget)
        seen["text"] = combo.currentText()
        return QDialog.DialogCode.Accepted

    try:
        monkeypatch.setattr(QDialog, "exec", fake_exec)
        assert dlg._edit_op_step(0, dlg._steps[0]) is True
        assert seen["text"] == "Legacy Vendor Step"
        assert dlg._steps[0][1] == "Legacy Vendor Step"
    finally:
        dlg.deleteLater()


def test_empty_operation_name_never_saves_custom_operation(qapp, monkeypatch):
    step = ("op", "Power On DUT", "—", "—", "—", "—", None)
    dlg = _SequenceEditorDialog("ict", [step], [True], [100], [5000])

    def fake_exec(widget):
        _standard_combo(widget).setCurrentText("")
        return QDialog.DialogCode.Accepted

    try:
        monkeypatch.setattr(QDialog, "exec", fake_exec)
        assert dlg._edit_op_step(0, dlg._steps[0]) is True
        assert dlg._steps[0][1] == "Power On DUT"
        assert dlg._steps[0][1] != "Custom Operation"
    finally:
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# §1 - left column: configurable hardware + optional placeholders
# ---------------------------------------------------------------------------
def test_left_column_lists_only_configurable_hardware(page):
    assert [(group, len(entries)) for group, entries in LEFT_ENTRIES] == [
        ("Instruments", 5), ("Fixture", 1), ("Peripherals", 9)]
    labels = [label for _g, entries in LEFT_ENTRIES
              for _key, label, _kind, _src in entries]
    for banned in ("display", "microphone", "speaker", " sd ", "usb",
                   "t1", "media converter", "power rail"):
        assert all(banned not in label.lower() for label in labels), banned
    # instrument / form / sub entries have a Config button ONLY; the
    # optional placeholders have a disabled "Not developed" button; the
    # group header has no button and the group_toggle has an Enable
    # checkbox.
    for _g, entries in LEFT_ENTRIES:
        for key, _label, kind, _src in entries:
            buttons = page.entry_buttons[key]
            if kind == "optional":
                assert set(buttons) == {"optional"}, key
            elif kind == "group":
                assert set(buttons) == set(), key
            elif kind == "group_toggle":
                assert set(buttons) == {"enable"}, key
            else:
                assert set(buttons) == {"config"}, key


def test_left_entries_has_no_dut_group():
    groups = [group for group, _entries in LEFT_ENTRIES]
    assert "DUT" not in groups
    keys = [key for _g, entries in LEFT_ENTRIES
            for key, _label, _kind, _src in entries]
    assert "dut_interface" not in keys
    assert "dut_console" not in keys
    assert "dut_ssh" not in keys


def test_optional_entry_renders_disabled_not_developed(page):
    """m122: the badge is short ("N/A") so it fit the 92 px column; the
    long caption is the tooltip. Still greyed and non-clickable."""
    for key in ("rf_test_set",):
        badge = page.entry_buttons[key]["optional"]
        assert badge.text() == "N/A"
        assert "Not developed" in badge.toolTip()
        assert badge.isEnabled() is False
        assert badge.cursor().shape() == Qt.CursorShape.ForbiddenCursor


def test_left_column_collapses_and_expands(page):
    assert not page.left_list.isHidden()
    page.btn_collapse.click()
    assert page.left_list.isHidden()
    page.btn_collapse.click()
    assert not page.left_list.isHidden()


def test_splitter_never_wider_than_right_column(page):
    page.splitter.setSizes([1000, 100])
    page.splitter.splitterMoved.emit(1000, 1)
    left, right = page.splitter.sizes()
    assert left <= right


def test_left_column_is_scrollable(page):
    assert page.left_list.widgetResizable()
    assert page.left_list.widget() is not None


# ---------------------------------------------------------------------------
# §1.2 - DAQ973A Mainframe: one dialog, one self-test
# ---------------------------------------------------------------------------
def test_daq_mainframe_one_config_dialog_covers_three_modules(page,
                                                              monkeypatch):
    captured = {}

    def fake_exec(dlg):
        captured["dlg"] = dlg
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    page.open_entry("daq973a")
    dlg = captured["dlg"]
    assert isinstance(dlg, _InstrumentDialog)
    assert "DAQ973A Mainframe" in dlg.windowTitle()
    texts = [edit.text() for edit in dlg.findChildren(QLineEdit)]
    blob = " ".join(texts)
    for module in ("DAQM908A #1", "DAQM908A #2", "DAQM907A"):
        assert module in blob
    dlg.deleteLater()


def test_daq_mainframe_one_self_test_button(page):
    """M54 §1: the ONE self-test action lives INSIDE the Config dialog -
    no row-level Test button exists any more."""
    from mtkgui.equipment_page import _INSTRUMENT_ACTIONS
    self_tests = [label for label, _fn in _INSTRUMENT_ACTIONS["daq973a"]
                  if label == "Self Test"]
    assert self_tests == ["Self Test"]
    assert "test" not in page.entry_buttons["daq973a"]


# ---------------------------------------------------------------------------
# §2 - the right column diagram is READ-ONLY
# ---------------------------------------------------------------------------
def test_diagram_click_opens_read_only_hardware_info(page, monkeypatch):
    captured = {"count": 0, "dlg": None}

    def fake_exec(dlg):
        captured["count"] += 1
        captured["dlg"] = dlg
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    page._on_block_clicked(page.blocks["daq973a"])
    assert captured["count"] == 1
    dlg = captured["dlg"]
    assert isinstance(dlg, _HardwareInfoDialog)
    assert not isinstance(dlg, _InstrumentDialog)
    # every field is read-only and there is no edit / config control
    edits = dlg.findChildren(QLineEdit)
    assert edits and all(edit.isReadOnly() for edit in edits)
    labels = [btn.text() for btn in dlg.findChildren(QPushButton)]
    assert not any(text in ("Config", "Save", "Apply") for text in labels)


def test_hardware_info_shows_specs_and_connections(page):
    dlg = _HardwareInfoDialog(
        page, "DAQ973A Mainframe", page._info_fields("daq973a"),
        page._info_connections("daq973a"))
    try:
        labels = []
        for edit in dlg.findChildren(QLineEdit):
            assert edit.isReadOnly()
            labels.append(edit.text())
        blob = " ".join(labels)
        assert "Keysight DAQ973A" in blob
        assert "SCPI" in blob
    finally:
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# §3 - instrument lamps: grey / yellow / green
# ---------------------------------------------------------------------------
def test_instrument_state_grey_yellow_green(page):
    assert page.instrument_state("daq973a") == "grey"
    page._instrument_connections["daq973a"] = True
    assert page.instrument_state("daq973a") == "yellow"
    # M54 §1: the self-test result comes from the Config dialog (the
    # page-level Test button is gone) but still drives the lamp
    page._set_instrument_selftest("daq973a", True)
    assert page.instrument_state("daq973a") == "green"


def test_instrument_row_has_led(page):
    """M100: the per-instrument LEDs moved from the status bar onto each
    instrument row in the left column."""
    for key in ("daq973a", "u2355a", "psu"):
        assert key in page.entry_leds, key
    assert page.btn_refresh.text() == "Refresh"
    assert page.btn_selftest_all.text() == "Self-Test All"


def test_refresh_runs_in_background_and_does_not_block(page, qapp):
    page._refresh_instruments()
    # the button flips to Busy immediately; the GUI thread was not held
    assert page.btn_refresh.text() == "Busy…"
    assert page.btn_refresh.isEnabled() is False
    _pump(qapp, lambda: page.btn_refresh.text() == "Refresh")
    for key in ("daq973a", "u2355a", "psu"):
        assert page._instrument_connections[key] is True
    # Refresh never marks the self-test as passed (still untested)
    assert page._instrument_selftest.get("psu") is not True


def test_selftest_all_turns_led_green(page, qapp):
    page._selftest_all_instruments()
    assert page.btn_selftest_all.text() == "Busy…"
    _pump(qapp, lambda: page.btn_selftest_all.text() == "Self-Test All")
    for key in ("daq973a", "u2355a", "psu"):
        assert page._instrument_connections[key] is True
        assert page._instrument_selftest[key] is True
        assert "#22c55e" in page.entry_leds[key].styleSheet()


def _pump(qapp, predicate, timeout_ms=3000):
    from PySide6.QtCore import QThread
    deadline = 0
    while deadline < timeout_ms:
        qapp.processEvents()
        if predicate():
            return True
        QThread.msleep(10)
        deadline += 10
    qapp.processEvents()
    return predicate()


# ---------------------------------------------------------------------------
# §5 - equipment yaml state model: load auto-fills, save persists
# ---------------------------------------------------------------------------
def test_grouped_equipment_state_round_trips(page):
    import yaml as pyyaml

    from mtkgui import project_config

    page.configs["dut"]["groups"]["ssh"] = {
        "ip": "192.168.1.60", "username": "root", "password": "secret"}
    page.configs["host_pc"]["groups"]["rj45"] = {
        "host_ip": "10.0.0.5", "lan_port": "en5", "gateway": "10.0.0.1"}
    page.configs["control_board"]["groups"]["signals"]["press"]["channel"] = \
        "DIO09"

    equipment = project_config._equipment_to_yaml(page.configs)
    assert equipment["dut"]["ssh"]["ip"] == "192.168.1.60"
    assert equipment["host_pc"]["rj45"]["host_ip"] == "10.0.0.5"
    assert equipment["control_board"]["signals"]["press"]["channel"] == \
        "DIO09"

    restored = project_config._equipment_from_yaml(
        pyyaml.safe_load(pyyaml.safe_dump(equipment)))
    assert restored["dut"]["groups"]["ssh"]["username"] == "root"
    assert restored["host_pc"]["groups"]["rj45"]["host_ip"] == "10.0.0.5"
    assert restored["control_board"]["groups"]["signals"]["press"][
        "channel"] == "DIO09"


def test_page_apply_save_yaml_button_emits_signal(page):
    seen = []
    page.apply_save_requested.connect(lambda: seen.append(True))
    page.btn_apply_save.click()
    assert seen == [True]


def test_refresh_from_configs_resets_connection_state(page):
    page._instrument_connections["u2355a"] = True
    page._instrument_selftest["u2355a"] = True
    page.refresh_from_configs()
    assert page.instrument_state("u2355a") == "grey"
