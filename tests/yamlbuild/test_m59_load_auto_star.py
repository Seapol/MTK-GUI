# -*- coding: utf-8 -*-
"""M59: loading an existing project YAML auto-stars blocks 01-03 from
stored data completeness - no SPF / NET / BoM re-import required."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mtkgui.gui.yamlbuild.model import YamlBuildModel  # noqa: E402

STAR = "star"

POWER_OK = {"net": "VDD_CORE", "test_point": "TP1", "instrument": "DAQ",
            "channel": "1", "impedance": "1 MOhm", "voltage": "1.0",
            "power_rails": "VDD_CORE", "r_gnd_min_ohm": "1000",
            "nominal_v": "1.0", "lower_v": "0.95", "upper_v": "1.05"}

POWER_NOK = {"net": "VDD_CORE", "instrument": "DAQ", "channel": "1",
             "impedance": "1 MOhm", "voltage": "1.0"}


def _design(**kw) -> dict:
    params = {"part_number": "MTK-1000", "product_id": "CORE01",
              "batch": "B01"}
    params.update(kw)
    return {"design_input": {"enabled": True, "params": params}}


def _state(alloc=POWER_OK, marks=None, design=None, nets=None) -> dict:
    return {
        "imported": {
            "net": {"file": "board.net", "raw": "(net data)"},
            "testable_nets": nets if nets is not None else {
                "VDD_CORE": {"category": "Power", "members": ["TP1"]}},
        },
        "channel_allocation": {
            "power": [alloc] if alloc else [],
            "clock": [], "gpio": []},
        "marks": dict(marks or {}),
        "modules": design if design is not None else _design(),
    }


def test_complete_legacy_state_auto_stars_all_three_blocks():
    model = YamlBuildModel()
    model.apply_state(_state())
    assert model.marks["design_input"] == STAR
    assert model.marks["parse_ict"] == STAR
    assert model.marks["channel_alloc"] == STAR


def test_nok_channel_validation_leaves_block_03_unstarred():
    model = YamlBuildModel()
    model.apply_state(_state(alloc=POWER_NOK))
    assert model.marks["design_input"] == STAR
    assert model.marks["parse_ict"] == STAR
    assert "channel_alloc" not in model.marks


def test_missing_product_data_leaves_block_01_unstarred():
    model = YamlBuildModel()
    model.apply_state(_state(design=_design(part_number="")))
    assert "design_input" not in model.marks
    # 02 / 03 do not depend on the product identity
    assert model.marks["parse_ict"] == STAR
    assert model.marks["channel_alloc"] == STAR


def test_stored_marks_win_over_derivation():
    model = YamlBuildModel()
    model.apply_state(_state(marks={
        "design_input": "check", "parse_ict": "", "channel_alloc": STAR}))
    assert model.marks["design_input"] == "check"     # stored mark kept
    assert model.marks["parse_ict"] == STAR           # absent -> derived
    assert model.marks["channel_alloc"] == STAR


def test_no_design_data_leaves_block_01_and_02_unstarred():
    model = YamlBuildModel()
    state = _state()
    state["imported"] = {"net": {"file": "", "raw": ""},
                         "testable_nets": {}}
    model.apply_state(state)
    assert "design_input" not in model.marks
    assert "parse_ict" not in model.marks
    assert model.marks["channel_alloc"] == STAR       # alloc data survives


def test_empty_state_derives_nothing_fresh_start_unchanged():
    model = YamlBuildModel()
    model.apply_state({})
    assert model.marks == {}
    assert model.marks.get("design_input") is None
    assert model.marks.get("channel_alloc") is None


def test_derived_marks_persist_with_the_next_save():
    model = YamlBuildModel()
    model.apply_state(_state())
    assert model.to_dict()["marks"] == {
        "design_input": STAR, "parse_ict": STAR, "channel_alloc": STAR}
