# -*- coding: utf-8 -*-
"""Instrument connection state truthfulness (user report).

The status-bar Instruments LEDs must follow the Equipment page
connect / disconnect, and the connect state must SURVIVE closing and
reopening the instrument dialog (it used to die with the modal
dialog, and the LEDs were force-set green everywhere)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from mtkgui.equipment_page import EquipmentPage  # noqa: E402
from mtkgui.main_window import MainWindow  # noqa: E402

ROLE_SUPERVISOR = "Supervisor"
FIXTURE_ATE = "ATE"

MainWindow.__test__ = False


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    p = EquipmentPage()
    p.virtual_mode = True
    yield p
    p.deleteLater()


@pytest.fixture()
def window(qapp):
    w = MainWindow(role=ROLE_SUPERVISOR, mode="Real", fixture=FIXTURE_ATE)
    yield w
    w.close()
    w.deleteLater()


def _connect_dialog(page, key, monkeypatch, connected=True):
    """Open the instrument dialog; connect (virtual, immediate) or not."""
    page.virtual_mode = True
    monkeypatch.setattr(
        "mtkgui.equipment_page.QTimer.singleShot",
        lambda _ms, fn: fn() if connected else None)
    # no exec loop: click Connect directly, then close
    captured = {}

    orig_exec = QDialog.exec

    def fake_exec(self):
        captured["dlg"] = self
        if connected and self._virtual:
            self._connect()
        return 0

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    block = page.blocks[key]
    page._on_block_clicked(block)
    monkeypatch.setattr(QDialog, "exec", orig_exec)
    return captured["dlg"]


def test_connect_state_survives_dialog_reopen(page, monkeypatch):
    """Connect on DAQ, close, reopen: the dialog restores Connected
    (was always Disconnected - the state died with the dialog)."""
    dlg = _connect_dialog(page, "u2355a", monkeypatch)
    assert dlg._connected is True
    assert page._instrument_connections["u2355a"] is True

    dlg2 = _connect_dialog(page, "u2355a", monkeypatch, connected=False)
    assert dlg2._connected is True          # restored from page state
    assert dlg2._conn_state.text() == "Connected (virtual)"


def test_rails_derived_from_channel_allocation(window, monkeypatch):
    """User report: 'no rails defined' although Channel Allocation had
    U2355A AI assignments - the rail set is now DERIVED from the power
    rows (ordered by channel, nominal parsed from the net name) and
    pushed into the Test Work Flow page."""
    window.yaml_build_page.model.set_channel_allocation({
        "power": [
            {"net": "DCDC_1V8",
             "power_rails": "U2355A AI02"},
            {"net": "5V_SDA_PSW",
             "power_rails": "U2355A AI01"},
            {"net": "CPVOUTN", "power_rails": "—"},   # unassigned
        ],
    })
    window._sync_rails_to_workflow()
    rails = window.workflow_page.rails
    assert [r[0] for r in rails] == ["5V_SDA_PSW", "DCDC_1V8"]
    # nominal parsed from the net name where possible (1V8 -> 1.8)
    assert rails[1][2] == pytest.approx(1.8)
    # capture parameters mirror into the page
    assert window.workflow_page.cap_rate == 200


def test_instrument_dialog_test_log_is_large(page):
    """User direction: the instrument dialog's Test Log is the main
    lower area (>= 240 px, expands with the dialog) instead of a
    cramped fixed 130 px strip."""
    from mtkgui.equipment_page import _InstrumentDialog
    dlg = _InstrumentDialog(page, "U2355A", [("Model", "U2355A")],
                            "u2355a", virtual=True)
    try:
        assert dlg._output.minimumHeight() >= 240
        assert dlg._output.maximumHeight() >= 100000  # NOT fixed
    finally:
        dlg.deleteLater()


def test_virtual_startup_does_not_force_green(qapp):
    """User report: the LEDs were ALWAYS green - Virtual startup must
    NOT force-connect the LEDs; they stay disconnected until the
    operator connects on the Equipment page."""
    w = MainWindow(role=ROLE_SUPERVISOR, mode="Virtual",
                   fixture=FIXTURE_ATE)
    try:
        w._connect_virtual_instruments()   # the old force-green path
        for abbr in ("DAQM", "DAQ", "PSU"):
            assert w.instr_status.states[abbr] == "disconnected", abbr
        # ... and a manual Equipment-page connect DOES light the LED
        w.equipment_page.instrument_connection_changed.emit("psu", True)
        assert w.instr_status.states["PSU"] == "connected"
    finally:
        w.close()
        w.deleteLater()


def test_status_leds_follow_equipment_connect(window, monkeypatch):
    """The status-bar LED for DAQ turns green exactly when the U2355A
    dialog connects, and gray on disconnect - no forced green."""
    window.instr_status.set_all("disconnected")
    events = []
    window.equipment_page.instrument_connection_changed.connect(
        lambda key, conn: events.append((key, conn)))
    window.equipment_page.instrument_connection_changed.emit(
        "u2355a", True)
    assert window.instr_status.states["DAQ"] == "connected"
    window.equipment_page.instrument_connection_changed.emit(
        "u2355a", False)
    assert window.instr_status.states["DAQ"] == "disconnected"
    assert events == [("u2355a", True), ("u2355a", False)]
