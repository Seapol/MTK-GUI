# -*- coding: utf-8 -*-
"""DesignDataModel tests: draft/committed gate, bind-back, meta."""
from __future__ import annotations

import pytest

from mtkgui.gui.yamlbuild.parser import parse_netlist

from mtkgui.gui.designinput.components import build_library
from mtkgui.gui.designinput.model import (
    BOARD_FULL_SYSTEM,
    BOARD_NO_MCU_SUB,
    STATE_COMMITTED,
    STATE_DRAFT,
    DesignDataModel,
    validate_power_tree,
)
from mtkgui.gui.designinput.netlist import NET_TYPE_GND_REF, \
    classify_nets

NETLIST = """
*SIGNAL* GND
J1.2 U1.1
*SIGNAL* 3V3
U2.VOUT U1.5
"""

COMPONENTS = [("U1", "MIMXRT798S"), ("U2", "PF1500")]

VALID_TREE = {
    "input_sources": [{"name": "DC12V", "nominal": "12", "unit": "V",
                       "mutually_exclusive": False, "output": "VIN_5V"}],
    "rails": [
        {"rail_name": "3V3", "nominal": "3.3", "alt_nominal": "",
         "tolerance_pct": "5", "source": "VPRE", "load": "MCU IO",
         "jumper_controlled": False},
        {"rail_name": "VPRE", "nominal": "5", "alt_nominal": "",
         "tolerance_pct": "5", "source": "", "load": "",
         "jumper_controlled": False},
    ],
}


def _model(source="native_text_spf") -> DesignDataModel:
    model = DesignDataModel(source_type=source)
    model.component_library = build_library(COMPONENTS)
    model.net_collection = classify_nets(parse_netlist(NETLIST))
    model.project_info = {"project_name": "FRDM-IMXRT700",
                          "core_id": "MIMXRT798S",
                          "main_chips": ["U1"]}
    for rec in model.net_collection.nets:
        if rec.net_type == NET_TYPE_GND_REF:
            rec.is_reference_gnd = True
        if rec.name == "3V3":
            rec.is_alternative_testpoint = True
    return model


# ------------------------------------------------------------- state
def test_starts_in_draft_state():
    assert _model().state == STATE_DRAFT
    assert not _model().is_committed


def test_board_type_inference():
    assert _model().infer_board_type() == BOARD_FULL_SYSTEM
    bare = _model()
    bare.project_info["main_chips"] = []
    assert bare.infer_board_type() == BOARD_NO_MCU_SUB


def test_core_id_suggestion():
    assert _model().core_id_suggestion() == "MIMXRT798S"


# -------------------------------------------------------- commit gate
def test_commit_blocked_without_power_tree():
    model = _model()
    errors, _warnings = model.commit()
    assert any("power_tree is empty" in e for e in errors)
    assert model.state == STATE_DRAFT


def test_commit_blocked_without_project_name():
    model = _model()
    model.power_tree = VALID_TREE
    model.project_info["project_name"] = ""
    errors, _ = model.commit()
    assert any("project_name" in e for e in errors)


def test_commit_blocked_without_reference_gnd():
    model = _model()
    model.power_tree = VALID_TREE
    for rec in model.net_collection.nets:
        rec.is_reference_gnd = False
    errors, _ = model.commit()
    assert any("reference GND" in e for e in errors)


def test_commit_success_and_audit_line():
    model = _model()
    model.power_tree = VALID_TREE
    errors, warnings = model.commit()
    assert errors == []
    assert model.is_committed and model.committed_at
    assert model.audit_line.startswith(
        "INFO: User performed Final Review & Commit Design-Input at ")
    assert "schematic_source_type=native_text_spf" in model.audit_line
    assert warnings  # alternative-tp review warning present


def test_commit_warning_core_id_empty():
    model = _model()
    model.power_tree = VALID_TREE
    model.project_info["core_id"] = ""
    _errors, warnings = model.validate_commit()
    assert any("core_id is empty" in w for w in warnings)


def test_commit_warning_other_devices():
    model = _model()
    model.power_tree = VALID_TREE
    model.component_library.records.append(
        model.component_library.records[0].__class__(
            refdes="U9", part_number="JUNK", dev_category="other"))
    _errors, warnings = model.validate_commit()
    assert any("'other'" in w and "U9" in w for w in warnings)


def test_commit_warning_smart_pdf_fixed_wording():
    model = _model(source="smart_pdf_spf")
    model.power_tree = VALID_TREE
    _errors, warnings = model.validate_commit()
    assert any(w.startswith("WARNING: Schematic source is Smart-PDF")
               for w in warnings)


# ------------------------------------------------------------- export
def test_official_export_refused_in_draft():
    model = _model()
    with pytest.raises(PermissionError):
        model.to_dict(official=True)


def test_official_export_allowed_after_commit():
    model = _model()
    model.power_tree = VALID_TREE
    model.commit()
    payload = model.to_dict(official=True)
    assert payload["meta"]["schematic_source_type"] == "native_text_spf"
    assert payload["meta"]["state"] == STATE_COMMITTED
    assert payload["power_tree"] == VALID_TREE


def test_draft_export_never_carries_power_tree():
    model = _model()
    model.power_tree = VALID_TREE
    payload = model.to_dict(official=False)
    assert payload["meta"]["kind"] == "candidate_design_data"
    assert payload["power_tree"] is None


# --------------------------------------------------------------- bind
def test_bind_power_tree_to_nets():
    model = _model()
    model.power_tree = VALID_TREE
    bound = model.bind_power_tree_to_nets()
    rec = model.net_collection.by_name("3V3")
    assert bound == 1
    assert rec.nominal == "3.3"
    assert rec.tolerance_pct == "5"
    assert rec.jumper_controlled is False


# ------------------------------------------------------ tree validate
def test_validate_power_tree_error_matrix():
    bad = {"rails": [
        {"rail_name": "A", "nominal": "", "tolerance_pct": "5",
         "source": "GHOST", "jumper_controlled": True,
         "alt_nominal": ""},
        {"rail_name": "B", "nominal": "1", "tolerance_pct": "",
         "source": "A"},
    ]}
    errors = validate_power_tree(bad)
    joined = "\n".join(errors)
    assert "A': nominal is empty" in joined
    assert "B': tolerance_pct is empty" in joined
    assert "source 'GHOST' does not exist" in joined
    assert "jumper_controlled requires alt_nominal" in joined


def test_validate_power_tree_circular():
    cyclic = {"rails": [
        {"rail_name": "A", "nominal": "1", "tolerance_pct": "1",
         "source": "B"},
        {"rail_name": "B", "nominal": "1", "tolerance_pct": "1",
         "source": "A"},
    ]}
    errors = validate_power_tree(cyclic)
    assert any("circular" in e for e in errors)


def test_validate_power_tree_ok():
    assert validate_power_tree(VALID_TREE) == []
