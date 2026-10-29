# -*- coding: utf-8 -*-
"""Real-mode honesty: WITHOUT a connected instrument gateway nothing
may pass.  Regression for the user-reported logic error (Real mode, no
instruments connected, Static Impedance rows PASSed with an EMPTY
Measured cell and no rail capture - the legacy dice-roll placeholder
simulated results in Real mode).

Real-mode contract:
  - standard ops without a gateway -> Error (equipment fault)
  - measurement rows without a gateway -> Error (Measured stays empty)
  - the DAQ AI rail row acquires through the gateway (capture_rails);
    without any backend -> Error; synthetic samples are Virtual-only
  - with a connected gateway the rows flow through it normally
  - the FIRST instrument fault aborts the run (RESOURCE stop policy)
"""
from __future__ import annotations

import pytest

from mtkgui.engine.runner import TestRunner

from tests.engine.conftest import make_env

# pytest must not collect the engine class as a test case
TestRunner.__test__ = False


def step_run(env) -> TestRunner:
    runner = TestRunner(env)
    env.runner = runner
    runner.start(1)
    for _ in range(10000):
        if runner.state != "running":
            break
        runner._run_step()
    return runner


def real_bare_env(tmp_path):
    """A Real-mode env with NO instrument backend (exactly the GUI
    Real-mode state: rack=None, gateway never wired)."""
    env, _stages = make_env(tmp_path=tmp_path)
    env.virtual_mode = False
    env.rack = None
    env.gateway = None
    return env


class TestRealModeNoBackend:
    def test_measurement_row_errors_not_pass(self, tmp_path):
        """A measurement row (Power Voltage) must ERROR with no
        gateway - it used to roll the virtual dice and PASS with an
        empty Measured cell."""
        env = real_bare_env(tmp_path)
        runner = TestRunner(env)
        env.runner = runner
        volt_idx = next(i for i, s in enumerate(env.ict_steps)
                        if s[0] == "Power Voltage")
        runner._exec_ict_row(volt_idx)
        assert env.rows.get(("ict", volt_idx)) == "Error"
        assert any("no instrument gateway connected (Real mode)"
                   in line for line in env._log_lines())

    def test_standard_op_errors_without_gateway(self, tmp_path):
        """Fixture / PSU / instrument ops must report Error - they used
        to log 'Done' with nothing connected."""
        env = real_bare_env(tmp_path)
        runner = TestRunner(env)
        env.runner = runner
        assert runner._run_op(
            "ICT", "Connect Instruments",
            {"type": "instruments", "instruments": ["DAQM"]}) == "Error"
        assert any("no instrument gateway connected (Real mode)"
                   in line for line in env._log_lines())

    def test_rail_capture_errors_without_gateway(self, tmp_path):
        """The DAQ AI row must ERROR instead of generating synthetic
        rail samples in Real mode."""
        env = real_bare_env(tmp_path)
        runner = TestRunner(env)
        env.runner = runner
        daq_idx = next(i for i, s in enumerate(env.ict_steps)
                       if s[0] == "DAQ AI")
        runner._exec_rail_capture_row(daq_idx)
        assert env.rows.get(("ict", daq_idx)) == "Error"
        assert env.rail_samples is None

    def test_full_run_aborts_on_first_instrument_fault(self, tmp_path):
        """End-to-end: the run stops at the FIRST instrument fault
        (RESOURCE stop policy) with an honest Error - the Overall
        Result can never be PASS."""
        env = real_bare_env(tmp_path)
        runner = step_run(env)
        assert runner.verdict() != "PASS"
        assert runner.state != "running"   # stopped (idle via _abort_run)
        error_rows = [(k, r) for (k, r), v in env.rows.items()
                      if v == "Error"]
        assert error_rows, "expected at least one Error row"
        assert any("no instrument gateway connected (Real mode)"
                   in line for line in env._log_lines())


class TestRealModeWithGateway:
    def test_rows_flow_through_connected_gateway(self, tmp_path):
        """With the operator-connected gateway handed to the run path
        (Tools 'Connect all' -> workflow_page.gateway), Real-mode rows
        execute through it - ops Done, measurements judged, rails
        captured via capture_rails."""
        env = real_bare_env(tmp_path)

        class _Out:
            def __init__(self, verdict="PASS", text="gw"):
                self.verdict = verdict
                self.text = text
                self.lines = [f"gw {verdict}"]

        class _FakeGateway:
            def __init__(self):
                self.ops: list = []
                self.measures: list = []
                self.captures = 0

            def execute_op(self, name, params):
                self.ops.append(name)
                return _Out("PASS")

            def measure_row(self, kind, name, unit, lo, hi, force=None):
                self.measures.append(name)
                return _Out("PASS", "12.34")

            def capture_rails(self, rails, start_s, end_s, rate_hz,
                              force=None):
                self.captures += 1
                frac, volts = env._generate_rail_samples()
                return frac, volts, None

        gw = _FakeGateway()
        env.gateway = gw
        runner = step_run(env)
        assert runner.verdict() == "PASS"
        assert gw.ops and gw.measures and gw.captures == 1


class TestRealModeGatewayInstrumentFaults:
    """Gateway CONNECTED but the instrument unreachable: the row is an
    Error AND the Event Log / row detail carry the reason."""

    def test_measure_connect_failure_shows_reason(self, tmp_path):
        env = real_bare_env(tmp_path)

        class _Out:
            verdict = "Error"
            text = ""
            lines = ["DAQ973A open failed: USB0::... not connected"]

        class _Gw:
            def measure_row(self, kind, name, unit, lo, hi, force=None):
                return _Out()

        env.gateway = _Gw()
        runner = TestRunner(env)
        env.runner = runner
        volt_idx = next(i for i, s in enumerate(env.ict_steps)
                        if s[0] == "Power Voltage")
        runner._exec_ict_row(volt_idx)
        # Result column = Error, detail carries the reason
        assert env.rows.get(("ict", volt_idx)) == "Error"
        assert "DAQ973A open failed" in env.measured[("ict", volt_idx)]
        assert any("DAQ973A open failed" in line
                   for line in env._log_lines())

    def test_op_connect_failure_shows_reason(self, tmp_path):
        env = real_bare_env(tmp_path)

        class _Out:
            verdict = "Error"
            lines = ["N5747A open failed: TCPIP0 timeout"]

        class _Gw:
            def execute_op(self, name, params):
                return _Out()

        env.gateway = _Gw()
        runner = TestRunner(env)
        env.runner = runner
        assert runner._run_op(
            "ICT", "Connect Instruments",
            {"type": "instruments", "instruments": ["PSU"]}) == "Error"
        assert "N5747A open failed" in runner._last_op_error
        assert any("N5747A open failed" in line
                   for line in env._log_lines())

    def test_rail_capture_failure_shows_reason(self, tmp_path):
        env = real_bare_env(tmp_path)

        class _Gw:
            last_error = "U2355A open failed: device not connected"

            def capture_rails(self, rails, start_s, end_s, rate_hz,
                              force=None):
                return None, None, "error"

        env.gateway = _Gw()
        runner = TestRunner(env)
        env.runner = runner
        daq_idx = next(i for i, s in enumerate(env.ict_steps)
                       if s[0] == "DAQ AI")
        runner._exec_rail_capture_row(daq_idx)
        assert env.rows.get(("ict", daq_idx)) == "Error"
        assert "U2355A open failed" in env.measured[("ict", daq_idx)]
        assert any("U2355A open failed" in line
                   for line in env._log_lines())
