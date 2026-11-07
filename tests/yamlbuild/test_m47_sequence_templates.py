# -*- coding: utf-8 -*-
"""M47: FCT Sequence reference templates + multi-select Remove + the
wait / send / capture optional-segment model.

Owner request 2026-11-01: the FCT Sequence page gains a "Load Template"
button (Bare Metal DUT / Linux DUT reference sequences inserted as
ORDINARY rows the operator may edit / delete / reorder; M56: the
current table is cleared first), multi-row selection with one-click
"Remove selected", and the formal guarantee that each Console segment
(wait / send / capture) may be left empty.

IRON RULE under test: the app NEVER injects steps on its own - only the
operator pressing Load Template replaces the rows, and nothing runs.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

import yaml  # noqa: E402
from PySide6.QtCore import QItemSelectionModel  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.fct_test_config import (  # noqa: E402
    KIND_BT_TEST,
    KIND_DELAY,
    KIND_MESSAGE,
    KIND_OP,
    KIND_SERIAL_PULL,
    KIND_SERIAL_PUT,
    KIND_SFTP_PUT,
    KIND_WIFI_TEST,
    STEP_TYPE_BT_PAIR,
    STEP_TYPE_BT_RSSI,
    STEP_TYPE_BT_TONE,
    STEP_TYPE_CONSOLE_SERIAL,
    STEP_TYPE_DELAY,
    STEP_TYPE_OPERATION,
    STEP_TYPE_SERIAL_PULL,
    STEP_TYPE_SERIAL_PUT,
    STEP_TYPE_SFTP_PUT,
    STEP_TYPE_WIFI_IPERF,
    STEP_TYPE_WIFI_PING,
    STEP_TYPE_WIFI_SCAN,
    ConsoleCommand,
    _console_row_steps,
    step_type_label,
)
from mtkgui.engine.fct_templates import (  # noqa: E402
    TEMPLATE_BARE_METAL,
    TEMPLATE_LABELS,
    TEMPLATE_LINUX,
    TEMPLATE_WIFI_SCAN,
    load_template,
    load_template_commands,
    template_path,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
    _COL_HASH,
    _COL_STEP,
    _COL_TYPE,
)

BARE_METAL_TYPES = [STEP_TYPE_OPERATION, STEP_TYPE_OPERATION,
                    STEP_TYPE_OPERATION, STEP_TYPE_DELAY,
                    STEP_TYPE_CONSOLE_SERIAL, STEP_TYPE_WIFI_SCAN,
                    STEP_TYPE_BT_RSSI, STEP_TYPE_OPERATION,
                    STEP_TYPE_OPERATION]
LINUX_TYPES = [STEP_TYPE_OPERATION, STEP_TYPE_OPERATION,
               STEP_TYPE_OPERATION, STEP_TYPE_DELAY,
               STEP_TYPE_CONSOLE_SERIAL, STEP_TYPE_CONSOLE_SERIAL,
               STEP_TYPE_CONSOLE_SERIAL, STEP_TYPE_SERIAL_PUT,
               STEP_TYPE_CONSOLE_SERIAL, STEP_TYPE_CONSOLE_SERIAL,
               STEP_TYPE_CONSOLE_SERIAL, STEP_TYPE_SFTP_PUT,
               STEP_TYPE_WIFI_PING, STEP_TYPE_WIFI_IPERF,
               STEP_TYPE_BT_PAIR, STEP_TYPE_BT_TONE,
               STEP_TYPE_SERIAL_PULL, STEP_TYPE_CONSOLE_SERIAL,
               STEP_TYPE_OPERATION, STEP_TYPE_OPERATION]

PROJECT_YAML = yaml.safe_dump({"fct_test_config": {
    "dut_type": "linux",
    "console": {"port": "/dev/cu.test", "baudrate": 115200},
    "wifi": {"interface": "mlan0", "ap_ssid": "FCT_AP",
             "ap_password": "secret", "rssi_min": -60},
    "bluetooth": {"expected_name": "MTK-DUT",
                  "expected_addr": "AA:BB:CC:DD:EE:FF", "rssi_min": -60},
}}, sort_keys=False)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    p = FCTTestConfigPanel()
    p.set_values({})
    return p


def _rows(panel) -> list:
    return [panel._get_row_cmd(r) for r in range(panel.cmd_table.rowCount())]


# ------------------------------------------------------- 1 / 2 templates
class TestTemplateFiles:
    def test_both_template_files_are_shipped(self):
        # M66 adds the operator-selectable Wifi_Scan (Host<->DUT) preset
        assert set(TEMPLATE_LABELS) == {
            TEMPLATE_BARE_METAL, TEMPLATE_LINUX, TEMPLATE_WIFI_SCAN}
        for label in TEMPLATE_LABELS:
            path = template_path(label)
            assert os.path.isfile(path), path
            assert os.path.basename(path) in ("fct_bare_metal.yaml",
                                              "fct_linux.yaml",
                                              "fct_wifi_scan.yaml")

    def test_bare_metal_template_has_nine_rows_in_order(self):
        rows = load_template_commands(TEMPLATE_BARE_METAL)
        assert len(rows) == 9
        assert [step_type_label(c) for c in rows] == BARE_METAL_TYPES
        assert rows[3].kind == KIND_DELAY and rows[3].wait_ms == 3000
        assert rows[5].kind == KIND_WIFI_TEST and rows[5].rf_subtest == "scan"
        assert rows[6].kind == KIND_BT_TEST and rows[6].rf_subtest == "rssi"

    def test_linux_template_has_twenty_rows_in_order(self):
        rows = load_template_commands(TEMPLATE_LINUX)
        assert len(rows) == 20
        assert [step_type_label(c) for c in rows] == LINUX_TYPES
        # row 5 = wait only, row 6 = send + capture (Console model §4)
        assert rows[4].wait_enabled and not rows[4].send_enabled
        assert rows[4].expect_pass == "login:"
        assert rows[5].send == "uname -r"
        assert rows[5].capture_enabled
        assert rows[6].send == "mkdir -p /root/fct_assets"
        assert rows[10].send == "bash /root/fct_assets/connect_wifi.sh router"

    def test_template_document_carries_name_and_steps(self):
        data = load_template(TEMPLATE_BARE_METAL)
        assert data["name"] == TEMPLATE_BARE_METAL
        assert len(data["steps"]) == 9

    def test_unknown_step_type_is_rejected(self):
        tmp = os.path.join(os.getcwd(), "_m47_bad_template.yaml")
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write("steps:\n  - type: NotARealType\n")
        try:
            with pytest.raises(ValueError):
                load_template_commands(TEMPLATE_BARE_METAL, path=tmp)
        finally:
            os.remove(tmp)


class TestTemplateLoadReplacesRows:
    def test_load_clears_stale_rows_then_inserts_the_template(self, panel):
        """M56: Load Template REPLACES the table - hand-added rows and
        previously loaded template rows are cleared first."""
        panel._insert_row(ConsoleCommand(kind=KIND_MESSAGE, name="Stale",
                                         dialog_style="yesno"))
        panel._load_template(TEMPLATE_LINUX)
        assert panel.cmd_table.rowCount() == len(LINUX_TYPES)
        panel._template_actions[TEMPLATE_BARE_METAL].trigger()
        assert panel.cmd_table.rowCount() == len(BARE_METAL_TYPES)
        assert [panel.cmd_table.item(r, _COL_TYPE).text()
                for r in range(len(BARE_METAL_TYPES))] == BARE_METAL_TYPES
        names = [panel._get_row_cmd(r).name
                 for r in range(panel.cmd_table.rowCount())]
        assert "Stale" not in names
        assert [panel.cmd_table.item(r, _COL_HASH).text()
                for r in range(len(BARE_METAL_TYPES))] == \
            [str(r + 1) for r in range(len(BARE_METAL_TYPES))]

    def test_clear_count_is_logged(self, panel):
        logs = []
        panel.task_log.connect(lambda level, msg: logs.append((level, msg)))
        for r in range(2):
            panel._insert_row(ConsoleCommand(kind=KIND_MESSAGE,
                                             name=f"Old {r}"))
        panel._load_template(TEMPLATE_BARE_METAL)
        assert ("INFO", f"Load Template '{TEMPLATE_BARE_METAL}': "
                        "cleared 2 existing row(s)") in logs

    def test_load_into_an_empty_table(self, panel):
        assert panel.cmd_table.rowCount() == 0
        panel._load_template(TEMPLATE_LINUX)
        assert panel.cmd_table.rowCount() == len(LINUX_TYPES)
        assert [panel.cmd_table.item(r, _COL_TYPE).text()
                for r in range(len(LINUX_TYPES))] == LINUX_TYPES

    def test_failed_template_load_leaves_the_table_empty(self, panel):
        logs = []
        panel.task_log.connect(lambda level, msg: logs.append((level, msg)))
        panel._insert_row(ConsoleCommand(kind=KIND_MESSAGE, name="Stale",
                                         dialog_style="yesno"))
        panel._load_template("No Such Template")
        assert panel.cmd_table.rowCount() == 0
        assert any(level == "ERROR" and "No Such Template" in msg
                   for level, msg in logs)
        assert not any(level == "INFO" and "step(s)" in msg
                       for level, msg in logs)

    def test_loaded_rows_carry_no_template_marker(self, panel):
        panel._load_template(TEMPLATE_LINUX)
        for cmd in _rows(panel):
            assert not hasattr(cmd, "template")
            assert not cmd.name.startswith("Template")

    def test_loaded_rows_behave_like_hand_added_rows(self, panel):
        panel._load_template(TEMPLATE_BARE_METAL)
        count = panel.cmd_table.rowCount()
        # edit: the Step cell is the visible name (no hidden override)
        panel.cmd_table.item(4, _COL_STEP).setText("Edited console step")
        assert panel._get_row_cmd(4).name == "Edited console step"
        # duplicate / move / delete work on template rows
        panel.cmd_table.setCurrentCell(1, 0)
        panel._duplicate_row()
        assert panel.cmd_table.rowCount() == count + 1
        panel._move_down()
        panel.cmd_table.setCurrentCell(0, 0)
        panel._remove_current()
        assert panel.cmd_table.rowCount() == count

    def test_template_rows_round_trip_through_values(self, panel):
        """M50: the single Sequence page round-trips through the new
        ``fct.steps`` schema (one entry per row, no split config)."""
        panel._load_template(TEMPLATE_BARE_METAL)
        out = panel.values()
        steps = ((yaml.safe_load(out["fct_steps_yaml"]) or {})
                 .get("fct") or {}).get("steps") or []
        assert len(steps) == 9
        assert len([s for s in steps
                    if s["type"] == STEP_TYPE_OPERATION]) == 5
        assert list(out) == ["fct_steps_yaml"]


# ------------------------------------------------- 3 multi-select Remove
class TestRemoveSelected:
    def _select(self, panel, rows: list) -> None:
        model = panel.cmd_table.selectionModel()
        for r in rows:
            model.select(panel.cmd_table.model().index(r, 0),
                         QItemSelectionModel.SelectionFlag.Select
                         | QItemSelectionModel.SelectionFlag.Rows)

    def test_table_supports_multi_row_selection(self, panel):
        panel._load_template(TEMPLATE_BARE_METAL)
        self._select(panel, [1, 3, 5])
        assert panel._selected_rows() == [1, 3, 5]

    def test_remove_selected_deletes_exactly_the_selected_rows(self, panel):
        panel._load_template(TEMPLATE_BARE_METAL)
        self._select(panel, [1, 3, 5])
        keep = [panel._get_row_cmd(r).name
                for r in range(panel.cmd_table.rowCount()) if r not in
                (1, 3, 5)]
        panel._remove_selected()
        assert panel.cmd_table.rowCount() == 6
        assert [c.name for c in _rows(panel)] == keep
        assert [panel.cmd_table.item(r, _COL_STEP).text() for r in range(6)] \
            == keep

    def test_remove_selected_is_disabled_with_no_selection(self, panel):
        panel._load_template(TEMPLATE_BARE_METAL)
        panel.cmd_table.clearSelection()
        assert panel._remove_sel_btn.isEnabled() is False
        before = panel.cmd_table.rowCount()
        panel._remove_selected()          # no-op
        assert panel.cmd_table.rowCount() == before
        self._select(panel, [0])
        assert panel._remove_sel_btn.isEnabled() is True

    def test_single_remove_still_removes_the_current_row(self, panel):
        panel._load_template(TEMPLATE_BARE_METAL)
        panel.cmd_table.setCurrentCell(2, 0)
        panel._remove_current()
        assert panel.cmd_table.rowCount() == 8
        assert [c.kind for c in _rows(panel)][0] == KIND_OP


# --------------------------------- 4 Console wait / send / capture optional
def _cmd(**overrides) -> ConsoleCommand:
    base = dict(kind="send", name="Console step", transport="serial",
                timeout=6.0, wait_timeout=10.0, send_timeout=4.0)
    base.update(overrides)
    return ConsoleCommand(**base)


class TestConsoleSegmentsAreOptional:
    def test_wait_only_row_carries_no_send(self):
        cmd = _cmd(kind="wait", wait_enabled=True, send_enabled=False,
                   expect_pass="login:", capture_enabled=False)
        steps = _console_row_steps(cmd, "console")
        assert len(steps) == 1
        assert steps[0].params["wait_enabled"] is True
        assert steps[0].params["send_enabled"] is False

    def test_send_only_row_carries_no_capture(self):
        cmd = _cmd(wait_enabled=False, send_enabled=True, send="uname -r",
                   capture_enabled=False)
        steps = _console_row_steps(cmd, "console")
        assert len(steps) == 1
        assert steps[0].params["capture_enabled"] is False
        assert steps[0].params["send"] == "uname -r"

    def test_capture_only_row_carries_no_send(self):
        cmd = _cmd(wait_enabled=False, send_enabled=False,
                   capture_enabled=True, capture_expected="Linux")
        steps = _console_row_steps(cmd, "console")
        assert len(steps) == 1
        assert steps[0].params["capture_enabled"] is True

    def test_all_segments_empty_is_valid_config(self, panel):
        """M50: an empty wait/send/capture row is a valid single-page
        step (connection data comes from Equipment references)."""
        panel._insert_row(_cmd(wait_enabled=False, send_enabled=False,
                               send="", capture_enabled=False))
        out = panel.values()
        steps = ((yaml.safe_load(out["fct_steps_yaml"]) or {})
                 .get("fct") or {}).get("steps") or []
        assert len(steps) == 1
        assert steps[0]["type"] == STEP_TYPE_CONSOLE_SERIAL


# ------------------------------------------------------------ 5 pre-fill
class TestTemplatePrefill:
    def test_defaults_when_project_carries_nothing(self, panel):
        panel._load_template(TEMPLATE_LINUX)
        rows = _rows(panel)
        assert rows[10].send == "bash /root/fct_assets/connect_wifi.sh router"
        assert rows[7].remote == "/root/fct_assets/connect_wifi.sh"
        assert rows[7].local == "assets/resources/scripts/connect_wifi.sh"

    def test_project_values_prefill_the_loaded_rows(self, panel):
        panel.set_values({"fct_test_config_yaml": PROJECT_YAML})
        assert panel.cmd_table.rowCount() == 0
        panel._load_template(TEMPLATE_LINUX)
        rows = _rows(panel)
        # the connect row runs a script - credentials are not injected
        assert rows[10].send == "bash /root/fct_assets/connect_wifi.sh router"
        assert rows[10].op_params is None
        assert rows[7].remote == "/root/fct_assets/connect_wifi.sh"
        assert rows[7].local != ""                    # project assets dir
        assert rows[16].remote == "/root"             # serial pull source

    def test_m83_template_single_file_push_keeps_its_sub_path(self):
        rows = load_template_commands(
            TEMPLATE_LINUX, {"assets_dir": "/proj/assets_FRDM-IMX93"})
        push = [c for c in rows
                if step_type_label(c) == STEP_TYPE_SERIAL_PUT][0]
        assert push.local == ("/proj/assets_FRDM-IMX93/resources/scripts/"
                              "connect_wifi.sh")

    def test_m83_template_directory_push_still_gets_the_assets_dir(self):
        from mtkgui.engine.fct_templates import apply_prefill

        cmd = ConsoleCommand(kind=KIND_SERIAL_PUT, name="push",
                             local="assets")
        assert apply_prefill(
            cmd, {"assets_dir": "/proj/assets_FRDM-IMX93"}).local == \
            "/proj/assets_FRDM-IMX93"

    def test_prefill_never_touches_non_referenced_fields(self, panel):
        panel.set_values({"fct_test_config_yaml": PROJECT_YAML})
        panel._load_template(TEMPLATE_BARE_METAL)
        rows = _rows(panel)
        assert rows[4].send == "at+fwver"
        assert rows[4].capture_expected == "OK"
        # M83/C9: a Power On row is a passive state carrier
        assert rows[2].op_params["state"] == "on"
