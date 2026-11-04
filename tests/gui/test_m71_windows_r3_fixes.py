# -*- coding: utf-8 -*-
"""M71: Windows R3 fixes.

F1  Console "Add Serial" adds a channel row AND opens the serial
    connection dialog (cancel removes the just-added row again).
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
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

import mtkgui.widgets.multi_console as mc_mod  # noqa: E402
from mtkgui.engine import fct_templates  # noqa: E402
from mtkgui.engine.steps import (  # noqa: E402
    OP_STEPS,
    WIFI_CONNECT_OP,
    op_status_lines,
    op_summary,
)
from mtkgui.equipment_page import (  # noqa: E402
    GROUP_FIELDS,
    NETWORK_FIELDS,
)
from mtkgui.widgets.multi_console import (  # noqa: E402
    APP_NAME,
    APP_ORG,
    MAX_SERIAL,
    MultiConsoleWidget,
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


class _FakeSerialDialog:
    """Stands in for SerialConfigDialog (records construction + result)."""

    instances: list = []
    accepted = True
    payload: dict = {}

    def __init__(self, parent, params=None):
        self.seen_params = dict(params or {})
        _FakeSerialDialog.instances.append(self)

    def exec(self):
        return (QDialog.DialogCode.Accepted if _FakeSerialDialog.accepted
                else QDialog.DialogCode.Rejected)

    def get_params(self):
        return dict(_FakeSerialDialog.payload or self.seen_params)


@pytest.fixture()
def serial_dialog(monkeypatch):
    _FakeSerialDialog.instances = []
    _FakeSerialDialog.accepted = True
    _FakeSerialDialog.payload = {}
    monkeypatch.setattr(mc_mod, "SerialConfigDialog", _FakeSerialDialog)
    return _FakeSerialDialog


def _keys(widget):
    return list(widget.channels)


# ------------------------------------------- F1 Add Serial dialog + row
def test_add_serial_click_opens_the_dialog_and_keeps_the_row(
        qapp, console_settings, serial_dialog):
    _FakeSerialDialog.payload = {"port": "COM7"}
    widget = MultiConsoleWidget()
    try:
        assert _keys(widget) == ["ser1"]
        widget.btn_add_serial.click()
        assert _keys(widget) == ["ser1", "ser2"]
        assert len(_FakeSerialDialog.instances) == 1
        assert _FakeSerialDialog.instances[0].seen_params["port"] is None
        assert widget.channels["ser2"]["params"]["port"] == "COM7"
    finally:
        widget.deleteLater()


def test_add_serial_cancel_removes_the_new_row(
        qapp, console_settings, serial_dialog):
    _FakeSerialDialog.accepted = False
    widget = MultiConsoleWidget()
    try:
        widget.btn_add_serial.click()
        assert _keys(widget) == ["ser1"]
        assert widget._next_serial_number() == 2
    finally:
        widget.deleteLater()


def test_add_serial_works_after_a_project_with_empty_console(
        qapp, console_settings, serial_dialog):
    # project load with "console: []" clears every channel and the
    # project applier re-adds the default serial row
    widget = MultiConsoleWidget()
    try:
        widget.clear_channels()
        assert _keys(widget) == []
        widget.add_serial()
        assert _keys(widget) == ["ser1"]
        widget.btn_add_serial.click()
        assert _keys(widget) == ["ser1", "ser2"]
        assert len(_FakeSerialDialog.instances) == 1
    finally:
        widget.deleteLater()


def test_add_serial_respects_the_max_serial_cap(
        qapp, console_settings, serial_dialog):
    widget = MultiConsoleWidget()
    try:
        while len(widget._serial_numbers) < MAX_SERIAL:
            assert widget.add_serial() is not None
        widget.btn_add_serial.click()
        assert len(widget.channels) == MAX_SERIAL
        assert _FakeSerialDialog.instances == []
    finally:
        widget.deleteLater()


def test_add_serial_respects_operator_permissions(
        qapp, console_settings, serial_dialog):
    widget = MultiConsoleWidget()
    try:
        widget.apply_permissions({}, False)
        assert not widget.btn_add_serial.isEnabled()
        assert widget.add_serial_interactive() is None
        assert _keys(widget) == ["ser1"]
        assert _FakeSerialDialog.instances == []
        # manage_channels without edit_serial_params: the row is added
        # but the parameter dialog stays closed
        widget.apply_permissions({"manage_channels": True}, False)
        widget.btn_add_serial.click()
        assert _keys(widget) == ["ser1", "ser2"]
        assert _FakeSerialDialog.instances == []
    finally:
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


def test_wifi_connect_defaults_are_mlan0():
    assert OP_STEPS[WIFI_CONNECT_OP]["iface"] == "mlan0"
    assert op_summary({"type": "wifi_connect"}) == "mlan0"
    assert op_status_lines(WIFI_CONNECT_OP, {})[0].startswith(
        "serial console mlan0:")


def test_equipment_dut_interface_defaults_are_mlan0():
    dut_wifi = dict((key, default)
                    for key, _label, default in GROUP_FIELDS[("dut", "wifi")])
    assert dut_wifi["interface"] == "mlan0"
    network = dict((key, default) for key, _label, default in NETWORK_FIELDS)
    assert network["wifi_dut_iface"] == "mlan0"


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
