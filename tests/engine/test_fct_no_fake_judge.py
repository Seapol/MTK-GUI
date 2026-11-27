# -*- coding: utf-8 -*-
"""m118 §3: no PASS without a positive judge.

Three executor branches used to return PASS without matching anything
(any output, silence after an expected-absence window, and a
``capture_is_expected: false`` row hiding its ``expect_pass_re``).
These tests pin the new verdicts and the two load-time rules.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mtkgui.engine.fct_exec import (
    VERDICT_ERROR,
    VERDICT_PASS,
    VERDICT_SKIP,
    FctStep,
    execute_fct_step,
    make_virtual_context,
)
from mtkgui.engine.yaml_validation import (SEVERITY_ERROR,
                                           validate_project_yaml)

NO_JUDGE_REASON = ("no judge configured: add expect_pass_re or set "
                   "setup_only: true")
NO_JUDGE_RULE_MSG = ("row has no judge: add expect_pass_re / "
                     "expect_fail_re / capture_end_line, or set "
                     "setup_only: true")
CONTRADICTION_MSG = ("capture_is_expected=false ignores expect_pass_re - "
                     "remove one of the two")


def _console_step(**params) -> FctStep:
    base = {"fct_console": True, "kind": "send", "send": "uname -a"}
    base.update(params)
    return FctStep(name="Kernel check", category="Console", type="serial",
                   channel="ser1", timeout_s=0.2, params=base)


def _row(**params) -> dict:
    return {
        "name": "Kernel check",
        "kind": "CapturefromConsole",
        "op_params": {"fct_step": {
            "name": "Kernel check",
            "category": "Console", "type": "serial",
            "channel": "ser1",
            "params": dict(params),
        }},
    }


def _errors(doc: dict) -> list:
    return [issue for issue in validate_project_yaml(doc)
            if issue.severity == SEVERITY_ERROR]


# ------------------------------------------------------------- executor
def test_setup_row_without_judge_is_skip():
    """A declared setup row is skipped - it never claims a PASS."""
    ctx, _ = make_virtual_context({"ser1": ["root@imx93:~#"]})
    out = execute_fct_step(_console_step(setup_only=True), ctx)
    assert out.verdict == VERDICT_SKIP
    assert out.reason == "setup row: no judge configured"


def test_message_row_without_judge_is_error():
    """Any echo used to mean PASS; now the missing judge is an ERROR."""
    ctx, _ = make_virtual_context({"ser1": ["root@imx93:~#"]})
    out = execute_fct_step(_console_step(), ctx)
    assert out.verdict == VERDICT_ERROR
    assert out.reason == NO_JUDGE_REASON


def test_expected_absence_without_end_line_is_error():
    """A clean timeout without an End Line is not evidence any more."""
    ctx, _ = make_virtual_context({"ser1": ["booting", "still fine"]})
    out = execute_fct_step(
        _console_step(expect_fail_re="FATAL", capture_is_expected=False),
        ctx)
    assert out.verdict == VERDICT_ERROR
    assert out.reason == "expected-absence row needs capture_end_line"


def test_expected_absence_with_end_line_still_passes():
    """The End Line is real evidence: zero fail hits up to it -> PASS."""
    ctx, _ = make_virtual_context({"ser1": ["all good", "PROMPT"]})
    out = execute_fct_step(
        _console_step(expect_fail_re="ERROR", capture_is_expected=False,
                      capture_end_line="PROMPT"), ctx)
    assert out.verdict == VERDICT_PASS
    assert out.reason == "clean window up to End Line"


# ------------------------------------------------------------ validator
def test_validator_blocks_row_without_judge():
    issues = _errors({"test_workflow": {"fct_test_cases": [_row()]}})
    assert any(issue.message == NO_JUDGE_RULE_MSG
               and issue.location == "fct_test_cases[0].name"
               for issue in issues)


def test_validator_allows_setup_only_row():
    assert _errors({"test_workflow": {
        "fct_test_cases": [_row(setup_only=True)]}}) == []


def test_validator_blocks_capture_is_expected_contradiction():
    issues = _errors({"test_workflow": {"fct_test_cases": [
        _row(capture_is_expected=False, expect_pass_re="READY")]}})
    assert any(issue.message == CONTRADICTION_MSG
               and issue.location == "fct_test_cases[0].name"
               for issue in issues)
