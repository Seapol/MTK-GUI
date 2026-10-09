# -*- coding: utf-8 -*-
"""P3-B5: Build FCT Test Work Flow OK -> apply/save behaviour.

Mirrors the ICT builder: accepting the FCT block must always reach the
apply/save prompt. An all-disabled FCT is a valid ICT-only project (zero
cases); parse/validation failures are returned as explicit errors so the
GUI can show them instead of silently ignoring the OK click.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

import yaml

from mtkgui.yaml_build_page import YamlBuildPage


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def page(qapp):
    return YamlBuildPage()


def _params(config_yaml_text):
    return {"fct_test_config_yaml": config_yaml_text}


def test_empty_text_is_valid_ict_only(page):
    # no FCT config at all -> zero cases, no error (ICT-only project)
    cases, errors = page._emit_fct_sequence({})
    assert errors == []
    assert cases == []


def test_all_disabled_config_is_valid_ict_only(page):
    text = yaml.safe_dump({"fct_test_config": {}}, sort_keys=False)
    cases, errors = page._emit_fct_sequence(_params(text))
    assert errors == []
    assert cases == []


def test_enabled_wifi_wraps_manual_power_spine(page):
    # default setup is manual adapter/USB power: on-prompt, body,
    # "FCT done.", off-prompt
    cfg = {"fct_test_config": {
        "dut_type": "linux",
        "wifi": {"enabled": True, "mode": "rssi_only"}}}
    text = yaml.safe_dump(cfg, sort_keys=False)
    cases, errors = page._emit_fct_sequence(_params(text))
    assert errors == []
    names = [c["name"] for c in cases]
    assert "FCT done." in names
    assert "Connect the power adapter" in names[0]
    assert "Disconnect the power adapter" in names[-1]
    done_idx = names.index("FCT done.")
    assert done_idx < len(names) - 1


def test_psu_power_uses_power_on_off_ops(page):
    cfg = {"fct_test_config": {
        "dut_type": "linux",
        "setup": {"power_mode": "psu", "use_fixture": True},
        "wifi": {"enabled": True, "mode": "rssi_only"}}}
    text = yaml.safe_dump(cfg, sort_keys=False)
    cases, errors = page._emit_fct_sequence(_params(text))
    assert errors == []
    names = [c["name"] for c in cases]
    # fixture clamp/lock before power-on, unlock/release at the very end
    assert names[:3] == ["Fixture Clamp Down", "Fixture Lock",
                         "Fixture E-Stop Healthy"]
    assert names[3] == "Power On DUT"
    assert names[-2:] == ["Fixture Unlock", "Fixture Release"]
    assert "Power Off DUT" in names
    # op rows carry the op marker
    ops = [c.get("op_params", {}).get("op") for c in cases]
    assert "Power On DUT" in ops and "Fixture Clamp Down" in ops


def test_parse_failure_returns_error(page):
    cases, errors = page._emit_fct_sequence(
        _params("fct_test_config: : :\n  - broken"))
    assert cases is None
    assert errors and "parse" in errors[0].lower()


def test_validation_failure_returns_error(page):
    # console enabled but no serial port -> validation error
    cfg = {"fct_test_config": {
        "dut_type": "linux",
        "console": {"enabled": True, "port": ""}}}
    text = yaml.safe_dump(cfg, sort_keys=False)
    cases, errors = page._emit_fct_sequence(_params(text))
    assert cases is None
    assert any("port" in e for e in errors)
