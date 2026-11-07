# -*- coding: utf-8 -*-
"""m30b: Wi-Fi/BT sub-tests as FCT sequence reference rows.

A reference row (kind ``wifi_test`` / ``bt_test`` + ``rf_subtest``)
lives in the single Sequence table.  M50 removed the Wi-Fi / Bluetooth
tabs: each row now shows its EFFECTIVE values resolved from the
Equipment page references (plus per-step overrides), and the engine
still expands the row AT its position when the FCT work flow is built.
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
    _COL_CMD,
    _COL_TYPE,
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


def _equipment_node():
    return {"equipment": {"peripherals": {
        "router": {"router_ap_ssid": "MTK-AP"},
        "bluetooth": {"scan_targets": "MTK-DUT"}}}}


def _ref_row(panel, label, params=None, overrides=None):
    """Append one RF reference row carrying its default Equipment refs."""
    cmd = console_command_for_label(label)
    cmd.step_params = dict(params or {})
    cmd.refs = panel._default_refs(cmd) or None
    cmd.overrides = dict(overrides or {}) or None
    panel._insert_row(cmd)
    return cmd


def test_reference_row_renders_effective_equipment_values(qapp):
    """M50: the summary cell resolves the row's ``ref`` against the
    current Equipment node (no deleted tab drives it)."""
    panel = FCTTestConfigPanel(equipment_provider=_equipment_node)
    _ref_row(panel, STEP_TYPE_WIFI_SCAN, {"rssi_min": -70})
    t = panel.cmd_table
    assert t.item(0, _COL_TYPE).text() == "Wifi_Scan"
    assert t.item(0, _COL_CMD).text() == "AP=MTK-AP, RSSI\u2265-70 dBm"


def test_reference_row_override_wins_over_the_equipment_value(qapp):
    panel = FCTTestConfigPanel(equipment_provider=_equipment_node)
    _ref_row(panel, STEP_TYPE_WIFI_SCAN, {"rssi_min": -70},
             {"ap_ssid": "LAB-AP"})
    assert panel.cmd_table.item(0, _COL_CMD).text() == \
        "AP=LAB-AP, RSSI\u2265-70 dBm"


def test_rf_rows_round_trip_through_the_message_schema(qapp):
    """M50: every RF row saves as one ``fct.steps`` entry with its own
    parameters plus the runtime ``ref`` map."""
    panel = FCTTestConfigPanel(equipment_provider=_equipment_node)
    _ref_row(panel, STEP_TYPE_WIFI_SCAN, {"rssi_min": -70, "timeout_s": 15})
    _ref_row(panel, STEP_TYPE_BT_RSSI, {"rssi_min": -70, "timeout_s": 15})
    steps = ((yaml.safe_load(panel.values()["fct_steps_yaml"]) or {})
             .get("fct") or {}).get("steps") or []
    assert [s["type"] for s in steps] == [STEP_TYPE_WIFI_SCAN, STEP_TYPE_BT_RSSI]
    assert steps[0]["ref"]["ap_ssid"] == \
        "equipment.peripherals.router.router_ap_ssid"
    assert steps[0]["rssi_min"] == -70
    assert steps[1]["ref"]["bt_name"] == "equipment.dut.bluetooth.name"


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
    """M50: a legacy project (no RF ref rows) imports into single-page
    rows and re-emits the new ``fct.steps`` schema."""
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
    steps = ((yaml.safe_load(out["fct_steps_yaml"]) or {})
             .get("fct") or {}).get("steps") or []
    assert [s["name"] for s in steps] == ["Power On DUT", "Kernel check"]
    assert [s["type"] for s in steps][1] == "Console_serial"
    assert list(out) == ["fct_steps_yaml"]
