# -*- coding: utf-8 -*-
"""Unit tests for the two-way sync + validation layer and the Excel
round-trip / publishing."""

from __future__ import annotations

import pytest
import yaml

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.sync import (
    sync_model_to_yaml,
    sync_preview_to_model,
    validate_yaml_text,
)
from mtkgui.gui.yamlbuild.excel_io import (
    export_to_excel,
    import_from_excel,
)
from mtkgui.gui.yamlbuild.publish import (
    archive_copy,
    build_plan_document,
    compare_plans,
    parse_plan_name,
    plan_filename,
    publish,
)


def make_model(enabled=True) -> YamlBuildModel:
    """Return a fully-enabled model with every required field filled
    (a valid, publishable configuration)."""
    model = YamlBuildModel()
    if enabled:
        model.enable_all()
    model.set_params("design_input", {
        "product_id": "IMXRT700", "part_number": "MTK12345",
        "sw_version": "1.2.3", "hw_version": "A",
        "batch": "MP (Production)",
    })
    model.set_params("parse_ict", {"netlist_file": "design.net",
                                   "ict_test_file": ""})
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


# ---------------------------------------------------------------------------
# two-way sync + validation
# ---------------------------------------------------------------------------


def test_model_to_yaml_then_back_is_stable():
    """model -> YAML -> model keeps the effective dict identical (no
    drift, no loop artifacts)."""
    model = make_model()
    model.set_params("clocks", {"clocks": "CLK1:32768:0.1",
                                "stabilize_ms": "100",
                                "drift_check": "true",
                                "multi_domain_check": "false"})
    text = sync_model_to_yaml(model)
    other = make_model()
    result = sync_preview_to_model(other, text)
    assert result.ok, result.errors
    assert other.to_effective_dict() == model.to_effective_dict()


def test_syntax_error_detected_with_line():
    """A YAML syntax error is reported with its line (red marker)."""
    model = make_model()
    result = validate_yaml_text("yaml_build:\n  modules: [", model)
    assert not result.ok
    assert any("syntax" in msg for msg, _ in result.errors)


def test_invalid_edit_never_touches_model():
    """An invalid hand edit is rejected: the model keeps its state
    (dirty data never enters the configuration)."""
    model = make_model()

    def semantic(model_dict: dict) -> dict:
        """Content snapshot without the volatile save timestamp (the
        two to_dict() calls may straddle a second boundary under
        load)."""
        return {k: v for k, v in model_dict.items() if k != "saved_at"}

    before = semantic(model.to_dict())
    bad = yaml.safe_load(model.to_effective_yaml())
    bad["yaml_build"]["modules"]["rails"]["on_voltage_v"] = 99
    result = sync_preview_to_model(
        model, yaml.safe_dump(bad, sort_keys=False))
    assert not result.ok
    assert semantic(model.to_dict()) == before


def test_missing_section_rejected():
    """A YAML without the yaml_build section is rejected."""
    model = make_model()
    result = validate_yaml_text("foo: bar", model)
    assert not result.ok
    assert any("yaml_build" in msg for msg, _ in result.errors)


def test_unknown_module_rejected():
    """Unknown module keys are reported (no silent invention)."""
    model = make_model()
    result = validate_yaml_text(
        "yaml_build:\n  modules:\n    bogus: {stage_index: 0}", model)
    assert not result.ok
    assert any("unknown module" in msg for msg, _ in result.errors)


# ---------------------------------------------------------------------------
# Excel round-trip
# ---------------------------------------------------------------------------


def test_excel_round_trip(tmp_path):
    """M91: numeric YamlBuild parameters are applied; structure and the
    enable flags stay review-only."""
    model = make_model()
    model.set_enabled("clocks", False)
    model.set_params("rails", {
        "sequence": "VDD:0.0\nVDDCORE:0.2",
        "voltage_tolerance_pct": "0.2",
        "impedance_min_ohm": "1.5",
        "sample_rate_hz": "2000",
        "pre_trigger_s": "-0.5",
        "post_trigger_s": "6.0",
        "anomaly_policy": "stop",
    })
    path = str(tmp_path / "cfg.xlsx")
    assert export_to_excel(model, path) > 10

    other = make_model(enabled=False)
    before_sequence = other.get_params("rails")["sequence"]
    before_states = {key: other.is_enabled(key)
                     for key in ("clocks", "rails", "design_input")}
    report = import_from_excel(other, path)
    assert report.applied, report.errors
    assert report.errors == []
    # only the two numeric differences are applied
    assert report.imported == 2
    assert report.applied_changes == [
        "YamlBuild rails.voltage_tolerance_pct",
        "YamlBuild rails.sample_rate_hz"]
    assert other.get_params("rails")["voltage_tolerance_pct"] == "0.2"
    assert other.get_params("rails")["sample_rate_hz"] == "2000"
    # structural values and enable flags are never touched
    assert other.get_params("rails")["sequence"] == before_sequence
    assert report.ignored_changes == ["YamlBuild clocks.enabled"]
    for key, state in before_states.items():
        assert other.is_enabled(key) == state


def _allocated_model() -> YamlBuildModel:
    """M70: model with all three allocation tables fully configured."""
    from mtkgui.gui.yamlbuild.channel_allocation import AllocatedRow
    from mtkgui.gui.yamlbuild.power_alloc import (
        CLOCK_BANDS,
        CLOCK_CHANNELS,
        DAQM908A_SENSE_CHANNELS,
        GPIO_DIO_CHANNELS,
        U2355A_AI_CHANNELS,
    )
    model = make_model()
    band = next(iter(CLOCK_BANDS.values()))
    model.set_channel_allocation({
        "power": [AllocatedRow(
            net="VDD_3V3", test_point="TP1.1",
            impedance=DAQM908A_SENSE_CHANNELS[0],
            power_rails=U2355A_AI_CHANNELS[0],
            voltage=DAQM908A_SENSE_CHANNELS[0],
            r_gnd_min_ohm="1.500", nominal_v="3.300",
            lower_v="3.135", upper_v="3.465").to_dict()],
        "clock": [AllocatedRow(
            net="CLK_24M", test_point="TP3.1",
            se_clock_hz=CLOCK_CHANNELS[0], band=band,
            nominal_khz="24000.000", lower_khz="23998.800",
            upper_khz="24001.200").to_dict()],
        "gpio": [AllocatedRow(
            net="GPIO_RST", test_point="TP2.1",
            dio_channel=GPIO_DIO_CHANNELS[0],
            op_type="U2355A DIO Write", drive_level="High").to_dict()],
    })
    return model


def test_excel_round_trip_keeps_channel_allocation_fields(tmp_path):
    """M70/M73: the whitelisted LIMIT fields round-trip losslessly; the
    structural cells stay GUI-owned (identical structure in the target
    model is preserved)."""
    model = _allocated_model()
    path = str(tmp_path / "alloc.xlsx")
    assert export_to_excel(model, path) > 10

    other = _allocated_model()           # same structure, stale limits
    alloc = other.get_channel_allocation()
    alloc["power"][0].update({"r_gnd_min_ohm": "9.000",
                              "nominal_v": "9.900",
                              "lower_v": "9.800", "upper_v": "10.000"})
    alloc["clock"][0].update({"nominal_khz": "1.000",
                              "lower_khz": "0.900",
                              "upper_khz": "1.100"})
    other.set_channel_allocation(alloc)

    report = import_from_excel(other, path)
    assert report.applied, report.errors
    assert report.errors == []
    assert len(report.applied_changes) == 7      # 4 power + 3 clock
    assert other.get_channel_allocation() == model.get_channel_allocation()
    power = other.get_channel_allocation()["power"][0]
    assert power["r_gnd_min_ohm"] == "1.500"
    assert power["nominal_v"] == "3.300"
    assert power["lower_v"] == "3.135"
    assert power["upper_v"] == "3.465"
    clock = other.get_channel_allocation()["clock"][0]
    assert clock["nominal_khz"] == "24000.000"
    assert clock["lower_khz"] == "23998.800"
    assert clock["upper_khz"] == "24001.200"
    gpio = other.get_channel_allocation()["gpio"][0]
    assert gpio["op_type"] == "U2355A DIO Write"
    assert gpio["drive_level"] == "High"


def test_legacy_workbook_keeps_model_values(tmp_path):
    """M70 backward compatibility: a pre-M70 workbook (without the new
    columns) still imports and keeps the values already on the model."""
    from openpyxl import load_workbook

    model = _allocated_model()
    path = str(tmp_path / "alloc.xlsx")
    export_to_excel(model, path)
    workbook = load_workbook(path)
    for sheet, new_columns in (
            ("Power", ("R-GND Min limit (ohm)", "Nominal (V)",
                       "Lower (V)", "Upper (V)")),
            ("Clock", ("Nominal (kHz)", "Lower (kHz)", "Upper (kHz)")),
            ("GPIO", ("Op Type", "Drive Level"))):
        ws = workbook[sheet]
        # M73: headers carry the read-only / editable suffix - match on
        # the base title and drop that whole column
        header = [cell.value for cell in ws[1]]
        for name in new_columns:
            idx = next((i for i, value in enumerate(header)
                        if str(value or "").startswith(name)), None)
            if idx is not None:
                ws.delete_cols(idx + 1)
                header.pop(idx)
    workbook.save(path)

    other = _allocated_model()
    report = import_from_excel(other, path)
    assert report.applied, report.errors
    assert other.get_channel_allocation() == model.get_channel_allocation()


def test_excel_import_rejects_invalid(tmp_path):
    """Invalid values abort the whole import with row errors (no
    partial overwrites)."""
    model = make_model()
    path = str(tmp_path / "cfg.xlsx")
    export_to_excel(model, path)

    from openpyxl import load_workbook
    wb = load_workbook(path)
    ws = wb["YamlBuild"]
    for row in ws.iter_rows(min_row=2):
        if row[2].value == "on_voltage_v":
            row[3].value = "999"          # above maximum 60
    wb.save(path)

    other = make_model(enabled=False)
    report = import_from_excel(other, path)
    assert not report.applied
    assert any("above maximum" in e for e in report.errors)


def test_excel_import_missing_sheet(tmp_path):
    """A workbook without the expected sheet is rejected cleanly."""
    from openpyxl import Workbook
    path = str(tmp_path / "other.xlsx")
    wb = Workbook()
    wb.save(path)
    report = import_from_excel(make_model(), path)
    assert not report.applied
    assert any("missing worksheet" in e for e in report.errors)


# ---------------------------------------------------------------------------
# publishing: naming / content / archive / compare
# ---------------------------------------------------------------------------


def test_plan_filename_rules():
    """The fixed naming (unified with the project Save-as name):
    [Part#]_[Core ID]_[Batch#]_rev_<ver>_<Kind>."""
    model = make_model()
    name = plan_filename(model, "draft")
    assert name == ("MTK12345_IMXRT700_MP-(Production)"
                    "_rev_1.0.0_Draft.yaml")
    final = plan_filename(model, "final")
    assert final == ("MTK12345_IMXRT700_MP-(Production)"
                     "_rev_1.0.0_Final.yaml")
    parsed = parse_plan_name(name)
    assert parsed == {"part": "MTK12345", "core": "IMXRT700",
                      "batch": "MP-(Production)", "version": "1.0.0",
                      "kind": "Draft"}
    assert parse_plan_name("random.yaml") is None
    # legacy Plan_..._build_... names no longer parse (best-effort)
    assert parse_plan_name(
        "Plan_IMXRT700_MTK12345_build_draft_v.1.0.0.yaml") is None


def test_plan_filename_requires_design_input():
    """Publishing without Core ID / Part # is rejected (fixed naming
    cannot be composed)."""
    model = YamlBuildModel()
    model.enable_all()
    with pytest.raises(ValueError):
        plan_filename(model, "draft")


def test_publish_draft_and_final(tmp_path):
    """Draft and Final files are written with correct header flags
    and the dynamic build version embedded."""
    model = make_model()
    draft = publish(model, "draft", tmp_path)
    final = publish(model, "final", tmp_path)
    assert draft.name.endswith("_rev_1.0.0_Draft.yaml")
    assert final.name.endswith("_rev_1.0.0_Final.yaml")
    doc = yaml.safe_load(final.read_text(encoding="utf-8"))
    assert doc["plan"]["kind"] == "final"
    assert doc["plan"]["locked"] is True
    assert doc["plan"]["core_id"] == "IMXRT700"
    assert doc["plan"]["built_with"]           # dynamic version suffix
    assert "modules" in doc["yaml_build"]


def test_archive_copy_and_compare(tmp_path):
    """Archiving writes a traceable copy per project (tenant-isolated
    archive, dynamic build suffix); compare produces a diff."""
    model = make_model()
    draft = publish(model, "draft", tmp_path)
    final = publish(model, "final", tmp_path)
    archived = archive_copy(draft, tmp_path, model.project_key())
    assert archived.exists()
    assert model.project_key() in str(archived)
    assert archived.parent.parent.name == "yamlbuild"
    diff = compare_plans(draft, final)
    assert "kind" in diff and "+draft" not in diff
    assert "-    \"kind\": draft" in diff or "kind: draft" in diff
    assert "final" in diff
