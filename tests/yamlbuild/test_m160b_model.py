# -*- coding: utf-8 -*-
"""M160b: FctStep on category + type; the legacy kind is gone."""
from __future__ import annotations

import pytest

from mtkgui.engine.step_types import (
    CATEGORY_CONSOLE,
    CATEGORY_EXTERNAL_GUI,
    CATEGORY_MESSAGE,
)
from mtkgui.gui.yamlbuild.fct_build import (
    FctSequence,
    FctStep,
    from_project_fct_cases,
    to_project_fct_cases,
)


def test_to_dict_emits_category_and_type_not_step_type():
    step = FctStep(name="Console login", category=CATEGORY_CONSOLE,
                   type="serial", channel="ser1", command="uname -a")
    data = step.to_dict()
    assert data["category"] == CATEGORY_CONSOLE
    assert data["type"] == "serial"
    assert "step_type" not in data
    assert data["channel"] == "ser1"
    assert data["command"] == "uname -a"


def test_from_dict_round_trips_category_and_type():
    step = FctStep(name="Confirm", category=CATEGORY_MESSAGE,
                   type="yesno_console", timeout_s=0.0,
                   params={"console_dialog": True})
    restored = FctStep.from_dict(step.to_dict())
    assert (restored.category, restored.type) == (
        CATEGORY_MESSAGE, "yesno_console")
    assert restored.to_dict() == step.to_dict()
    # a legacy document is NOT silently migrated
    legacy = FctStep.from_dict({"name": "old", "step_type": "MESSAGE_CHECK"})
    assert legacy.category == "" and legacy.type == ""
    assert legacy.validate({"old"})  # rejected by the validator


def test_validate_rejects_bad_category_type_and_slot():
    bad_category = FctStep(name="x", category="Nope", type="serial")
    assert "unknown category" in " ".join(bad_category.validate({"x"}))
    bad_type = FctStep(name="x", category=CATEGORY_CONSOLE, type="flash")
    assert "not valid for category" in " ".join(bad_type.validate({"x"}))
    bad_slot = FctStep(name="f", category=CATEGORY_EXTERNAL_GUI,
                       type="flash", params={"slot": "x"})
    assert "params.slot" in " ".join(bad_slot.validate({"f"}))
    ok = FctStep(name="f", category=CATEGORY_EXTERNAL_GUI, type="flash",
                 params={"slot": "fat"})
    assert ok.validate({"f"}) == []


def test_from_project_fct_cases_rejects_missing_or_unknown_marker():
    with pytest.raises(ValueError, match="no op_params.fct_step"):
        from_project_fct_cases([{"name": "legacy", "kind": "MessageOK",
                                 "op_params": None}])
    with pytest.raises(ValueError, match="unknown category/type"):
        from_project_fct_cases([{
            "name": "unknown", "kind": "MessageOK",
            "op_params": {"fct_step": {"name": "unknown",
                                       "category": CATEGORY_CONSOLE,
                                       "type": "flash"}}}])
    # a valid marker is accepted and the top-level kind is ignored
    step = FctStep(name="ok", category=CATEGORY_MESSAGE, type="ok")
    cases = to_project_fct_cases(FctSequence(name="s", steps=[step]))
    cases[0]["kind"] = "LegacyNonsense"
    restored = from_project_fct_cases(cases)
    assert (restored.steps[0].category, restored.steps[0].type) == (
        CATEGORY_MESSAGE, "ok")
