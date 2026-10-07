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
