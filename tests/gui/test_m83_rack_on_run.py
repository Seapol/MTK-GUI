# -*- coding: utf-8 -*-
"""M83 C14: the Tools > Set all instruments submenu is gone and the
Run press opens the instrument rack itself (no manual pre-click)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from mtkgui.main_window import MainWindow  # noqa: E402
from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402

MainWindow.__test__ = False
TestWorkFlowPage.__test__ = False

_DAQ_ADDRESS = "TCPIP0::1.2.3.4::inst0::INSTR"
_PSU_ADDRESS = "USB0::123::INSTR"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def window(qapp):
    win = MainWindow()
    yield win
    win.close()


@pytest.fixture()
def page(qapp):
    p = TestWorkFlowPage()
    yield p
    p.deleteLater()


class _FakeOutcome:
    def __init__(self, verdict="Done", lines=None):
        self.verdict = verdict
        self.lines = list(lines or [])


class _FakeGateway:
    """Scripted RealGateway: records every call, no hardware."""

    def __init__(self, configs=None, fail_key=None):
        self.configs = dict(configs or {})
        self.fail_key = fail_key
        self.calls: list = []
        self.closed = False

    def execute_op(self, name, params):
        self.calls.append((name, dict(params or {})))
        key = (params or {}).get("instruments", [""])[0]
        if key == self.fail_key:
            return _FakeOutcome(
                "Error", [f"{key} init failed: connection refused"])
        return _FakeOutcome("Done", [f"{key} init OK: FAKE-IDN"])

    def close(self):
        self.closed = True


def _fake_gateway(monkeypatch, fail_key=None):
    made: list = []

    def _factory(configs=None):
        gw = _FakeGateway(configs, fail_key=fail_key)
        made.append(gw)
        return gw

    monkeypatch.setattr("mtkgui.engine.instruments.RealGateway", _factory)
    return made


def _ready_page(page, configs):
    """Pass the Run gates without starting the engine."""
    page.project_path = "dummy.yaml"
    page.set_overall_en([True, False])
    page.ict_steps = [("test", "Static Impedance - 3V3", "Ω",
                       "—", "30", "—")]
    page.equipment_configs_provider = lambda: configs


# ------------------------------------------------------------ menu gone
def test_m83_tools_menu_has_no_set_all_instruments(window):
    tools = [a for a in window.menuBar().actions()
             if a.text() == "Tools"][0]
    texts = [a.text() for a in tools.menu().actions()]
    assert not any("set all" in t.lower() for t in texts)
    assert not hasattr(window, "act_connect_all")
    assert not hasattr(window, "act_disconnect_all")
    assert not hasattr(window, "act_reset_all")
    assert not hasattr(window, "act_test_all")


# ------------------------------------------------- run-start acquisition
def test_m83_run_opens_the_rack_when_no_session_exists(page, monkeypatch):
    made = _fake_gateway(monkeypatch)
    logs: list = []
    page.log_line.connect(logs.append)
    _ready_page(page, {
        "daq973a": {"fields": {"Address": _DAQ_ADDRESS}},
        "psu": {"fields": {"Address": _PSU_ADDRESS}},
    })
    monkeypatch.setattr(page, "_pretest", lambda: False)
    page.start_run()

    assert len(made) == 1
    gw = made[0]
    assert gw.configs["daq973a"]
    assert [c[1]["instruments"] for c in gw.calls] == \
        [["daq973a"], ["psu"]]
    assert page.gateway is gw
    assert any("Keysight DAQ973A" in ln and "connected" in ln
               for ln in logs)
    assert any("instruments: opened 2 instrument(s)" in ln for ln in logs)


def test_m83_run_reuses_an_existing_session(page, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("RealGateway must not be created")

    monkeypatch.setattr("mtkgui.engine.instruments.RealGateway", _boom)
    logs: list = []
    page.log_line.connect(logs.append)
    page.gateway = SimpleNamespace(close=lambda: None)
    _ready_page(page, {"daq973a": {"fields": {"Address": _DAQ_ADDRESS}}})
    monkeypatch.setattr(page, "_pretest", lambda: False)
    page.start_run()

    assert any("reusing the open session" in ln for ln in logs)


def test_m83_run_refuses_to_start_when_an_instrument_fails(
        page, monkeypatch):
    made = _fake_gateway(monkeypatch, fail_key="psu")
    warnings: list = []
    monkeypatch.setattr(
        "mtkgui.test_workflow_page.QMessageBox.warning",
        lambda *a, **k: warnings.append(a[2]))
    _ready_page(page, {
        "daq973a": {"fields": {"Address": _DAQ_ADDRESS}},
        "psu": {"fields": {"Address": _PSU_ADDRESS}},
    })
    monkeypatch.setattr(page, "_pretest", lambda: False)
    page.start_run()

    assert len(made) == 1
    assert made[0].closed is True
    assert page.gateway is None
    assert page.run_state != "running"
    assert len(warnings) == 1
    assert "Cannot open the instrument rack" in warnings[0]
    assert "connection refused" in warnings[0]
    assert "Equipment" in warnings[0]


def test_m83_run_start_reports_each_instrument_once(page, monkeypatch):
    made = _fake_gateway(monkeypatch)
    logs: list = []
    page.log_line.connect(logs.append)
    _ready_page(page, {
        "daq973a": {"fields": {"Address": _DAQ_ADDRESS}},
        "psu": {"fields": {"Address": _PSU_ADDRESS}},
    })
    monkeypatch.setattr(page, "_pretest", lambda: False)
    page.start_run()

    assert len(made) == 1
    connected_lines = [ln for ln in logs if "connected (*IDN?" in ln]
    assert len(connected_lines) == 2
    assert any("Keysight DAQ973A" in ln for ln in connected_lines)
    assert any("Keysight N5747A" in ln for ln in connected_lines)


# ------------------------------------------------- instruments panel
def test_m83_instruments_panel_connect_publishes_the_gateway(
        qapp, monkeypatch):
    from mtkgui.gui.yamlbuild.instruments_panel import InstrumentsPanel

    made = _fake_gateway(monkeypatch)
    page = QWidget()
    page._tools_gateway = None
    page.equipment_page = SimpleNamespace(
        configs={"daq973a": {"fields": {"Address": _DAQ_ADDRESS}}})
    page.workflow_page = SimpleNamespace(gateway=None, mode="Real")
    page.mode = "Real"
    panel = InstrumentsPanel(parent=page)
    panel._rows["daq_visa"]["btn"].click()

    assert page._tools_gateway is made[0]
    assert page.workflow_page.gateway is made[0]
    panel.deleteLater()
    page.deleteLater()


# ------------------------------------------------------------ LEDs
def test_m83_instrument_leds_follow_the_run_start_connect(
        window, monkeypatch):
    _fake_gateway(monkeypatch)
    window.mode = "Real"
    window.equipment_page.configs = {
        "daq973a": {"fields": {"Address": _DAQ_ADDRESS}},
        "psu": {"fields": {"Address": _PSU_ADDRESS}},
    }
    window.workflow_page.gateway = None
    assert window.workflow_page._ensure_rack_for_run() is True
    assert window.instr_status.states["DAQM"] == "connected"
    assert window.instr_status.states["PSU"] == "connected"
    window.workflow_page._release_rack()


def test_m83_gateway_is_closed_on_stop(page, monkeypatch):
    gw = _FakeGateway({"psu": {"fields": {"Address": _PSU_ADDRESS}}})
    page.gateway = gw
    logs: list = []
    page.log_line.connect(logs.append)
    monkeypatch.setattr(page._runner, "abort", lambda: None)
    page.stop_run()

    assert gw.closed is True
    assert page.gateway is None
    assert any("instruments: closed" in ln for ln in logs)


# ------------------------------------------------------------ docs
def test_m83_help_docs_mention_no_set_all_instruments():
    docs = Path(__file__).resolve().parents[2] / "docs" / "help"
    assert docs.is_dir()
    offenders = [p.name for p in docs.glob("*.md")
                 if "set all instruments" in p.read_text(
                     encoding="utf-8").lower()]
    assert offenders == []
    joined = "\n".join(p.read_text(encoding="utf-8")
                       for p in docs.glob("*.md")).lower()
    assert "when you press run" in joined
