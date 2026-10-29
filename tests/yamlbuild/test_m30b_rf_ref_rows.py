# -*- coding: utf-8 -*-
"""m30b: Wi-Fi/BT sub-tests as FCT sequence reference rows.

A reference row (kind ``wifi_test`` / ``bt_test`` + ``rf_subtest``)
lives in the merged Sequence table, expands AT its position when the FCT
work flow is built, re-renders its summary live from the Wi-Fi /
Bluetooth tabs, and double-clicking it jumps to the matching tab (no
modal dialog).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

import yaml  # noqa: E402

from mtkgui.engine.fct_test_config import (  # noqa: E402
    BluetoothCfg,
    ConsoleCfg,
    ConsoleCommand,
    FctTestConfig,
    WifiCfg,
    STEP_TYPE_WIFI_SCAN,
    STEP_TYPE_WIFI_PING,
    STEP_TYPE_WIFI_IPERF,
    STEP_TYPE_BT_RSSI,
    STEP_TYPE_BT_PAIR,
    STEP_TYPE_BT_TONE,
    build_fct_steps,
    console_command_for_label,
    rf_subtest_for_label,
    step_type_label,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
    _COL_CAPTURE,
    _COL_CMD,
    _COL_SEND,
    _COL_STEP,
    _COL_TIMEOUT,
    _COL_TYPE,
    _COL_WAIT,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


RF_LABELS = {
    STEP_TYPE_WIFI_SCAN: ("wifi_test", "scan"),
    STEP_TYPE_WIFI_PING: ("wifi_test", "ping"),
    STEP_TYPE_WIFI_IPERF: ("wifi_test", "iperf"),
    STEP_TYPE_BT_RSSI: ("bt_test", "rssi"),
    STEP_TYPE_BT_PAIR: ("bt_test", "pair"),
    STEP_TYPE_BT_TONE: ("bt_test", "tone"),
}


def test_six_rf_labels_map_both_ways(qapp):
    for label, (kind, subtest) in RF_LABELS.items():
        cmd = console_command_for_label(label)
        assert cmd.kind == kind
        assert cmd.rf_subtest == subtest
        assert step_type_label(cmd) == label
        assert rf_subtest_for_label(label) == (kind, subtest)
        # default row builders are inert reference rows (no inline dialog)
        assert cmd.wait_enabled is False
        assert cmd.send_enabled is False
        assert cmd.capture_enabled is False


def test_add_menu_has_rf_groups_and_bare_metal_gating(qapp):
    panel = FCTTestConfigPanel()
    for label in RF_LABELS:
        assert label in panel._add_actions
    # Linux default: Linux-only items visible
    assert panel._add_actions[STEP_TYPE_WIFI_IPERF].isVisible()
    assert panel._add_actions[STEP_TYPE_BT_PAIR].isVisible()
    assert panel._add_actions[STEP_TYPE_BT_TONE].isVisible()
    panel.dut_type.setCurrentText("bare_metal")
    assert not panel._add_actions[STEP_TYPE_WIFI_IPERF].isVisible()
    assert not panel._add_actions[STEP_TYPE_BT_PAIR].isVisible()
    assert not panel._add_actions[STEP_TYPE_BT_TONE].isVisible()
    # discovery-only rows stay on both DUT kinds
    assert panel._add_actions[STEP_TYPE_WIFI_SCAN].isVisible()
    assert panel._add_actions[STEP_TYPE_BT_RSSI].isVisible()


RF_RENDER_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: false
    test_commands:
      - {name: "Wi-Fi: Scan / RSSI", kind: wifi_test, rf_subtest: scan,
         wait_enabled: false, send_enabled: false, capture_enabled: false}
      - {name: "Bluetooth: Tone / A2DP", kind: bt_test, rf_subtest: tone,
         wait_enabled: false, send_enabled: false, capture_enabled: false}
  wifi:
    enabled: true
    scan_enabled: true
    ping_enabled: false
    iperf_enabled: false
    ap_ssid: "FRDM-IMX93-DUT"
    rssi_min: -70
    scan_timeout: 15
  bluetooth:
    enabled: true
    rssi_enabled: false
    pair_enabled: false
    tone_enabled: true
    tone_timeout: 15
"""


def _rf_panel(qapp) -> FCTTestConfigPanel:
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": RF_RENDER_YAML})
    return panel


def test_reference_row_renders_live_summary(qapp):
    panel = _rf_panel(qapp)
    t = panel.cmd_table
    assert t.item(0, _COL_TYPE).text() == "Wifi_Scan"
    assert t.item(1, _COL_TYPE).text() == "BT_Tone"
    for r in (0, 1):
        assert t.item(r, _COL_WAIT).text() == "\u2014"
        assert t.item(r, _COL_SEND).text() == "\u2014"
        assert t.item(r, _COL_CAPTURE).text() == "\u2014"
    assert t.item(0, _COL_TIMEOUT).text() == "15s"
    assert t.item(1, _COL_TIMEOUT).text() == "15s"
    assert t.item(0, _COL_CMD).text() == \
        "SSID=FRDM-IMX93-DUT, RSSI\u2265-70 dBm"
    assert t.item(1, _COL_CMD).text() == "tone_1khz_6s.wav, 6s"

    # live refresh: a Wi-Fi tab edit re-renders the summary cell
    panel.wifi_ap_ssid.setText("NEW-SSID")
    assert t.item(0, _COL_CMD).text() == "SSID=NEW-SSID, RSSI\u2265-70 dBm"


def test_reference_row_enabled_mirrors_module_checkboxes(qapp):
    panel = _rf_panel(qapp)
    scan_cmd = panel._row_cmd(0)
    tone_cmd = panel._row_cmd(1)
    assert panel._rf_effective_enabled(scan_cmd) is True
    assert panel._rf_effective_enabled(tone_cmd) is True
    # M36: no master switch - the Scan/RSSI checkbox is the source
    panel.wifi_scan_box.setChecked(False)
    assert panel._rf_effective_enabled(scan_cmd) is False
    assert panel.cmd_table.item(0, _COL_STEP).foreground().color().name() \
        == "#9ca3af"
    panel.wifi_scan_box.setChecked(True)
    assert panel._rf_effective_enabled(scan_cmd) is True


def test_double_click_jumps_to_rf_tab(qapp):
    panel = FCTTestConfigPanel()
    r0 = panel.cmd_table.rowCount()
    panel._add_row_for_label(STEP_TYPE_WIFI_SCAN)
    r1 = panel.cmd_table.rowCount()
    panel._add_row_for_label(STEP_TYPE_BT_TONE)
    panel._on_cmd_double_click(r0, _COL_STEP)
    assert panel.tabs.currentWidget() is panel.wifi_tab
    qapp.processEvents()
    panel._on_cmd_double_click(r1, _COL_STEP)
    assert panel.tabs.currentWidget() is panel.bt_tab
    qapp.processEvents()


def test_build_order_expands_wifi_row_at_its_position():
    cfg = FctTestConfig(
        dut_type="linux",
        wifi=WifiCfg(ap_ssid="DUT-AP", scan_enabled=False,
                     ping_enabled=True, ping_count=20),
        bluetooth=BluetoothCfg())
    cfg.console = ConsoleCfg(
        test_commands=[
            ConsoleCommand(name="before", kind="send", send="x",
                           wait_enabled=False, send_enabled=True,
                           capture_enabled=False),
            ConsoleCommand(name="Wi-Fi: Ping", kind="wifi_test",
                           rf_subtest="ping", wait_enabled=False,
                           send_enabled=False, capture_enabled=False),
            ConsoleCommand(name="after", kind="send", send="y",
                           wait_enabled=False, send_enabled=True,
                           capture_enabled=False),
        ])
    names = [s.name for s in build_fct_steps(cfg, channel_key="ser1")]
    assert names == ["before",
                     "Wi-Fi Ping (Host->AP / DUT->AP / DUT->Host)",
                     "after"]


def test_legacy_config_without_reference_rows_round_trips(qapp):
    yaml_text = """
fct_test_config:
  dut_type: linux
  console:
    enabled: false
    test_commands:
      - {name: Kernel check, kind: send, send: "uname -a",
         wait_enabled: false, send_enabled: true, capture_enabled: true,
         capture_expected: "Linux", timeout: 5}
  wifi: {enabled: false}
  bluetooth: {enabled: false}
"""
    seq = [{"name": "Power On DUT", "kind": "op", "enable": True,
            "wait_ms": 100, "timeout_ms": 5000, "op_params": None}]
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": yaml_text,
                      "fct_sequence_cases_yaml": yaml.safe_dump(
                          seq, sort_keys=False)})
    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])["fct_test_config"]
    cmds = FctTestConfig.from_dict(node).console.test_commands
    assert [c.name for c in cmds] == ["Kernel check"]
    assert [c.kind for c in cmds] == ["send"]
    assert all(c.rf_subtest == "" for c in cmds)
    seq_out = yaml.safe_load(out["fct_sequence_cases_yaml"])
    assert [c["name"] for c in seq_out] == ["Power On DUT"]
    assert seq_out[0]["kind"] == "op"