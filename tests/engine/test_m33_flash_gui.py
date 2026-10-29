# -*- coding: utf-8 -*-
"""M33: the Flash_GUI step and the retirement of the legacy flash ops.

Four execution states (missing path / launch failure / launch + GO /
already-running reuse + STOP), the model round-trip and label mapping,
the merged-table Add menu / editor, the OP_STEPS retirement, and the
guarantee that an OLD yaml that still carries flash steps LOADS (the
M39 importer is what will later block them, not this change)."""
from __future__ import annotations

import pytest

from mtkgui.engine.fct_test_config import (
    DEFAULT_FLASH_GUI_MESSAGE,
    FctTestConfig,
    KIND_FLASH_GUI,
    STEP_TYPE_FLASH_GUI,
    STEP_TYPE_LABELS,
    ConsoleCommand,
    console_command_for_label,
    step_type_label,
)
from mtkgui.engine import fct_test_runner as runner_mod
from mtkgui.engine.fct_test_runner import FctTestRunner
from mtkgui.engine.sequence import load_sequence
from mtkgui.engine.steps import OP_STEPS


FLASH_PATH = "/opt/flash/Flasher.exe"


def _flash_cmd(**kw) -> ConsoleCommand:
    kw.setdefault("flash_gui_path", FLASH_PATH)
    return ConsoleCommand(kind=KIND_FLASH_GUI, name="Flash_GUI", **kw)


def _config(*cmds: ConsoleCommand) -> FctTestConfig:
    return FctTestConfig.from_dict({
        "dut_type": "linux",
        "console": {"enabled": True, "port": "COM1", "baudrate": 115200,
                    "test_commands": [c.to_dict() for c in cmds]},
    })


# --------------------------------------------------------------- model
class TestFlashGuiModel:
    def test_fields_roundtrip(self):
        cmd = ConsoleCommand(kind=KIND_FLASH_GUI, name="Flash",
                             flash_gui_path=FLASH_PATH,
                             flash_gui_message="custom prompt")
        data = cmd.to_dict()
        assert data["flash_gui_path"] == FLASH_PATH
        assert data["flash_gui_message"] == "custom prompt"
        back = ConsoleCommand._from_dict_v2(data)
        assert back.kind == KIND_FLASH_GUI
        assert back.flash_gui_path == FLASH_PATH
        assert back.flash_gui_message == "custom prompt"

    def test_label_mapping(self):
        cmd = ConsoleCommand(kind=KIND_FLASH_GUI)
        assert step_type_label(cmd) == STEP_TYPE_FLASH_GUI
        assert STEP_TYPE_FLASH_GUI in STEP_TYPE_LABELS
        default = console_command_for_label(STEP_TYPE_FLASH_GUI, "Flash_GUI")
        assert default.kind == KIND_FLASH_GUI
        assert default.flash_gui_path == ""
        assert default.flash_gui_message == DEFAULT_FLASH_GUI_MESSAGE


# ------------------------------------------------------------- runner
class TestFlashGuiExecution:
    def _runner(self, *cmds, logs=None, confirm=True):
        runner = FctTestRunner(_config(*cmds),
                               log_sink=(logs if logs is not None
                                         else (lambda _m: None)))
        runner._human_confirm = lambda _m: confirm
        return runner

    def test_missing_path_fails(self):
        r = self._runner(_flash_cmd(flash_gui_path=""))
        results = r.run_console(object())
        assert len(results) == 1
        assert results[0].verdict == "FAIL"
        assert "not configured" in results[0].detail

    def test_launch_failure_fails(self, monkeypatch):
        monkeypatch.setattr(runner_mod, "_flash_gui_process_running",
                            lambda _p: False)
        monkeypatch.setattr("mtkgui.engine.flash_tool.launch_tool_gui",
                            lambda _p: (False, "boom"))
        r = self._runner(_flash_cmd())
        results = r.run_console(object())
        assert results[0].verdict == "FAIL"
        assert "launch failed" in results[0].detail

    def test_launch_and_go_passes(self, monkeypatch):
        launched = []
        messages = []
        monkeypatch.setattr(runner_mod, "_flash_gui_process_running",
                            lambda _p: False)
        monkeypatch.setattr(
            "mtkgui.engine.flash_tool.launch_tool_gui",
            lambda p: (launched.append(p) or (True, "launched (detached)")))

        def confirm(msg):
            messages.append(msg)
            return True
        r = FctTestRunner(_config(_flash_cmd(flash_gui_message="custom")))
        r._human_confirm = confirm
        results = r.run_console(object())
        assert launched == [FLASH_PATH]
        assert messages == ["custom"]
        assert results[0].verdict == "PASS"
        assert "GO" in results[0].detail

    def test_already_running_is_reused_not_relaunched(self, monkeypatch):
        launched = []
        logs: list = []
        monkeypatch.setattr(runner_mod, "_flash_gui_process_running",
                            lambda _p: True)
        monkeypatch.setattr(
            "mtkgui.engine.flash_tool.launch_tool_gui",
            lambda p: (launched.append(p) or (True, "launched")))
        r = self._runner(_flash_cmd(), logs=logs.append)
        results = r.run_console(object())
        assert launched == []
        assert any("reusing running GUI (no relaunch)" in ln for ln in logs)
        assert results[0].verdict == "PASS"

    def test_stop_fails_and_stops_the_remaining_rows(self, monkeypatch):
        launched = []
        monkeypatch.setattr(runner_mod, "_flash_gui_process_running",
                            lambda _p: False)
        monkeypatch.setattr(
            "mtkgui.engine.flash_tool.launch_tool_gui",
            lambda p: (launched.append(p) or (True, "launched")))
        after = ConsoleCommand(kind="wait", name="After flash",
                               wait_enabled=True, expect_pass="prompt")
        r = self._runner(_flash_cmd(retries=2), after, confirm=False)
        results = r.run_console(object())
        assert len(results) == 1          # stop-chain: later rows never run
        assert results[0].verdict == "FAIL"
        assert "STOP" in results[0].detail
        assert launched == [FLASH_PATH]   # a STOP is never retried

    def test_runs_without_console_or_serial(self, monkeypatch):
        """M33: a Flash_GUI row never touches the DUT console, so it
        must still run when the console is disabled / no port is bound."""
        launched = []
        monkeypatch.setattr(runner_mod, "_flash_gui_process_running",
                            lambda _p: False)
        monkeypatch.setattr(
            "mtkgui.engine.flash_tool.launch_tool_gui",
            lambda p: (launched.append(p) or (True, "launched")))
        cfg = FctTestConfig.from_dict({
            "dut_type": "bare_metal",
            "console": {"enabled": False,
                        "test_commands": [_flash_cmd().to_dict()]},
        })
        runner = FctTestRunner(cfg, log_sink=lambda _m: None)
        runner._human_confirm = lambda _m: True
        results = runner.run_console(None)
        assert launched == [FLASH_PATH]
        assert results[0].verdict == "PASS"


# --------------------------------------------- published-YAML step
def test_built_step_is_gostop_confirm_with_path():
    """The published YAML carries a GUI_CONFIRM (Go / Stop) step."""
    from mtkgui.engine.fct_test_config import _console_row_steps
    from mtkgui.gui.yamlbuild.fct_build import STEP_GUI_CONFIRM
    (step,) = _console_row_steps(_flash_cmd(flash_gui_message="custom"),
                                 "console")
    assert step.step_type == STEP_GUI_CONFIRM
    assert step.params["style"] == "gostop"
    assert step.params["message"] == "custom"
    assert step.params["flash_gui_path"] == FLASH_PATH


# -------------------------------------------------------------- GUI
class TestFlashGuiPanel:
    @pytest.fixture
    def panel(self):
        pytest.importorskip("PySide6")
        from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (
            FCTTestConfigPanel)
        return FCTTestConfigPanel()

    def test_add_menu_has_flash_section(self, panel):
        from PySide6.QtWidgets import QMenu
        action = panel._add_actions[STEP_TYPE_FLASH_GUI]
        menu = action.parent()
        assert isinstance(menu, QMenu)
        assert "Flash" in [a.text() for a in menu.actions()]

    def test_new_row_summary_shows_no_path(self, panel):
        from mtkgui.gui.yamlbuild.FCTTestConfigWidget import _COL_CMD
        panel.set_values({})
        row = panel.cmd_table.rowCount()
        panel._add_row_for_label(STEP_TYPE_FLASH_GUI)
        cmd = panel._get_row_cmd(row)
        assert cmd.kind == KIND_FLASH_GUI
        assert panel.cmd_table.item(row, _COL_CMD).text() == "(no path)"

    def test_editor_has_path_and_message_fields(self, panel, monkeypatch):
        from PySide6.QtWidgets import (QDialog, QLineEdit, QTextEdit)
        from mtkgui.gui.yamlbuild.FCTTestConfigWidget import _COL_CMD
        panel.set_values({})
        row = panel.cmd_table.rowCount()
        panel._add_row_for_label(STEP_TYPE_FLASH_GUI)

        def fake_exec(dlg):
            assert dlg.windowTitle() == "Flash_GUI editor"
            line = dlg.findChildren(QLineEdit)[0]
            line.setText(FLASH_PATH)
            text = dlg.findChildren(QTextEdit)[0]
            text.setPlainText("custom prompt")
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        panel._edit_current_row(row)
        cmd = panel._get_row_cmd(row)
        assert cmd.kind == KIND_FLASH_GUI
        assert cmd.flash_gui_path == FLASH_PATH
        assert cmd.flash_gui_message == "custom prompt"
        assert panel.cmd_table.item(row, _COL_CMD).text() == FLASH_PATH


# --------------------------------------------- retired legacy flash ops
def test_op_steps_no_longer_carry_flash_ops():
    assert "Flash FAT Firmware" not in OP_STEPS
    assert "Flash OOBE Firmware" not in OP_STEPS


# ------------------------------------ old flash yaml still LOADS (M39 later)
def test_legacy_flash_sequence_yaml_still_loads():
    cfg = {
        "test_workflow": {
            "overall_flow": [
                {"stage": "ICT", "enable": True},
                {"stage": "Flash FAT Firmware", "enable": True},
                {"stage": "FCT", "enable": True},
            ],
            "ict_test_cases": [],
            "fct_test_cases": [
                {"name": "Flash FAT Firmware", "kind": "op",
                 "op_params": {"type": "flash",
                               "flash_params": {"mode": "jlink"}}},
            ],
        },
    }
    stages = load_sequence(cfg)
    assert [s.name for s in stages] == ["ICT", "FCT"]
    flash = next(s for s in stages[1].steps
                 if s.name == "Flash FAT Firmware")
    assert flash.kind == "op"
    assert flash.op_params["type"] == "flash"


def test_legacy_flash_sequence_rows_still_load():
    pytest.importorskip("PySide6")
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel
    yaml_text = (
        "- name: Flash FAT Firmware\n"
        "  kind: op\n"
        "  op_params: {type: flash, flash_params: {mode: jlink}}\n")
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_sequence_cases_yaml": yaml_text})
    assert panel.cmd_table.rowCount() == 1
    cmd = panel._get_row_cmd(0)
    assert cmd.kind == "op" and cmd.op_kind == "op"
    assert cmd.op_params["type"] == "flash"
    assert cmd.op_params["flash_params"]["mode"] == "jlink"
