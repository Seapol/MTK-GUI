# -*- coding: utf-8 -*-
"""Overall Flow stop strategies and result rollup (mtkgui.engine).

Stop strategies (interface_spec.md §3):
  * stop_if_failure   (default false per spec): abort the run as soon
    as any step reports FAIL / ERROR.
  * stop_if_any_short (default true): abort before power-up when an
    impedance-short row reports out-of-limit — a short under power
    risks damaging the board.

The engine decides PASS/FAIL from the YAML limits; the drivers never
do (interface_spec.md §2).
"""
from __future__ import annotations

# display texts that count as judged per table kind (legacy semantics:
# ICT op steps report "Done" and count; FCT op "Done" does not judge)
_JUDGED_OK = {"ict": ("PASS", "Done"), "fct": ("PASS",)}
_JUDGED_BAD = ("FAIL", "Error")


def policy_abort_reason(kind: str, raw_status: str | None, name: str,
                        *, is_short: bool = False,
                        stop_if_failure: bool = False,
                        stop_if_any_short: bool = True,
                        on_fail: str | None = None) -> str | None:
    """Check a just-finished step against the Overall Flow stop
    strategies. Returns an abort log message, or None to continue."""
    if kind == "ict":
        if raw_status not in _JUDGED_BAD:
            return None
        if is_short and stop_if_any_short:
            if raw_status == "FAIL":
                return (f"Stop policy (Stop if any R-GND short): low impedance "
                        f"detected at '{name}' -> run aborted BEFORE power "
                        f"on. Overall Result: FAIL")
            if raw_status == "Error":
                return (f"Stop policy (Stop if any R-GND short): R-GND "
                        f"'{name}' could not be verified (Error) -> run "
                        f"aborted BEFORE power on. Overall Result: FAIL")
            # a future judged-bad status: still unsafe to power on
            return (f"Stop policy (Stop if any R-GND short): R-GND '{name}' "
                    f"not PASS ({raw_status}) -> run aborted BEFORE power "
                    f"on. Overall Result: FAIL")
        if stop_if_failure:
            return (f"Stop policy (Stop if failure): '{name}' reported "
                    f"{raw_status} -> run aborted. Overall Result: FAIL")
    elif kind == "fct":
        if raw_status not in _JUDGED_BAD:
            return None
        # M115: the step's own policy; absent / unknown means abort
        policy = on_fail or "abort"
        if stop_if_failure and policy == "continue":
            return (f"Stop policy (Stop if failure, forced): FCT "
                    f"'{name}' reported {raw_status} -> run aborted "
                    f"(on_fail=continue overridden). Overall Result: FAIL")
        if policy == "continue" and not stop_if_failure:
            return None
        return (f"Stop policy (Stop if failure): FCT '{name}' reported "
                f"{raw_status} -> run aborted. Overall Result: FAIL")
    return None


def normalize_retry_count(value) -> int:
    """Validate / clamp a retry setting to a non-negative integer.

    Single source of truth for the basic fault-policy retry parameter
    (interface_spec.md §3).  Any invalid input (None, non-numeric
    strings, negative values) is clamped to 0 so no illegal value can
    reach the retry scheduling logic:
      * int / numeric string / float -> max(0, int(value))
      * bool (int subclass)          -> 0 / 1
      * None / "abc" / other garbage -> 0
    """
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def rollup(results: dict) -> str | None:
    """Overall result of the executed steps: "FAIL" if any non-ignored
    step FAIL/ERROR, "Pending" if any step is TBD (measured but no
    limit), "PASS" if at least one step judged good, None when nothing
    judged yet.  A Pending board is not shippable - it is never PASS.

    results: {(table_kind, row): display status text} tracked by the
    TestRunner for every rendered step result."""
    judged_any = False
    failed = False
    tbd = False
    for (kind, _row), text in results.items():
        if text in _JUDGED_OK.get(kind, ()):
            judged_any = True
        elif text in _JUDGED_BAD:
            judged_any = True
            failed = True
        elif text == "TBD":
            judged_any = True
            tbd = True
    if not judged_any:
        return None
    if failed:
        return "FAIL"
    if tbd:
        return "Pending"
    return "PASS"
