# -*- coding: utf-8 -*-
"""Stop strategies and result rollup (mtkgui.engine.policies)."""
from __future__ import annotations

from mtkgui.engine.policies import policy_abort_reason, rollup


class TestPolicyAbortReason:
    def test_stop_if_failure_ict(self):
        msg = policy_abort_reason(
            "ict", "FAIL", "Power Voltage (80 pts)",
            stop_if_failure=True)
        assert "Stop if failure" in msg
        assert "Power Voltage (80 pts)" in msg
        assert "Overall Result: FAIL" in msg

    def test_no_abort_when_policy_off(self):
        assert policy_abort_reason(
            "ict", "FAIL", "row", stop_if_failure=False) is None

    def test_no_abort_on_pass(self):
        assert policy_abort_reason(
            "ict", "PASS", "row", stop_if_failure=True) is None

    def test_short_aborts_before_power_on(self):
        msg = policy_abort_reason(
            "ict", "FAIL", "Impedance Shorts (80 pts)", is_short=True,
            stop_if_any_short=True)
        assert "Stop if any short" in msg
        assert "BEFORE power on" in msg

    def test_short_policy_can_be_disabled(self):
        assert policy_abort_reason(
            "ict", "FAIL", "Impedance Shorts (80 pts)", is_short=True,
            stop_if_any_short=False) is None

    def test_short_wins_over_generic_failure_policy(self):
        msg = policy_abort_reason(
            "ict", "FAIL", "Impedance Shorts", is_short=True,
            stop_if_failure=True, stop_if_any_short=True)
        assert "Stop if any short" in msg

    def test_fct_stop_if_failure(self):
        msg = policy_abort_reason(
            "fct", "FAIL", "WIFI: scan", stop_if_failure=True)
        assert "FCT 'WIFI: scan' reported FAIL" in msg

    def test_fct_error_does_not_stop(self):
        # legacy behavior: FCT stop policy keys on FAIL only
        assert policy_abort_reason(
            "fct", "Error", "WIFI: scan", stop_if_failure=True) is None

    def test_stage_rows_never_abort(self):
        assert policy_abort_reason(
            "stage", "FAIL", "ICT", stop_if_failure=True) is None


class TestRollup:
    def test_nothing_judged(self):
        assert rollup({}) is None

    def test_all_pass(self):
        results = {("ict", 0): "Done", ("ict", 1): "PASS",
                   ("fct", 0): "PASS"}
        assert rollup(results) == "PASS"

    def test_fail_wins(self):
        results = {("ict", 0): "PASS", ("fct", 0): "FAIL"}
        assert rollup(results) == "FAIL"

    def test_error_counts_as_fail(self):
        assert rollup({("ict", 0): "Error"}) == "FAIL"

    def test_ignored_excluded(self):
        # disabled steps report "Ignore" and never judge the run
        assert rollup({("ict", 0): "Ignore"}) is None

    def test_fct_done_does_not_judge(self):
        # legacy semantics: an FCT op "Done" alone does not judge PASS
        assert rollup({("fct", 0): "Done"}) is None

    def test_ict_done_judges(self):
        assert rollup({("ict", 0): "Done"}) == "PASS"
