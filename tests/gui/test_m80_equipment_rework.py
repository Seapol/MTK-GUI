# -*- coding: utf-8 -*-
"""M80: Equipment page rework (layout, deletions, merges, network modes).

Part A covers the layout, the removed entries, the merged DUT Interface,
the gated control board and the read-only host Bluetooth block.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QWidget,
)

from mtkgui import project_config  # noqa: E402
from mtkgui.engine import host_platform  # noqa: E402
from mtkgui.equipment_page import (  # noqa: E402
    DIO_CHANNELS,
    DIO_SIGNALS,
    EquipmentPage,
    GROUP_FIELDS,
    LEFT_ENTRIES,
    LEFT_COLUMN_MAX_PX,
    LEFT_COLUMN_MIN_PX,
    DutInterfaceDialog,
    RouterNetworkDialog,
    _ControlBoardDialog,
    _InstrumentDialog,
    _TopologyDiagram,
    _TESTABLE_FORM_KEYS,
    _mock_configs,
    host_bluetooth_block,
    normalise_dut_ports,
)
from mtkgui.gui.yamlbuild.instrument_status import HUB  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _hub_reset():
    HUB.disconnect()
    yield
    HUB.disconnect()


@pytest.fixture()
def page(qapp):
    p = EquipmentPage()
    p.resize(1600, 900)
    p.show()
    qapp.processEvents()
    yield p
    p.close()
    p.deleteLater()


def _entry_keys() -> list:
    return [key for _group, entries in LEFT_ENTRIES
            for key, _label, _kind, _source in entries]


def _instrument(parent=None, key="daq973a", last_size=None, config=None):
    cfg = _mock_configs()[key]
    return _InstrumentDialog(parent, cfg["title"], cfg["fields"], key, True,
                             config=config if config is not None else cfg,
                             last_size=last_size)


def _record_exec(monkeypatch, action=None):
    captured = {}

    def fake_exec(dlg):
        captured["dlg"] = dlg
        if callable(action):
            action(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    return captured


# --------------------------------------------------------- M80-1 left column
def test_m80_left_column_fits_longest_label(page):
    assert page.computed_left_width >= LEFT_COLUMN_MIN_PX
    assert page.computed_left_width <= LEFT_COLUMN_MAX_PX
    for key, name in page.entry_labels.items():
        label = name.toolTip()
        metrics = name.fontMetrics()
        assert page.computed_left_width >= \
            metrics.horizontalAdvance(label) + 92, key
        # no elision at the default width
        assert label == name.text(), key


def test_m80_left_column_clamped_320_480(page):
    assert LEFT_COLUMN_MIN_PX == 320
    assert LEFT_COLUMN_MAX_PX == 480
    assert LEFT_COLUMN_MIN_PX <= page.computed_left_width
    assert page.computed_left_width <= LEFT_COLUMN_MAX_PX


# ------------------------------------------------- M80-2 / M80-3 instruments
def test_m80_instrument_dialog_min_size_and_connection_visible(qapp):
    dlg = _instrument()
    try:
        assert dlg.width() >= 980
        assert dlg.height() >= 860
        # Connection first, Instrument Information last
        assert dlg._group_order[0] is dlg._conn_group
        assert dlg._group_order[1] is dlg._param_group
        assert dlg._group_order[3] is dlg._info_group
        assert dlg._info_content.isVisible() is False
        line = dlg._output.fontMetrics().lineSpacing()
        assert dlg._output.minimumHeight() >= 8 * line
    finally:
        dlg.deleteLater()


def test_m80_instrument_dialog_remembers_last_size(page, monkeypatch):
    def size_it(dlg):
        dlg.resize(980, 860)

    _record_exec(monkeypatch, size_it)
    page.open_entry("daq973a")
    first = page._instrument_sizes["daq973a"]
    assert first.width() == 980
    assert first.height() == 860
    dlg = _instrument(last_size=QSize(980, 860))
    try:
        assert dlg.width() == 980
        assert dlg.height() == 860
    finally:
        dlg.deleteLater()


def test_m80_address_is_editable_combo_with_refresh(qapp):
    dlg = _instrument()
    cfg = {"title": "DAQ973A Mainframe"}
    try:
        assert isinstance(dlg._address, QComboBox)
        assert dlg._address.isEditable()
        assert dlg.btn_refresh.text() == "Refresh"
        dlg._address.setCurrentText("TCPIP0::1.2.3.4::inst0")
        dlg.apply_to_config(cfg)
        assert cfg["connection"]["address"] == "TCPIP0::1.2.3.4::inst0"
    finally:
        dlg.deleteLater()


def test_m80_address_scan_falls_back_without_pyvisa(qapp):
    dlg = _instrument()
    try:
        dlg._scan_addresses()
        log = dlg._output.toPlainText()
        assert "no VISA runtime found - showing known addresses only" in log
        assert dlg._address.findText("GPIB0::9::INSTR") >= 0
    finally:
        dlg.deleteLater()


# ------------------------------------------------ M80-4 fixture UI removal
def test_m80_fixture_probe_board_entry_removed(page):
    assert "fixture" not in _entry_keys()
    assert "fixture" not in page.entry_buttons
    labels = [label for _g, entries in LEFT_ENTRIES
              for _key, label, _kind, _src in entries]
    assert "Fixture Probe Board" not in labels


def test_m80_fixture_probe_board_diagram_block_removed(page):
    assert "fixture" not in page.blocks
    assert "Fixture Probe Board" not in [
        item.text() for item in page.scene.items()
        if hasattr(item, "text")]


def test_m80_fixture_yaml_key_still_round_trips(page):
    equipment = project_config._equipment_to_yaml(page.configs)
    assert "fixture" in equipment
    restored = project_config._equipment_from_yaml(equipment)
    assert "fixture" in restored
    assert restored["fixture"]["title"] == "Fixture"


# ------------------------------------------------------- M80-5 control board
def test_m80_control_board_config_gated_by_daq_status(qapp):
    page = EquipmentPage()
    button = page.entry_buttons["control_board"]["config"]
    try:
        assert button.isEnabled() is False
        assert button.toolTip() == "Connect DAQ973A Mainframe first"
        HUB.set_connected(True)
        HUB.set_test_connection("OK")
        assert button.isEnabled() is True
        assert button.toolTip() == ""
    finally:
        page.deleteLater()


def test_m80_control_board_channel_dropdown_is_dio01_dio08(qapp):
    signals = {key: {"channel": channel, "direction": direction}
               for key, _label, channel, direction in DIO_SIGNALS}
    dlg = _ControlBoardDialog(None, "ATE Fixture Control Board", signals,
                              True)
    try:
        assert DIO_CHANNELS == tuple(f"DIO{index:02d}"
                                     for index in range(1, 9))
        for combo, _in, _out in dlg._rows.values():
            assert [combo.itemText(index) for index in range(combo.count())] \
                == ["", *DIO_CHANNELS]
    finally:
        dlg.deleteLater()


def test_m80_control_board_duplicate_channel_is_error(qapp):
    dlg = _ControlBoardDialog(None, "ATE Fixture Control Board", {}, True)
    try:
        dlg._rows["inpos"][0].setCurrentText("DIO01")
        errors = dlg.validate()
        assert errors
        assert "DIO01" in errors[0]
    finally:
        dlg.deleteLater()


def test_m80_control_board_direction_round_trip(qapp):
    dlg = _ControlBoardDialog(None, "ATE Fixture Control Board", {}, True)
    try:
        dlg._rows["press"][2].setChecked(True)      # Output
        dlg._rows["estop"][1].setChecked(True)      # Input
        values = dlg.values()
        assert values["press"]["direction"] == "output"
        assert values["estop"]["direction"] == "input"
        assert values["estop"]["channel"] == "DIO04"
        back = _ControlBoardDialog(None, "ATE Fixture Control Board",
                                   values, True)
        try:
            assert back.values() == values
        finally:
            back.deleteLater()
    finally:
        dlg.deleteLater()


# ------------------------------------------------------ M80-6 DUT restructure
def test_m80_dut_board_os_entry_removed(page):
    assert "dut_os" not in _entry_keys()
    assert ("dut", "board_os") not in GROUP_FIELDS


def test_m80_dut_interface_edits_wifi_bt_lan_together(qapp, page):
    dlg = DutInterfaceDialog(None, {"ssid": "old", "interface": "mlan0"},
                             {"name": "old-bt", "bd_addr": ""},
                             "eth0", "10.0.0.2")
    try:
        dlg._wifi["ssid"].setText("DUT-AP")
        dlg._bt["name"].setText("DUT-BT")
        dlg.edit_ports.setText("eth0,eth1")
        values = dlg.values()
    finally:
        dlg.deleteLater()
    assert values["wifi"]["ssid"] == "DUT-AP"
    assert values["bluetooth"]["name"] == "DUT-BT"
    assert values["ethernet_ports"] == "eth0,eth1"
    page.apply_dut_interface(values["wifi"], values["bluetooth"],
                             values["ethernet_ports"])
    groups = page.configs["dut"]["groups"]
    assert groups["wifi"]["ssid"] == "DUT-AP"
    assert groups["bluetooth"]["name"] == "DUT-BT"
    assert groups["interface"]["ethernet"]["ports"] == "eth0,eth1"


def test_m80_dut_interface_ports_comma_normalised(qapp):
    assert normalise_dut_ports(" eth0, ,eth1,eth0,bad port! ") == "eth0,eth1"
    assert normalise_dut_ports("") == ""
    dlg = DutInterfaceDialog(None, {}, {}, "eth0, eth0, eth2, bad!", "")
    try:
        assert dlg.values()["ethernet_ports"] == "eth0,eth2"
    finally:
        dlg.deleteLater()


def test_m80_dut_interface_has_no_test_button(page, monkeypatch):
    captured = {}

    def fake_exec(dlg):
        captured["dlg"] = dlg
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    page.open_entry("dut_interface")
    dlg = captured["dlg"]
    try:
        labels = [button.text() for button in dlg.findChildren(QWidget)
                  if hasattr(button, "text")]
        assert "Test Connection" not in labels
    finally:
        dlg.deleteLater()
    assert "dut_interface" not in _TESTABLE_FORM_KEYS


def test_m80_ssh_login_entry_removed(page):
    assert "dut_ssh" not in _entry_keys()
    assert "dut_ssh" not in page.entry_buttons
    # the YAML paths stay alive (fed by the Console panel)
    assert ("dut", "ssh") in GROUP_FIELDS


def test_m80_console_mirrors_into_equipment_yaml(qapp):
    from mtkgui.test_workflow_page import TestWorkFlowPage

    page = TestWorkFlowPage()
    try:
        configs = _mock_configs()
        page.equipment_configs_provider = lambda: configs
        page.multi_console.set_channel_params(
            "ser1", {"port": "/dev/tty.test", "baudrate": 115200})
        page.multi_console.add_ssh()
        page.multi_console.set_channel_params(
            "ssh1", {"host": "192.168.1.60", "username": "root",
                     "password": "secret"})
        page._mirror_console_channels()
        groups = configs["dut"]["groups"]
        assert groups["console"]["channel"] == "ser1"
        assert groups["console"]["port"] == "/dev/tty.test"
        assert groups["console"]["baud"] == "115200"
        assert groups["ssh"]["ip"] == "192.168.1.60"
        assert groups["ssh"]["username"] == "root"
    finally:
        page.deleteLater()


def test_m80_console_config_navigates_to_workflow(qapp, monkeypatch):
    window = QMainWindow()
    tabs = QTabWidget(window)
    workflow = QWidget()
    tabs.addTab(workflow, "Test Work Flow")
    window.tabs = tabs
    window.workflow_page = workflow
    window.setCentralWidget(tabs)
    page = EquipmentPage(window)
    window.show()
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    try:
        page._open_console_pointer()
        assert tabs.currentWidget() is workflow
    finally:
        page.deleteLater()
        window.deleteLater()


# -------------------------------------------- M80-7 network dialog layout
def test_m80_network_dialog_no_top_gap(qapp):
    dlg = RouterNetworkDialog(None, {}, save_callback=None)
    dlg.resize(700, 620)
    dlg.show()
    qapp.processEvents()
    try:
        note = next(label for label in dlg.findChildren(QLabel)
                    if label.text().startswith("Wired (RJ45) and Wireless"))
        assert note.height() <= note.sizeHint().height() + 4
    finally:
        dlg.deleteLater()


def test_m80_network_dialog_fonts_at_least_10pt(qapp):
    assert _TopologyDiagram.FONT_PT >= 10.0


# --------------------------------------------- M80-8 / M80-9 host PC blocks
def test_m80_host_bt_info_is_read_only(qapp, monkeypatch):
    monkeypatch.setattr(host_platform, "host_bt_identity",
                        lambda: ("PC-BT", "AA:BB:CC:DD:EE:FF"))
    box = host_bluetooth_block()
    try:
        edits = box.findChildren(QLineEdit)
        assert [edit.text() for edit in edits] == \
            ["PC-BT", "AA:BB:CC:DD:EE:FF"]
        assert all(edit.isReadOnly() for edit in edits)
    finally:
        box.deleteLater()
    monkeypatch.setattr(host_platform, "host_bt_identity",
                        lambda: (_ for _ in ()).throw(RuntimeError("no bt")))
    box = host_bluetooth_block()
    try:
        assert [edit.text() for edit in box.findChildren(QLineEdit)] == \
            ["unavailable", "unavailable"]
    finally:
        box.deleteLater()


def test_m80_pc_wifi_and_pc_bt_entries_removed(page):
    assert "pc_wifi" not in _entry_keys()
    assert "pc_bt" not in _entry_keys()
    assert "pc_wifi" not in _TESTABLE_FORM_KEYS
    assert "pc_bt" not in _TESTABLE_FORM_KEYS


def test_m80_peripherals_wifi_mirrored_from_network(page, monkeypatch):
    monkeypatch.setattr(host_platform, "host_bt_identity",
                        lambda: ("PC-BT", ""))
    page._mirror_network_peripherals({
        "hotspot_ssid": "AP", "hotspot_password": "pw",
        "wifi_host_ip": "10.0.0.5"}, "DUT-BT")
    groups = page.configs["peripherals"]["groups"]
    assert groups["wifi"]["ap_ssid"] == "AP"
    assert groups["wifi"]["ap_password"] == "pw"
    assert groups["wifi"]["host_ip"] == "10.0.0.5"
    assert groups["bluetooth"]["scan_targets"] == "DUT-BT"
    assert groups["bluetooth"]["adapter"] == "PC-BT"
    equipment = project_config._equipment_to_yaml(page.configs)
    assert equipment["peripherals"]["wifi"]["ap_ssid"] == "AP"
