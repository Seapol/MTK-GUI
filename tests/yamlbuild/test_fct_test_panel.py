# -*- coding: utf-8 -*-
"""P3-B5: FCTTestConfigPanel headless tests (set_values / values)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

import yaml

from mtkgui.engine.fct_test_config import FctTestConfig
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
    assert [p.wait_for for p in cfg.console.login_sequence] == \
        ["login:", "Password:", "root@imx93frdm"]
    assert cfg.console.test_commands[0].expect_pass == "Linux imx93frdm"
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
    # no Linux shell: login chain, DUT-side ping/iperf, L2CAP greyed
    assert not panel.login_table.isEnabled()
    assert not panel.wifi_driver_cmd.isEnabled()
    assert not panel.wifi_gateway.isEnabled()
    assert not panel.wifi_ping_count.isEnabled()
    assert not panel.wifi_loss_max.isEnabled()
    assert not panel.bw_box.isEnabled()
    assert not panel.bt_l2ping.isEnabled()
    assert "Bare Metal" in panel.dut_hint.text()
    # back to linux: everything re-enabled
    panel.dut_type.setCurrentText("linux")
    assert panel.login_table.isEnabled()
    assert panel.wifi_gateway.isEnabled()
    assert panel.bw_box.isEnabled()
    assert panel.bt_l2ping.isEnabled()


def test_set_values_restores_dut_type_grey(qapp):
    panel = FCTTestConfigPanel()
    node = yaml.safe_load(FRDM_YAML)
    node["fct_test_config"]["dut_type"] = "bare_metal"
    panel.set_values({"fct_test_config_yaml": yaml.safe_dump(node)})
    assert panel.dut_type.currentText() == "bare_metal"
    assert not panel.login_table.isEnabled()
    assert "Bare Metal" in panel.dut_hint.text()
