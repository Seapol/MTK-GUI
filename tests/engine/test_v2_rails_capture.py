# -*- coding: utf-8 -*-
"""v2-9b: the power-rails capture is a DAQ AI Start / End op pair.

Start arms the capture and returns immediately (Done, no measurement).
End closes the window and only RECORDS the waveform (CSV + AI review +
plot) - it is never a PASS / FAIL, so a capture can never decide the
board verdict.  The retired single ``kind: DAQ AI`` row is refused at
load with a message that names the pair to use instead.
"""
from __future__ import annotations

from mtkgui.engine.runner import TestRunner
from mtkgui.engine.yaml_validation import (
    blocking_issues, validate_project_yaml)

from tests.engine.conftest import make_env

# pytest must not collect the engine class as a test case
TestRunner.__test__ = False


def _idx(env, name: str) -> int:
    return next(i for i, s in enumerate(env.ict_steps) if s[1] == name)


def test_rails_start_arms_without_measuring(env):
    runner = TestRunner(env)
    env.runner = runner
    idx = _idx(env, "DAQ AI Start")
    runner._exec_ict_row(idx)
    assert env.rows[("ict", idx)] == "Done"
    assert env.rail_csv_path is None
    assert env.rail_samples is None


def test_rails_end_records_and_plots(env):
    runner = TestRunner(env)
    env.runner = runner
    start_idx = _idx(env, "DAQ AI Start")
    end_idx = _idx(env, "DAQ AI End")
    runner._exec_ict_row(start_idx)
    runner._exec_ict_row(end_idx)
    assert env.rows[("ict", end_idx)] == "Recorded"
    assert env.rail_csv_path is not None and env.rail_csv_path.exists()
    review = env.rail_csv_path.with_name(
        env.rail_csv_path.stem + "_ai_review.txt")
    assert review.exists()
    assert env.rail_samples is not None


def test_rails_end_without_start_is_error(env):
    runner = TestRunner(env)
    env.runner = runner
    idx = _idx(env, "DAQ AI End")
    runner._exec_ict_row(idx)
    assert env.rows[("ict", idx)] == "Error"
    assert env.measured[("ict", idx)] == (
        "DAQ AI capture is not armed - add the DAQ AI Start step")


def test_second_rails_start_is_refused(env):
    runner = TestRunner(env)
    env.runner = runner
    idx = _idx(env, "DAQ AI Start")
    runner._exec_ict_row(idx)
    runner._exec_ict_row(idx)
    assert env.rows[("ict", idx)] == "Error"
    assert env.measured[("ict", idx)] == "Rails capture already armed"


def test_recorded_never_decides_the_board(env, tmp_path):
    end_idx = _idx(env, "DAQ AI End")

    # (a) a healthy capture + passing measurements -> board PASS
    runner = TestRunner(env)
    env.runner = runner
    runner.run_demo()
    assert env.rows[("ict", end_idx)] == "Recorded"
    assert runner.verdict() == "PASS"

    # (b) a corrupt waveform stays Recorded and cannot turn the board red
    e2, _ = make_env(tmp_path=tmp_path / "b")
    r2 = TestRunner(e2)
    e2.runner = r2
    e2.ict_sim_fail.add(_idx(e2, "DAQ AI End"))
    r2.run_demo()
    assert e2.rows[("ict", _idx(e2, "DAQ AI End"))] == "Recorded"
    assert r2.verdict() == "PASS"


def test_legacy_daq_ai_row_is_refused():
    doc = {"test_workflow": {"ict_test_cases": [
        {"name": "DAQ AI - Power rails", "kind": "DAQ AI"}]}}
    issues = blocking_issues(validate_project_yaml(doc))
    messages = [i.message for i in issues]
    assert any("the 'DAQ AI' capture row was retired" in m
               for m in messages)
    assert any("use 'DAQ AI Start' and 'DAQ AI End'" in m
               for m in messages)
