# -*- coding: utf-8 -*-
"""M79: a sequence must contain at least one real test.

The rule reports ERROR (blocking) when an ENABLED, configured stage
has zero rows or only non-test rows (Done / Ignore / Delay / notice).
A disabled stage and a stage with no sequence section are exempt.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine import policies, yaml_validation as yv  # noqa: E402
from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _doc(ict=None, fct=None, flow=None) -> dict:
    wf: dict = {
        "ict_test_cases": [] if ict is None else list(ict),
        "fct_test_cases": [] if fct is None else list(fct),
    }
    if flow is not None:
        wf["overall_flow"] = flow
    return {"test_workflow": wf}


_REAL_ICT = {"name": "R-GND - TP_P01", "kind": "R-GND"}
_REAL_FCT = {"name": "Wi-Fi Scan", "kind": "WIFI"}
_OP = {"name": "Power On DUT", "kind": "op"}
_DELAY = {"name": "Delay - system boot wait", "kind": "Delay"}
_NOTICE = {"name": "Operator notice", "kind": "MessageOK"}


def _errors(doc: dict) -> list:
    return yv.blocking_issues(yv.validate_project_yaml(doc))


# ------------------------------------------------------------ FCT cases
def test_m79_fct_all_op_rows_is_error():
    """100 % op rows -> ERROR naming FCT."""
    issues = _errors(_doc(ict=[_REAL_ICT], fct=[_OP, dict(_OP)]))
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == yv.SEVERITY_ERROR
    assert issue.location == "fct_test_cases"
    assert issue.message == (
        "FCT sequence contains no valid test (every row is Done / "
        "Ignore / Delay / notice) - add at least one real test")


def test_m79_fct_all_skipped_rows_is_error():
    """Every row skip / disabled -> ERROR (they run as Ignore)."""
    rows = [
        {"name": "Console - kernel version", "kind": "SendtoCLI",
         "skip": True},
        {"name": "Wi-Fi scan", "kind": "WIFI", "enable": False},
        {"name": "Marker skip", "kind": "SendtoCLI",
         "op_params": {"fct_step": {"params": {"skip": True}}}},
    ]
    issues = _errors(_doc(ict=[_REAL_ICT], fct=rows))
    assert len(issues) == 1
    assert "FCT sequence contains no valid test" in issues[0].message
    assert issues[0].location == "fct_test_cases"


def test_m79_fct_empty_sequence_is_error():
    """Zero rows -> ERROR with the exact empty-sequence text."""
    issues = _errors(_doc(ict=[_REAL_ICT], fct=[]))
    assert len(issues) == 1
    assert issues[0].message == (
        "FCT sequence is empty - no test is defined")
    assert issues[0].severity == yv.SEVERITY_ERROR
    assert issues[0].location == "fct_test_cases"


# ------------------------------------------------------------ ICT cases
def test_m79_ict_all_op_rows_is_error():
    """Same rule for the ICT stage."""
    issues = _errors(_doc(ict=[_OP, dict(_OP)], fct=[_REAL_FCT]))
    assert len(issues) == 1
    assert issues[0].message == (
        "ICT sequence contains no valid test (every row is Done / "
        "Ignore / Delay / notice) - add at least one real test")
    assert issues[0].location == "ict_test_cases"


# --------------------------------------------------------- exemptions
def test_m79_disabled_stage_is_exempt():
    """ICT-only project (FCT disabled, no FCT rows) passes - and the
    reverse direction too."""
    ict_only = _doc(
        ict=[_REAL_ICT], fct=[],
        flow=[{"stage": "ICT", "enable": True},
              {"stage": "FCT", "enable": False}])
    assert _errors(ict_only) == []
    fct_only = _doc(
        ict=[], fct=[_REAL_FCT],
        flow=[{"stage": "ICT", "enable": False},
              {"stage": "FCT", "enable": True}])
    assert _errors(fct_only) == []


def test_m79_one_real_test_is_enough():
    """A single Console / WIFI row makes the sequence legal."""
    rows = [_OP, _DELAY,
            {"name": "Wi-Fi scan", "kind": "WIFI"},
            {"name": "Kernel check", "kind": "CapturefromConsole"}]
    assert _errors(_doc(ict=[_REAL_ICT], fct=rows)) == []


def test_m79_delay_and_notice_do_not_count():
    """Delay + MessageOK only -> ERROR (they never judge the DUT)."""
    rows = [_DELAY, _NOTICE,
            {"name": "Delay via marker", "kind": "MessageOK",
             "op_params": {"fct_step": {
                 "step_type": "EXTERNAL_TOOL",
                 "params": {"fct_delay_ms": 5000}}}}]
    issues = _errors(_doc(ict=[_REAL_ICT], fct=rows))
    assert len(issues) == 1
    assert issues[0].message == (
        "FCT sequence contains no valid test (every row is Done / "
        "Ignore / Delay / notice) - add at least one real test")


# ------------------------------------------------ load / apply gating
def test_m79_error_blocks_apply_and_load(qapp, monkeypatch):
    """The engine gate returns the error on BOTH paths.

    Apply and Save Yaml: ``_apply_save_fct_params`` returns the text
    and emits nothing (the dialog stays open).  Load Yaml: the same
    ``blocking_issues()`` list stops the load before it starts."""
    page = YamlBuildPage()
    monkeypatch.setattr(
        page, "_emit_fct_sequence",
        lambda params: ([dict(_OP)], []))
    monkeypatch.setattr(page.model, "validate_module", lambda key: [])
    applied: list = []
    page.fct_sequence_applied.connect(applied.append)
    error = page._apply_save_fct_params({})
    assert error and "FCT sequence contains no valid test" in error
    assert applied == []                 # nothing applied / saved
    # the Load Yaml gate consumes the same blocking list
    bad = _doc(ict=[_REAL_ICT], fct=[_OP])
    assert yv.blocking_issues(yv.validate_project_yaml(bad))
    page.deleteLater()


# ------------------------------------------------------ rollup guard
def test_m79_rollup_ignores_done_and_ignore():
    """Done keeps counting as executed; Ignore stays skipped - neither
    changes the Overall Result (operator's lexical rule)."""
    from mtkgui.engine.policies import rollup
    assert rollup({("ict", 0): "Done", ("fct", 0): "Ignore"}) == "PASS"
    assert rollup({("fct", 0): "Ignore", ("fct", 1): "Ignore"}) is None
    assert rollup({("fct", 0): "FAIL", ("fct", 1): "Ignore"}) == "FAIL"
    assert rollup({("fct", 0): "PASS", ("fct", 1): "Done"}) == "PASS"
    # the judged sets are untouched (regression guard)
    assert policies._JUDGED_OK == {"ict": ("PASS", "Done"),
                                   "fct": ("PASS",)}
    assert policies._JUDGED_BAD == ("FAIL", "Error")
