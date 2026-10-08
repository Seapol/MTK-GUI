# -*- coding: utf-8 -*-
"""Unit tests for the Yaml Build model (enable semantics, effective
YAML, legacy compatibility, persistence)."""

from __future__ import annotations

import pytest
import yaml

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.schema import fields_for
from mtkgui.gui.yamlbuild.stages import STAGE_KEYS, WORKFLOW_STAGES


def make_model(enabled=True) -> YamlBuildModel:
    """Return a model with every module enabled and all required
    fields filled (a valid, publishable configuration)."""
    model = YamlBuildModel()
    if enabled:
        model.enable_all()
    model.set_params("design_input", {
        "product_id": "IMXRT700", "part_number": "MTK12345",
        "sw_version": "1.2.3", "hw_version": "A",
        "batch": "MP (Production)",
    })
    model.set_params("parse_ict", {"netlist_file": "design.net"})
    model.set_params("instruments", {
        "psu_visa": "TCPIP0::192.168.1.20::inst0",
        "daq_visa": "GPIB0::9::INSTR", "dmm_visa": "",
        "self_test": "true",
    })
    model.set_params("rails", {
        "on_voltage_v": "5.0", "current_limit_a": "1.0",
        "on_delay_ms": "100", "off_delay_ms": "200",
        "off_protection": "true",
        "sequence": "VDD:0.0\nVDDCORE:0.2",
        "voltage_tolerance_pct": "0.1",
        "impedance_min_ohm": "1.5",
        "sample_rate_hz": "1000",
        "pre_trigger_s": "-0.5", "post_trigger_s": "6.0",
        "anomaly_policy": "stop",
    })
    model.set_params("clocks", {"clocks": "CLK1:32768:0.1",
                                "stabilize_ms": "100",
                                "drift_check": "true",
                                "multi_domain_check": "false"})
    model.set_params("gpios", {"groups": "LED1:PA0:out:none",
                               "level_threshold_v": "1.5",
                               "exception_check": "true"})
    model.set_params("fct_build", {"flow_steps": "step1\nstep2",
                                   "yield_threshold_pct": "98.0",
                                   "exception_branch": "stop",
                                   "case_link": ""})
    return model


def test_stage_count_and_order():
    """Exactly the eleven fixed stages in the required order (item 23
    redefinition: parse_ict moved to 02, instruments to 03, the FCT
    parse block retired, validate/export close the flow, legacy
    power_dut absorbed into rails)."""
    assert [s.key for s in WORKFLOW_STAGES] == [
        "design_input", "parse_ict", "instruments", "rails", "clocks",
        "gpios", "programmer", "peripherals", "fct_build",
        "validate_sequence", "preview_export"]
    assert "power_dut" not in STAGE_KEYS


def test_power_rails_synced_into_yaml():
    """User question: the Test Work Flow page's power-rails capture
    config MUST land in the YAML - stored as its own section, mirrored
    into the rails module's capture parameters, round-tripped."""
    import yaml
    model = YamlBuildModel()
    model.set_power_rails({
        "instrument": "Keysight U2355A analog input", "channels": 2,
        "duration_s": 6.5, "pre_trigger_s": -0.5, "post_trigger_s": 6.0,
        "sample_rate_hz": 200,
        "rails": [
            {"name": "VDD_3V3", "nominal_v": 3.3,
             "ramp_offset_s": 0.0, "color": "#c00"},
            {"name": "VDD_1V8", "nominal_v": 1.8,
             "ramp_offset_s": 0.2, "color": "#0c0"},
        ],
    })
    data = yaml.safe_load(model.to_effective_yaml())
    seq = data["yaml_build"]["power_rails_up_sequence"]
    assert seq["sample_rate_hz"] == 200
    assert [r["name"] for r in seq["rails"]] == ["VDD_3V3", "VDD_1V8"]
    # mirrored into the rails module capture parameters
    params = model.get_params("rails")
    assert params["sample_rate_hz"] == "200"
    assert params["pre_trigger_s"] == "-0.5"
    assert params["post_trigger_s"] == "6.0"
    # state round trip (restart-safe)
    restored = YamlBuildModel()
    restored.apply_state(model.to_dict())
    assert restored.power_rails_up_sequence["duration_s"] == 6.5
    assert restored.get_params("rails")["sample_rate_hz"] == "200"


def test_built_yaml_is_lean():
    """User direction: the built YAML carries NO redundant fields -
    no per-module stage_index / group bookkeeping and no power_tree
    section (the Power Tree page was retired)."""
    model = make_model()
    data = yaml.safe_load(model.to_effective_yaml())
    for name, entry in data["yaml_build"]["modules"].items():
        assert "stage_index" not in entry, name
        assert "group" not in entry, name
    assert "power_tree" not in data["yaml_build"]


def test_disabled_excluded_from_effective_yaml_but_retained():
    """Disable: skipped in the effective YAML, parameters silently
    retained in the model."""
    model = make_model()
    model.set_params("clocks", {"clocks": "CLK1:32768:0.1",
                                "stabilize_ms": "100"})
    model.set_enabled("clocks", False)
    data = yaml.safe_load(model.to_effective_yaml())
    modules = data["yaml_build"]["modules"]
    assert "clocks" not in modules
    assert "design_input" in modules           # others unaffected
    assert model.get_params("clocks")["clocks"] == "CLK1:32768:0.1"
    assert model.is_enabled("clocks") is False


def test_enabled_modules_in_fixed_order():
    """The effective YAML emits modules in the fixed stage order."""
    model = make_model()
    data = yaml.safe_load(model.to_effective_yaml())
    keys = list(data["yaml_build"]["modules"].keys())
    assert keys == list(STAGE_KEYS)


def test_effective_yaml_types_coerced():
    """Numeric/bool fields are typed in the effective YAML; text
    fields become line lists."""
    model = make_model()
    model.set_params("rails", {
        "on_voltage_v": "5.0", "current_limit_a": "1.0",
        "on_delay_ms": "100", "off_delay_ms": "200",
        "off_protection": "true",
    })
    model.set_params("peripherals", {"init_sequence": "step1\nstep2"})
    data = yaml.safe_load(model.to_effective_yaml())
    rails = data["yaml_build"]["modules"]["rails"]
    assert rails["on_voltage_v"] == 5.0
    assert rails["off_delay_ms"] == 200
    assert rails["off_protection"] is True
    periph = data["yaml_build"]["modules"]["peripherals"]
    assert periph["init_sequence"] == ["step1", "step2"]


def test_validation_range_and_required():
    """Field validation: range violations, required emptiness,
    choice membership."""
    model = make_model()
    model.set_params("rails", {
        "on_voltage_v": "70",            # above maximum 60
        "current_limit_a": "1.0",
        "sequence": "VDD:0.0", "on_delay_ms": "0", "off_delay_ms": "0",
    })
    errors = model.validate_module("rails")
    assert any("above maximum" in e for e in errors)

    model.set_params("programmer", {"protocol": "USB"})   # bad choice
    errors = model.validate_module("programmer")
    assert any("must be one of" in e for e in errors)


def test_disabled_modules_not_validated():
    """Validation skips disabled modules (they are out of the flow)."""
    model = make_model()
    model.set_enabled("rails", False)
    model.set_params("rails", {"sequence": "",       # would be invalid
                               "voltage_tolerance_pct": "0.1",
                               "impedance_min_ohm": "1.5",
                               "sample_rate_hz": "1000",
                               "pre_trigger_s": "-0.5",
                               "post_trigger_s": "6.0",
                               "anomaly_policy": "stop"})
    assert model.validate_module("rails") == []


def test_default_all_enabled_and_legacy_import():
    """Global default (rule 3.2): a fresh model, a new project and a
    legacy YAML import all come up with every module ENABLED."""
    model = YamlBuildModel()
    assert all(model.is_enabled(k) for k in STAGE_KEYS)
    model.enable_all()   # legacy import path - stays all-enabled
    assert all(model.is_enabled(k) for k in STAGE_KEYS)
    model.disable_all()
    assert not any(model.is_enabled(k) for k in STAGE_KEYS)
    model.enable_all()
    assert all(model.is_enabled(k) for k in STAGE_KEYS)


def test_apply_yaml_round_trip():
    """apply_yaml_dict accepts the model's own effective output
    (round trip) and reports no errors."""
    model = make_model()
    data = yaml.safe_load(model.to_effective_yaml())
    other = YamlBuildModel()
    errors = other.apply_yaml_dict(data)
    assert errors == []
    assert other.to_effective_dict() == model.to_effective_dict()


def test_apply_yaml_sequence_violation():
    """A document whose modules break the fixed order is rejected."""
    model = make_model()
    data = yaml.safe_load(model.to_effective_yaml())
    modules = data["yaml_build"]["modules"]
    reordered = dict(reversed(list(modules.items())))
    data["yaml_build"]["modules"] = reordered
    other = YamlBuildModel()
    errors = other.apply_yaml_dict(data)
    assert any("sequence violates" in e for e in errors)


def test_state_round_trip_and_tenant_isolation():
    """State serialization restores params + enable flags; the
    project key derives from Design Input (tenant isolation)."""
    model = make_model()
    model.set_enabled("clocks", False)
    model.set_params("clocks", {"clocks": "CLK1:32768:0.1",
                                "stabilize_ms": "50"})
    state = model.to_dict()
    other = YamlBuildModel()
    other.apply_state(state)
    assert other.is_enabled("clocks") is False
    assert other.get_params("clocks")["clocks"] == "CLK1:32768:0.1"
    assert other.project_key() == "IMXRT700_MTK12345"
    empty = YamlBuildModel()
    assert empty.project_key() == "default"


def test_every_module_has_fields():
    """Every fixed stage owns an independent field schema (no module
    is left without its dedicated parameters)."""
    for key in STAGE_KEYS:
        assert len(fields_for(key)) > 0, key


def test_allocated_testable_filters_unallocated_nets():
    """User rule: nets WITHOUT an allocated instrument channel are
    auto Do-Not-Test - allocated_testable() only returns the nets
    whose channel cells are fully assigned."""
    model = YamlBuildModel()
    model.imported["testable_nets"] = {
        "VDD_1V8": {"category": "Power", "members": ["TP1.1"]},
        "VDD_3V3": {"category": "Power", "members": ["TP2.1"]},
        "CLK_OUT": {"category": "Clock", "members": ["TP3.1"]},
        "CLK_RTC": {"category": "Clock", "members": ["TP4.1"]},
        "GPIO_EN": {"category": "GPIO", "members": ["R1.1"]},
        "GPIO_STRAP": {"category": "GPIO", "members": ["R2.1"]},
    }
    model.set_channel_allocation({
        "power": [
            {"net": "VDD_1V8", "impedance": "DAQM908A #1 CH101",
             "power_rails": "U2355A AI01", "voltage": "DAQM908A #1 CH101"},
            # VDD_3V3: no channels -> excluded
            {"net": "VDD_3V3", "impedance": "—", "power_rails": "—",
             "voltage": "—"},
        ],
        "clock": [
            {"net": "CLK_OUT", "se_clock_hz": "DAQM907A TOT"},
            {"net": "CLK_RTC", "se_clock_hz": "—"},   # excluded
        ],
        "gpio": [
            {"net": "GPIO_EN", "dio_channel": "DIO1"},
            {"net": "GPIO_STRAP", "dio_channel": ""},  # excluded
        ],
    })
    got = model.allocated_testable()
    assert set(got) == {"VDD_1V8", "CLK_OUT", "GPIO_EN"}
    assert got["VDD_1V8"]["category"] == "Power"
    # empty allocation -> nothing is testable
    model.set_channel_allocation({})
    assert model.allocated_testable() == {}
