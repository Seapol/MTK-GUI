# -*- coding: utf-8 -*-
"""Workflow redefinition tests: fixed stage list, responsibility
boundaries, legacy power_dut migration and the 2026-10-13 module
retirement compatibility."""
from __future__ import annotations

import pytest
import yaml

pytest.importorskip("PySide6")

from mtkgui.gui.yamlbuild.block_flow import MODULE_TOOLTIPS, \
    BlockFlowWidget
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.schema import MODULE_FIELDS, fields_for
from mtkgui.gui.yamlbuild.stages import (
    LEGACY_MODULE_MAP,
    LEGACY_ORDER_SWAP,
    REMOVED_MODULES,
    STAGE_BY_KEY,
    STAGE_KEYS,
    WORKFLOW_STAGES,
)


# --------------------------------------------------------------- stage list
def test_stage_list_fixed_order():
    assert [s.key for s in WORKFLOW_STAGES] == [
        "design_input", "parse_ict", "instruments", "rails", "clocks",
        "gpios", "fct_build"]


def test_titles_match_numbering():
    """Parse nets for ICT is block 02, instruments stay a YAML module
    (Equipment page holds the values) and the retired stages are gone."""
    titles = [s.title for s in WORKFLOW_STAGES]
    assert titles[0] == "Design Input"
    assert titles[1] == "Parse nets for ICT"
    assert titles[2] == "Configure Instruments"
    assert titles[3] == \
        "Build Impedance/Voltage/Power rails up sequence"
    assert titles[6] == "Build FCT Test Work Flow Sequence"


# ------------------------------------------------- responsibility boundary
def test_block03_is_the_only_rack_instrument_editor():
    """Rack-ATE instrument fields (VISA addresses / channel alloc)
    exist ONLY in the instruments module - no Build block redefines
    them."""
    instrument_fields = {f.name for f in fields_for("instruments")}
    assert {"psu_visa", "daq_visa", "dmm_visa",
            "channel_alloc"} <= instrument_fields
    for key in STAGE_KEYS:
        if key == "instruments":
            continue
        names = {f.name for f in fields_for(key)}
        assert not ({"psu_visa", "daq_visa", "dmm_visa",
                     "channel_alloc"} & names), key


def test_retired_modules_have_no_schema_and_no_stage():
    """The 2026-10-13 retirement: programmer / peripherals /
    validate_sequence / preview_export are OUT of the stage list and
    have NO field schema (their parameters had no runtime consumer;
    the Equipment page owns the hardware config)."""
    for key in REMOVED_MODULES:
        assert key not in STAGE_KEYS, key
        assert key not in STAGE_BY_KEY, key
        assert key not in MODULE_FIELDS, key
        assert not fields_for(key), key


def test_power_up_sequence_lives_in_block04():
    """DUT power-up fields moved from legacy power_dut into rails."""
    rail_fields = {f.name for f in fields_for("rails")}
    assert {"on_voltage_v", "current_limit_a", "on_delay_ms",
            "off_delay_ms", "off_protection"} <= rail_fields
    assert not fields_for("power_dut")      # legacy block gone


def test_parse_build_separation_in_tooltips():
    """Parse blocks state 'no sequence generation'; Build blocks state
    'reuse instruments / no reconfiguration' - the boundary wording is
    normative (GUI language = English)."""
    assert "no test sequence generation" in MODULE_TOOLTIPS["parse_ict"]
    assert "no instrument reconfiguration" in \
        MODULE_TOOLTIPS["fct_build"]
    assert "no reconfiguration" in MODULE_TOOLTIPS["rails"]
    assert "Equipment page" in MODULE_TOOLTIPS["instruments"]


def test_every_stage_has_tooltip():
    for key in STAGE_KEYS:
        assert MODULE_TOOLTIPS.get(key, "").strip(), key


# ------------------------------------------------------------------ marks
def test_card_marks_star_then_check(qapp=None):
    """User direction: OK on a module marks its card with a star
    (top-right); marks survive a state round trip (restart-safe)."""
    from PySide6.QtWidgets import QApplication
    from mtkgui.gui.yamlbuild.block_flow import (
        MARK_CHECK,
        MARK_NONE,
        MARK_STAR,
    )
    QApplication.instance() or QApplication([])
    flow = BlockFlowWidget()
    flow.set_module_mark("rails", MARK_STAR)
    assert flow._cards["ict_workflow"].mark_label.text() == "★"
    flow.set_module_mark("fct_build", MARK_STAR)
    assert flow._cards["fct_build"].mark_label.text() == "★"
    flow.set_module_mark("rails", MARK_CHECK)
    flow.set_module_mark("fct_build", MARK_CHECK)
    assert flow._cards["ict_workflow"].mark_label.text() == "✓"
    assert flow._cards["fct_build"].mark_label.text() == "✓"
    flow.deleteLater()

    model = YamlBuildModel()
    model.set_mark("rails", MARK_STAR)
    model.set_mark("instruments", MARK_CHECK)
    state = model.to_dict()
    restored = YamlBuildModel()
    restored.apply_state(state)
    assert restored.marks["rails"] == MARK_STAR
    assert restored.marks["instruments"] == MARK_CHECK
    model.set_mark("rails", MARK_NONE)
    assert "rails" not in model.marks


# ------------------------------------------------------------------ UI
def test_block_flow_renders_merged_display_cards():
    """The UI renders the MERGED display sequence: rails/clocks/gpios
    collapse into the single 'Build ICT Test Work Flow Sequence' card,
    the retired modules show NO card and the Channel Allocation nav
    card joins the flow (5 cards); the YAML model keeps the 7-module
    sequence."""
    from PySide6.QtWidgets import QApplication
    from mtkgui.gui.yamlbuild.block_flow import MARK_STAR
    from mtkgui.gui.yamlbuild.stages import (
        DISPLAY_CHANNEL_ALLOC,
        DISPLAY_ICT_WORKFLOW,
        WORKFLOW_DISPLAY_STAGES,
    )
    QApplication.instance() or QApplication([])
    flow = BlockFlowWidget()
    assert len(flow._cards) == 5
    assert list(flow._cards) == [s.key for s in WORKFLOW_DISPLAY_STAGES]
    assert flow._card_modules[DISPLAY_ICT_WORKFLOW] == \
        ("rails", "clocks", "gpios")
    # nav card: no enable state ever, but it CARRIES a mark (the star
    # shows once the auto allocation ran - user direction 2026-10-13)
    flow.set_state(DISPLAY_CHANNEL_ALLOC, False)
    assert "Disabled" not in flow._cards[
        DISPLAY_CHANNEL_ALLOC].state_label.text()
    assert flow._cards[DISPLAY_CHANNEL_ALLOC].mark_label.text() == ""
    flow.set_module_mark(DISPLAY_CHANNEL_ALLOC, MARK_STAR)
    assert flow._cards[DISPLAY_CHANNEL_ALLOC].mark_label.text() == "★"
    flow.deleteLater()


# ------------------------------------------------------------- migration
def test_legacy_yaml_power_dut_migrates_to_rails():
    """A pre-M0 YAML carrying power_dut applies its parameters to
    rails without an 'unknown module' error."""
    model = YamlBuildModel()
    legacy = {"yaml_build": {"plan_version": "1.0.0", "modules": {
        "design_input": {"enabled": True},
        "power_dut": {"enabled": True, "on_voltage_v": "12.0",
                      "on_delay_ms": "150"},
        "parse_ict": {"enabled": True},
    }}}
    errors = model.apply_yaml_dict(legacy)
    assert not any("unknown module" in e for e in errors)
    assert model.get_params("rails")["on_voltage_v"] == "12.0"
    assert model.get_params("rails")["on_delay_ms"] == "150"
    assert model.is_enabled("rails") is True


def test_retired_modules_drop_silently_from_yaml():
    """Old YAML files carrying the retired modules load WITHOUT an
    'unknown module' error - the entries are dropped by the migration
    and never reach the effective YAML again (2026-10-13)."""
    model = YamlBuildModel()
    legacy = {"yaml_build": {"plan_version": "1.0.0", "modules": {
        "design_input": {"enabled": True},
        "programmer": {"enabled": True, "protocol": "JTAG"},
        "peripherals": {"enabled": True, "wifi_ssid": "lab"},
        "validate_sequence": {"enabled": True},
        "preview_export": {"enabled": True,
                           "export_dir": "old/dir"},
        "parse_ict": {"enabled": True},
    }}}
    errors = model.apply_yaml_dict(legacy)
    assert not any("unknown module" in e for e in errors), errors
    data = yaml.safe_load(model.to_effective_yaml())
    modules = data["yaml_build"]["modules"]
    for key in REMOVED_MODULES:
        assert key not in modules, key


def test_legacy_state_with_retired_modules_loads():
    """A pre-2026-10-13 saved state dict carrying the retired module
    entries applies cleanly (apply_state only reads known keys)."""
    model = YamlBuildModel()
    model.apply_state({"plan_version": "1.0.0", "imported": {},
                       "modules": {
                           "design_input": {"enabled": True,
                                            "params": {}},
                           "programmer": {"enabled": False,
                                          "params": {}},
                           "peripherals": {"enabled": True,
                                           "params": {}},
                       }})
    assert model.is_enabled("design_input") is True
    assert model.is_enabled("rails") is True


def test_legacy_migration_keeps_existing_rails_entry():
    """When the YAML already carries rails, legacy power_dut params
    merge in WITHOUT clobbering the rails entry's own enabled state."""
    model = YamlBuildModel()
    legacy = {"yaml_build": {"plan_version": "1.0.0", "modules": {
        "rails": {"enabled": True, "sequence": "VDD:0.0"},
        "power_dut": {"enabled": False, "on_voltage_v": "7.0"},
    }}}
    model.apply_yaml_dict(legacy)
    assert model.get_params("rails")["on_voltage_v"] == "7.0"
    assert model.get_params("rails")["sequence"] == "VDD:0.0"
    assert model.is_enabled("rails") is True   # rails own state wins


def test_legacy_map_covers_only_power_dut():
    assert LEGACY_MODULE_MAP == {"power_dut": "rails"}


def test_legacy_pre_item23_order_swaps_to_canonical():
    """Item 23: projects saved with instruments BEFORE parse_ict load
    cleanly - the legacy pair is swapped onto the canonical sequence
    instead of failing the order check."""
    model = YamlBuildModel()
    legacy = {"yaml_build": {"plan_version": "1.0.0", "modules": {
        "design_input": {"enabled": True},
        "instruments": {"enabled": True, "daq_visa": "GPIB0::9::INSTR"},
        "parse_ict": {"enabled": True, "netlist_file": "n.net"},
    }}}
    errors = model.apply_yaml_dict(legacy)
    assert not any("sequence violates" in e for e in errors)
    assert model.get_params("instruments")["daq_visa"] == \
        "GPIB0::9::INSTR"
    assert model.get_params("parse_ict")["netlist_file"] == "n.net"
    # a saved round trip emits the NEW canonical order
    data = yaml.safe_load(model.to_effective_yaml())
    modules = list(data["yaml_build"]["modules"])
    assert modules.index("parse_ict") < modules.index("instruments")


def test_other_order_violations_still_fail():
    """The legacy swap covers ONLY the exact instruments/parse_ict
    pair - a different wrong sequence still fails the check."""
    model = YamlBuildModel()
    bad = {"yaml_build": {"plan_version": "1.0.0", "modules": {
        "design_input": {"enabled": True},
        "clocks": {"enabled": True},
        "rails": {"enabled": True},
    }}}
    errors = model.apply_yaml_dict(bad)
    assert any("sequence violates" in e for e in errors)


def test_effective_yaml_emits_twelve_in_order():
    model = YamlBuildModel()
    model.enable_all()
    data = yaml.safe_load(model.to_effective_yaml())
    assert list(data["yaml_build"]["modules"]) == list(STAGE_KEYS)
