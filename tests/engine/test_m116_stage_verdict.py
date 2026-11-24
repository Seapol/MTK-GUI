# -*- coding: utf-8 -*-
"""M116-C: the Overall Flow stage row rolls up its child verdicts."""
from __future__ import annotations

from mtkgui.engine.runner import stage_verdict


def test_stage_fails_when_a_child_row_fails():
    results = {("ict", 0): "PASS", ("ict", 1): "FAIL",
               ("fct", 0): "PASS"}
    assert stage_verdict(results, "ict") == "FAIL"
    assert stage_verdict(results, "fct") == "PASS"
    # Error counts like FAIL
    assert stage_verdict({("fct", 0): "Error"}, "fct") == "FAIL"


def test_stage_passes_with_only_ignored_rows():
    results = {("ict", 0): "Ignore", ("ict", 1): "Ignore"}
    # rollup excludes ignored rows -> nothing judged -> not FAIL
    # (the runner maps None to PASS)
    assert stage_verdict(results, "ict") is None
