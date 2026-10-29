# -*- coding: utf-8 -*-
"""M38 execution semantics (owner-confirmed 2026-10-30).

U2355A DIO: Write -> Done, Read -> the value is PRESENTED (no
pass/fail judgement).
DAQM907A fixture: Write -> Done; Read compares the level against the
expectation stored in the step's cmd / params (op_params["expect"] /
["unexpected"]): match -> Done, mismatch -> Fail, unexpected present
-> Fail.  Virtual and Real+Manual fixtures are always Done.
"""
from __future__ import annotations

import pytest

from mtkgui.engine.instruments import RealGateway
from mtkgui.engine.runner import TestRunner
from mtkgui.engine.steps import fixture_level, op_summary, op_status_lines

from tests.engine.conftest import make_config, make_env

TestRunner.__test__ = False

EQUIPMENT = {
    "daq973a": {"fields": {"Address": "GPIB0::9::INSTR"}},
    "u2355a": {"fields": {"Address": "USB0::U2355A::INSTR"}},
    "psu": {"fields": {"Address": "TCPIP0::192.168.1.20::inst0"}},
    "fixture": {"fields": {"Channel": "DIO16"}},
}


@pytest.fixture
def gw(scripted_drivers):
    return RealGateway(EQUIPMENT)


class TestFixtureLevel:
    def test_normalisation(self):
        assert fixture_level("H") == "High"
        assert fixture_level("high") == "High"
        assert fixture_level("1") == "High"
        assert fixture_level("L") == "Low"
        assert fixture_level("0") == "Low"
        assert fixture_level("") == ""
        assert fixture_level(None) == ""


class TestExpectationSummary:
    def test_summary_renders_expectation(self):
        params = {"type": "fixture", "signal": "inpos", "level": "H",
                  "expect": "High", "unexpected": "Low"}
        assert op_summary(params) == "inpos=H Expect High Unexpected Low"

    def test_summary_unchanged_without_expectation(self):
        assert op_summary({"type": "fixture", "signal": "press",
                           "level": "H"}) == "press=H"

    def test_status_lines_read_wording(self):
        lines = op_status_lines("Fixture Lock", {
            "type": "fixture", "signal": "inpos", "level": "H",
            "expect": "High"})
        assert lines == ["fixture read inpos, expect High"]


class TestFixtureWrite:
    def test_write_is_done(self, gw, scripted_drivers):
        out = gw.execute_op("Fixture Clamp Down", {
            "type": "fixture", "signal": "press", "level": "H"})
        assert out.verdict == "Done"
        assert ("dio", "DIO16", 1) in scripted_drivers._record.calls

    def test_manual_never_touches_hardware(self, scripted_drivers):
        # no driver import needed: Manual returns Done immediately
        g = RealGateway(EQUIPMENT, fixture_type="Manual")
        out = g.execute_op("Fixture Clamp Down", {
            "type": "fixture", "signal": "press", "level": "H",
            "expect": "High"})
        assert out.verdict == "Done"
        assert "Manual fixture" in out.lines[0]
        assert not [call for call in scripted_drivers._record.calls
                    if call[0] in ("dio", "read_dio")]


class TestFixtureReadExpectation:
    def test_match_is_done(self, gw, scripted_drivers):
        scripted_drivers._record.read_dio_value = 1
        out = gw.execute_op("Fixture Lock", {
            "type": "fixture", "signal": "inpos", "level": "H",
            "expect": "High"})
        assert out.verdict == "Done"
        assert out.text == "Expect High"
        assert ("read_dio", "DIO16") in scripted_drivers._record.calls

    def test_mismatch_fails(self, gw, scripted_drivers):
        scripted_drivers._record.read_dio_value = 0
        out = gw.execute_op("Fixture Lock", {
            "type": "fixture", "signal": "inpos", "level": "H",
            "expect": "High"})
        assert out.verdict == "Fail"
        assert out.text == "Expect High / read Low"
        assert any("but read Low -> FAIL" in line for line in out.lines)

    def test_unexpected_present_fails(self, gw, scripted_drivers):
        scripted_drivers._record.read_dio_value = 1
        out = gw.execute_op("Fixture E-Stop Healthy", {
            "type": "fixture", "signal": "estop", "level": "L",
            "unexpected": "High"})
        assert out.verdict == "Fail"
        assert out.text == "Unexpected High / read High"

    def test_unexpected_absent_is_done(self, gw, scripted_drivers):
        scripted_drivers._record.read_dio_value = 0
        out = gw.execute_op("Fixture E-Stop Healthy", {
            "type": "fixture", "signal": "estop", "level": "L",
            "unexpected": "High"})
        assert out.verdict == "Done"


class TestU2355AReadPresentsValue:
    def test_real_read_value_line(self, gw, scripted_drivers):
        rows = [{"net": "SOC_RST0", "dio": "DIO01"}]
        out = gw.execute_op("U2355A DIO Read", {
            "type": "dio_read", "control_io": rows})
        assert out.verdict == "Done"          # no judgement
        assert out.text.startswith("DIO Read = 0x18")
        assert "DIO01=L" in out.text
        assert any(line.startswith("Control IO SOC_RST0: DIO01 = ")
                   for line in out.lines)


class TestRunnerPropagation:
    def _env(self, tmp_path, mode="real"):
        env, _stages = make_env(make_config(), mode=mode, tmp_path=tmp_path)
        return env

    def test_fixture_read_fail_maps_to_row_fail(self, tmp_path,
                                                scripted_drivers):
        gw = RealGateway(EQUIPMENT, fixture_type="ATE")
        scripted_drivers._record.read_dio_value = 0
        env = self._env(tmp_path)
        env.gateway = gw
        runner = TestRunner(env)
        env.runner = runner
        verdict = runner._run_op("ICT", "Fixture Lock", {
            "type": "fixture", "signal": "inpos", "level": "H",
            "expect": "High"}, interactive=False)
        assert verdict == "Fail"
        assert runner._last_op_error == "Expect High / read Low"
        assert any("but read Low -> FAIL" in line
                   for line in env._log_lines())

    def test_fixture_manual_done_in_real_mode(self, tmp_path,
                                              scripted_drivers):
        gw = RealGateway(EQUIPMENT)
        env = self._env(tmp_path)
        env.gateway = gw
        env.fixture_type = "Manual"
        runner = TestRunner(env)
        env.runner = runner
        verdict = runner._run_op("ICT", "Fixture Lock", {
            "type": "fixture", "signal": "inpos", "level": "H",
            "expect": "High"}, interactive=False)
        assert verdict == "Done"
        assert gw.fixture_type == "Manual"
        assert not [call for call in scripted_drivers._record.calls
                    if call[0] in ("dio", "read_dio")]

    def test_virtual_fixture_with_expectation_is_done(self, tmp_path):
        env = self._env(tmp_path, mode="virtual")
        runner = TestRunner(env)
        env.runner = runner
        verdict = runner._run_op("FCT", "Fixture Clamp Down", {
            "type": "fixture", "signal": "press", "level": "H",
            "expect": "High"}, interactive=False)
        assert verdict == "Done"

    def test_virtual_dio_read_is_done_with_value_line(self, tmp_path):
        env = self._env(tmp_path, mode="virtual")
        env.control_io_provider = lambda: [
            {"net": "SOC_RST0", "dio": "DIO01", "isolated": True,
             "active_drivers": [], "members": []}]
        runner = TestRunner(env)
        env.runner = runner
        verdict = runner._run_op("ICT", "U2355A DIO Read",
                                 {"type": "dio_read"}, interactive=False)
        assert verdict == "Done"
        assert any("DIO Read = " in line for line in env._log_lines())
