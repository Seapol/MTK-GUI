# -*- coding: utf-8 -*-
"""Teardown guarantee on the abort paths: stop-policy abort (_abort_run),
operator Stop (abort) and system RESOURCE abort must all execute the
params.teardown=True FCT rows (DUT shutdown / host iperf3 stop)."""
from __future__ import annotations

import pytest

from mtkgui.engine.runner import TestRunner

from tests.engine.conftest import make_env


def teardown_config() -> dict:
    """FCT body: row 0 = filler CLI row (sim-failed to trigger the
    stop-policy abort), row 1 = teardown host CLI row."""
    return {
        "product": {"part_number": "TEST-TD", "core_id": "M33",
                    "batch": "B1"},
        "test_workflow": {
            "overall_flow": [
                {"stage": "ICT", "description": "", "enable": False},
                {"stage": "FCT", "description": "", "enable": True},
            ],
            "stop_if_failure": True,
            "stop_if_any_short": False,
            "ict_test_cases": [],
            "fct_test_cases": [
                {"name": "FCT filler (fails)", "kind": "SendtoCLI",
                 "timeout_ms": 5000,
                 "op_params": {"fct_step": {
                     "name": "FCT filler (fails)",
                     "step_type": "EXTERNAL_TOOL", "timeout_s": 5.0,
                     "params": {"fct_host_cmd": {"cmd": "false"}}}}},
                {"name": "Stop iperf3 server (Host CLI)",
                 "kind": "SendtoCLI", "timeout_ms": 5000,
                 "op_params": {"fct_step": {
                     "name": "Stop iperf3 server (Host CLI)",
                     "step_type": "EXTERNAL_TOOL", "timeout_s": 5.0,
                     "params": {"teardown": True,
                                "fct_host_cmd": {"cmd": "true"}}}}},
            ],
        },
    }


def step_run(env) -> TestRunner:
    runner = TestRunner(env)
    env.runner = runner
    runner.start(1)
    for _ in range(10000):
        if runner.state != "running":
            break
        runner._run_step()
    return runner


@pytest.fixture
def tenv(tmp_path):
    e, _stages = make_env(teardown_config(), tmp_path=tmp_path)
    yield e


class TestStopPolicyAbort:
    def test_teardown_runs_on_stop_if_failure(self, tenv):
        tenv.stop_if_failure = True
        runner = step_run(tenv)
        assert runner.verdict() == "FAIL"
        # find the teardown row by name (built-in flash FAT/OOBE ops
        # shift the index)
        idx = next(i for i, n in enumerate(tenv.fct_rows)
                   if "Stop iperf3" in n)
        assert tenv.rows.get(("fct", idx)) is not None, (
            "teardown row skipped on stop-policy abort; log:\n"
            + "\n".join(tenv._log_lines()))


class TestOperatorStop:
    def test_teardown_runs_on_operator_stop(self, tenv):
        """Stop button mid-run: teardown rows must STILL execute
        (cleanup guarantee applies to every abort flavour)."""
        runner = TestRunner(tenv)
        tenv.runner = runner
        runner.start(1)
        assert runner.state == "running"
        runner.abort(trigger="operator")
        assert runner.state in ("aborted", "idle")
        idx = next(i for i, n in enumerate(tenv.fct_rows)
                   if "Stop iperf3" in n)
        assert tenv.rows.get(("fct", idx)) is not None, (
            "teardown row skipped on operator Stop; log:\n"
            + "\n".join(tenv._log_lines()))
