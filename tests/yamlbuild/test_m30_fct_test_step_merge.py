# -*- coding: utf-8 -*-
"""m30: Sequence tab merged into ONE "FCT test step" table.

These tests lock the merge contract: the 12 Type labels round-trip, an
old project config (test_commands + standard ops) loads into the merged
table in order and saves back to equivalent YAML, the unified Capture
fields round-trip, and the legacy capture_is_expected migration works.
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
    FctTestConfig,
    STEP_TYPE_LABELS,
    console_command_for_label,
    step_type_label,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
    _COL_CMD,
    _COL_CAPTURE,
    _COL_STEP,
    _COL_TYPE,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_twelve_type_labels_round_trip(qapp):
    """Each of the 12 Type labels maps back to itself through its
    ConsoleCommand backing."""
    for label in STEP_TYPE_LABELS:
        cmd = console_command_for_label(label, "step")
        assert step_type_label(cmd) == label, label


MERGE_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/cu.test"
    baudrate: 115200
    test_commands:
      - {name: Kernel check, kind: send, send: "uname -a",
         wait_enabled: false, send_enabled: true, capture_enabled: true,
         capture_expected: "Linux", timeout: 5}
      - {name: Pull report, transport: ssh, kind: sftp_get,
         wait_enabled: false, send_enabled: true, capture_enabled: false,
         remote: "/root/fat.json", local: "{{dut_report}}/fat.json"}
      - {name: Stop iperf3, kind: host, send_enabled: true,
         capture_enabled: false, host_cmd_windows: "taskkill /IM iperf3.exe"}
  wifi: {enabled: false}
  bluetooth: {enabled: false}
"""

SEQ_CASES = [
    {"name": "Power On DUT", "kind": "op", "enable": True,
     "wait_ms": 100, "timeout_ms": 5000,
     "op_params": {"type": "power", "voltage": 5.0, "current": 1.0}},
    {"name": "Delay", "kind": "Delay", "enable": True,
     "wait_ms": 100, "timeout_ms": 1000, "op_params": None},
]


def test_merge_and_split_round_trip(qapp):
    """An old config (test_commands + standard ops) loads into ONE table
    with the same ordered steps (ops first) and saves back to equivalent
    YAML (ops -> fct_sequence_cases_yaml, commands -> test_commands)."""
    panel = FCTTestConfigPanel()
    panel.set_values({
        "fct_test_config_yaml": MERGE_YAML,
        "fct_sequence_cases_yaml": yaml.safe_dump(
            SEQ_CASES, sort_keys=False),
    })
    t = panel.cmd_table
    assert [t.item(r, _COL_STEP).text() for r in range(t.rowCount())] == \
        ["Power On DUT", "Delay", "Kernel check", "Pull report",
         "Stop iperf3"]
    assert [t.item(r, _COL_TYPE).text() for r in range(t.rowCount())] == \
        ["Operation", "Operation", "Console_serial", "SFTP_get",
         "Console_cli"]

    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])["fct_test_config"]
    cmds = FctTestConfig.from_dict(node).console.test_commands
    assert [c.name for c in cmds] == ["Kernel check", "Pull report",
                                      "Stop iperf3"]
    assert [c.kind for c in cmds] == ["send", "sftp_get", "host"]
    assert cmds[0].capture_expected == "Linux"
    assert cmds[2].host_cmd_windows == "taskkill /IM iperf3.exe"

    seq = yaml.safe_load(out["fct_sequence_cases_yaml"])
    assert [c["name"] for c in seq] == ["Power On DUT", "Delay"]
    assert seq[0]["kind"] == "op"
    assert seq[0]["op_params"]["type"] == "power"
    assert seq[1]["kind"] == "Delay"
    assert seq[1]["op_params"] is None


LEGACY_CAPTURE_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    test_commands:
      - {name: expect_yes, kind: send, send: "x",
         wait_enabled: false, send_enabled: true, capture_enabled: true,
         capture_is_expected: true, expect_fail: "GOOD", timeout: 5}
      - {name: expect_no, kind: send, send: "x",
         wait_enabled: false, send_enabled: true, capture_enabled: true,
         capture_is_expected: false, expect_fail: "BAD", timeout: 5}
  wifi: {enabled: false}
  bluetooth: {enabled: false}
"""


def test_legacy_capture_is_expected_migration(qapp):
    """capture_is_expected True/False migrates to capture_expected /
    capture_unexpected (and the merged Capture column renders it)."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": LEGACY_CAPTURE_YAML})
    good = panel._row_cmd(0)
    bad = panel._row_cmd(1)
    assert good.capture_expected == "GOOD" and good.capture_unexpected == ""
    assert bad.capture_unexpected == "BAD" and bad.capture_expected == ""
    t = panel.cmd_table
    assert t.item(0, _COL_CAPTURE).text() == '+ "GOOD"'
    assert t.item(1, _COL_CAPTURE).text() == '- "BAD"'


def test_capture_fields_round_trip_through_panel(qapp):
    """A step's Expected / Unexpected pair survives the table -> values()
    -> YAML -> model round-trip and renders in the Capture column."""
    from mtkgui.engine.fct_test_config import ConsoleCommand
    panel = FCTTestConfigPanel()
    panel.set_values({})
    r = panel.cmd_table.rowCount()
    panel.cmd_table.insertRow(r)
    panel._save_row_cmd(r, ConsoleCommand(
        name="fat verdict", kind="send", send="run",
        wait_enabled=False, send_enabled=True, capture_enabled=True,
        capture_expected="Overall result: PASS",
        capture_unexpected="Overall result: FAIL"))
    assert panel.cmd_table.item(r, _COL_CAPTURE).text() == \
        '+ "Overall result: PASS"  - "Overall result: FAIL"'
    out = panel.values()
    restored = FctTestConfig.from_dict(yaml.safe_load(
        out["fct_test_config_yaml"])["fct_test_config"]
    ).console.test_commands[0]
    assert restored.capture_expected == "Overall result: PASS"
    assert restored.capture_unexpected == "Overall result: FAIL"


def test_merged_table_has_eight_columns(qapp):
    """The merged table uses the fixed 8-column header contract."""
    panel = FCTTestConfigPanel()
    headers = [panel.cmd_table.horizontalHeaderItem(c).text()
               for c in range(panel.cmd_table.columnCount())]
    assert headers == ["#", "Step", "Type", "WaitFor", "SendTo",
                       "Capture", "Timeout", "cmd / params"]
    assert panel.cmd_table.columnCount() == 8