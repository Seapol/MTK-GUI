# -*- coding: utf-8 -*-
"""P3-B2 T9: Configure Instruments module refactor tests.

Simplified block 02: one Connect / Disconnect button + two health
indicators (Test Connection / Self-Test) synced from the Equipment
page through the shared status hub.  No parameter configuration, no
connection test / self-test triggering in this module; GUI layer
only."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QMessageBox,
)

from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog  # noqa: E402
from mtkgui.gui.yamlbuild.instrument_status import (  # noqa: E402
    InstrumentStatusHub,
    STATUS_NOK,
    STATUS_OK,
    STATUS_UNKNOWN,
)
from mtkgui.gui.yamlbuild.instruments_panel import (  # noqa: E402
    InstrumentsPanel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def hub():
    return InstrumentStatusHub()


@pytest.fixture()
def panel(qapp, hub):
    w = InstrumentsPanel(hub=hub)
    yield w
    w.deleteLater()


# ------------------------------------------------------------------ hub
def test_hub_defaults_unknown(hub):
    snap = hub.snapshot()
    assert snap == {"connected": False,
                    "test_connection": STATUS_UNKNOWN,
                    "self_test": STATUS_UNKNOWN}


def test_hub_subscriber_notified(hub):
    calls = []
    callback = lambda: calls.append(1)  # noqa: E731
    hub.subscribe(callback)
    hub.set_connected(True)
    hub.set_test_connection(STATUS_OK)
    assert len(calls) == 2
    hub.unsubscribe(callback)
    hub.set_self_test(STATUS_OK)
    assert len(calls) == 2          # no longer notified


def test_hub_rejects_invalid_status(hub):
    hub.set_test_connection("MAYBE")
    assert hub.test_connection == STATUS_UNKNOWN


def test_hub_disconnect_resets_statuses(hub):
    hub.set_connected(True)
    hub.set_test_connection(STATUS_OK)
    hub.set_self_test(STATUS_OK)
    hub.disconnect()
    assert hub.snapshot() == {"connected": False,
                              "test_connection": STATUS_UNKNOWN,
                              "self_test": STATUS_UNKNOWN}


# --------------------------------------------------------------- panel
CONFIGURED = {"psu_visa": "TCPIP0::1.2.3.4::inst0",
              "daq_visa": "GPIB0::9::INSTR", "dmm_visa": "",
              "channel_alloc": "", "self_test": "true"}


def test_per_instrument_rows_no_global_button(panel):
    """Item 22: one row per configured instrument, each with its own
    Connect / Disconnect button; the single global button is gone."""
    panel.set_params(CONFIGURED)
    assert not hasattr(panel, "btn_connect")     # global button removed
    assert set(panel._rows) == {"daq_visa", "psu_visa"}   # dmm empty
    for state in panel._rows.values():
        assert state["btn"].text() == "Connect"
        assert state["conn"].text() == STATUS_UNKNOWN
        assert state["self"].text() == STATUS_UNKNOWN
    # unconfigured (empty) instruments are NOT listed
    assert "dmm_visa" not in panel._rows


def test_empty_config_shows_placeholder(panel):
    """Without configured instruments a muted hint is shown and no
    rows are built."""
    panel.set_params({})
    assert panel._rows == {}
    assert not panel.lbl_empty.isHidden()


def test_row_independent_connect(panel, hub):
    """Each instrument connects individually (one-by-one control):
    only the clicked row switches to Connected; the other row stays
    untouched; the hub mirrors 'connected' for the status bar."""
    panel.set_params(CONFIGURED)
    logs = []
    panel.task_log.connect(lambda l, m: logs.append((l, m)))
    daq, psu = panel._rows["daq_visa"], panel._rows["psu_visa"]
    daq["btn"].click()
    assert daq["conn"].text() == "Connected"
    assert daq["btn"].text() == "Disconnect"
    assert psu["conn"].text() == STATUS_UNKNOWN   # independent
    assert psu["btn"].text() == "Connect"
    assert hub.connected is True
    assert any("DAQ973A" in m and "connect requested" in m
               for _l, m in logs)


def test_row_disconnect_prompts_and_resets(panel, hub, monkeypatch):
    """Row disconnect: prompt pointing to the Equipment page, the row
    Connection goes Disconnected and the row Self-Test resets to
    Unknown; the last disconnect resets the shared hub."""
    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.append(a) or 0)
    panel.set_params(CONFIGURED)
    daq, psu = panel._rows["daq_visa"], panel._rows["psu_visa"]
    hub.set_self_test(STATUS_OK)
    daq["btn"].click()                 # connect
    daq["btn"].click()                 # disconnect again
    assert shown and "Equipment page" in shown[0][2]
    assert daq["conn"].text() == "Disconnected"
    assert daq["self"].text() == STATUS_UNKNOWN   # stale result reset
    assert daq["btn"].text() == "Connect"
    # no row is connected any more -> the shared hub is reset
    assert hub.connected is False
    assert hub.test_connection == STATUS_UNKNOWN
    assert hub.self_test == STATUS_UNKNOWN
    # one remaining connected row keeps the hub connected; the LAST
    # disconnect resets it
    psu["btn"].click()
    daq["btn"].click()                 # reconnect daq
    assert hub.connected is True
    daq["btn"].click()                 # daq off, psu still on
    assert hub.connected is True
    psu["btn"].click()                 # last row off -> hub reset
    assert hub.connected is False


def test_row_self_test_syncs_from_hub(panel, hub):
    """The Equipment-page Self-Test result maps onto every row
    (OK -> Pass, NOK -> Fail, else Unknown); connected rows keep
    their own display until disconnected."""
    panel.set_params(CONFIGURED)
    hub.set_self_test(STATUS_OK)
    for state in panel._rows.values():
        assert state["self"].text() == "Pass"
    hub.set_self_test(STATUS_NOK)
    for state in panel._rows.values():
        assert state["self"].text() == "Fail"


def test_panel_no_parameter_editors(panel):
    """The module shows ONLY the per-instrument rows - no instrument
    parameter configuration, no test/self-test trigger."""
    panel.set_params(CONFIGURED)
    # no line edits anywhere on the panel (no VISA / parameter input)
    from PySide6.QtWidgets import QLineEdit
    assert panel.findChild(QLineEdit) is None


def test_panel_values_passthrough(panel):
    """Block 02 owns no parameters: the stored values pass through
    unchanged on save (Equipment page is the configuration owner)."""
    stored = {"psu_visa": "TCPIP0::1.2.3.4::inst0",
              "daq_visa": "GPIB0::9::INSTR", "dmm_visa": "",
              "channel_alloc": "", "self_test": "true"}
    panel.set_params(stored)
    assert panel.values() == stored


# ------------------------------------------------------ block02 embed
def test_block02_dialog_embeds_panel(qapp):
    """The instruments dialog hosts the per-instrument panel - no
    generic form fields, parameters passthrough, no global button."""
    stored = {"psu_visa": "V1", "daq_visa": "V2", "dmm_visa": "",
              "channel_alloc": "", "self_test": "true"}
    dlg = BlockConfigDialog("instruments", stored)
    try:
        assert dlg.panel is not None
        assert dlg.form.rowCount() == 0
        assert dlg.panel.values() == stored
        assert not hasattr(dlg.panel, "btn_connect")
        assert set(dlg.panel._rows) == {"daq_visa", "psu_visa"}
    finally:
        dlg.deleteLater()


# --------------------------------------------- equipment page sync hooks
def test_equipment_page_syncs_hub(qapp, monkeypatch):
    """The Equipment page connection dialog syncs the hub: virtual
    connect -> connected, disconnect -> reset, test -> OK, self-test
    action -> OK/NOK (GUI layer hooks only - the connection kernel is
    untouched)."""
    from mtkgui.gui.yamlbuild.instrument_status import HUB
    hub0 = (HUB.connected, HUB.test_connection, HUB.self_test)
    try:
        import inspect
        import mtkgui.equipment_page as eq
        src = inspect.getsource(eq)
        # the sync hooks exist and use the hub (GUI-layer mirror)
        assert "HUB.set_connected(True)" in src
        assert "HUB.disconnect()" in src
        assert "HUB.set_test_connection" in src
        assert "HUB.set_self_test" in src

        # functional: the Self-Test action syncs the hub result
        HUB.set_self_test(STATUS_UNKNOWN)
        page = eq.EquipmentPage()
        dlg = eq._InstrumentDialog(page, "DAQ973A", {}, "daq973a",
                                   virtual=True)
        try:
            dlg._run_action("Self Test")
            assert HUB.self_test == STATUS_OK
        finally:
            dlg.deleteLater()
            page.deleteLater()
    finally:
        HUB.set_connected(hub0[0])
        HUB.set_test_connection(hub0[1])
        HUB.set_self_test(hub0[2])
