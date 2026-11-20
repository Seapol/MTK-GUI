# -*- coding: utf-8 -*-
"""v2-3a: the seven-step shell — routing, project tree and draft hook.

Qt-free tests for ``mtkgui/gui/yamlbuild/steps_v2.py``: the step table,
the four routes, the next/prev inverse, the project-tree creator and the
draft hook.  The Qt step bar is covered in ``test_v2_shell_qt.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mtkgui.gui.yamlbuild import steps_v2 as sv
from mtkgui.gui.yamlbuild.model import YamlBuildModel


def _model(core="96317", part="MTK12345") -> YamlBuildModel:
    model = YamlBuildModel()
    model.set_params("design_input", {
        "product_id": core, "part_number": part,
        "sw_version": "1.2.3", "hw_version": "A",
        "batch": "EVT (Proto-1)",
    })
    return model


# ------------------------------------------------------------- step table
def test_step_table_has_seven_steps():
    assert tuple(s.key for s in sv.YAML_STEPS) == (
        "design_input", "parse_ict", "firmware", "equipment",
        "build_ict", "build_fct", "apply_save",
    )
    assert tuple(s.group for s in sv.YAML_STEPS) == (
        "both", "ict", "fct", "both", "ict", "fct", "both",
    )
    assert tuple(s.kind for s in sv.YAML_STEPS) == (
        "panel", "panel", "panel", "panel",
        "panel", "panel", "panel",
    )
    assert sv.step_label("firmware") == "03 · Firmware Config"


def test_placeholder_set_pinned():
    # v2-17 flipped the last placeholder (node 07 Apply & Save Yaml)
    assert sv.PLACEHOLDER_STEPS == frozenset()


# ---------------------------------------------------------------- routing
def test_route_full_both_enabled():
    assert sv.enabled_step_keys(True, True) == (
        "design_input", "parse_ict", "firmware", "equipment",
        "build_ict", "build_fct", "apply_save",
    )


def test_route_ict_only_skips_fct_steps():
    assert sv.enabled_step_keys(True, False) == (
        "design_input", "parse_ict", "equipment", "build_ict", "apply_save",
    )


def test_route_fct_only_skips_ict_steps():
    assert sv.enabled_step_keys(False, True) == (
        "design_input", "firmware", "equipment", "build_fct", "apply_save",
    )


def test_both_blocks_off_disables_next():
    assert sv.enabled_step_keys(False, False) == ()
    for key in sv.STEP_KEYS:
        assert sv.next_key(key, False, False) is None


def test_next_label_shows_target_number():
    # FCT-only sitting on 01 -> the next reachable step is firmware (03)
    assert sv.next_label("design_input", False, True) == "Next: 03 >"
    assert sv.next_label("design_input", True, True) == "Next: 02 >"
    assert sv.next_label("apply_save", True, True) == "Next: >"


def test_prev_is_the_inverse_of_next():
    for ict_on in (True, False):
        for fct_on in (True, False):
            keys = sv.enabled_step_keys(ict_on, fct_on)
            for key in keys:
                nxt = sv.next_key(key, ict_on, fct_on)
                if nxt is not None:
                    assert sv.prev_key(nxt, ict_on, fct_on) == key
    assert sv.prev_key("design_input", True, True) is None


# ----------------------------------------------------------- project tree
def test_next_creates_project_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    base = sv.ensure_project_tree("96317")
    assert (base / "sources").is_dir()
    assert (base / "rules").is_dir()
    assert (base / "DUT Report").is_dir()
    # assets/ and exports/ are NOT created here
    assert not (base / "assets").exists()
    assert not (base / "exports").exists()
    # idempotent: a second call must not fail nor drop a rule file
    (base / "rules" / "project_rules.json").write_text("{}", encoding="utf-8")
    again = sv.ensure_project_tree("96317")
    assert again == base
    assert (base / "rules" / "project_rules.json").is_file()


# ---------------------------------------------------------------- draft hook
def test_save_draft_writes_only_draft(tmp_path, monkeypatch):
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    model = _model()
    path = sv.save_draft(model)
    assert path.is_file()
    # a named draft lands under <work>/drafts/ and NO project folder exists
    assert path.parent == tmp_path / "work" / "drafts"
    assert not (tmp_path / "work" / "96317").exists()


def test_save_draft_before_required_fields_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    model = YamlBuildModel()
    model.set_params("design_input", {"product_id": "", "part_number": ""})
    path = sv.save_draft(model)          # must not raise ValueError
    assert path.parent == tmp_path / "work" / "drafts"
    assert path.name.startswith("draft_") and path.name.endswith(".yaml")


def test_save_draft_into_tree_after_next(tmp_path, monkeypatch):
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    model = _model()
    sv.ensure_project_tree("96317")
    path = sv.save_draft(model)
    assert path.parent == tmp_path / "work" / "96317"
    assert path.name.endswith("_Draft.yaml")
