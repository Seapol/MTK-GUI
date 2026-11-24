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
        assert "Stop if any R-GND short" in msg
        assert "BEFORE power on" in msg

    def test_short_policy_can_be_disabled(self):
        assert policy_abort_reason(
            "ict", "FAIL", "Impedance Shorts (80 pts)", is_short=True,
            stop_if_any_short=False) is None

    def test_short_fail_keeps_short_wording(self):
        # regression: a FAIL impedance row IS the short case
        msg = policy_abort_reason(
            "ict", "FAIL", "AGND", is_short=True,
            stop_if_any_short=True)
        assert "low impedance detected at 'AGND'" in msg
        assert "Overall Result: FAIL" in msg

    def test_short_error_names_instrument_error(self):
        # instrument Error (e.g. READ? timeout) is NOT a board short
        msg = policy_abort_reason(
            "ict", "Error", "AGND", is_short=True,
            stop_if_any_short=True)
        assert "could not be verified (Error)" in msg
        assert "low impedance" not in msg
        assert "Overall Result: FAIL" in msg

    def test_short_error_uses_failure_policy_when_short_policy_off(self):
        msg = policy_abort_reason(
            "ict", "Error", "AGND", is_short=True,
            stop_if_any_short=False, stop_if_failure=True)
        assert "Stop policy (Stop if failure)" in msg
        assert "Overall Result: FAIL" in msg

    def test_short_wins_over_generic_failure_policy(self):
        msg = policy_abort_reason(
            "ict", "FAIL", "Impedance Shorts", is_short=True,
            stop_if_failure=True, stop_if_any_short=True)
        assert "Stop if any R-GND short" in msg

    def test_fct_stop_if_failure(self):
        msg = policy_abort_reason(
            "fct", "FAIL", "WIFI: scan", stop_if_failure=True)
        assert "FCT 'WIFI: scan' reported FAIL" in msg

    def test_fct_error_aborts_when_stop_if_failure(self):
        # M115: Error is judged-bad exactly like FAIL
        msg = policy_abort_reason(
            "fct", "Error", "Deploy test assets", stop_if_failure=True)
        assert msg == ("Stop policy (Stop if failure): FCT 'Deploy test "
                       "assets' reported Error -> run aborted. Overall "
                       "Result: FAIL")

    def test_fct_on_fail_continue_survives_failure(self):
        assert policy_abort_reason(
            "fct", "FAIL", "Wi-Fi scan", stop_if_failure=False,
            on_fail="continue") is None
        assert policy_abort_reason(
            "fct", "Error", "Wi-Fi scan", stop_if_failure=False,
            on_fail="continue") is None

    def test_fct_on_fail_continue_still_aborts_when_forced(self):
        msg = policy_abort_reason(
            "fct", "FAIL", "Wi-Fi scan", stop_if_failure=True,
            on_fail="continue")
        assert msg == ("Stop policy (Stop if failure, forced): FCT 'Wi-Fi "
                       "scan' reported FAIL -> run aborted (on_fail=continue "
                       "overridden). Overall Result: FAIL")

    def test_fct_default_on_fail_aborts(self):
        # an absent or unknown on_fail means abort, never continue
        for on_fail in (None, "", "bogus"):
            msg = policy_abort_reason(
                "fct", "FAIL", "Load RF drivers", stop_if_failure=False,
                on_fail=on_fail)
            assert msg == ("Stop policy (Stop if failure): FCT 'Load RF "
                           "drivers' reported FAIL -> run aborted. Overall "
                           "Result: FAIL")

    def test_fct_fail_message_unchanged(self):
        msg = policy_abort_reason(
            "fct", "FAIL", "WIFI: scan", stop_if_failure=True)
        assert msg == ("Stop policy (Stop if failure): FCT 'WIFI: scan' "
                       "reported FAIL -> run aborted. Overall Result: FAIL")

    def test_ict_branch_ignores_on_fail(self):
        assert policy_abort_reason(
            "ict", "FAIL", "row", stop_if_failure=True,
            on_fail="continue") == (
            "Stop policy (Stop if failure): 'row' reported FAIL -> run "
            "aborted. Overall Result: FAIL")

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
