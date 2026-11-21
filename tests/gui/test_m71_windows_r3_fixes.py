# -*- coding: utf-8 -*-
"""M71: Windows R3 fixes.

F2  DUT-side Wi-Fi interface default is mlan0 (NXP mwifiex / moal);
    the Host PC adapter keeps its wlan0 semantics.
F3  A legacy Wifi_Scan row without scan_via loads as dut_console
    (matching the engine default), not as a Host-side scan.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

import yaml  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine import fct_templates  # noqa: E402
from mtkgui.widgets.multi_console import (  # noqa: E402
    APP_NAME,
    APP_ORG,
)
from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def console_settings():
    """Isolate the console_window/<key> QSettings keys per test."""
    settings = QSettings(APP_ORG, APP_NAME)
    settings.clear()
    yield settings
    settings.clear()


@pytest.fixture()
def page(qapp):
    widget = YamlBuildPage()
    yield widget
    widget.deleteLater()


# ------------------------------- F2 DUT interface defaults = mlan0
def test_wifi_scan_template_has_no_wlan0():
    text = Path(fct_templates.template_path(
        fct_templates.TEMPLATE_WIFI_SCAN)).read_text(encoding="utf-8")
    assert "wlan0" not in text
    assert "iw dev mlan0 info" in text
    assert "ip -4 addr show mlan0" in text


def test_driver_probe_fallback_interface_is_mlan0():
    cmd = fct_templates.load_template_commands(
        fct_templates.TEMPLATE_WIFI_SCAN,
        {"wifi_driver_load_cmd": "modprobe moal"})[0]
    assert "iw dev mlan0 info" in cmd.send


# ------------------------- F3 legacy Wifi_Scan default = dut_console
def test_legacy_wifi_scan_without_scan_via_loads_as_dut_console(page):
    steps = {"fct": {"dut_type": "linux", "steps": [{
        "type": "Wifi_Scan", "name": "Wi-Fi Scan", "rf_subtest": "scan",
        "rssi_min": -70, "dut_rssi_min": -70,
        "override": {"ap_ssid": "Factory-AP", "dut_ssid": "DUT-AP"}}]}}
    cases, errors = page._emit_fct_sequence(
        {"fct_steps_yaml": yaml.safe_dump(steps, sort_keys=False)})
    assert errors == []
    # the DUT-console verdict name (a Host-side scan keeps the plain
    # "Wi-Fi Scan / RSSI" name)
    assert cases[0]["name"] == "Wi-Fi Scan / RSSI (DUT console)"
