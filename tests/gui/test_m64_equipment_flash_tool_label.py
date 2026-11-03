# -*- coding: utf-8 -*-
"""M64: the "J-Link" peripheral is relabelled "Flash Tool/Programmer"
with a reworked config dialog (executable path + arguments + operator
prompt, Self-Test instead of Test Connection) and legacy-YAML
compatibility."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from mtkgui import project_config
from mtkgui.engine import flash_tool
from mtkgui.engine.fct_test_config import (
    DEFAULT_FLASH_GUI_MESSAGE,
    KIND_FLASH_GUI,
    ConsoleCommand,
    flash_gui_message,
)
from mtkgui.engine.ref_resolver import (
    EQUIPMENT_PATHS,
    describe,
    resolve,
    validate_refs,
)
from mtkgui.equipment_page import (
    JLINK_FIELDS,
    DEFAULT_FLASH_TOOL_PROMPT,
    FLASH_TOOL_NAME,
    LEFT_ENTRIES,
    _BlockConfigDialog,
    _mock_configs,
    _flash_tool_self_test,
    _TESTABLE_FORM_KEYS,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------- naming
def _entry(key):
    for _group, entries in LEFT_ENTRIES:
        for ekey, label, _kind, _source in entries:
            if ekey == key:
                return label
    return None


def test_peripheral_is_relabelled():
    assert _entry("jlink") == "Flash Tool/Programmer"
    cfg = _mock_configs()["jlink"]
    assert cfg["title"] == FLASH_TOOL_NAME
    assert dict(cfg["fields"])["Self-test"] == (
        "Launches the tool and asks the operator to confirm usability")


def test_config_fields_are_the_three_user_fields():
    keys = [key for key, _label, _default in JLINK_FIELDS]
    assert keys == ["executable_path", "arguments", "prompt"]
    assert "device" not in keys
    assert JLINK_FIELDS[2][2] == DEFAULT_FLASH_TOOL_PROMPT
    assert "Flash Tool/Programmer" in DEFAULT_FLASH_TOOL_PROMPT


def test_flash_tool_has_no_test_connection_probe():
    assert "jlink" not in _TESTABLE_FORM_KEYS


# ------------------------------------------------------- config dialog
def _dialog(self_test=_flash_tool_self_test):
    cfg = {"title": FLASH_TOOL_NAME, "params": {}}
    return _BlockConfigDialog(
        None, FLASH_TOOL_NAME, _mock_configs()["jlink"]["fields"],
        "", editor=JLINK_FIELDS, config=cfg, self_test=self_test)


def test_dialog_has_self_test_not_test_connection(qapp):
    dlg = _dialog()
    try:
        buttons = [b.text() for b in dlg.findChildren(QPushButton)]
        assert "Self-Test" in buttons
        assert "Test Connection" not in buttons
        assert dlg.windowTitle() == f"{FLASH_TOOL_NAME} - Configuration"
        info_values = [e.text() for e in dlg.findChildren(QLineEdit)
                       if e.isReadOnly()]
        assert "Launches the tool and asks the operator to confirm " \
               "usability" in info_values
    finally:
        dlg.deleteLater()


def test_self_test_button_reports_the_result(qapp):
    seen = []

    def fake(values):
        seen.append(values)
        return True, "Self-Test PASSED: usable"

    dlg = _dialog(self_test=fake)
    try:
        dlg._edits["executable_path"].setText("/opt/flash/Flasher.exe")
        dlg._edits["arguments"].setText("--silent")
        dlg.test_button.click()
        assert seen and seen[0]["executable_path"] == "/opt/flash/Flasher.exe"
        assert "Self-Test PASSED" in dlg.test_result.text()
    finally:
        dlg.deleteLater()


# -------------------------------------------------- legacy YAML merge
def test_legacy_install_path_and_executable_merge_on_load():
    data = {"jlink": {"title": "J-Link", "params": {
        "install_path": "C:/Program Files/SEGGER/JLink",
        "executable": "JLink.exe", "device": "nRF52"}}}
    params = project_config._equipment_from_yaml(data)["jlink"]["params"]
    assert params["executable_path"] == os.path.join(
        "C:/Program Files/SEGGER/JLink", "JLink.exe")
    assert "install_path" not in params
    assert "executable" not in params
    assert "device" not in params


def test_absolute_executable_wins_the_merge():
    data = {"jlink": {"params": {"install_path": "C:/x",
                                 "executable": "/opt/flash/Tool"}}}
    params = project_config._equipment_from_yaml(data)["jlink"]["params"]
    assert params["executable_path"] == "/opt/flash/Tool"


def test_save_writes_executable_path_only():
    cfg = {"jlink": {"title": "x", "params": {
        "install_path": "/opt", "executable": "Flasher.exe",
        "device": "ignored"}}}
    entry = project_config._equipment_to_yaml(cfg)["jlink"]["params"]
    assert entry["executable_path"] == os.path.join("/opt", "Flasher.exe")
    assert set(entry) <= {"executable_path", "arguments", "prompt"}


# ------------------------------------------------------- refs resolve
def test_new_refs_resolve_from_params():
    equipment = {"equipment": {"jlink": {"params": {
        "executable_path": "/opt/flash/Tool",
        "arguments": "--silent", "prompt": "Use the tool"}}}}
    assert resolve("equipment.jlink.executable_path", equipment) == \
        "/opt/flash/Tool"
    assert resolve("equipment.jlink.arguments", equipment) == "--silent"
    assert resolve("equipment.jlink.prompt", equipment) == "Use the tool"
    assert describe("equipment.jlink.executable_path").startswith(
        "Flash Tool/Programmer")


def test_legacy_refs_still_load():
    equipment = {"equipment": {"jlink": {"params": {
        "executable_path": "/opt/flash/Tool"}}}}
    # removed from the schema, but old project refs keep resolving
    assert "equipment.jlink.executable" not in EQUIPMENT_PATHS
    assert resolve("equipment.jlink.executable", equipment) == \
        "/opt/flash/Tool"
    steps = [{"name": "Flash", "ref": {
        "jlink": "equipment.jlink.executable"}}]
    assert validate_refs(steps, equipment) == []


# ------------------------------------------- prompt chain + arguments
def test_prompt_falls_back_to_the_equipment_prompt():
    cmd = ConsoleCommand(kind=KIND_FLASH_GUI, flash_gui_path="/x",
                         flash_gui_message="",
                         flash_gui_prompt="Equipment prompt")
    assert flash_gui_message(cmd) == "Equipment prompt"
    explicit = ConsoleCommand(kind=KIND_FLASH_GUI,
                              flash_gui_message="custom step message",
                              flash_gui_prompt="Equipment prompt")
    assert flash_gui_message(explicit) == "custom step message"
    bare = ConsoleCommand(kind=KIND_FLASH_GUI, flash_gui_message="")
    assert flash_gui_message(bare) == DEFAULT_FLASH_GUI_MESSAGE


def test_built_step_carries_arguments_and_prompt():
    from mtkgui.engine.fct_test_config import _console_row_steps

    cmd = ConsoleCommand(kind=KIND_FLASH_GUI, flash_gui_path="/opt/Flasher",
                         flash_gui_message="",
                         flash_gui_arguments="--silent --force",
                         flash_gui_prompt="Equipment prompt")
    (step,) = _console_row_steps(cmd, "console")
    assert step.params["message"] == "Equipment prompt"
    assert step.params["flash_gui_arguments"] == "--silent --force"
    assert step.params["flash_gui_prompt"] == "Equipment prompt"


def test_command_round_trips_the_m64_fields():
    cmd = ConsoleCommand(kind=KIND_FLASH_GUI, flash_gui_path="/x",
                         flash_gui_arguments="--silent",
                         flash_gui_prompt="Equipment prompt")
    back = ConsoleCommand._from_dict_v2(cmd.to_dict())
    assert back.flash_gui_arguments == "--silent"
    assert back.flash_gui_prompt == "Equipment prompt"


def test_launch_passes_arguments_detached(monkeypatch):
    seen = []

    class _QProcess:
        @staticmethod
        def startDetached(exe, args):
            seen.append((exe, args))
            return (True, 0)

    import PySide6.QtCore as qtcore
    monkeypatch.setattr(qtcore, "QProcess", _QProcess)
    started, detail = flash_tool.launch_tool_gui("/opt/Flasher",
                                                 "--silent --force")
    assert started and "detached" in detail
    assert seen == [("/opt/Flasher", ["--silent", "--force"])]


def test_launch_without_arguments_keeps_the_old_behaviour(monkeypatch):
    seen = []

    class _QProcess:
        @staticmethod
        def startDetached(exe, args):
            seen.append((exe, args))
            return (True, 0)

    import PySide6.QtCore as qtcore
    monkeypatch.setattr(qtcore, "QProcess", _QProcess)
    flash_tool.launch_tool_gui("/opt/Flasher")
    assert seen == [("/opt/Flasher", [])]


def test_launch_never_waits_for_the_process():
    import inspect
    source = inspect.getsource(flash_tool)
    # the contract is a DETACHED launch: no synchronous wait calls
    assert "waitForStarted" not in source
    assert "waitForFinished" not in source
    assert "startDetached" in source


# ----------------------------------------------------------- Self-Test
def test_self_test_requires_an_absolute_path():
    ok, message = _flash_tool_self_test(
        {"executable_path": ""},
        launch=lambda _p, _a: pytest.fail("must not launch"),
        ask=lambda _q: pytest.fail("must not ask"))
    assert not ok and "not configured" in message
    ok, _message = _flash_tool_self_test(
        {"executable_path": "Flasher.exe"},
        launch=lambda _p, _a: pytest.fail("must not launch"),
        ask=lambda _q: pytest.fail("must not ask"))
    assert not ok


def test_self_test_launches_async_then_asks_yes():
    calls = []

    def launch(path, args):
        calls.append(("launch", path, args))
        return True, "launched (detached)"

    def ask(question):
        calls.append(("ask", question))
        return True

    ok, message = _flash_tool_self_test(
        {"executable_path": "/opt/Flasher", "arguments": "--silent",
         "prompt": "Flash now"}, launch=launch, ask=ask)
    assert ok and "PASSED" in message
    # launch happens FIRST (detached), then the operator prompt
    assert [c[0] for c in calls] == ["launch", "ask"]
    assert calls[0][1:] == ("/opt/Flasher", "--silent")
    assert "Flash now" in calls[1][1]
    assert "usable" in calls[1][1]


def test_self_test_operator_no_fails():
    ok, message = _flash_tool_self_test(
        {"executable_path": "/opt/Flasher"},
        launch=lambda _p, _a: (True, "launched"),
        ask=lambda _q: False)
    assert not ok and "not usable" in message


def test_self_test_launch_failure_fails():
    ok, message = _flash_tool_self_test(
        {"executable_path": "/opt/Flasher"},
        launch=lambda _p, _a: (False, "boom"),
        ask=lambda _q: pytest.fail("must not ask"))
    assert not ok and "could not be started" in message


def test_self_test_default_prompt_is_the_configured_default():
    questions = []
    _flash_tool_self_test(
        {"executable_path": "/opt/Flasher", "prompt": ""},
        launch=lambda _p, _a: (True, "launched"),
        ask=lambda q: (questions.append(q) or True))
    assert DEFAULT_FLASH_TOOL_PROMPT in questions[0]
