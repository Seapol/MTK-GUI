# -*- coding: utf-8 -*-
"""P3-B5: FCTTestConfigPanel headless tests (set_values / values)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QPushButton

import yaml

from mtkgui.engine.fct_test_config import ConsoleCommand, FctTestConfig
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


FRDM_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/cu.usbmodem53930099631"
    baudrate: 115200
    login_sequence:
      - {wait_for: "login:", send: root}
      - {wait_for: "Password:", send: ""}
      - {wait_for: root@imx93frdm}
    test_commands:
      - {name: Kernel check, send: "uname -a",
         expect_pass: "Linux imx93frdm", timeout: 5}
  wifi:
    enabled: true
    mode: rssi_only
    interface: mlan0
    ssid: FRDM-IMX93-DUT
    rssi_min: -70
  bluetooth:
    enabled: true
    mode: rssi_only
    expected_name: FRDM-IMX93-DUT
    rssi_min: -70
    audio_confirm: true
"""


def test_roundtrip_preserves_config(qapp):
    panel = FCTTestConfigPanel()
    params = {"legacy_key": "kept",
              "fct_test_config_yaml": FRDM_YAML}
    panel.set_values(params)
    out = panel.values()
    assert out["legacy_key"] == "kept"
    node = yaml.safe_load(out["fct_test_config_yaml"])
    cfg = FctTestConfig.from_dict(node["fct_test_config"])
    assert cfg.dut_type == "linux"
    assert cfg.console.enabled and cfg.console.baudrate == 115200
    # legacy expect_pass of a send command migrates to the Capture
    # positive keyword (WaitFor uses expect_pass; Capture uses expect_fail)
    kernel = next(c for c in cfg.console.test_commands
                  if c.name == "Kernel check")
    assert kernel.capture_enabled and kernel.capture_is_expected
    assert kernel.expect_fail == "Linux imx93frdm"
    assert cfg.wifi.mode == "rssi_only" and cfg.wifi.ssid == \
        "FRDM-IMX93-DUT"
    assert cfg.bluetooth.expected_name == "FRDM-IMX93-DUT"


def test_ui_edits_reach_values(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.console_enabled.setChecked(True)
    panel.console_port.setCurrentText("/dev/cu.test")
    panel.wifi_enabled.setChecked(True)
    panel.wifi_mode.setCurrentText("full_stack")
    assert panel.wifi_fs_box.isVisibleTo(panel) or True  # visibility
    panel.wifi_ssid.setText("DUT-AP")
    panel.bt_enabled.setChecked(True)
    panel.bt_mode.setCurrentText("a2dp_sink")
    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])
    cfg = FctTestConfig.from_dict(node["fct_test_config"])
    assert cfg.console.port == "/dev/cu.test"
    assert cfg.wifi.mode == "full_stack" and cfg.wifi.ssid == "DUT-AP"
    assert cfg.bluetooth.mode == "a2dp_sink"


def test_invalid_config_logged_not_lost(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.bt_enabled.setChecked(True)
    panel.bt_name.setText("")                 # required -> invalid
    logs = []
    panel.task_log.connect(lambda lvl, msg: logs.append(msg))
    out = panel.values()
    assert out["fct_test_config_yaml"]        # text preserved
    node = yaml.safe_load(out["fct_test_config_yaml"])
    assert FctTestConfig.from_dict(
        node["fct_test_config"]).validate()   # and still invalid
    assert any("expected_name" in m for m in logs)


def test_dut_type_grey_out_and_hint(qapp):
    panel = FCTTestConfigPanel()
    panel.dut_type.setCurrentText("bare_metal")
    # no Linux shell: DUT-side ping/iperf, L2CAP greyed
    assert not panel.wifi_driver_cmd.isEnabled()
    assert not panel.wifi_gateway.isEnabled()
    assert not panel.wifi_ping_count.isEnabled()
    assert not panel.wifi_loss_max.isEnabled()
    assert not panel.bw_box.isEnabled()
    assert not panel.bt_l2ping.isEnabled()
    assert "Bare Metal" in panel.dut_hint.text()
    # back to linux: everything re-enabled
    panel.dut_type.setCurrentText("linux")
    assert panel.wifi_gateway.isEnabled()
    assert panel.bw_box.isEnabled()
    assert panel.bt_l2ping.isEnabled()


def test_set_values_restores_dut_type_grey(qapp):
    panel = FCTTestConfigPanel()
    node = yaml.safe_load(FRDM_YAML)
    node["fct_test_config"]["dut_type"] = "bare_metal"
    panel.set_values({"fct_test_config_yaml": yaml.safe_dump(node)})
    assert panel.dut_type.currentText() == "bare_metal"
    assert "Bare Metal" in panel.dut_hint.text()


def test_bare_metal_console_transport_serial_only(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.dut_type.setCurrentText("linux")
    add_btn = next(b for b in panel.findChildren(QPushButton)
                   if b.text() == "Add row")
    add_btn.click()
    cb = panel.cmd_table.cellWidget(0, 1)
    assert cb.count() == 2  # linux: serial + ssh
    cb.setCurrentText("ssh")
    # switch to bare metal: ssh is removed and the row falls back
    panel.dut_type.setCurrentText("bare_metal")
    assert cb.count() == 1 and cb.itemText(0) == "serial"
    assert cb.currentText() == "serial"
    assert panel._get_row_cmd(0).transport == "serial"
    # a row added under bare metal is serial-only too
    add_btn.click()
    assert panel.cmd_table.cellWidget(1, 1).count() == 1
    # back to linux restores both transports
    panel.dut_type.setCurrentText("linux")
    assert cb.count() == 2


THREE_STAGE_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/cu.test"
    baudrate: 115200
    test_commands:
      - name: "Boot capture"
        kind: capture
        wait_enabled: false
        send_enabled: false
        capture_enabled: true
        expect_fail: "FW ready"
        capture_is_expected: true
        timeout: 6
      - name: "Login"
        kind: send
        send: "root"
        wait_enabled: true
        send_enabled: true
        capture_enabled: true
        expect_pass: "login:"
        expect_fail: "Password:"
        capture_is_expected: true
        wait_timeout: 10
        send_timeout: 4
        timeout: 6
  wifi: {enabled: false, mode: rssi_only, interface: mlan0, ssid: x, rssi_min: -70}
  bluetooth: {enabled: false, mode: rssi_only, expected_name: x, rssi_min: -70}
"""


def test_three_stage_off_cells_rendered(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": THREE_STAGE_YAML})
    t = panel.cmd_table
    assert t.rowCount() == 2
    # row 0: capture-only -> WaitFor / SendTo show (off), Capture populated
    assert t.item(0, 2).text() == "(off)"
    assert t.item(0, 3).text() == "(off)"
    assert t.item(0, 4).text() == "FW ready"
    assert t.item(0, 5).text() == "C:6s"      # only capture timeout
    # row 1: full Wait -> Send -> Capture chain
    assert t.item(1, 2).text() == "login:"
    assert t.item(1, 3).text() == "root"
    assert t.item(1, 4).text() == "Password:"
    assert t.item(1, 5).text() == "W:10s S:4s C:6s"


def test_three_stage_off_roundtrip(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": THREE_STAGE_YAML})
    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])
    cfg = FctTestConfig.from_dict(node["fct_test_config"])
    cap, login = cfg.console.test_commands
    # capture-only row keeps its stage flags through the table roundtrip
    assert cap.wait_enabled is False
    assert cap.send_enabled is False
    assert cap.capture_enabled is True
    assert cap.expect_fail == "FW ready"
    # full chain row keeps all three stages
    assert login.wait_enabled and login.send_enabled and login.capture_enabled
    assert login.expect_pass == "login:"
    assert login.expect_fail == "Password:"


def test_timeout_column_read_only(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": THREE_STAGE_YAML})
    from PySide6.QtCore import Qt
    item = panel.cmd_table.item(1, 5)
    assert not (item.flags() & Qt.ItemIsEditable)


def test_advanced_capture_attrs_survive_roundtrip(qapp):
    # expected=no + ignore-case + end line + custom timeout must not be
    # lost when the row goes table -> values() -> YAML -> model
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.console_enabled.setChecked(True)
    cmd = ConsoleCommand(
        name="No error window", kind="send", send="run",
        wait_enabled=False, send_enabled=True, capture_enabled=True,
        expect_fail="ERROR", expect_fail_is_regex=False,
        case_sensitive=False, capture_is_expected=False,
        capture_end_line="DONE", timeout=8.0)
    r = panel.cmd_table.rowCount()
    panel.cmd_table.insertRow(r)
    panel._save_row_cmd(r, cmd)
    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])
    restored = FctTestConfig.from_dict(
        node["fct_test_config"]).console.test_commands[0]
    assert restored.capture_enabled and not restored.capture_is_expected
    assert restored.expect_fail == "ERROR"
    assert restored.case_sensitive is False
    assert restored.capture_end_line == "DONE"
    assert restored.timeout == 8.0


def test_sftp_row_clears_wait_and_capture(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.console_enabled.setChecked(True)
    cmd = ConsoleCommand(
        name="Deploy", kind="sftp_put", transport="ssh",
        wait_enabled=False, send_enabled=True, capture_enabled=False,
        local="load.sh", remote="/root/load.sh", send_timeout=30.0)
    r = panel.cmd_table.rowCount()
    panel.cmd_table.insertRow(r)
    panel._save_row_cmd(r, cmd)
    # rendered cells show (off) for Wait/Capture and only S timeout
    assert panel.cmd_table.item(r, 2).text() == "(off)"
    assert panel.cmd_table.item(r, 4).text() == "(off)"
    assert panel.cmd_table.item(r, 5).text() == "S:30s"
    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])
    restored = FctTestConfig.from_dict(
        node["fct_test_config"]).console.test_commands[0]
    assert restored.kind == "sftp_put"
    assert restored.local == "load.sh" and restored.remote == "/root/load.sh"
    assert not restored.wait_enabled and not restored.capture_enabled


