# -*- coding: utf-8 -*-
"""M83 C11: BT Pair count truth and the console-serial l2ping path."""
from __future__ import annotations

import pytest

from mtkgui.engine.fct_exec import FctContext, execute_fct_step
from mtkgui.engine.yaml_validation import (
    SEVERITY_WARNING,
    validate_project_yaml,
)
from mtkgui.gui.yamlbuild.fct_build import STEP_EXTERNAL_TOOL, FctStep


def _pair_step(count: int) -> FctStep:
    return FctStep(
        name="BT pair", step_type=STEP_EXTERNAL_TOOL, channel="ser1",
        timeout_s=20.0,
        params={"fct_console": True, "kind": "send",
                "fct_bt_l2ping": {"count": count}})


def test_m83_bt_pair_zero_count_is_warning_on_load():
    doc = {"test_workflow": {"fct_test_cases": [{
        "name": "Bluetooth: Pair", "kind": "BT_Pair",
        "op_params": {"fct_step": {
            "name": "Bluetooth: Pair", "step_type": "MESSAGE_CHECK",
            "channel": "ser1",
            "params": {"rf_subtest": "pair", "l2ping": 0}}}}]}}
    issues = validate_project_yaml(doc)
    assert any(issue.severity == SEVERITY_WARNING
               and "L2CAP ping count is 0 — l2ping disabled"
               in issue.message
               for issue in issues)


class _SerialChannel:
    """A console channel answering the l2ping summary."""

    def __init__(self, summary="1 sent, 1 received, 0.0% loss"):
        self.writes: list = []
        self.summary = summary

    def write(self, data):
        self.writes.append(bytes(data))

    def read_lines(self, max_lines=200, timeout_s=0.1):
        out, self.summary = ([self.summary], "") if self.summary else ([], "")
        return out


def test_m83_bt_pair_runs_script_over_console_serial(monkeypatch):
    from mtkgui.engine import fct_test_runner

    monkeypatch.setattr(fct_test_runner, "host_bt_address",
                        lambda _runner: "AA:BB:CC:DD:EE:FF")
    channel = _SerialChannel()
    ctx = FctContext(channels={"ser1": channel})
    outcome = execute_fct_step(_pair_step(1), ctx)
    assert outcome.verdict in ("PASS", "FAIL")
    written = b"".join(channel.writes).decode("utf-8", "replace")
    # the pair check runs ON THE DUT through the console serial
    assert "l2ping -c 1 AA:BB:CC:DD:EE:FF" in written


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
