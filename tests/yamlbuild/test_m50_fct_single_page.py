# -*- coding: utf-8 -*-
"""M50: FCT single-page rework.

Locks the M50 contract:
* §1 the panel has ONE page (Console / Wi-Fi / Bluetooth tabs removed);
* §2 every step row opens its own config dialog and each referenced
  field shows ``ref`` + the EFFECTIVE Equipment value + an override box;
* §3/§5 shared parameters live in the Equipment page and steps carry
  runtime references (``equipment.dut.ssh.ip`` ...);
* §4 every testable Equipment config exposes "Test Connection";
* §6 the new ``fct.steps`` schema is validated on load AND apply-save -
  an unknown / missing reference names the step and blocks the save;
* §7 the M47 templates / M48 Add menu / M49b RSSI rows survive.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import (QApplication, QDialog,  # noqa: E402
                               QLabel, QLineEdit)

import yaml  # noqa: E402

from mtkgui.engine.fct_test_config import (  # noqa: E402
    STEP_TYPE_BT_RSSI,
    STEP_TYPE_CONSOLE_SSH,
    STEP_TYPE_SFTP_GET,
    STEP_TYPE_WIFI_SCAN,
    console_command_for_label,
)
from mtkgui.engine.ref_resolver import (  # noqa: E402
    RefError,
    describe,
    effective,
    is_ref,
    resolve,
    validate_refs,
)
from mtkgui.equipment_page import EquipmentPage  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)
from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _steps(panel) -> list:
    node = yaml.safe_load(panel.values()["fct_steps_yaml"]) or {}
    return (node.get("fct") or {}).get("steps") or []


def _lines(dlg) -> list:
    return [label.text() for label in dlg.findChildren(QLabel)]


def _overrides(dlg) -> list:
    return [edit for edit in dlg.findChildren(QLineEdit)
            if "override" in edit.placeholderText()]


EQUIPMENT = {"equipment": {
    "dut": {"ssh": {"ip": "192.168.1.20", "username": "root",
                    "password": "pw"},
            "console": {"port": "/dev/cu.test", "baud": 115200},
            "wifi": {"ssid": "MTK-DUT-AP", "interface": "wlan0"},
            "bluetooth": {"name": "MTK-DUT", "bd_addr": "AA:BB:CC:DD:EE:FF"}},
    "peripherals": {"wifi": {"ap_ssid": "MTK-AP",
                             "ap_password": "secret"}},
}}


# --------------------------------------------------------- §3 ref_resolver
def test_ref_resolver_reads_the_equipment_yaml():
    assert is_ref("equipment.dut.ssh.ip")
    assert not is_ref("dut.ssh.ip")
    assert resolve("equipment.dut.ssh.ip", EQUIPMENT) == "192.168.1.20"
    assert resolve("equipment.peripherals.wifi.ap_ssid", EQUIPMENT) == "MTK-AP"
    assert describe("equipment.dut.ssh.ip") == "SSH Login - IP address"
    # an override always wins over the referenced value
    assert effective("equipment.dut.ssh.ip", "10.0.0.9",
                     EQUIPMENT) == "10.0.0.9"


def test_ref_resolver_rejects_unknown_and_missing_paths():
    with pytest.raises(RefError) as err:
        resolve("equipment.not.a.real.path", EQUIPMENT)
    assert "unknown equipment reference" in str(err.value)
    with pytest.raises(RefError) as err:
        resolve("equipment.dut.ssh.ip", {})
    assert "is not set" in str(err.value)
    with pytest.raises(RefError) as err:
        resolve("dut.ssh.ip", EQUIPMENT)
    assert "is not an equipment reference" in str(err.value)


def test_validate_refs_names_the_step_and_the_path():
    steps = [{"name": "bad row",
              "ref": {"port": "equipment.not.a.real.path"}}]
    errors = validate_refs(steps, EQUIPMENT)
    assert len(errors) == 1
    assert "bad row" in errors[0] and "equipment.not.a.real.path" in errors[0]


# ------------------------------------------------------- §1 single page
def test_panel_has_exactly_one_sequence_page(qapp):
    panel = FCTTestConfigPanel()
    labels = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert labels == ["Sequence"]
    assert panel.tabs.tabBar().isVisible() is False


# ---------------------------- §2 per-test dialog: ref + effective + override
def test_rf_step_dialog_shows_ref_effective_and_override(qapp, monkeypatch):
    panel = FCTTestConfigPanel(equipment_provider=lambda: EQUIPMENT)
    panel._add_row_for_label(STEP_TYPE_WIFI_SCAN)
    seen = {}

    def fake_exec(dlg):
        seen["lines"] = _lines(dlg)
        seen["overrides"] = _overrides(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(0)
    assert any("ref: equipment.peripherals.wifi.ap_ssid" in t
               for t in seen["lines"])
    assert any("effective: MTK-AP" in t for t in seen["lines"])
    assert len(seen["overrides"]) == 2


def test_rf_step_dialog_override_is_saved_on_accept(qapp, monkeypatch):
    panel = FCTTestConfigPanel(equipment_provider=lambda: EQUIPMENT)
    panel._add_row_for_label(STEP_TYPE_WIFI_SCAN)

    def fake_exec(dlg):
        edits = _overrides(dlg)
        edits[0].setText("LAB-AP")            # override the AP SSID only
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(0)
    step = _steps(panel)[0]
    assert step["ref"]["ap_ssid"] == "equipment.peripherals.wifi.ap_ssid"
    assert step["override"]["ap_ssid"] == "LAB-AP"


def test_equipment_edit_flows_into_every_referencing_step(qapp):
    """§3: the step stores a reference, never a copy - editing the
    Equipment value changes the row's effective value live."""
    node = {"equipment": {"peripherals": {"wifi": {"ap_ssid": "MTK-AP"}}}}
    panel = FCTTestConfigPanel(equipment_provider=lambda: node)
    cmd = console_command_for_label(STEP_TYPE_WIFI_SCAN)
    cmd.refs = {"ap_ssid": "equipment.peripherals.wifi.ap_ssid"}
    panel._insert_row(cmd)
    assert panel._rf_summary(panel._get_row_cmd(0)) == \
        "AP=MTK-AP, RSSI\u2265-70 dBm"
    node["equipment"]["peripherals"]["wifi"]["ap_ssid"] = "NEW-AP"
    assert panel._rf_summary(panel._get_row_cmd(0)) == \
        "AP=NEW-AP, RSSI\u2265-70 dBm"


def test_ssh_step_dialog_references_the_equipment_ssh_login(qapp,
                                                            monkeypatch):
    panel = FCTTestConfigPanel(equipment_provider=lambda: EQUIPMENT)
    panel._add_row_for_label(STEP_TYPE_SFTP_GET)
    seen = {}

    def fake_exec(dlg):
        seen["lines"] = _lines(dlg)
        seen["overrides"] = _overrides(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(0)
    assert any("ref: equipment.dut.ssh.ip" in t for t in seen["lines"])
    assert any("effective: 192.168.1.20" in t for t in seen["lines"])
    assert len(seen["overrides"]) >= 3      # host / username / password


# ------------------------------- §6 validation blocks load AND apply-save
def test_unknown_reference_blocks_the_apply_save(qapp):
    page = YamlBuildPage()
    page.equipment_provider = lambda: EQUIPMENT
    bad = {"fct": {"dut_type": "linux", "steps": [
        {"type": "Console_serial", "name": "bad row",
         "ref": {"port": "equipment.not.a.real.path"}}]}}
    cases, errors = page._emit_fct_sequence(
        {"fct_steps_yaml": yaml.safe_dump(bad)})
    assert cases is None
    assert errors and "bad row" in errors[0]
    assert "equipment.not.a.real.path" in errors[0]


def test_missing_reference_value_blocks_the_apply_save(qapp):
    page = YamlBuildPage()
    page.equipment_provider = lambda: {"equipment": {"dut": {}}}
    bad = {"fct": {"dut_type": "linux", "steps": [
        {"type": "Console_serial", "name": "no ssh",
         "ref": {"host": "equipment.dut.ssh.ip"}}]}}
    cases, errors = page._emit_fct_sequence(
        {"fct_steps_yaml": yaml.safe_dump(bad)})
    assert cases is None
    assert any("no ssh" in e and "equipment.dut.ssh.ip" in e
               for e in errors)


def test_valid_schema_round_trips_through_load_and_emit(qapp):
    panel = FCTTestConfigPanel(equipment_provider=lambda: EQUIPMENT)
    panel._add_row_for_label(STEP_TYPE_WIFI_SCAN)
    panel._add_row_for_label(STEP_TYPE_BT_RSSI)
    loaded = panel.values()
    page = YamlBuildPage()
    page.equipment_provider = lambda: EQUIPMENT
    cases, errors = page._emit_fct_sequence(loaded)
    assert errors == []
    assert cases
    # the rows keep their runtime references across the round-trip
    steps = _steps(panel)
    assert steps[0]["ref"]["ap_ssid"] == \
        "equipment.peripherals.wifi.ap_ssid"
    assert steps[1]["ref"]["bt_name"] == "equipment.dut.bluetooth.name"


# ---------------------------------------------------- §5 SSH credentials
def test_ssh_and_serial_rows_reference_the_equipment_dut_group(qapp):
    panel = FCTTestConfigPanel(equipment_provider=lambda: EQUIPMENT)
    serial = console_command_for_label("Console_serial")
    serial.refs = panel._default_refs(serial)
    panel._insert_row(serial)
    ssh = console_command_for_label(STEP_TYPE_CONSOLE_SSH)
    ssh.refs = panel._default_refs(ssh)
    panel._insert_row(ssh)
    steps = _steps(panel)
    assert steps[0]["ref"] == {"port": "equipment.dut.console.port",
                               "baud": "equipment.dut.console.baud",
                               "parity": "equipment.dut.console.parity"}
    assert steps[1]["ref"] == {"host": "equipment.dut.ssh.ip",
                               "username": "equipment.dut.ssh.username",
                               "password": "equipment.dut.ssh.password"}


# ----------------------------------------------- §4 Test Connection buttons
def test_each_testable_equipment_config_has_a_test_button(qapp):
    page = EquipmentPage()
    try:
        for key in ("pc_wifi", "pc_bt", "router", "jlink",
                    "dut_wifi", "dut_bt", "dut_ssh", "dut_console"):
            buttons = page.entry_buttons[key]
            assert "test" in buttons, key
            assert buttons["test"].toolTip() == "Test Connection"
        # a non-testable config keeps Config only
        assert "test" not in page.entry_buttons["fixture"]
    finally:
        page.deleteLater()


# -------------------------------------------- §7 M47 / M48 / M49b survive
def test_m47_load_template_still_appends_ordinary_rows(qapp):
    from mtkgui.engine.fct_templates import TEMPLATE_BARE_METAL
    panel = FCTTestConfigPanel()
    panel._load_template(TEMPLATE_BARE_METAL)
    assert panel.cmd_table.rowCount() == 9


def test_m48_network_add_menu_and_m49b_rssi_rows_survive(qapp):
    from mtkgui.engine.steps import WIFI_CONNECT_OP
    panel = FCTTestConfigPanel(equipment_provider=lambda: EQUIPMENT)
    assert WIFI_CONNECT_OP in panel._network_add_actions
    panel._add_operation_row(WIFI_CONNECT_OP)
    panel._add_row_for_label(STEP_TYPE_WIFI_SCAN)
    panel._add_row_for_label(STEP_TYPE_BT_RSSI)
    steps = _steps(panel)
    assert steps[0]["ref"]["ssid"] == \
        "equipment.peripherals.wifi.ap_ssid"
    assert steps[0]["op_params"]["ssid"] == "MTK-AP"
    assert steps[1]["ref"]["ap_ssid"] == \
        "equipment.peripherals.wifi.ap_ssid"
    assert steps[2]["ref"]["bt_name"] == "equipment.dut.bluetooth.name"
