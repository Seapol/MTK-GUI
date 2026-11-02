# -*- coding: utf-8 -*-
"""M49a §4 - equipment state model: hardware is the PRECONDITION of a
step, not a global gate.  An absent instrument attributes an Error to
that step (with the instrument name in the Event Log); the sequence
keeps running; once the instrument is available the re-run passes."""
from __future__ import annotations

import pytest

from mtkgui.engine.runner import TestRunner

from tests.engine.conftest import make_env

TestRunner.__test__ = False


def _real_bare_env(tmp_path):
    env, _stages = make_env(tmp_path=tmp_path)
    env.virtual_mode = False
    env.rack = None
    env.gateway = None
    return env


def _measurement_index(env):
    return next(i for i, s in enumerate(env.ict_steps)
                if s[0] == "Power Voltage")


def test_absent_instrument_is_a_step_level_error(tmp_path):
    env = _real_bare_env(tmp_path)
    runner = TestRunner(env)
    env.runner = runner
    idx = _measurement_index(env)
    runner._exec_ict_row(idx)
    assert env.rows.get(("ict", idx)) == "Error"
    logs = env._log_lines()
    assert any("no instrument gateway connected (Real mode)" in line
               for line in logs)
    # the cause NAMES the instrument (M49a: "U2355A not connected" ...)
    assert any("not connected" in line and "DAQM" in line for line in logs)


def test_hardware_absence_does_not_block_other_steps(tmp_path):
    """No global pre-check: a hardware-free step after the failed
    measurement row still runs to PASS."""
    env = _real_bare_env(tmp_path)
    runner = TestRunner(env)
    env.runner = runner
    idx = _measurement_index(env)
    runner._exec_ict_row(idx)
    assert env.rows.get(("ict", idx)) == "Error"

    env.ict_steps.append(("delay", "Delay", "—", "—", "—", "—"))
    delay_idx = len(env.ict_steps) - 1
    runner._exec_ict_row(delay_idx)
    assert env.rows.get(("ict", delay_idx)) == "PASS"


def test_rerun_passes_once_the_instrument_is_available(tmp_path):
    env = _real_bare_env(tmp_path)

    class _Out:
        verdict = "PASS"
        text = "12.34"
        lines = ["gw PASS"]

    class _FakeGateway:
        def measure_row(self, kind, name, unit, lo, hi, force=None):
            return _Out()

        def execute_op(self, name, params):
            return _Out()

        def capture_rails(self, rails, start_s, end_s, rate_hz,
                          force=None):
            return 0.0, [], None

    runner = TestRunner(env)
    env.runner = runner
    idx = _measurement_index(env)
    runner._exec_ict_row(idx)
    assert env.rows.get(("ict", idx)) == "Error"

    # self-test OK + connected: the same row now executes through the
    # available instrument
    env.gateway = _FakeGateway()
    runner._exec_ict_row(idx)
    assert env.rows.get(("ict", idx)) == "PASS"
