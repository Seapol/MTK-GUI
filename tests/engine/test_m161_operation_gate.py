# -*- coding: utf-8 -*-
"""M161: FCT Operation power_on / power_off with a dialog ``style`` is an
operator gate, never an instrument-gateway op.

A bare-metal FCT bench (FRDM-IMX93) has no DAQ / PSU gateway; its
Power On / Off rows ask the operator (Go/Stop, OK) instead.
"""
from __future__ import annotations

import pytest

from mtkgui.engine.fct_exec import (
    VERDICT_PASS,
    FctContext,
    execute_fct_step,
)
from mtkgui.gui.yamlbuild.fct_build import FctStep


def _step(**kw):
    base = {
        "name": "Power On DUT",
        "category": "Operation",
        "type": "power_on",
        "timeout_s": 0.0,
        "params": {"style": "gostop"},
    }
    base.update(kw)
    return FctStep.from_dict(base)


def _ctx(confirm_answer=True):
    calls = {"op": []}

    def run_op(op_name, op_params):
        calls["op"].append((op_name, op_params))
        return "Done"

    ctx = FctContext(human_confirm=lambda step: confirm_answer,
                     run_op=run_op)
    return ctx, calls


def test_power_on_style_is_human_gate():
    ctx, calls = _ctx(confirm_answer=True)
    outcome = execute_fct_step(_step(), ctx)
    assert outcome.verdict == VERDICT_PASS
    # must NOT drive the instrument gateway
    assert calls["op"] == []


def test_power_off_style_is_human_gate():
    step = _step(name="Power Off DUT", type="power_off",
                 params={"style": "ok"})
    ctx, calls = _ctx(confirm_answer=True)
    outcome = execute_fct_step(step, ctx)
    assert outcome.verdict == VERDICT_PASS
    assert calls["op"] == []


def test_power_on_with_op_name_still_drives_instrument():
    # regression guard: a step with a concrete op name keeps the legacy
    # instrument-gateway path (ICT-style Power On DUT)
    step = _step(params={"op": "Power On DUT"})
    ctx, calls = _ctx(confirm_answer=True)
    outcome = execute_fct_step(step, ctx)
    assert outcome.verdict == VERDICT_PASS
    assert len(calls["op"]) == 1
    assert calls["op"][0][0] == "Power On DUT"


class _FakeMc:
    def __init__(self):
        self.channels = {}

    def channel_connected(self, key):
        return key in self.channels


class _Env:
    def __init__(self, answer="go"):
        self.multi_console = _FakeMc()
        self.fct_rows = ["row"]
        self.fct_kinds = ["Operation"]
        self.fct_op_params = [None]
        self.fct_enables = [True]
        self.fct_timeouts = [1000]
        self.logs = []
        self.answer = answer
        self.dialogs = []
        self.gateway = None      # a bare-metal bench has NO gateway

    def _log(self, line):
        self.logs.append(line)

    def _render_step(self, *args, **kwargs):
        pass

    def _fct_message_dialog(self, kind, name, timeout_s=0.0):
        self.dialogs.append(kind)
        return self.answer


def _marker(category, sub_type, name, params=None):
    return {"name": name, "category": category, "type": sub_type,
            "channel": "", "timeout_s": 0.0, "params": dict(params or {})}


def _run_b3(env, marker, answer):
    from mtkgui.engine.runner import TestRunner
    env.answer = answer
    runner = TestRunner(env)
    runner.state = "running"
    env.runner = runner
    stops = []
    runner.abort = lambda trigger="operator": stops.append(trigger)
    runner._exec_fct_b3(0, str(marker.get("name", "")), marker, 0.0, True)
    return runner, stops


def test_power_on_style_dialog_not_gateway():
    # end-to-end at the runner level: Operation.power_on with style=gostop
    # pops a GoStop dialog and never touches the (absent) gateway.
    env = _Env()
    runner, stops = _run_b3(
        env, _marker("Operation", "power_on", "Power On DUT",
                     {"style": "gostop"}), "go")
    assert env.dialogs == ["MessageGoStop"]
    assert runner._results[("fct", 0)] == "PASS"
    assert stops == []


def test_power_off_style_dialog_not_gateway():
    env = _Env()
    runner, stops = _run_b3(
        env, _marker("Operation", "power_off", "Power Off DUT",
                     {"style": "ok"}), "ok")
    assert env.dialogs == ["MessageOK"]
    assert runner._results[("fct", 0)] == "PASS"
    assert stops == []
