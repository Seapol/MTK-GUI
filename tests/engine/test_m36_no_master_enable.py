# -*- coding: utf-8 -*-
"""M36: the console / Wi-Fi / Bluetooth master ``enabled`` switches are
gone.  The configured fields and the per-sub-test flags are the single
source of truth; a legacy YAML ``enabled`` key is ignored on load and the
DUT-kind capability gating stays untouched."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.fct_test_config import (  # noqa: E402
    BluetoothCfg,
    ConsoleCfg,
    ConsoleCommand,
    FctTestConfig,
    KIND_DELAY,
    KIND_FLASH_GUI,
    WifiCfg,
    build_fct_steps,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ------------------------------------------------------------- the model
def test_cfg_dataclasses_have_no_enabled_field():
    for cfg in (ConsoleCfg(), WifiCfg(), BluetoothCfg()):
        assert not hasattr(cfg, "enabled")
    assert "enabled" not in ConsoleCfg().to_dict()
    assert "enabled" not in WifiCfg().to_dict()
    assert "enabled" not in BluetoothCfg().to_dict()


def test_subtest_defaults_are_opt_in():
    """Before M36 the master switch kept scan / RSSI inert; without it the
    sub-test flags must default to OFF."""
    w, b = WifiCfg(), BluetoothCfg()
    assert not w.scan_enabled and not w.any_enabled
    assert not b.rssi_enabled and not b.any_enabled


def test_empty_config_validates_and_builds_nothing():
    cfg = FctTestConfig()
    assert cfg.validate() == []
    assert build_fct_steps(cfg) == []


def test_legacy_enabled_keys_are_ignored_on_load():
    cfg = FctTestConfig.from_dict({
        "dut_type": "linux",
        "console": {"enabled": True, "port": "/dev/cu.test"},
        "wifi": {"enabled": False, "scan_enabled": True, "ap_ssid": "AP"},
        "bluetooth": {"enabled": False, "rssi_enabled": True,
                      "expected_name": "DUT-BT"},
    })
    assert cfg.console.port == "/dev/cu.test"
    assert cfg.wifi.any_enabled and cfg.bluetooth.any_enabled
    names = [s.name for s in build_fct_steps(cfg)]
    assert "Wi-Fi Scan / RSSI" in names and "Bluetooth RSSI" in names


def test_roundtrip_drops_the_legacy_keys():
    cfg = FctTestConfig.from_dict({"console": {"enabled": True}})
    node = cfg.to_yaml_node()["fct_test_config"]
    assert "enabled" not in node["console"]
    assert "enabled" not in node["wifi"]
    assert "enabled" not in node["bluetooth"]


# ---------------------------------------------------------- validation
def test_serial_row_without_port_is_an_error():
    cfg = FctTestConfig(console=ConsoleCfg(test_commands=[
        ConsoleCommand(kind="send", name="cmd", send="uname -a")]))
    assert any("port" in e for e in cfg.validate())


def test_rows_that_need_no_serial_accept_an_empty_port():
    """Flash_GUI / Delay rows never touch the console (M33 / M35)."""
    cfg = FctTestConfig(console=ConsoleCfg(test_commands=[
        ConsoleCommand(kind=KIND_FLASH_GUI, name="Flash"),
        ConsoleCommand(kind=KIND_DELAY, name="Wait", wait_ms=500,
                       timeout=5.0)]))
    assert cfg.validate() == []


def test_module_with_all_subtests_off_is_not_an_error():
    cfg = FctTestConfig(dut_type="linux", console=ConsoleCfg(
        port="/dev/cu.test",
        test_commands=[ConsoleCommand(kind="send", name="cmd", send="x")]))
    assert cfg.validate() == []
    assert [s.name for s in build_fct_steps(cfg)] == ["cmd"]


# ------------------------------------------------------------- the panel
def test_panel_has_no_master_checkboxes(qapp):
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel
    panel = FCTTestConfigPanel()
    assert not hasattr(panel, "console_enabled")
    assert not hasattr(panel, "wifi_enabled")
    assert not hasattr(panel, "bt_enabled")


def test_panel_defaults_emit_no_rf_steps(qapp):
    import yaml
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel
    panel = FCTTestConfigPanel()
    panel.set_values({})
    out = panel.values()
    cfg = FctTestConfig.from_dict(
        yaml.safe_load(out["fct_test_config_yaml"])["fct_test_config"])
    assert cfg.validate() == []
    assert not cfg.wifi.any_enabled and not cfg.bluetooth.any_enabled


def test_panel_wifi_subtests_reach_values_without_a_master(qapp):
    import yaml
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.wifi_scan_box.setChecked(True)
    panel.wifi_ap_ssid.setText("DUT-AP")
    panel.bt_rssi_box.setChecked(True)
    panel.bt_name.setText("DUT-BT")
    out = panel.values()
    cfg = FctTestConfig.from_dict(
        yaml.safe_load(out["fct_test_config_yaml"])["fct_test_config"])
    assert cfg.wifi.scan_enabled and cfg.wifi.ap_ssid == "DUT-AP"
    assert cfg.bluetooth.rssi_enabled
    assert cfg.bluetooth.expected_name == "DUT-BT"


def test_dut_kind_gating_is_kept(qapp):
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel
    panel = FCTTestConfigPanel()
    panel.dut_type.setCurrentText("bare_metal")
    assert not panel.wifi_ping_box.isEnabled()
    assert not panel.wifi_iperf_box.isEnabled()
    assert not panel.wifi_driver_cmd.isEnabled()
    assert panel.wifi_scan_box.isEnabled()
    assert not panel.bt_pair_box.isEnabled()
    assert not panel.bt_tone_box.isEnabled()
    assert panel.bt_rssi_box.isEnabled()
