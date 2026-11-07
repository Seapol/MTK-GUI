# -*- coding: utf-8 -*-
"""M83 C10: instrument params are the single source (Equipment keys)."""
from __future__ import annotations

import pytest

from mtkgui.engine.instruments import (
    INSTRUMENT_MODEL_DEFAULTS,
    RealGateway,
    normalize_instrument_key,
    normalize_instrument_list,
)
from mtkgui.engine.yaml_validation import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    validate_project_yaml,
)

EQUIPMENT = {
    "daq973a": {"fields": {"Address": "GPIB0::9::INSTR"},
                "params": {"Scan speed (ch/s)": "450",
                           "Timeout (ms)": "2000", "NPLC": "1.0"}},
    "u2355a": {"fields": {"Address": "USB0::U2355A::INSTR"},
               "params": {"Sample rate (kSa/s)": "20",
                          "Range (V)": "10", "Averaging": "1"}},
    "psu": {"fields": {"Address": "TCPIP0::192.168.1.20::inst0",
                       "Model": "Keysight N5747A DC Power Supply"},
            "params": {"Voltage set (V)": "5.0",
                       "Current limit (A)": "1.0", "OVP (V)": "15.0"}},
    "jlink": {"fields": {"Address": "JLinkExe"}},
    "measure_channels": {"TP_P01": "101"},
}


def _gateway():
    return RealGateway(EQUIPMENT)


def test_m83_init_pushes_equipment_params(scripted_drivers):
    gw = _gateway()
    before = len(scripted_drivers._record.calls)
    out = gw._op_instruments({"type": "instruments",
                              "instruments": ["daq973a", "psu"]}, reset=False)
    calls = scripted_drivers._record.calls[before:]
    assert out.verdict == "Done"
    assert ("set_v", 5.0) in calls and ("set_i", 1.0) in calls
    assert any("pushed" in line for line in out.lines)
    assert any("'Scan speed (ch/s)' has no SCPI writer — not pushed"
               in line for line in out.lines)


def test_m83_init_without_params_resets_and_logs(scripted_drivers):
    equipment = {"daq973a": {"fields": {"Address": "GPIB0::9::INSTR"}}}
    gw = RealGateway(equipment)
    before = len(scripted_drivers._record.calls)
    out = gw._op_instruments({"type": "instruments",
                              "instruments": ["daq973a"]}, reset=False)
    assert out.verdict == "Done"
    assert any("no params configured in Equipment — reset only" in line
               for line in out.lines)
    assert ("reset", "DAQ973A") in scripted_drivers._record.calls[before:]


def test_m83_init_reports_error_naming_instrument(scripted_drivers,
                                                  monkeypatch):
    mod = scripted_drivers

    class _BoomPSU(mod.N5747ADriver):
        def set_voltage(self, volts):
            raise mod.InstrumentError("boom")

    monkeypatch.setattr(mod, "N5747ADriver", _BoomPSU)
    gw = _gateway()
    out = gw._op_instruments({"type": "instruments",
                              "instruments": ["psu"]}, reset=False)
    assert out.verdict == "Error"
    assert any("Keysight N5747A DC Power Supply: set_voltage failed: boom"
               in line for line in out.lines)


def test_m83_reset_resets_every_selected_instrument(scripted_drivers):
    gw = _gateway()
    before = len(scripted_drivers._record.calls)
    out = gw._op_instruments({"type": "reset",
                              "instruments": ["daq973a", "u2355a", "psu"]},
                             reset=True)
    calls = scripted_drivers._record.calls[before:]
    assert out.verdict == "Done"
    assert ("reset", "DAQ973A") in calls
    assert ("reset", "U2355A") in calls
    assert ("reset", "PSU") in calls
    # reset never pushes setpoints
    assert not any(call[0] in ("set_v", "set_i") for call in calls)


def test_m83_reset_reports_done_or_error_only(scripted_drivers):
    gw = _gateway()
    ok = gw._op_instruments({"type": "reset", "instruments": ["psu"]},
                            reset=True)
    bad = gw._op_instruments({"type": "reset", "instruments": ["mystery"]},
                             reset=True)
    assert ok.verdict == "Done"
    assert bad.verdict == "Error"


def test_m83_unknown_instrument_key_is_error(scripted_drivers):
    gw = _gateway()
    out = gw._op_instruments({"type": "instruments",
                              "instruments": ["mystery"]}, reset=False)
    assert out.verdict == "Error"
    assert any("unknown instrument 'mystery'" in line for line in out.lines)
    assert any("daq973a / u2355a / psu / jlink" in line
               for line in out.lines)


def test_m83_power_on_reads_equipment_psu_params(scripted_drivers):
    gw = _gateway()
    before = len(scripted_drivers._record.calls)
    out = gw._op_power({"type": "power", "state": "on"})
    calls = scripted_drivers._record.calls[before:]
    assert out.verdict == "Done"
    assert ("set_v", 5.0) in calls and ("set_i", 1.0) in calls


def test_m83_model_mismatch_is_warning(scripted_drivers):
    equipment = {"psu": {
        "fields": {"Address": "TCPIP0::x", "Model": "Keysight N5747A"},
        "params": {"Voltage set (V)": "5.0", "Current limit (A)": "1.0"}}}
    gw = RealGateway(equipment)
    out = gw._op_instruments({"type": "instruments",
                              "instruments": ["psu"]}, reset=False)
    assert out.verdict == "Done"          # warning only, never Error
    assert any("does not match *IDN?" in line for line in out.lines)


def test_m83_measure_row_reads_nplc_from_params(scripted_drivers):
    gw = _gateway()
    out = gw.measure_row("Power Voltage", "TP_P01", "V", "3.2", "3.4")
    assert out.verdict in ("PASS", "FAIL")
    assert any("'NPLC' has no SCPI writer — not pushed" in line
               for line in out.lines)


def test_m83_legacy_abbr_is_normalised_to_equipment_key(scripted_drivers):
    assert normalize_instrument_list(["DAQM", "DAQ", "PSU"]) == \
        ["daq973a", "u2355a", "psu"]
    assert normalize_instrument_key("DAQM") == "daq973a"
    assert normalize_instrument_key("mystery") is None
    gw = _gateway()
    out = gw._op_instruments({"type": "instruments",
                              "instruments": ["DAQM"]}, reset=False)
    assert out.verdict == "Done"
    assert not any("unknown instrument" in line for line in out.lines)
    doc = {"test_workflow": {"fct_test_cases": [
        {"name": "Init Instruments", "kind": "op",
         "op_params": {"type": "instruments", "instruments": ["DAQM"]}}]}}
    issues = validate_project_yaml(doc)
    assert any(issue.severity == SEVERITY_WARNING
               and "legacy instrument abbreviations" in issue.message
               for issue in issues)
    # an unmapped value blocks the build
    doc["test_workflow"]["fct_test_cases"][0]["op_params"]["instruments"] = \
        ["mystery"]
    issues = validate_project_yaml(doc)
    assert any(issue.severity == SEVERITY_ERROR
               and "unknown instrument 'mystery'" in issue.message
               for issue in issues)


def test_m83_param_without_scpi_writer_warns(scripted_drivers):
    gw = _gateway()
    out = gw._op_instruments({"type": "instruments",
                              "instruments": ["daq973a"]}, reset=False)
    text = " ".join(out.lines)
    assert "'Scan speed (ch/s)' has no SCPI writer" in text
    assert "'Timeout (ms)' has no SCPI writer" in text
    assert "'NPLC' has no SCPI writer" in text
    assert INSTRUMENT_MODEL_DEFAULTS["daq973a"] in text


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
