# -*- coding: utf-8 -*-
"""Load current yaml (user direction 2026-10-13).

The "Load current yaml" button derives the ICT / FCT sequences from
the CURRENT Yaml Build model and pushes them into the Test Work Flow
page.  Readiness gate: without a usable ICT configuration (parsed +
fully allocated nets, rails/clocks/gpios enabled) or FCT
configuration (configured fct_test_config) a warning is shown and
NOTHING is executed."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.main_window import MainWindow  # noqa: E402

MainWindow.__test__ = False


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp):
    w = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    yield w
    w.close()
    w.deleteLater()


def _make_ict_ready(window):
    """Parsed nets + full channel allocation + enabled build modules
    (the blocks 01-04 readiness state)."""
    model = window.yaml_build_page.model
    model.imported["testable_nets"] = {
        "3V3": {"category": "Power", "members": ["U1.5"]},
        "CLK_24M": {"category": "Clock", "members": ["U1.10"]},
    }
    model.set_channel_allocation({
        "power": [{"net": "3V3", "impedance": "DAQM908A #1 CH101",
                   "power_rails": "U2355A AI01",
                   "voltage": "DAQM908A #1 CH101"}],
        "clock": [{"net": "CLK_24M", "se_clock_hz": "DAQM907A TOT"}],
        "gpio": [],
    })
    window.yaml_build_page.channel_alloc.refresh_from_model()


def test_load_blocked_without_configuration(window, monkeypatch):
    """Fresh model: nothing usable -> the warning box shows, nothing
    is loaded (empty ICT table, no 'Current yaml loaded' log line)."""
    warnings = []
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.warning",
        lambda *a, **k: warnings.append(k[1] if len(k) > 1 else a[1]))
    window._load_current_yaml()
    assert warnings == ["Load current yaml"]
    # nothing generated: no ICT test rows (the placeholder op row of
    # a fresh page is fine)
    steps = window.workflow_page.ict_steps
    assert not any("Impedance" in s[1] or "Clock Hz" in s[1]
                   for s in steps)
    logged = window.event_log.toPlainText()
    assert "Current yaml loaded" not in logged


def test_load_pushes_ict_sequence_and_jumps(window):
    """With blocks 01-04 ready the ICT sequence (tests + standard
    operations) lands in the ICT table and the GUI jumps to the Test
    Work Flow tab."""
    _make_ict_ready(window)
    window._load_current_yaml()
    assert window.tabs.currentWidget() is window.workflow_page
    ict_steps = window.workflow_page.ict_steps
    names = [s[1] for s in ict_steps]
    # standard operations around the generated tests
    assert "Init Instruments" in names
    assert any(n.startswith("Static Impedance") for n in names)
    assert any(n.startswith("Power Voltage") for n in names)
    assert any(n.startswith("Clock Hz") for n in names)
    # the derived limits: P3V3-style net name absent, but the power
    # rails channel rows carry the sequence; row count = 4 ops before
    # + 2 tests + 1 op mid + 1 test + 4 ops after
    assert len(ict_steps) == 12


def test_load_current_yaml_button_wired(window, monkeypatch):
    """The page "Load current yaml" button routes into the main
    window slot (the same behavior as the File-menu style slot)."""
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.warning",
        lambda *a, **k: None)      # the fresh-model gate warns (mocked)
    clicked = []
    window.yaml_build_page.load_yaml_requested.connect(
        lambda: clicked.append(True))
    window.yaml_build_page.btn_load_yaml.click()
    assert clicked == [True]
