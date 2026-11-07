# -*- coding: utf-8 -*-
"""M83 C12: Flash_GUI path comes from Equipment; one prompt key."""
from __future__ import annotations

import pytest

from mtkgui.engine.fct_exec import FctContext, execute_fct_step
from mtkgui.engine.fct_test_config import (
    KIND_FLASH_GUI,
    ConsoleCommand,
    _console_row_steps,
    flash_gui_message,
)
from mtkgui.engine.yaml_validation import (
    LEGACY_FLASH_MESSAGE_MSG,
    LEGACY_FLASH_PATH_MSG,
    SEVERITY_WARNING,
    validate_project_yaml,
)


def test_m83_flash_gui_path_comes_from_equipment(qapp):
    import yaml

    from mtkgui.yaml_build_page import YamlBuildPage

    page = YamlBuildPage()
    page.equipment_provider = lambda: {"equipment": {
        "host": {"params": {"flash_tool": "C:/Tools/flash.exe"}}}}
    steps = {"fct": {"steps": [{"type": "Flash_GUI", "name": "Flash"}]}}
    cases, errors = page._emit_fct_sequence(
        {"fct_steps_yaml": yaml.safe_dump(steps)})
    assert errors == [] and cases
    marker = cases[0]["op_params"]["fct_step"]
    assert marker["params"]["flash_gui_path"] == "C:/Tools/flash.exe"
    page.deleteLater()


def test_m83_flash_gui_legacy_path_is_ignored_with_warning():
    doc = {"test_workflow": {"fct_test_cases": [{
        "name": "Flash_GUI", "kind": "Flash_GUI",
        "op_params": {"fct_step": {
            "name": "Flash_GUI", "step_type": "GUI_CONFIRM",
            "params": {"flash_gui_path": "C:/old.exe",
                       "flash_gui_message": "old prompt"}}}}]}}
    warnings = [issue for issue in validate_project_yaml(doc)
                if issue.severity == SEVERITY_WARNING]
    assert any(issue.message == LEGACY_FLASH_PATH_MSG for issue in warnings)
    assert any(issue.message == LEGACY_FLASH_MESSAGE_MSG
               for issue in warnings)


def test_m83_flash_gui_message_prompt_is_single_key():
    cmd = ConsoleCommand(kind=KIND_FLASH_GUI,
                         flash_gui_prompt="Press Go when done",
                         flash_gui_message="legacy prompt",
                         flash_gui_path="C:/old.exe")
    assert flash_gui_message(cmd) == "Press Go when done"
    data = cmd.to_dict()
    assert data["flash_gui_prompt"] == "Press Go when done"
    assert "flash_gui_message" not in data
    assert "flash_gui_path" not in data


def test_m83_flash_gui_gostop_semantics_preserved(monkeypatch):
    from mtkgui.engine import fct_test_runner

    monkeypatch.setattr(fct_test_runner, "_flash_gui_process_running",
                        lambda _path: False)
    from mtkgui.engine import flash_tool
    monkeypatch.setattr(flash_tool, "launch_tool_gui",
                        lambda path, args="": (True, f"{path} started"))
    cmd = ConsoleCommand(kind=KIND_FLASH_GUI, name="Flash_GUI",
                         flash_gui_prompt="Flash done?")
    cmd.flash_gui_path = "C:/Tools/flash.exe"
    (step,) = _console_row_steps(cmd, "")
    assert step.params["style"] == "gostop"
    assert step.params["message"] == "Flash done?"
    go = execute_fct_step(step, FctContext(human_confirm=lambda _s: True))
    assert go.verdict == "PASS"
    stop = execute_fct_step(step, FctContext(human_confirm=lambda _s: False))
    assert stop.verdict == "FAIL"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
