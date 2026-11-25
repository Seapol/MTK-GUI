"""M128: per-module padlocks, colour coding and Empty/Edited badges."""

from __future__ import annotations

import pytest

from mtkgui.gui.yamlbuild import flow_view as fv
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.publish import build_plan_document
from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard

DESIGN = {
    "part_number": "MTK12345", "product_id": "96317",
    "sw_version": "1.2.3", "hw_version": "A",
    "batch": "EVT (Proto-1)", "ict_block_enabled": "true",
    "spf_file": "s.spf", "net_file": "n.net", "bom_file": "b.csv",
}


@pytest.fixture()
def wizard():
    w = YamlBuildWizard()
    try:
        yield w
    finally:
        w.deleteLater()


def test_locks_accept_the_flowchart_keys_and_survive_a_yaml_roundtrip():
    model = YamlBuildModel()
    model.set_locked("firmware", True)
    model.set_locked("build_ict", True)
    assert model.locked_keys() == ("firmware", "build_ict")

    doc = build_plan_document(model, "draft")
    assert doc["yaml_build"]["locks"] == {"build_ict": True, "firmware": True}

    restored = YamlBuildModel()
    restored.apply_yaml_dict(doc, validate_no_ui=False)
    assert restored.locked_keys() == ("firmware", "build_ict")


def test_unlocked_modules_are_not_written_to_yaml():
    model = YamlBuildModel()
    model.set_locked("design_input", True)
    model.set_locked("design_input", False)
    doc = build_plan_document(model, "draft")
    assert "locks" not in doc["yaml_build"]


def test_loading_another_yaml_replaces_the_lock_state():
    model = YamlBuildModel()
    model.set_locked("parse_ict", True)
    doc = {"schema": "mtkgui.plan/1.0", "yaml_build": {"locks": {}}}
    model.apply_yaml_dict(doc, validate_no_ui=False)
    assert model.locked_keys() == ()


def test_unlocking_a_module_releases_every_later_module(wizard):
    for key in ("design_input", "parse_ict", "firmware", "equipment"):
        wizard.model.set_locked(key, True)
    wizard._unlock_from("parse_ict")
    assert wizard.model.locked_keys() == ("design_input",)


def test_lock_checks_first_and_refuses_when_the_module_is_incomplete(wizard):
    wizard._panels["design_input"].set_values({})  # empty -> validation fails
    ok, message = wizard._check_and_lock(
        "design_input", wizard._panels["design_input"])

    assert ok is False
    assert message
    assert wizard.model.is_locked("design_input") is False


def test_lock_succeeds_on_a_complete_module(wizard, monkeypatch):
    monkeypatch.setattr("mtkgui.gui.yamlbuild.steps_v2.save_draft",
                        lambda model: None)
    monkeypatch.setattr("mtkgui.gui.yamlbuild.steps_v2.ensure_project_tree",
                        lambda core: None)
    wizard._panels["design_input"].set_values(DESIGN)

    ok, message = wizard._check_and_lock(
        "design_input", wizard._panels["design_input"])

    assert ok is True, message
    assert wizard.model.is_locked("design_input") is True


def test_visuals_follow_the_lock_and_the_badge_text(wizard):
    wizard._panels["design_input"].set_values(DESIGN)
    wizard.model.set_locked("design_input", True)
    wizard._sync_visuals()

    locked = wizard.flow.step_visual("design_input")
    assert locked["locked"] is True
    assert locked["edited"] is True

    todo = wizard.flow.step_visual("parse_ict")
    assert todo == {"unused": False, "locked": False, "edited": False}


def test_flow_view_paints_three_colours():
    assert fv._UNUSED["fill"] != fv._TODO["fill"] != fv._LOCKED["fill"]
    view = fv.YamlBuildFlowView()
    try:
        view.set_step_visual("parse_ict", unused=True, locked=False, edited=False)
        view.set_step_visual("equipment", unused=False, locked=False, edited=True)
        view.set_step_visual("apply_save", unused=False, locked=True, edited=True)
        assert view.step_visual("parse_ict")["unused"] is True
        assert view.step_visual("equipment")["edited"] is True
        assert view.step_visual("apply_save")["locked"] is True
        view._draw_node  # drawing must not raise for the new badge
        view.resize(1330, 420)
        view.grab()
    finally:
        view.deleteLater()


def test_module_has_content_ignores_schema_defaults():
    model = YamlBuildModel()
    assert model.module_has_content("design_input") is False
    assert model.module_has_content("parse_ict") is False
    assert model.module_has_content("build_ict") is False
    model.set_params("design_input", {"part_number": "ABC"})
    assert model.module_has_content("design_input") is True


def test_close_yaml_clears_values_and_locks(wizard):
    wizard._panels["design_input"].set_values(DESIGN)
    wizard.model.set_locked("design_input", True)

    wizard.model.apply_state({})
    wizard.model.reset_locks()
    wizard.refresh_from_model()

    assert wizard.model.get_params("design_input").get("part_number", "") == ""
    assert wizard.model.locked_keys() == ()
    assert wizard._panels["design_input"].values().get("part_number", "") == ""
