# -*- coding: utf-8 -*-
"""v2-9c: a measurement with no limit is TBD, never Error / FAIL.

A Clock or Power Voltage row whose Expected / Min / Max are empty still
runs and reports the measured value as ``TBD`` (yellow).  TBD never
trips a stop policy and never counts as PASS: the board rolls up to
``Pending`` (not shippable) when any row is TBD and nothing is FAIL.
"""
from __future__ import annotations

from mtkgui.engine.policies import policy_abort_reason, rollup
from mtkgui.engine.runner import TestRunner
from mtkgui.gui.statistics_store import (
    VERDICT_FAIL, VERDICT_PASS, VERDICT_PENDING, RunRecord, overview)

from tests.engine.conftest import make_env

# pytest must not collect the engine class as a test case
TestRunner.__test__ = False


def _blank_limits(env, kind: str) -> int:
    """Clear Expected/Min/Max on the first row whose kind is ``kind``,
    so the virtual rack reports TBD instead of judging."""
    idx = next(i for i, s in enumerate(env.ict_steps)
               if s[0] == kind)
    row = list(env.ict_steps[idx])
    row[3], row[4], row[5] = "—", "—", "—"
    env.ict_steps[idx] = tuple(row)
    return idx


def test_clock_without_limits_is_tbd(env):
    runner = TestRunner(env)
    env.runner = runner
    idx = _blank_limits(env, "Clock Hz")
    runner._exec_ict_row(idx)
    assert env.rows[("ict", idx)] == "TBD"
    # the cell still holds a measured frequency (unit lives in the Unit
    # column), not a blank
    measured = env.measured[("ict", idx)].replace(",", "")
    assert float(measured) > 0


def test_voltage_without_limits_is_tbd(env):
    runner = TestRunner(env)
    env.runner = runner
    idx = _blank_limits(env, "Power Voltage")
    runner._exec_ict_row(idx)
    assert env.rows[("ict", idx)] == "TBD"


def test_tbd_does_not_trigger_stop_if_failure(env):
    runner = TestRunner(env)
    env.runner = runner
    # v2-9c: TBD is a measurement with no limit, not a defect - it must
    # not trip the Stop-if-failure strategy that FAIL / ERROR trip.
    assert policy_abort_reason(
        "ict", "TBD", "CLK_24M", stop_if_failure=True) is None
    # and the row still runs to a result instead of aborting the stage
    idx = _blank_limits(env, "Clock Hz")
    runner._exec_ict_row(idx)
    assert env.rows[("ict", idx)] == "TBD"


def test_board_with_tbd_is_pending():
    # no FAIL / Error, but a TBD row -> the board is Pending (cannot ship)
    assert rollup({("ict", 0): "PASS", ("ict", 1): "TBD"}) == "Pending"
    # all measured values, nothing judged good or bad -> still Pending
    assert rollup({("ict", 0): "TBD"}) == "Pending"


def test_fail_beats_tbd():
    # a real FAIL wins over a TBD row
    assert rollup({("ict", 0): "TBD", ("ict", 1): "FAIL"}) == "FAIL"
    assert rollup({("ict", 0): "PASS", ("ict", 1): "Error",
                   ("ict", 2): "TBD"}) == "FAIL"


def test_pending_is_not_counted_as_pass():
    records = [
        RunRecord("t", "s1", VERDICT_PASS, 1.0, 1, 0),
        RunRecord("t", "s2", VERDICT_FAIL, 1.0, 0, 1),
        RunRecord("t", "s3", VERDICT_PENDING, 1.0, 0, 0),
        RunRecord("t", "s4", VERDICT_PENDING, 1.0, 0, 0),
    ]
    o = overview(records)
    assert o["total"] == 4
    assert o["passed"] == 1
    assert o["failed"] == 1
    assert o["pending"] == 2
    # pass rate = PASS / (PASS + FAIL); Pending is excluded from both
    assert o["yield_pct"] == 50.0


def test_limits_hint_is_gone():
    # v2-9c: the old '[WARNING] Clock limits missing' guidance is gone -
    # a missing limit no longer stops the run, it reports TBD.
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2]
           / "mtkgui" / "gui" / "yamlbuild" / "ict_sequence.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    assert "Clock limits missing" not in body


def test_production_batch_missing_limits_banner():
    # v2-9c: only a Production batch with an unfilled limit shows the
    # note; the build itself still proceeds (the note never blocks).
    from mtkgui.gui.yamlbuild.ict_sequence import (
        production_missing_limits_note)
    complete = ("test", "CLKOUT1 TP_C2 - 4 MHz", "Hz", "4000000",
                "3960000", "4040000")
    missing = ("test", "CLKOUT1 TP_C2 - 4 MHz", "Hz", "—", "—", "—")
    note = ("Production batch with missing limits - every run will be "
            "Pending and cannot ship")
    assert production_missing_limits_note("MP (Production)", [missing]) == note
    assert production_missing_limits_note("MP (Production)", [complete]) is None
    # proto / engineering batches may run without limits on purpose
    assert production_missing_limits_note("EVT (Proto-1)", [missing]) is None
    assert production_missing_limits_note("DVT (Proto-2)", [missing]) is None
    assert production_missing_limits_note("", [missing]) is None
