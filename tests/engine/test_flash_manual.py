# -*- coding: utf-8 -*-
"""Manual (operator-judged) flash path (R3 of the dual-path flash).

``op_params.mode == "manual"`` opens the third-party GUI and takes the
operator's MessageGoStop answer as the verdict: GO -> PASS (Done),
STOP -> FAIL and the run stops, timeout -> FAIL, no operator dialog
(headless) -> IGNORED (never guessed).  Run Demo simulates the GO.
The auto path never touches the operator dialog."""
from __future__ import annotations

import pytest

from mtkgui.engine.results import StepStatus  # noqa: E402
from mtkgui.engine.runner import (TestRunner,  # noqa: E402
                                  op_verdict_status)

FLASH_NAME = "Flash FAT Firmware"
TestRunner.__test__ = False     # pytest must not collect the engine class
FLASH_OP = ("op", FLASH_NAME, "—", "—", "—", "—",
            {"type": "flash", "slot": "fat", "mode": "manual"})


def _flash_params(**over):
    params = {"type": "flash", "slot": "fat", "mode": "manual"}
    params.update(over)
    return params


def _env_with_flash(env, params=None, question=True):
    """One ICT flash op row and a recording operator dialog whose
    answers come from ``env._answers`` (empty -> timeout)."""
    env.ict_steps = [("op", FLASH_NAME, "—", "—", "—", "—",
                      params or _flash_params())]
    env.ict_enables = [True]
    env._answers = []
    env.dialog_calls = []

    def _dialog(kind, name, timeout_s=0.0):
        env.dialog_calls.append((kind, name, timeout_s))
        return env._answers.pop(0) if env._answers else "timeout"

    if question:
        env._fct_message_dialog = _dialog
    return env


def _run_ict(env, interactive=True) -> TestRunner:
    """Execute the flash op row through the ICT staging path (the
    interactivity travels on the runner, set by _exec_with_retry)."""
    runner = TestRunner(env)
    env.runner = runner
    runner._op_interactive = interactive
    runner._exec_ict_row(0)
    return runner


# ------------------------------------------------------- verdict mapping
def test_op_verdict_status_maps_every_verdict():
    assert op_verdict_status("Done") is StepStatus.PASS
    assert op_verdict_status("Fail") is StepStatus.FAIL
    assert op_verdict_status("Ignore") is StepStatus.IGNORED
    assert op_verdict_status("Error") is StepStatus.ERROR
    assert op_verdict_status("garbage") is StepStatus.ERROR   # safe default


# -------------------------------------------------------------- GO / STOP
def test_manual_go_passes_and_asks_gostop(env):
    """GO -> the operator judged the flash OK -> row Done."""
    _env_with_flash(env)
    env._answers = ["go"]
    _run_ict(env)
    assert env.rows[("ict", 0)] == "Done"
    kind, prompt, timeout = env.dialog_calls[0]
    assert kind == "MessageGoStop"
    assert "fat" in prompt and "GO / STOP" in prompt
    assert timeout == 0.0


def test_manual_stop_fails_and_stops_the_run(env):
    """STOP -> FAIL and the run stops (operator-style abort)."""
    _env_with_flash(env)
    env._answers = ["stop"]
    runner = TestRunner(env)
    env.runner = runner
    stops = []
    runner.abort = lambda trigger="operator": stops.append(trigger)
    runner._exec_ict_row(0)
    assert env.rows[("ict", 0)] == "FAIL"
    assert stops == ["operator"]


def test_manual_timeout_fails_without_stopping(env):
    """A timeout is an honest FAIL, but it is NOT an operator STOP -
    the run keeps going (the stop policy decides)."""
    _env_with_flash(env)
    env._answers = ["timeout"]
    runner = TestRunner(env)
    env.runner = runner
    stops = []
    runner.abort = lambda trigger="operator": stops.append(trigger)
    runner._exec_ict_row(0)
    assert env.rows[("ict", 0)] == "FAIL"
    assert stops == []


def test_manual_go_stop_reason_surfaces_in_detail(env):
    """The row detail carries the reason (the report shows why)."""
    _env_with_flash(env)
    env._answers = ["stop"]
    runner = TestRunner(env)
    env.runner = runner
    runner.abort = lambda trigger="operator": None
    runner._exec_ict_row(0)
    # R4: the Measured cell carries the operator verdict source
    assert "Operator: Stop" in str(env.measured.get(("ict", 0), ""))
    assert "operator STOP" in str(getattr(runner, "_last_op_error", ""))


# ---------------------------------------------------------- headless
def test_manual_headless_is_ignored(env):
    """No operator dialog (headless) -> the row is IGNORE, never a
    guessed PASS."""
    _env_with_flash(env, question=False)
    _run_ict(env)
    assert env.rows[("ict", 0)] == "Ignore"


def test_manual_legacy_two_arg_stub_is_ignored(env):
    """The demo env exposes a 2-arg ``_fct_message_dialog`` stub - the
    manual path must not crash on it, it IGNOREs instead."""
    _env_with_flash(env)
    env._fct_message_dialog = lambda kind, name: "PASS"
    _run_ict(env)
    assert env.rows[("ict", 0)] == "Ignore"


def test_manual_run_demo_simulates_go(env):
    """interactive=False (Run Demo / smoke) never pops a dialog - the
    operator GO is simulated and the row PASSes."""
    _env_with_flash(env)
    _run_ict(env, interactive=False)
    assert env.rows[("ict", 0)] == "Done"
    assert env.dialog_calls == []


# ------------------------------------------------------------ launch GUI
def test_manual_launch_is_optional_and_non_blocking(env, monkeypatch):
    """A configured ``launch`` path is handed to the detached launcher;
    a launch FAILURE is logged but never blocks the operator verdict."""
    _env_with_flash(env, params=_flash_params(
        launch="C:/Tools/FlashTool.exe"))
    env._answers = ["go"]
    calls = []

    def fake_launch(exe):
        calls.append(exe)
        return False, "launch failed: FileNotFoundError: nope"

    monkeypatch.setattr("mtkgui.engine.flash_tool.launch_tool_gui",
                        fake_launch)
    _run_ict(env)
    assert calls == ["C:/Tools/FlashTool.exe"]
    assert env.rows[("ict", 0)] == "Done"          # still judged by GO
    assert any("launch failed" in ln for ln in env._log_lines())


def test_manual_without_launch_does_not_call_the_launcher(env,
                                                         monkeypatch):
    _env_with_flash(env)                            # no launch configured
    env._answers = ["go"]
    calls = []
    monkeypatch.setattr("mtkgui.engine.flash_tool.launch_tool_gui",
                        lambda exe: calls.append(exe) or (True, "x"))
    _run_ict(env)
    assert calls == []


# ----------------------------------------------------------- auto path
def test_auto_mode_never_uses_the_operator_dialog(env):
    """mode=auto is the CLI/keyword path - it must not touch the
    operator dialog (here it runs the virtual simulated flash)."""
    _env_with_flash(env, params={"type": "flash", "slot": "fat",
                                 "mode": "auto"})
    _run_ict(env)
    assert env.dialog_calls == []
    assert env.rows[("ict", 0)] == "Done"


def test_missing_mode_defaults_to_auto(env):
    """R1 default: a flash row without an explicit mode behaves as
    auto - no operator dialog, no operator verdict."""
    _env_with_flash(env, params={"type": "flash", "slot": "fat"})
    _run_ict(env)
    assert env.dialog_calls == []
    assert env.rows[("ict", 0)] == "Done"


# --------------------------------------------------------- FCT op rows
def test_fct_manual_flash_row_status(env):
    """The FCT staging path applies the same verdict mapping."""
    env.fct_rows = [FLASH_NAME]
    env.fct_kinds = ["op"]
    env.fct_op_params = [_flash_params()]
    env.fct_enables = [True]
    env._answers = ["stop"]
    env.dialog_calls = []

    def _dialog(kind, name, timeout_s=0.0):
        env.dialog_calls.append((kind, name, timeout_s))
        return env._answers.pop(0)

    env._fct_message_dialog = _dialog
    runner = TestRunner(env)
    env.runner = runner
    runner.abort = lambda trigger="operator": None
    runner._exec_fct_row(0, interactive=True)
    assert env.rows[("fct", 0)] == "FAIL"
    assert env.dialog_calls[0][0] == "MessageGoStop"


# --------------------------------------------- R4: verdict source report
def test_measured_carries_the_operator_verdict(env):
    """R4: the report Measured column tells WHO judged the flash -
    the operator answer lands verbatim ("Operator: GO" / STOP)."""
    _env_with_flash(env)
    env._answers = ["go"]
    _run_ict(env)
    assert env.measured[("ict", 0)] == "Operator: GO"

    _env_with_flash(env)
    env._answers = ["stop"]
    _run_ict(env).abort = lambda trigger="operator": None
    assert env.measured[("ict", 0)] == "Operator: Stop"


def test_measured_simulated_go_is_labelled(env):
    """Run Demo flashes show 'Operator: GO (simulated)' - the report
    never disguises a simulated verdict as a real one."""
    _env_with_flash(env)
    _run_ict(env, interactive=False)
    assert env.measured[("ict", 0)] == "Operator: GO (simulated)"


def test_fct_flash_row_measured_instead_of_duration(env):
    """R4: the FCT flash row writes the verdict source and NO duration
    (the report renders duration-or-measured - the source must win)."""
    env.fct_rows = [FLASH_NAME]
    env.fct_kinds = ["op"]
    env.fct_op_params = [_flash_params()]
    env.fct_enables = [True]
    env._answers = ["go"]
    env.dialog_calls = []

    def _dialog(kind, name, timeout_s=0.0):
        env.dialog_calls.append((kind, name, timeout_s))
        return env._answers.pop(0)

    env._fct_message_dialog = _dialog
    runner = TestRunner(env)
    env.runner = runner
    runner._exec_fct_row(0, interactive=True)
    assert env.measured[("fct", 0)] == "Operator: GO"


def test_flash_audit_line_in_the_run_log(env):
    """R4: every flash attempt logs one [FLASH] audit line - mode,
    slot, tool, image and the verdict."""
    _env_with_flash(env)
    env._answers = ["go"]
    _run_ict(env)
    audit = [ln for ln in env._log_lines() if ln.startswith("[FLASH]")]
    assert len(audit) == 1
    assert "mode=manual" in audit[0]
    assert "slot=fat" in audit[0]
    assert "tool=J-Link" in audit[0]
    assert "verdict=Done (Operator: GO)" in audit[0]


def test_auto_flash_audit_line_mode(env):
    """The auto path audits with mode=auto and no operator source."""
    _env_with_flash(env, params={"type": "flash", "slot": "fat",
                                 "mode": "auto"})
    _run_ict(env)
    audit = [ln for ln in env._log_lines() if ln.startswith("[FLASH]")]
    assert len(audit) == 1 and "mode=auto" in audit[0]
    assert "verdict=Done" in audit[0] and "Operator" not in audit[0]


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
