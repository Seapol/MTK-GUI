# -*- coding: utf-8 -*-
"""M83 C9: Operation rows - passive power carrier, dead field removal."""
from __future__ import annotations

import pytest

from mtkgui.engine.instruments import RealGateway
from mtkgui.engine.steps import OP_STEPS
from mtkgui.engine.yaml_validation import (
    LEGACY_OP_WAIT_MSG,
    LEGACY_POWER_SETPOINT_MSG,
    SEVERITY_WARNING,
    validate_project_yaml,
)

EQUIPMENT = {
    "psu": {"fields": {"Address": "TCPIP0::192.168.1.20::inst0"},
            "params": {"Voltage set (V)": "5.0",
                       "Current limit (A)": "1.0", "OVP (V)": "15.0"}},
}


def _gateway():
    return RealGateway(EQUIPMENT)


def _calls(mod) -> list:
    return list(mod._record.calls)


def _new_calls(mod, since: int) -> list:
    return _calls(mod)[since:]


def test_m83_power_off_never_sets_setpoints(scripted_drivers):
    gw = _gateway()
    before = len(_calls(scripted_drivers))
    out = gw._op_power({"type": "power", "state": "off"},
                       name="Power Off DUT")
    calls = _new_calls(scripted_drivers, before)
    assert out.verdict == "Done"
    assert ("out_off",) in calls
    assert not any(call[0] in ("set_v", "set_i", "out_on") for call in calls)


def test_m83_power_off_drops_legacy_voltage_on_save(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from mtkgui.gui.steps_editor import edit_op_step_dialog

    monkeypatch.setattr(QDialog, "exec",
                        lambda _dlg: QDialog.DialogCode.Accepted)
    legacy = {"type": "power", "voltage": 5.0, "current": 1.0}
    result = edit_op_step_dialog(None, "Power Off DUT", legacy, True, 100, 5000)
    assert result is not None
    _name, params, _enable, _wait, _timeout = result
    assert params == {"type": "power", "state": "off"}
    assert "voltage" not in params and "current" not in params


def test_m83_power_on_state_comes_from_catalog_state_key(scripted_drivers):
    assert OP_STEPS["Power On DUT"] == {"type": "power", "state": "on"}
    assert OP_STEPS["Power Off DUT"] == {"type": "power", "state": "off"}
    # a state-only row (no name hint) still turns the supply ON
    gw = _gateway()
    before = len(_calls(scripted_drivers))
    out = gw._op_power({"type": "power", "state": "on"})
    calls = _new_calls(scripted_drivers, before)
    assert out.verdict == "Done"
    assert ("out_on",) in calls and ("set_v", 5.0) in calls


def test_m83_power_on_sets_from_equipment_params(scripted_drivers):
    gw = _gateway()
    before = len(_calls(scripted_drivers))
    out = gw._op_power({"type": "power", "state": "on"},
                       name="Power On DUT")
    calls = _new_calls(scripted_drivers, before)
    assert out.verdict == "Done"
    assert ("set_v", 5.0) in calls
    assert ("set_i", 1.0) in calls
    assert ("out_on",) in calls
    assert any("equipment.psu.params" in line for line in out.lines)


def test_m83_legacy_voltage_row_is_classified_with_warning(scripted_drivers):
    gw = _gateway()
    before = len(_calls(scripted_drivers))
    out = gw._op_power({"type": "power", "voltage": 5.0, "current": 1.0},
                       name="Power On DUT")
    calls = _new_calls(scripted_drivers, before)
    assert out.verdict == "Done"
    assert ("out_on",) in calls          # classified ON by the name
    assert any("legacy power row carries voltage/current" in line
               for line in out.lines)
    # and the load-time rule reports the same legacy pair
    doc = {"test_workflow": {"fct_test_cases": [
        {"name": "Power On DUT", "kind": "op",
         "op_params": {"type": "power", "voltage": 5.0, "current": 1.0}}]}}
    warnings = [issue for issue in validate_project_yaml(doc)
                if issue.severity == SEVERITY_WARNING]
    assert any(LEGACY_POWER_SETPOINT_MSG in issue.message
               for issue in warnings)


def test_m83_op_wait_timeout_ignored():
    import yaml as _yaml
    step = {"type": "Operation", "name": "Power On DUT",
            "op_params": {"type": "power", "state": "on"},
            "op_wait_ms": 500, "op_timeout_ms": 9000}
    text = _yaml.safe_dump({"fct": {"steps": [step]}}, sort_keys=False)
    doc = {"yaml_build_state": {"modules": {"fct_build": {"params": {
        "fct_steps_yaml": text}}}},
        "test_workflow": {"fct_test_cases": []}}
    warnings = [issue for issue in validate_project_yaml(doc)
                if issue.severity == SEVERITY_WARNING]
    assert any(LEGACY_OP_WAIT_MSG in issue.message for issue in warnings)


def test_m83_catalog_power_rows_carry_no_voltage():
    for name in ("Power On DUT", "Power Off DUT"):
        entry = OP_STEPS[name]
        assert "voltage" not in entry and "current" not in entry


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
