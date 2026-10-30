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


def test_enabled_wifi_is_the_only_emitted_step(page):
    """M44: setup.power_mode / use_fixture no longer injects a spine -
    the configured Wi-Fi row is the ONLY row in the run-time sequence
    (iron rule: never add steps the user did not configure)."""
    cfg = {"fct_test_config": {
        "dut_type": "linux",
        "wifi": {"enabled": True, "mode": "rssi_only", "ssid": "DUT-AP"}}}
    text = yaml.safe_dump(cfg, sort_keys=False)
    cases, errors = page._emit_fct_sequence(_params(text))
    assert errors == []
    names = [c["name"] for c in cases]
    assert names == ["Wi-Fi Scan / RSSI"]


def test_psu_fixture_setup_adds_nothing(page):
    """M44: the PSU / fixture setup node is preserved in the YAML but
    never adds Power On/Off or Fixture rows around the body."""
    cfg = {"fct_test_config": {
        "dut_type": "linux",
        "setup": {"power_mode": "psu", "use_fixture": True},
        "wifi": {"enabled": True, "mode": "rssi_only", "ssid": "DUT-AP"}}}
    text = yaml.safe_dump(cfg, sort_keys=False)
    cases, errors = page._emit_fct_sequence(_params(text))
    assert errors == []
    names = [c["name"] for c in cases]
    assert names == ["Wi-Fi Scan / RSSI"]
    ops = [c.get("op_params", {}).get("op") for c in cases]
    assert "Power On DUT" not in ops
    assert not any(str(o).startswith("Fixture ") for o in ops if o)


def test_parse_failure_returns_error(page):
    cases, errors = page._emit_fct_sequence(
        _params("fct_test_config: : :\n  - broken"))
    assert cases is None
    assert errors and "parse" in errors[0].lower()


def test_validation_failure_returns_error(page):
    # a serial console row with no port -> validation error (M36: no
    # master switch, the configured row itself activates the console)
    cfg = {"fct_test_config": {
        "dut_type": "linux",
        "console": {"port": "", "test_commands": [
            {"name": "Kernel check", "kind": "send", "send": "uname -a",
             "timeout": 5}]}}}
    text = yaml.safe_dump(cfg, sort_keys=False)
    cases, errors = page._emit_fct_sequence(_params(text))
    assert cases is None
    assert any("port" in e for e in errors)


def test_message_row_becomes_standard_op_case(page):
    """P3-B7: a Console '(message)' row publishes as the standard op
    kind (MessageYesNo / MessageOK) at its sequence position - the
    Test Work Flow page keeps showing the same op kinds it always
    did, so editing either side no longer overwrites the other."""
    cfg = {"fct_test_config": {
        "dut_type": "linux",
        "console": {"enabled": True, "port": "/dev/cu.test",
                    "test_commands": [
                        {"name": "Kernel check", "kind": "send",
                         "send": "uname -a", "timeout": 5},
                        {"name": "Swap DUT fixture", "kind": "message",
                         "dialog_style": "yesno", "timeout": 30},
                        {"name": "Ready check", "kind": "message",
                         "dialog_style": "ok", "timeout": 10}]}},
        "wifi": {"enabled": False}, "bluetooth": {"enabled": False}}
    text = yaml.safe_dump(cfg, sort_keys=False)
    cases, errors = page._emit_fct_sequence(_params(text))
    assert errors == []
    by_name = {c["name"]: c["kind"] for c in cases}
    # unified model: the visible name IS the step name (no keyword
    # artifact suffix) - ONE row per Console row
    assert by_name["Kernel check"] == "CapturefromConsole"
    assert by_name["Swap DUT fixture"] == "MessageYesNotoConsole"
    assert by_name["Ready check"] == "MessageOKtoConsole"
    # console message rows wait on the console channel first, then prompt
    for c in cases:
        if c["kind"] in ("MessageOKtoConsole", "MessageYesNotoConsole"):
            assert c["op_params"]["fct_step"]["channel"] == "ser1"
            assert c["op_params"]["fct_step"]["params"]["console_dialog"] is True
