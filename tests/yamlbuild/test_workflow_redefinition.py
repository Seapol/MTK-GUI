# -*- coding: utf-8 -*-
"""M0 workflow redefinition tests: twelve-stage list, responsibility
boundaries, and legacy power_dut migration."""
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
    STAGE_BY_KEY,
    STAGE_KEYS,
    WORKFLOW_STAGES,
)


# --------------------------------------------------------------- stage list
def test_twelve_stage_fixed_order():
    assert [s.key for s in WORKFLOW_STAGES] == [
        "design_input", "parse_ict", "instruments", "rails", "clocks",
        "gpios", "programmer", "peripherals", "fct_parse", "fct_build",
        "validate_sequence", "preview_export"]


def test_titles_match_item23_numbering():
    """Item 23: Parse nets for ICT is block 02, Configure Instruments
    block 03 (SPF+NET parse first, instruments after)."""
    titles = [s.title for s in WORKFLOW_STAGES]
    assert titles[0] == "Design Input"
    assert titles[1] == "Parse nets for ICT"
    assert titles[2] == "Configure Instruments"
    assert titles[3] == \
        "Build Impedance/Voltage/Power rails up sequence"
    assert titles[10] == "Validate Full Test Sequence"
    assert titles[11] == "Preview & Export YAML"


# ------------------------------------------------- responsibility boundary
def test_block03_is_the_only_rack_instrument_editor():
    """Rack-ATE instrument fields (VISA addresses / channel alloc)
    exist ONLY in block 03 - no later Build block redefines them."""
    instrument_fields = {f.name for f in fields_for("instruments")}
    assert {"psu_visa", "daq_visa", "dmm_visa",
            "channel_alloc"} <= instrument_fields
    for key in STAGE_KEYS:
        if key == "instruments":
            continue
        names = {f.name for f in fields_for(key)}
        assert not ({"psu_visa", "daq_visa", "dmm_visa",
                     "channel_alloc"} & names), key


def test_resource_types_separated():
    """Three disjoint resource families: rack ATE (03), programmer
    (07), DUT peripherals (08) - each owns its own parameter set."""
    rack = {f.name for f in fields_for("instruments")}
    debug = {f.name for f in fields_for("programmer")}
    periph = {f.name for f in fields_for("peripherals")}
    assert rack and debug and periph
    assert not (rack & debug) and not (rack & periph) \
        and not (debug & periph)


def test_power_up_sequence_lives_in_block04():
    """DUT power-up fields moved from legacy power_dut into rails."""
    rail_fields = {f.name for f in fields_for("rails")}
    assert {"on_voltage_v", "current_limit_a", "on_delay_ms",
            "off_delay_ms", "off_protection"} <= rail_fields
    assert not fields_for("power_dut")      # legacy block gone


def test_parse_build_separation_in_tooltips():
    """Parse blocks state 'no sequence generation'; Build blocks state
    'reuse instruments / no reconfiguration'; validate states 'no data
    modification' - the M0 boundary wording is normative."""
    assert "不生成测试序列" in MODULE_TOOLTIPS["parse_ict"]
    assert "不生成测试序列" in MODULE_TOOLTIPS["fct_parse"]
    assert "不重新配置仪器" in MODULE_TOOLTIPS["fct_build"]
    assert "不重复配置仪器" in MODULE_TOOLTIPS["rails"]
    assert "不修改流程数据" in MODULE_TOOLTIPS["validate_sequence"]
    assert "唯一仪器配置入口" in MODULE_TOOLTIPS["instruments"]


def test_validate_and_export_blocks_exist_in_schema():
    assert "resource_conflict_check" in {
        f.name for f in fields_for("validate_sequence")}
    assert "export_dir" in {f.name for f in fields_for("preview_export")}


def test_every_stage_has_tooltip():
    for key in STAGE_KEYS:
        assert MODULE_TOOLTIPS.get(key, "").strip(), key


# ------------------------------------------------------------------ UI
def test_block_flow_renders_merged_display_cards():
    """The UI renders the MERGED display sequence: 04/05/06 collapse
    into the single 'Build ICT Test Work Flow Sequence' card (10
    cards); the YAML model keeps the full 12-module sequence."""
    from PySide6.QtWidgets import QApplication
    from mtkgui.gui.yamlbuild.stages import (
        DISPLAY_ICT_WORKFLOW,
        WORKFLOW_DISPLAY_STAGES,
    )
    QApplication.instance() or QApplication([])
    flow = BlockFlowWidget()
    assert len(flow._cards) == 10
    assert list(flow._cards) == [s.key for s in WORKFLOW_DISPLAY_STAGES]
    assert flow._card_modules[DISPLAY_ICT_WORKFLOW] == \
        ("rails", "clocks", "gpios")
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


def test_legacy_state_power_dut_migrates_to_rails():
    """A pre-M0 persisted state dict migrates power_dut -> rails; new
    M0 blocks default ENABLED (rule 3.2)."""
    model = YamlBuildModel()
    model.apply_state({"plan_version": "1.0.0", "imported": {},
                       "modules": {
                           "design_input": {"enabled": True,
                                            "params": {}},
                           "power_dut": {"enabled": True,
                                         "params": {
                                             "on_voltage_v": "9.0"}},
                       }})
    assert model.get_params("rails")["on_voltage_v"] == "9.0"
    assert model.is_enabled("rails") is True
    for key in ("instruments", "validate_sequence", "preview_export"):
        assert model.is_enabled(key), key


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
