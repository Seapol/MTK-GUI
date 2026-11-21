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
    _ControlBoardDialog,
    _InstrumentDialog,
    _TESTABLE_FORM_KEYS,
    _mock_configs,
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
    # M100: the network groups moved out of ``peripherals`` into the
    # dedicated ``host_pc`` / ``router`` configs.
    assert "groups" not in page.configs["peripherals"]
    assert set(page.configs["host_pc"]["groups"]) == {
        "serial", "ssh", "rj45", "wifi", "bluetooth"}
    assert set(page.configs["router"]["groups"]) == {
        "enabled", "ethernet", "ap"}


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
def test_control_board_config_opens_without_daq_gate(qapp):
    page = EquipmentPage()
    button = page.entry_buttons["control_board"]["config"]
    try:
        # M100: the DAQ973A "connect first" gate is gone - the Config
        # button and the dialog's OK are always enabled
        assert button.isEnabled() is True
        assert button.toolTip() == ""
    finally:
        page.deleteLater()


def test_m80_control_board_channel_dropdown_is_8_read_8_write(qapp):
    signals = {key: {"channel": channel, "direction": direction}
               for key, _label, channel, direction in DIO_SIGNALS}
    dlg = _ControlBoardDialog(None, "ATE Fixture Control Board", signals)
    try:
        assert DIO_CHANNELS == tuple(
            [f"DIO_R{index:02d}" for index in range(1, 9)]
            + [f"DIO_W{index:02d}" for index in range(1, 9)])
        assert len(DIO_CHANNELS) == 16
        for combo, _in, _out in dlg._rows.values():
            assert [combo.itemText(index) for index in range(combo.count())] \
                == ["", *DIO_CHANNELS]
    finally:
        dlg.deleteLater()


def test_dio_channels_are_8_read_8_write():
    read = [f"DIO_R{index:02d}" for index in range(1, 9)]
    write = [f"DIO_W{index:02d}" for index in range(1, 9)]
    assert DIO_CHANNELS == tuple(read + write)
    assert len(read) == 8 and len(write) == 8


def test_dio_signal_directions_read_group():
    directions = {key: direction
                  for key, _label, _channel, direction in DIO_SIGNALS}
    assert directions["press"] == "output"
    assert directions["inpos"] == "input"
    assert directions["presence"] == "input"
    assert directions["estop"] == "input"
    # the read group (DIO_R*) is input, the write group (DIO_W*) output
    for key, _label, channel, direction in DIO_SIGNALS:
        if channel.startswith("DIO_R"):
            assert direction == "input", key
        elif channel.startswith("DIO_W"):
            assert direction == "output", key


def test_m80_control_board_duplicate_channel_is_error(qapp):
    dlg = _ControlBoardDialog(None, "ATE Fixture Control Board", {})
    try:
        dlg._rows["inpos"][0].setCurrentText("DIO_R02")
        errors = dlg.validate()
        assert errors
        assert "DIO_R02" in errors[0]
    finally:
        dlg.deleteLater()


def test_m80_control_board_direction_round_trip(qapp):
    dlg = _ControlBoardDialog(None, "ATE Fixture Control Board", {})
    try:
        dlg._rows["press"][2].setChecked(True)      # Output
        dlg._rows["estop"][1].setChecked(True)      # Input
        values = dlg.values()
        assert values["press"]["direction"] == "output"
        assert values["estop"]["direction"] == "input"
        assert values["estop"]["channel"] == "DIO_R03"
        back = _ControlBoardDialog(None, "ATE Fixture Control Board",
                                   values)
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


def test_m80_ssh_login_entry_removed(page):
    assert "dut_ssh" not in _entry_keys()
    assert "dut_ssh" not in page.entry_buttons
    # M100: the DUT SSH / console editor moved into the FCT steps (the
    # Console panel still mirrors serial / SSH into equipment.dut.*)
    assert ("dut", "ssh") not in GROUP_FIELDS
    assert ("dut", "console") not in GROUP_FIELDS


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


def test_m80_pc_wifi_and_pc_bt_entries_removed(page):
    assert "pc_wifi" not in _entry_keys()
    assert "pc_bt" not in _entry_keys()
    assert "pc_wifi" not in _TESTABLE_FORM_KEYS
    assert "pc_bt" not in _TESTABLE_FORM_KEYS


def test_m80_fct_refs_still_resolve(page):
    from mtkgui.engine import ref_resolver

    page.configs["dut"]["groups"]["ssh"] = {
        "ip": "192.168.1.60", "username": "root", "password": "secret"}
    page.configs["dut"]["groups"]["console"] = {
        "channel": "ser1", "port": "/dev/tty.test", "baud": "115200",
        "parity": "None"}
    doc = {"equipment": project_config._equipment_to_yaml(page.configs)}
    assert ref_resolver.resolve("equipment.dut.ssh.ip", doc) == \
        "192.168.1.60"
    assert ref_resolver.resolve("equipment.dut.console.port", doc) == \
        "/dev/tty.test"
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
