# -*- coding: utf-8 -*-
"""m118 §2: the visible Timeout column is the ONE budget source.

The Yaml Build Timeout column writes ``timeout_ms`` on the case row
while the published step marker carries ``fct_step.timeout_s`` - and
the marker wins at run time.  ``unify_row_budgets`` rewrites a missing
or >10 % stale marker from the row before the sequence is published.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mtkgui.engine.fct_test_config import unify_row_budgets


def _case(name: str = "A", timeout_ms: int = 8000,
          marker_s=5.0) -> dict:
    marker = {"step_type": "message_check"}
    if marker_s is not None:
        marker["timeout_s"] = marker_s
    return {"name": name, "timeout_ms": timeout_ms,
            "op_params": {"fct_step": marker}}


def _collector(logs: list):
    def log(level: str, message: str) -> None:
        logs.append((level, message))
    return log


def test_row_timeout_ms_wins_over_marker():
    """An edited Timeout column (8 s) rewrites a stale 5 s marker."""
    logs: list = []
    case = _case(timeout_ms=8000, marker_s=5)
    cases = unify_row_budgets([case], _collector(logs))
    assert cases[0]["op_params"]["fct_step"]["timeout_s"] == 8.0
    assert logs == [("INFO",
                     "budget unified: A 8s (row timeout_ms wins)")]


def test_matching_budgets_are_left_untouched():
    """Agreement (and a <=10 % difference) never rewrites or logs."""
    logs: list = []
    exact = _case(name="A", timeout_ms=5000, marker_s=5.0)
    close = _case(name="B", timeout_ms=5000, marker_s=4.6)
    unify_row_budgets([exact, close], _collector(logs))
    assert exact["op_params"]["fct_step"]["timeout_s"] == 5.0
    assert close["op_params"]["fct_step"]["timeout_s"] == 4.6
    assert logs == []


def test_zero_row_budget_never_overwrites_a_positive_marker():
    """timeout_ms = 0 carries no budget - the positive marker stays."""
    logs: list = []
    case = _case(timeout_ms=0, marker_s=12)
    unify_row_budgets([case], _collector(logs))
    assert case["op_params"]["fct_step"]["timeout_s"] == 12
    assert logs == []
