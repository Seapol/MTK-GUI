# -*- coding: utf-8 -*-
"""M83 C7: SFTP rows need a usable SSH channel.

The rule is document-driven: an SFTP row without any SSH channel in the
``console`` section is a build ERROR; a configured but disconnected SSH
channel is a warning (the run-time pre-check refuses the run).
"""
from __future__ import annotations

import pytest

from mtkgui.engine.fct_exec import FctContext, execute_fct_step
from mtkgui.engine.yaml_validation import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    SFTP_NEEDS_SSH_MESSAGE,
    validate_project_yaml,
)
from mtkgui.gui.yamlbuild.fct_build import STEP_MESSAGE_CHECK, FctStep

SFTP_ROW = {"name": "SFTP - push assets",
            "kind": "SSH SFTP: Push file to DUT"}


def _doc(console: list) -> dict:
    return {
        "console": console,
        "test_workflow": {
            "overall_flow": [{"stage": "FCT", "enable": True}],
            "fct_test_cases": [SFTP_ROW],
        },
    }


def _console_issues(doc: dict, **kwargs) -> list:
    return [issue for issue in validate_project_yaml(doc, **kwargs)
            if issue.location == "console"]


def test_m83_sftp_without_ssh_channel_is_error():
    issues = _console_issues(_doc([]))
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_ERROR
    assert issues[0].message == SFTP_NEEDS_SSH_MESSAGE
    assert "add it in the Console panel" in issues[0].message


def test_m83_sftp_with_unconnected_ssh_channel_is_warning():
    doc = _doc([{"kind": "ssh", "params": {"host": "192.168.1.20"}}])
    issues = _console_issues(doc, connected_keys=set())
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_WARNING
    assert "configured but not connected" in issues[0].message


def test_m83_sftp_with_connected_ssh_channel_passes_validation():
    doc = _doc([{"kind": "ssh", "params": {"host": "192.168.1.20"}}])
    assert _console_issues(doc, connected_keys={"ssh1"}) == []


def test_m83_sftp_capture_fields_not_persisted(qapp, monkeypatch):
    """Opening and accepting an SFTP row never keeps capture fields."""
    from PySide6.QtWidgets import QDialog

    from mtkgui.engine.fct_test_config import (
        STEP_TYPE_SFTP_PUT,
        ConsoleCommand,
    )
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel

    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel._insert_row(ConsoleCommand(
        kind="sftp_put", name="SFTP - push", channel="ssh1",
        local="assets/", remote="/root/", capture_enabled=True,
        capture_expected="LEGACY-EXPECTED", capture_unexpected="LEGACY-BAD"))
    monkeypatch.setattr(QDialog, "exec",
                        lambda _dlg: QDialog.DialogCode.Accepted)
    panel._edit_current_row(0)
    saved = panel._get_row_cmd(0)
    assert saved.capture_expected == ""
    assert saved.capture_unexpected == ""
    assert saved.capture_enabled is False
    panel.deleteLater()


def test_m83_sftp_runtime_message_names_the_ssh_requirement():
    step = FctStep(
        name="SFTP - push", step_type=STEP_MESSAGE_CHECK, channel="ssh1",
        timeout_s=5.0,
        params={"fct_console": True, "kind": "sftp_put",
                "action": "sftp_put", "local": "a", "remote": "/root/a"})
    outcome = execute_fct_step(step, FctContext())
    assert outcome.verdict == "ERROR"
    assert "no usable SSH channel" in outcome.reason


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
