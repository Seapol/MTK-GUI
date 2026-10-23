# -*- coding: utf-8 -*-
"""M7 W4/W5: U2355A DIO Read / DIO Write standard operations.

Read is reference-only (always Done, no judgement); Write drives the
bank and is guarded by the isolation preflight (W6) - verified here on
the headless environment.
"""
from __future__ import annotations

import pytest

from mtkgui.engine.runner import TestRunner
from mtkgui.engine.steps import (OP_STEPS, dio_pattern_value,
                                 expand_dio_channels, op_step)
from mtkgui.engine.results import StepStatus

from tests.engine.conftest import make_config, make_env

TestRunner.__test__ = False

ROWS = [
    {"net": "SOC_RST0", "dio": "DIO01", "isolated": False,
     "active_drivers": ["U1"], "members": ["U1.3", "TP3.1"]},
    {"net": "BOOT_MODE0", "dio": "DIO02", "isolated": True,
     "active_drivers": [], "members": ["R10.1", "SW1.2"]},
    {"net": "WIFI_EN0", "dio": "DIO03", "isolated": None,
     "active_drivers": [], "members": ["Q9.1"]},
]


def op_params(name):
    return dict(OP_STEPS[name])


def test_op_catalog_lists_both_dio_ops():
    assert OP_STEPS["U2355A DIO Read"]["type"] == "dio_read"
    write = OP_STEPS["U2355A DIO Write"]
    assert write["type"] == "dio_out"
    assert write["channels"] and write["pattern"]
    assert op_step("U2355A DIO Read")[6]["type"] == "dio_read"
    assert op_step("U2355A DIO Write")[6]["type"] == "dio_out"


def test_dio_helpers():
    assert expand_dio_channels("DIO01-DIO08") == \
        [f"DIO{i:02d}" for i in range(1, 9)]
    assert expand_dio_channels("DIO01,DIO03") == ["DIO01", "DIO03"]
    assert dio_pattern_value("0x3C") == 0x3C
    assert dio_pattern_value("DIO01=1,DIO03=0") == 0b1
    assert dio_pattern_value("1,0,1", "DIO01-DIO03") == 0b101


def test_virtual_rack_dio_read_reports_allocated_nets(env):
    env.rack.control_io = ROWS
    m = env.rack.execute_op("U2355A DIO Read", {"type": "dio_read"})
    assert m.verdict == "Done"
    assert m.text == "—"
    for row in ROWS:
        prefix = f"Control IO {row['net']}: {row['dio']} = "
        assert any(line.startswith(prefix) for line in m.lines)


def test_virtual_rack_dio_write_logs_channels_pattern(env):
    m = env.rack.execute_op("U2355A DIO Write",
                            {"type": "dio_out", "channels": "DIO01-DIO08",
                             "pattern": "0x3C"})
    assert m.verdict == "Done"
    assert any("DIO01-DIO08 = 0x3C -> written" in line for line in m.lines)


def test_runner_dio_read_ict_and_fct(tmp_path):
    """A7: the Read op inserted in ICT and FCT both return Done and log
    every allocated control net as ``Control IO <NET>: DIO<n> = H/L``."""
    config = make_config()
    read = {"name": "U2355A DIO Read", "kind": "op",
            "op_params": {"type": "dio_read"}}
    config["test_workflow"]["ict_test_cases"].insert(1, read)
    config["test_workflow"]["fct_test_cases"].insert(0, dict(read))
    env, stages = make_env(config, tmp_path=tmp_path)
    env.control_io_provider = lambda: list(ROWS)
    runner = TestRunner(env)
    env.runner = runner
    runner.run_demo()
    lines = env._log_lines()
    for row in ROWS:
        assert sum(1 for line in lines
                   if f"Control IO {row['net']}: {row['dio']} = " in line) \
            >= 2          # once from ICT, once from FCT
    assert env.rows.get(("ict", 1)) == "Pass" or \
        env.rows.get(("ict", 1)) == "Done"


def test_runner_dio_write_mid_ict_done(tmp_path):
    """A7: a Write op mid-ICT returns Done (virtual) and logs the
    channels / pattern."""
    config = make_config()
    config["test_workflow"]["ict_test_cases"].insert(2, {
        "name": "U2355A DIO Write", "kind": "op",
        "op_params": {"type": "dio_out", "channels": "DIO02",
                      "pattern": "0x01"}})
    env, stages = make_env(config, tmp_path=tmp_path)
    env.control_io_provider = lambda: [ROWS[1]]   # BOOT_MODE0, isolated
    runner = TestRunner(env)
    env.runner = runner
    runner.run_demo()
    lines = env._log_lines()
    assert any("DIO write DIO02 = 0x01 -> written" in line
               for line in lines)
    assert env.rows.get(("ict", 2)) == "Done"


def _row(net="SOC_RST0", dio="DIO01", isolated=False):
    return {"net": net, "dio": dio, "isolated": isolated,
            "active_drivers": ["U1"] if isolated is False else [],
            "members": ["U1.3", "TP3.1"] if isolated is False
            else ["R10.1", "SW1.2"]}


class TestIsolationPreflight:
    def test_headless_refuses_non_isolated(self, env):
        env.control_io_provider = lambda: [_row(isolated=False)]
        runner = TestRunner(env)
        env.runner = runner
        verdict = runner._run_op(
            "ICT", "U2355A DIO Write",
            {"type": "dio_out", "channels": "DIO01", "pattern": "0x01"},
            interactive=False)
        assert verdict == "Error"
        lines = env._log_lines()
        assert any("[WARN] Control IO SOC_RST0 connects active IO" in line
                   for line in lines)
        assert any("DIO write refused" in line for line in lines)
        # the bank was NOT driven
        assert not any("-> written" in line for line in lines)

    def test_headless_refuses_unknown(self, env):
        env.control_io_provider = lambda: [_row(isolated=None)]
        runner = TestRunner(env)
        env.runner = runner
        verdict = runner._run_op(
            "ICT", "U2355A DIO Write",
            {"type": "dio_out", "channels": "DIO01", "pattern": "0x01"},
            interactive=False)
        assert verdict == "Error"
        assert any("isolation cannot be confirmed" in line
                   for line in env._log_lines())

    def test_force_flag_allows(self, env):
        env.control_io_provider = lambda: [_row(isolated=False)]
        runner = TestRunner(env)
        env.runner = runner
        params = {"type": "dio_out", "channels": "DIO01",
                  "pattern": "0x01", "force": True}
        verdict = runner._run_op("ICT", "U2355A DIO Write", params,
                                 interactive=False)
        assert verdict == "Done"
        assert any("operator forced (not isolated)" in line
                   for line in env._log_lines())

    def test_gui_dialog_force_sets_flag(self, env):
        env.control_io_provider = lambda: [_row(isolated=False)]
        seen = []
        env._dio_write_preflight_dialog = lambda blocked: (
            seen.append(list(blocked)) or "force")
        runner = TestRunner(env)
        env.runner = runner
        params = {"type": "dio_out", "channels": "DIO01",
                  "pattern": "0x01"}
        verdict = runner._run_op("ICT", "U2355A DIO Write", params,
                                 interactive=True)
        assert verdict == "Done"
        assert seen and seen[0][0]["net"] == "SOC_RST0"
        assert params["force"] is True

    def test_gui_dialog_cancel_refuses(self, env):
        env.control_io_provider = lambda: [_row(isolated=False)]
        env._dio_write_preflight_dialog = lambda blocked: "cancel"
        runner = TestRunner(env)
        env.runner = runner
        verdict = runner._run_op(
            "ICT", "U2355A DIO Write",
            {"type": "dio_out", "channels": "DIO01", "pattern": "0x01"},
            interactive=True)
        assert verdict == "Error"
        assert any("operator cancelled" in line
                   for line in env._log_lines())

    def test_benign_reminder_lists_all_members(self, env):
        env.control_io_provider = lambda: [_row(isolated=True)]
        seen = []
        env._dio_passive_reminder = lambda net, members: seen.append(
            (net, members))
        runner = TestRunner(env)
        env.runner = runner
        verdict = runner._run_op(
            "ICT", "U2355A DIO Write",
            {"type": "dio_out", "channels": "DIO01", "pattern": "0x01"},
            interactive=True)
        assert verdict == "Done"          # no cancel gate
        assert seen == [("SOC_RST0", "R10.1 SW1.2")]
        line = next(line for line in env._log_lines()
                    if "[INFO] Control IO SOC_RST0" in line)
        assert "All connections: R10.1 SW1.2" in line
