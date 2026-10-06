# -*- coding: utf-8 -*-
"""Configure Instruments panel tests (core standard section 6): the
window lists EVERY rack-ATE instrument (one row each, configured or
not), shows ONLY the connection status and ONE Connect / Disconnect
button per row.  All parameters are configured on the Equipment page.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLineEdit,
    QMessageBox,
)

from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog  # noqa: E402
from mtkgui.gui.yamlbuild.instrument_status import (  # noqa: E402
    InstrumentStatusHub,
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


# --------------------------------------------------------------- panel
CONFIGURED = {"psu_visa": "TCPIP0::1.2.3.4::inst0",
              "daq_visa": "GPIB0::9::INSTR", "dmm_visa": "",
              "channel_alloc": "", "self_test": "true"}


def test_all_instruments_listed_one_per_row(panel):
    """Requirement 1: ALL instruments are listed in the table, one
    row each - configured or not (the DMM too, marked unconfigured)."""
    panel.set_params(CONFIGURED)
    assert set(panel._rows) == {"daq_visa", "psu_visa", "dmm_visa"}
    for state in panel._rows.values():
        assert state["btn"].text() == "Connect"
        assert state["conn"].text() == "Disconnected"
    # even with NO configuration at all the three rows still exist
    panel.set_params({})
    assert set(panel._rows) == {"daq_visa", "psu_visa", "dmm_visa"}


def test_window_shows_status_and_button_only(panel, qapp):
    """Requirement 3: the window shows ONLY the status and the
    Connect / Disconnect control - no parameter editors, no self-test
    column."""
    from PySide6.QtWidgets import QLabel
    panel.set_params(CONFIGURED)
    assert panel.findChild(QLineEdit) is None      # no parameter input
    for state in panel._rows.values():
        assert not hasattr(state, "self")          # no self-test column
        assert state["btn"].text() in ("Connect", "Disconnect")
    texts = [w.text() for w in panel.findChildren(QLabel)]
    assert not any("Self-Test" == t for t in texts)


def test_row_independent_connect(panel, hub):
    """Each instrument connects individually: only the clicked row
    switches to Connected; the hub mirrors 'connected'."""
    panel.set_params(CONFIGURED)
    logs = []
    panel.task_log.connect(lambda l, m: logs.append((l, m)))
    daq, psu = panel._rows["daq_visa"], panel._rows["psu_visa"]
    daq["btn"].click()
    assert daq["conn"].text() == "Connected"
    assert daq["btn"].text() == "Disconnect"
    assert psu["conn"].text() == "Disconnected"   # independent
    assert psu["btn"].text() == "Connect"
    assert hub.connected is True
    assert any("DAQ973A" in m and "connect requested" in m
               for _l, m in logs)


def test_row_disconnect_resets_hub(panel, hub):
    """Row disconnect: the row goes Disconnected; the LAST disconnect
    resets the shared hub - no popup, no self-test column."""
    panel.set_params(CONFIGURED)
    daq, psu = panel._rows["daq_visa"], panel._rows["psu_visa"]
    daq["btn"].click()                 # connect
    daq["btn"].click()                 # disconnect again
    assert daq["conn"].text() == "Disconnected"
    assert daq["btn"].text() == "Connect"
    assert hub.connected is False
    psu["btn"].click()
    daq["btn"].click()                 # reconnect daq
    assert hub.connected is True
    daq["btn"].click()                 # daq off, psu still on
    assert hub.connected is True
    psu["btn"].click()                 # last row off -> hub reset
    assert hub.connected is False


def test_connect_all_and_disconnect_all(panel, hub):
    """The bulk controls: Connect All connects every row, Disconnect
    All disconnects every row (the hub resets on the last one)."""
    panel.set_params(CONFIGURED)
    panel._connect_all()
    for state in panel._rows.values():
        assert state["conn"].text() == "Connected"
        assert state["btn"].text() == "Disconnect"
    assert hub.connected is True
    panel._disconnect_all()
    for state in panel._rows.values():
        assert state["conn"].text() == "Disconnected"
        assert state["btn"].text() == "Connect"
    assert hub.connected is False


def test_panel_values_passthrough(panel):
    """Block 03 owns no parameters here: the stored values pass
    through unchanged on save (Equipment page is the owner)."""
    panel.set_params(CONFIGURED)
    assert panel.values() == CONFIGURED


# ------------------------------------------------------ block02 embed
def test_block02_dialog_embeds_panel(qapp):
    """The instruments dialog hosts the status table - no generic
    form fields, parameters passthrough, no global button."""
    stored = {"psu_visa": "V1", "daq_visa": "V2", "dmm_visa": "",
              "channel_alloc": "", "self_test": "true"}
    dlg = BlockConfigDialog("instruments", stored)
    try:
        assert dlg.panel is not None
        assert dlg.form.rowCount() == 0
        assert dlg.panel.values() == stored
        assert not hasattr(dlg.panel, "btn_connect")
        assert set(dlg.panel._rows) == {"daq_visa", "psu_visa",
                                        "dmm_visa"}
    finally:
        dlg.deleteLater()
