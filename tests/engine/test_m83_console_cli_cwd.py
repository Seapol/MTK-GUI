# -*- coding: utf-8 -*-
"""M83 C6: Console_cli working directory + capture regex flags."""
from __future__ import annotations

import pytest

from mtkgui.engine.fct_test_config import (
    ConsoleCommand,
    FctTestConfig,
    _console_row_steps,
)
from mtkgui.engine.fct_test_runner import FctTestRunner
from mtkgui.gui.yamlbuild.fct_build import FctStep


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _cli(cwd: str = "", **fields) -> ConsoleCommand:
    base = {"kind": "host", "name": "iperf3 server",
            "host_cmd_windows": "iperf3 -s"}
    base.update(fields)
    return ConsoleCommand(cwd=cwd, **base)


def test_m83_cli_cwd_reaches_fct_host_cmd():
    (step,) = _console_row_steps(_cli("C:\\Tools\\iperf"), "")
    assert isinstance(step, FctStep)
    assert step.params["fct_host_cmd"]["cwd"] == "C:\\Tools\\iperf"


def test_m83_cli_empty_cwd_stays_empty():
    (step,) = _console_row_steps(_cli(""), "")
    assert step.params["fct_host_cmd"]["cwd"] == ""


def test_m83_cli_cwd_is_not_written_when_empty():
    empty = _cli("").to_dict()
    assert "cwd" not in empty
    filled = _cli("C:\\Tools\\iperf").to_dict()
    assert filled["cwd"] == "C:\\Tools\\iperf"
    restored = ConsoleCommand._from_dict_v2(filled)
    assert restored.cwd == "C:\\Tools\\iperf"


class _HostResult:
    def __init__(self, exit_code: int, lines: list):
        self.exit_code = exit_code
        self.lines = lines
        self.reason = ""


class _HostRunner:
    def __init__(self, lines: list):
        self.lines = lines

    def run(self, _line):
        return _HostResult(0, list(self.lines))


def test_m83_cli_regex_flags_are_honoured():
    runner = FctTestRunner(FctTestConfig.from_dict(
        {"console": {"enabled": True}}))
    host = _HostRunner(["IPv4 Address. . . 192.168.1.5"])
    # a regex capture passes only when the row says it is a regex
    regex_cmd = _cli(capture_expected=r"IPv4\s+Address.*192\.168",
                     expect_pass_is_regex=True)
    verdict, _detail = runner._run_host_cli(regex_cmd, host)
    assert verdict == "PASS"
    literal_cmd = _cli(capture_expected=r"IPv4\s+Address.*192\.168",
                       expect_pass_is_regex=False)
    verdict, detail = runner._run_host_cli(literal_cmd, host)
    assert verdict == "FAIL" and "expected not found" in detail
    # the unexpected flag is independent of the expected one
    unexp_cmd = _cli(capture_unexpected=r"Media\s+disconnected",
                     expect_fail_is_regex=True)
    verdict, detail = runner._run_host_cli(
        unexp_cmd, _HostRunner(["Media   disconnected"]))
    assert verdict == "FAIL" and "unexpected found" in detail


def test_m83_cli_dialog_has_working_directory_and_browse(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog, QLabel, QPushButton

    from mtkgui.engine.fct_test_config import STEP_TYPE_CONSOLE_CLI
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel

    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel._add_row_for_label(STEP_TYPE_CONSOLE_CLI)
    row = panel.cmd_table.rowCount() - 1
    seen: dict = {}

    def fake_exec(dlg):
        seen["labels"] = [lab.text() for lab in dlg.findChildren(QLabel)]
        seen["buttons"] = [b.text() for b in dlg.findChildren(QPushButton)]
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(row)
    assert any("Working directory:" in text for text in seen["labels"])
    assert "Browse..." in seen["buttons"]
    joined = " ".join(seen["labels"])
    assert "Empty = the executable's own directory" in joined
    panel.deleteLater()
