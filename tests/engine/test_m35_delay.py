# -*- coding: utf-8 -*-
"""M35: merge the duplicate Add menus and add the Delay main-table Type.

The legacy StepsEditorDialog keeps only the 11 standard operations +
Custom + Delay; every other step type is added from the main FCT
Sequence table (20 Types = 18 + Flash_GUI + Delay).  A Delay row is a
plain fixed wait (no console / instrument I/O), result Done.

M42: Delay has NO timeout of its own - the wait is never capped by
the step timeout, the editor holds only the wait input and the
main-table Timeout cell is a read-only 0."""
from __future__ import annotations

import time

import pytest

from mtkgui.engine import fct_exec as fe
from mtkgui.engine.fct_test_config import (
    KIND_DELAY,
    STEP_TYPE_DELAY,
    STEP_TYPE_LABELS,
    _console_row_steps,
    ConsoleCommand,
    FctTestConfig,
    console_command_for_label,
    step_type_label,
)
from mtkgui.engine.fct_test_runner import FctTestRunner
from mtkgui.engine.steps import OP_STEPS


def _config(*cmds: ConsoleCommand) -> FctTestConfig:
    return FctTestConfig.from_dict({
        "dut_type": "linux",
        "console": {"enabled": True, "port": "COM1", "baudrate": 115200,
                    "test_commands": [c.to_dict() for c in cmds]},
    })


# ---------------------------------------------------------------- model
class TestDelayModel:
    def test_label_and_defaults(self):
        # M43: Delay is no longer a standalone Add-menu Type item (it
        # lives in the Operation submenu); the kind stays valid
        assert STEP_TYPE_DELAY not in STEP_TYPE_LABELS
        assert len(STEP_TYPE_LABELS) == 19
        cmd = console_command_for_label(STEP_TYPE_DELAY, "Delay")
        assert cmd.kind == KIND_DELAY
        assert cmd.wait_ms == 1000
        assert cmd.timeout == 0.0
        assert step_type_label(cmd) == STEP_TYPE_DELAY

    def test_roundtrip(self):
        cmd = ConsoleCommand(kind=KIND_DELAY, name="Settle", wait_ms=2500,
                             timeout=3.0)
        data = cmd.to_dict()
        assert data["wait_ms"] == 2500
        back = ConsoleCommand._from_dict_v2(data)
        assert back.kind == KIND_DELAY
        assert back.wait_ms == 2500
        assert back.timeout == 3.0

    def test_built_step_is_delay_action(self):
        (step,) = _console_row_steps(
            ConsoleCommand(kind=KIND_DELAY, name="Wait", wait_ms=750,
                           timeout=2.0), "console")
        assert step.params["fct_delay_ms"] == 750
        assert step.step_type == "EXTERNAL_TOOL"


# ------------------------------------------------------------- execution
class TestDelayExecution:
    def test_runner_waits_and_passes(self, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(time, "sleep",
                            lambda s: slept.append(float(s)))
        logs: list[str] = []
        runner = FctTestRunner(
            _config(ConsoleCommand(kind=KIND_DELAY, name="Delay",
                                   wait_ms=500)),
            log_sink=logs.append)
        results = runner.run_console(object())
        assert slept == [0.5]
        assert results[0].verdict == "PASS"
        assert "Done" in results[0].detail

    def test_runner_waits_full_wait_regardless_of_timeout(self, monkeypatch):
        """M42: a Delay waits its full wait_ms - the step timeout is not
        a Delay concept and never caps the wait."""
        slept: list[float] = []
        monkeypatch.setattr(time, "sleep",
                            lambda s: slept.append(float(s)))
        runner = FctTestRunner(
            _config(ConsoleCommand(kind=KIND_DELAY, wait_ms=9000,
                                   timeout=2.5)),
            log_sink=lambda _m: None)
        results = runner.run_console(object())
        assert slept == [9.0]
        assert results[0].verdict == "PASS"

    def test_runner_runs_without_console_or_serial(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        cfg = FctTestConfig.from_dict({
            "dut_type": "bare_metal",
            "console": {"enabled": False,
                        "test_commands": [
                            ConsoleCommand(kind=KIND_DELAY,
                                           wait_ms=100).to_dict()]},
        })
        runner = FctTestRunner(cfg, log_sink=lambda _m: None)
        results = runner.run_console(None)
        assert results[0].verdict == "PASS"

    def test_delay_does_not_stop_the_chain(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        cfg = FctTestConfig.from_dict({
            "dut_type": "linux",
            "console": {"enabled": False,
                        "test_commands": [
                            ConsoleCommand(kind=KIND_DELAY,
                                           wait_ms=100).to_dict(),
                            ConsoleCommand(kind=KIND_DELAY,
                                           wait_ms=200).to_dict()]},
        })
        runner = FctTestRunner(cfg, log_sink=lambda _m: None)
        results = runner.run_console(None)
        assert [r.verdict for r in results] == ["PASS", "PASS"]

    def test_exec_step_waits(self, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(time, "sleep",
                            lambda s: slept.append(float(s)))
        step = _console_row_steps(
            ConsoleCommand(kind=KIND_DELAY, wait_ms=400, timeout=1.0),
            "console")[0]
        ctx = fe.FctContext()
        out = fe.execute_fct_step(step, ctx)
        assert out.verdict == "PASS"
        assert slept == [0.4]
        assert "Done" in out.reason

    def test_exec_step_waits_full_wait_regardless_of_timeout(self, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(time, "sleep",
                            lambda s: slept.append(float(s)))
        step = _console_row_steps(
            ConsoleCommand(kind=KIND_DELAY, wait_ms=9000, timeout=2.0),
            "console")[0]
        out = fe.execute_fct_step(step, fe.FctContext())
        assert slept == [9.0]
        assert out.verdict == "PASS"


# ---------------------------------------------------------------- GUI
@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestAddMenus:
    def test_main_table_menu_offers_delay_via_operation_submenu(self, qapp):
        """M43: Delay is added from the Operation submenu (standalone
        item gone)."""
        from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (
            FCTTestConfigPanel, _COL_CMD, _COL_TYPE, _COL_TIMEOUT)
        panel = FCTTestConfigPanel()
        panel.set_values({})
        assert STEP_TYPE_DELAY not in panel._add_actions
        action = panel._op_add_actions["Delay — plain wait (ms)"]
        assert action.isEnabled()
        action.trigger()
        row = panel.cmd_table.rowCount() - 1
        cmd = panel._get_row_cmd(row)
        assert cmd.kind == KIND_DELAY
        assert panel.cmd_table.item(row, _COL_TYPE).text() == STEP_TYPE_DELAY
        assert panel.cmd_table.item(row, _COL_CMD).text() == "1000 ms"
        assert panel.cmd_table.item(row, _COL_TIMEOUT).text() == "0"

    def test_main_table_covers_all_direct_types(self, qapp):
        """M43: 18 direct Type items; Operation is a submenu."""
        from mtkgui.engine.fct_test_config import STEP_TYPE_OPERATION
        from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (
            FCTTestConfigPanel, _COL_TYPE)
        panel = FCTTestConfigPanel()
        panel.set_values({})
        direct = set(STEP_TYPE_LABELS) - {STEP_TYPE_OPERATION}
        assert set(panel._add_actions) == direct
        assert len(panel._add_actions) == 18
        for label in direct:
            panel._add_row_for_label(label)
            row = panel.cmd_table.rowCount() - 1
            assert panel.cmd_table.item(row, _COL_TYPE).text() == label

    def test_delay_editor_sets_wait_without_timeout(self, qapp, monkeypatch):
        """M42: the Delay editor holds ONLY the wait input - no Timeout
        row, no timeout spin, and the dialog stays a narrow single
        column form."""
        from PySide6.QtWidgets import QDialog, QDoubleSpinBox, QLabel, \
            QSpinBox
        from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (
            FCTTestConfigPanel, _COL_CMD)
        panel = FCTTestConfigPanel()
        panel.set_values({})
        row = panel.cmd_table.rowCount()
        panel._add_row_for_label(STEP_TYPE_DELAY)

        def fake_exec(dlg):
            assert dlg.windowTitle() == "Delay editor"
            # narrow single-column form (M42)
            assert dlg.maximumWidth() <= 420
            labels = [lab.text() for lab in dlg.findChildren(QLabel)]
            assert not any("Timeout" in t for t in labels)
            assert dlg.findChildren(QDoubleSpinBox) == []
            spin = dlg.findChildren(QSpinBox)[0]
            spin.setValue(2500)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        panel._edit_current_row(row)
        cmd = panel._get_row_cmd(row)
        assert cmd.kind == KIND_DELAY
        assert cmd.wait_ms == 2500
        assert cmd.timeout == 0.0
        assert panel.cmd_table.item(row, _COL_CMD).text() == "2500 ms"

    def test_delay_row_timeout_cell_is_read_only_zero(self, qapp):
        """M42: a Delay row's Timeout cell shows 0 and cannot be edited."""
        from PySide6.QtCore import Qt
        from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (
            FCTTestConfigPanel, _COL_TIMEOUT)
        panel = FCTTestConfigPanel()
        panel.set_values({})
        row = panel.cmd_table.rowCount()
        panel._add_row_for_label(STEP_TYPE_DELAY)
        item = panel.cmd_table.item(row, _COL_TIMEOUT)
        assert item.text() == "0"
        assert not (item.flags() & Qt.ItemIsEditable)

    def test_legacy_fct_menu_keeps_only_ops_custom_delay(self, qapp):
        from mtkgui.gui.steps_editor import StepsEditorDialog
        dlg = StepsEditorDialog("fct", [], [], [], [])
        texts = [a.text() for a in dlg.btn_add.menu().actions()]
        expected = [f"Operation: {n}" for n in OP_STEPS]
        expected += ["Operation: Custom", "Delay — plain wait (ms)"]
        assert texts == expected
        assert not any("MessageOK" in t for t in texts)
        assert not any(t.startswith(("Sendto", "Waitfor", "Capturefrom"))
                       for t in texts)
        assert not any(t.startswith(("WIFI", "Bluetooth")) for t in texts)

    def test_legacy_ict_menu_keeps_measurements(self, qapp):
        from mtkgui.gui.steps_editor import StepsEditorDialog
        dlg = StepsEditorDialog("ict", [], [], [], [])
        texts = [a.text() for a in dlg.btn_add.menu().actions()]
        assert "Delay — plain wait (ms)" in texts
        assert any(t.startswith("R-GND") for t in texts)
        assert not any("MessageOK" in t for t in texts)
