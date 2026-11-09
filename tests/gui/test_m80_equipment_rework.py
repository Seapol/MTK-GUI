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
    MODE_TITLES,
    DutInterfaceDialog,
    RouterNetworkDialog,
    _ControlBoardDialog,
    _InstrumentDialog,
    _RouterModeDialog,
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


def test_m80_pc_wifi_bt_peripheral_entries_removed(page):
    names = [row[0] for row in page.configs["peripherals"]["table"]]
    assert "PC Wi-Fi" not in names
    assert "PC Bluetooth" not in names
    assert "Wired & Wireless Network" in names
    assert {"wifi", "bluetooth", "router"} <= set(
        page.configs["peripherals"]["groups"])


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


# ===================================================== M80-B network modes
def test_m80_router_mode_has_no_host_wired_ip(qapp):
    dlg = _RouterModeDialog(None, "router", {}, None)
    try:
        assert "wired_host_ip" not in dlg._edits
        assert "router_ap_ssid" in dlg._edits
        assert "router_ap_password" in dlg._edits
        assert dlg._edits["router_ap_password"].toolTip() == \
            "the DUT also uses it when joining the same AP"
        assert dlg._edits["wifi_dut_iface"].toolTip() == (
            "login to the DUT and run 'ifconfig' to read the interface "
            "name (e.g. mlan0)")
    finally:
        dlg.deleteLater()


def test_m80_router_ssid_auto_detected(qapp, monkeypatch):
    monkeypatch.setattr(host_platform, "platform_key", lambda: "mac")
    canned = ("Interfaces:\n"
              "  en0:\n"
              "    Current Network Information:\n"
              "      Factory-AP:\n"
              "        Signal / Noise: -45 dBm / -90 dBm\n")

    def fake_cmd(cmd, *_args, **_kwargs):
        return canned if "SPAirPortDataType" in cmd else ""

    monkeypatch.setattr(host_platform, "run_link_cmd", fake_cmd)
    info = host_platform.detect_host_network()
    assert info["wifi_ssid"] == "Factory-AP"
    dlg = _RouterModeDialog(None, "router", {}, None)
    try:
        dlg._fill_auto(info)
        assert dlg._edits["router_ap_ssid"].text() == "Factory-AP"
        assert "router_ap_ssid" in dlg._auto_detected
        assert dlg._edits["router_ap_ssid"].isReadOnly() is False
    finally:
        dlg.deleteLater()


def test_m80_lan_mode_has_no_ethernet_ports(qapp):
    dlg = _RouterModeDialog(None, "lan", {}, None)
    try:
        assert "wired_eth_ports" not in dlg._edits
        assert "wired_host_port" in dlg._edits
    finally:
        dlg.deleteLater()


def test_m80_lan_mode_auto_detects_host_fields(qapp):
    dlg = _RouterModeDialog(None, "lan", {}, None)
    try:
        dlg._fill_auto({"wired_port": "en5", "wired_ip": "10.0.0.7",
                        "gateway": "10.0.0.1", "wifi_ip": ""})
        assert dlg._edits["wired_host_port"].text() == "en5"
        assert dlg._edits["wired_host_ip"].text() == "10.0.0.7"
        assert dlg._edits["wired_gateway"].text() == "10.0.0.1"
        assert {"wired_host_port", "wired_host_ip",
                "wired_gateway"} <= dlg._auto_detected
        # DUT Port(s) stays purely manual
        assert dlg._edits["wired_dut_ports"].text() == ""
    finally:
        dlg.deleteLater()


def test_m80_mode_titles_distinguish_wired_wireless(qapp):
    assert MODE_TITLES == {
        "direct": "Wired (RJ45) - Direct (no router)",
        "lan": "Wired (RJ45) - LAN via router",
        "hotspot": "Wireless (AP hotspot) - Host PC hotspot (no router)",
        "router": "Wireless (AP hotspot) - Wi-Fi router",
    }
    for mode, title in MODE_TITLES.items():
        dlg = _RouterModeDialog(None, mode, {}, None)
        try:
            assert dlg.windowTitle() == title
        finally:
            dlg.deleteLater()


def test_m80_single_click_only_selects(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(_RouterModeDialog, "exec",
                        lambda self: opened.append(self._mode))
    dlg = RouterNetworkDialog(None, {"wired_mode": "direct"}, None)
    try:
        dlg._cards["wired"]["lan"].clicked.emit("lan")
        assert opened == []
        assert dlg._values["wired_mode"] == "lan"
        assert dlg._cards["wired"]["lan"]._selected is True
        assert dlg._cards["wired"]["direct"]._selected is False
        assert "LAN via router" in dlg._hints["wired"].text()
    finally:
        dlg.deleteLater()


def test_m80_edit_button_opens_mode_dialog(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(_RouterModeDialog, "exec",
                        lambda self: opened.append(self._mode))
    dlg = RouterNetworkDialog(None, {"wired_mode": "lan"}, None)
    try:
        dlg._edit_buttons["wired"].click()
        assert opened == ["lan"]
    finally:
        dlg.deleteLater()


def test_m80_sibling_mode_resets_on_edit(qapp, monkeypatch):
    monkeypatch.setattr(_RouterModeDialog, "exec", lambda self: None)
    dlg = RouterNetworkDialog(None, {
        "wired_mode": "direct", "wired_host_port": "COM3",
        "wired_host_ip": "10.0.0.9",
        "wifi_mode": "hotspot", "hotspot_ssid": "AP"}, None)
    try:
        dlg._open_mode("wired", "lan")
        assert dlg._values["wired_host_port"] == ""
        assert dlg._values["wired_host_ip"] == ""
        # the wireless module keeps its own values
        assert dlg._values["hotspot_ssid"] == "AP"
    finally:
        dlg.deleteLater()


def test_m80_save_writes_only_selected_mode(qapp):
    dlg = RouterNetworkDialog(None, {
        "wired_mode": "lan", "wifi_mode": "router",
        "wired_host_port": "en5", "wired_gateway": "10.0.0.1",
        "router_ap_ssid": "Factory-AP", "wifi_gateway": "10.0.0.1",
        "router_ap_password": "pw", "hotspot_ssid": "stale"}, None)
    try:
        values = dlg.values()
    finally:
        dlg.deleteLater()
    assert values["wired_mode"] == "lan"
    assert values["wifi_mode"] == "router"
    assert values["wired_host_port"] == "en5"
    assert values["wired_gateway"] == "10.0.0.1"
    assert values["router_ap_ssid"] == "Factory-AP"
    assert "wired_eth_ports" not in values
    # M80-C3: an unselected mode's key that came from the input survives;
    # the selected mode's own field set is unchanged.
    assert values["hotspot_ssid"] == "stale"
    assert values["wired_enabled"] is True
    assert values["wifi_enabled"] is True


def test_m80_fct_refs_still_resolve(page):
    from mtkgui.engine import ref_resolver

    page.apply_dut_interface({"ssid": "DUT-AP", "interface": "mlan0"},
                             {"name": "DUT-BT", "bd_addr": ""}, "eth0")
    page.configs["dut"]["groups"]["ssh"] = {
        "ip": "192.168.1.60", "username": "root", "password": "secret"}
    page.configs["dut"]["groups"]["console"] = {
        "channel": "ser1", "port": "/dev/tty.test", "baud": "115200",
        "parity": "None"}
    page.configs["peripherals"]["groups"]["wifi"] = {
        "ap_ssid": "AP", "ap_ip": "", "host_ip": "10.0.0.5",
        "ap_password": "pw"}
    doc = {"equipment": project_config._equipment_to_yaml(page.configs)}
    assert ref_resolver.resolve("equipment.dut.wifi.ssid", doc) == "DUT-AP"
    assert ref_resolver.resolve("equipment.dut.ssh.ip", doc) == \
        "192.168.1.60"
    assert ref_resolver.resolve("equipment.dut.console.port", doc) == \
        "/dev/tty.test"
    assert ref_resolver.resolve("equipment.peripherals.wifi.ap_ssid", doc) \
        == "AP"
    # equipment.fixture stays in the schema (engine op path untouched)
    assert "fixture" in doc["equipment"]
    restored = project_config._equipment_from_yaml(doc["equipment"])
    assert "fixture" in restored


# ===================================================== M80-C2 / C3 guards
class _MirrorMc:
    def __init__(self, channels):
        self.channels = channels


class _MirrorShim:
    def __init__(self, channels, configs):
        self.multi_console = _MirrorMc(channels)
        self.equipment_configs_provider = lambda: configs


def test_m80_console_mirror_keeps_ssh_when_no_ssh_channel(qapp):
    from mtkgui.test_workflow_page import TestWorkFlowPage

    configs = _mock_configs()
    configs["dut"]["groups"]["ssh"] = {
        "ip": "192.168.1.60", "username": "root", "password": "secret"}
    shim = _MirrorShim({"ser1": {"kind": "serial",
                                 "params": {"port": "COM7",
                                            "baudrate": 115200}}}, configs)
    TestWorkFlowPage._mirror_console_channels(shim)
    assert configs["dut"]["groups"]["ssh"] == {
        "ip": "192.168.1.60", "username": "root", "password": "secret"}
    # the serial channel exists, so the console group IS updated
    assert configs["dut"]["groups"]["console"]["port"] == "COM7"
    equipment = project_config._equipment_to_yaml(configs)
    assert equipment["dut"]["ssh"]["ip"] == "192.168.1.60"


def test_m80_console_mirror_keeps_console_when_no_serial_channel(qapp):
    from mtkgui.test_workflow_page import TestWorkFlowPage

    configs = _mock_configs()
    configs["dut"]["groups"]["console"] = {
        "channel": "ser1", "port": "COM5", "baud": "115200",
        "parity": "None"}
    shim = _MirrorShim({"ssh1": {"kind": "ssh",
                                 "params": {"host": "192.168.1.60",
                                            "username": "root"}}}, configs)
    TestWorkFlowPage._mirror_console_channels(shim)
    assert configs["dut"]["groups"]["console"]["port"] == "COM5"
    assert configs["dut"]["groups"]["ssh"]["ip"] == "192.168.1.60"


def test_m80_save_keeps_unselected_mode_keys(qapp):
    dlg = RouterNetworkDialog(None, {
        "wired_mode": "direct", "wired_dut_ports": "eth0",
        "wired_host_port": "COM3", "wired_host_ip": "10.0.0.9",
        "wired_gateway": "10.0.0.1"}, None)
    try:
        values = dlg.values()
    finally:
        dlg.deleteLater()
    # the unselected LAN key that came from the input survives
    assert values["wired_gateway"] == "10.0.0.1"
    assert values["wired_dut_ports"] == "eth0"
    assert values["wired_host_port"] == "COM3"
    assert values["wired_host_ip"] == "10.0.0.9"
    # a key that was never in the YAML is not created out of nothing
    assert "router_ap_ssid" not in values
