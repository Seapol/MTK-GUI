# -*- coding: utf-8 -*-
"""Configure Instruments panel (item 22): per-instrument rows.

Per the unified equipment management rule, ALL instrument
configuration and connection validation lives on the Equipment page.
This panel lists every configured instrument, one row each:

* Instrument name / model;
* Connection status (Unknown / Connected / Disconnected / Error);
* Self-Test status (Unknown / Pass / Fail);
* an individual Connect / Disconnect button (one by one control,
  NO global bulk connect).

A row disconnect asks for confirmation (the user is pointed to the
Equipment page for reconfiguration and retest) and resets the row
Self-Test to Unknown.  No parameter configuration, no connection
test or self-test triggering happens here - GUI layer only, the
instrument driver and connection kernel are untouched.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.instrument_status import (
    HUB,
    STATUS_UNKNOWN,
)

_DISCONNECT_NOTICE = (
    "Instrument disconnected.\n\n"
    "Reconfigure and retest the instrument connection on the "
    "Equipment page (all instrument configuration and connection "
    "validation is centralized there).")

#: the configured rack-ATE instruments (block 03 params -> row);
#: dmm is optional and only listed when a VISA address is configured
_ROW_SPECS = (
    ("daq_visa", "DAQ973A + 908A/907A"),
    ("psu_visa", "N5747A DC Power Supply"),
    ("dmm_visa", "DMM (optional)"),
)

_CONN_COLORS = {"Connected": "#16a34a", "Disconnected": "#6b7280",
                "Error": "#dc2626"}
_SELF_COLORS = {"Pass": "#16a34a", "Fail": "#dc2626"}


def _self_test_display(hub_value: str) -> str:
    """Map the Equipment-page Self-Test hub value (OK / NOK / Unknown)
    onto the per-row display value (Pass / Fail / Unknown)."""
    return {"OK": "Pass", "NOK": "Fail"}.get(hub_value, STATUS_UNKNOWN)


class InstrumentsPanel(QWidget):
    """Block 03 embedded panel: per-instrument rows with individual
    Connect / Disconnect control and dual status display."""

    #: (level, message) Event-Log mirror (T6)
    task_log = Signal(str, str)

    def __init__(self, parent: QWidget | None = None,
                 hub=HUB) -> None:
        super().__init__(parent)
        self._hub = hub
        self._params: dict = {}      # stored block 03 passthrough
        self._rows: dict[str, dict] = {}   # param key -> row widgets

        # item 22: adaptive layout - the panel grows with the dialog
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        note = QLabel(
            "All instrument configuration and connection validation "
            "is centralized on the Equipment page. This module only "
            "shows the connection status and performs the connect / "
            "disconnect control.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        # header row of the instrument list
        header = QHBoxLayout()
        for text, stretch in (("Instrument", 1), ("Connection", 0),
                              ("Self-Test", 0)):
            lbl = QLabel(text)
            lbl.setObjectName("strong")
            header.addWidget(lbl, stretch)
        header.addSpacing(96)        # room for the row buttons
        lay.addLayout(header)

        self.rows_lay = QVBoxLayout()
        self.rows_lay.setSpacing(8)
        lay.addLayout(self.rows_lay)

        self.lbl_empty = QLabel(
            "No instruments configured - configure the rack-ATE "
            "instruments on the Equipment page (block 03 reads the "
            "configuration from the project parameters).")
        self.lbl_empty.setObjectName("muted")
        self.lbl_empty.setWordWrap(True)
        lay.addWidget(self.lbl_empty)
        lay.addStretch(1)

        self._hub.subscribe(self._sync_from_hub)

    # ------------------------------------------------------------- rows
    def _rebuild_rows(self) -> None:
        """(Re)build one row per configured instrument from the
        stored block 03 parameters (row per instrument, individual
        Connect / Disconnect button)."""
        while self.rows_lay.count():
            item = self.rows_lay.takeAt(self.rows_lay.count() - 1)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows = {}
        any_configured = False
        for param_key, model_name in _ROW_SPECS:
            if not str(self._params.get(param_key) or "").strip():
                continue            # not configured -> not listed
            any_configured = True
            self._rows[param_key] = self._build_row(param_key,
                                                    model_name)
        self.lbl_empty.setVisible(not any_configured)

    def _build_row(self, param_key: str, model_name: str) -> dict:
        """Build one instrument row: name / connection status /
        self-test status / individual Connect / Disconnect button."""
        frame = QFrame()
        frame.setObjectName("instrument_row")
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)
        lbl_name = QLabel(model_name)
        lbl_name.setToolTip(
            f"{model_name} - configured on the Equipment page "
            f"(connection: {self._params.get(param_key, '')})")
        lbl_conn = QLabel(STATUS_UNKNOWN)
        lbl_conn.setToolTip(
            "Connection status (Unknown / Connected / Disconnected / "
            "Error)")
        lbl_conn.setMinimumWidth(90)
        lbl_conn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_self = QLabel(STATUS_UNKNOWN)
        lbl_self.setToolTip(
            "Self-Test status (Unknown / Pass / Fail)")
        lbl_self.setMinimumWidth(70)
        btn = QPushButton("Connect")
        btn.setMinimumHeight(30)
        btn.setMinimumWidth(96)
        btn.setToolTip(
            f"Connect / disconnect {model_name} individually "
            "(one-by-one control, no bulk connect)")
        row.addWidget(lbl_name, 1)
        row.addWidget(lbl_conn, 0)
        row.addWidget(lbl_self, 0)
        row.addWidget(btn, 0)
        self.rows_lay.addWidget(frame)
        state = {"key": param_key, "name": model_name,
                 "conn": lbl_conn, "self": lbl_self,
                 "btn": btn, "connected": False}
        btn.clicked.connect(lambda _c=False, s=state:
                            self._toggle_row(s))
        self._paint_row(state)
        return state

    def _toggle_row(self, state: dict) -> None:
        """Individual Connect / Disconnect for ONE instrument row
        (GUI layer only - the connection kernel is untouched)."""
        if state["connected"]:
            QMessageBox.information(self, "Disconnect",
                                    _DISCONNECT_NOTICE)
            state["connected"] = False
            state["conn"].setText("Disconnected")
            state["self"].setText(STATUS_UNKNOWN)   # stale result reset
            self.task_log.emit(
                "INFO",
                f"{state['name']} disconnected - Self-Test reset to "
                "Unknown (reconfigure and retest on the Equipment "
                "page)")
            if not any(r["connected"] for r in self._rows.values()):
                self._hub.disconnect()   # no instrument connected left
        else:
            state["connected"] = True
            state["conn"].setText("Connected")
            self._hub.set_connected(True)
            self.task_log.emit(
                "INFO",
                f"{state['name']} connect requested - connection "
                "validated on the Equipment page")
        self._paint_row(state)

    def _paint_row(self, state: dict) -> None:
        """Apply the row status texts + colors + the dynamic button
        label (Connect <-> Disconnect)."""
        conn = state["conn"].text()
        state["conn"].setStyleSheet(
            f"color: {_CONN_COLORS.get(conn, '#6b7280')}; "
            "font-weight: bold;")
        self_value = state["self"].text()
        state["self"].setStyleSheet(
            f"color: {_SELF_COLORS.get(self_value, '#6b7280')}; "
            "font-weight: bold;")
        state["btn"].setText(
            "Disconnect" if state["connected"] else "Connect")

    # --------------------------------------------------------------- sync
    def _sync_from_hub(self) -> None:
        """Mirror the hub Self-Test result onto every row (the
        Equipment page owns the self-test state); connection states
        are per-row and stay user-controlled."""
        display = _self_test_display(self._hub.self_test)
        for state in self._rows.values():
            if not state["connected"]:
                state["self"].setText(display)
            self._paint_row(state)

    def values(self) -> dict:
        """Passthrough: the module owns NO instrument parameters
        (configuration is centralized on the Equipment page).  The
        stored block 03 parameters are returned unchanged."""
        return dict(self._params)

    def set_params(self, params: dict) -> None:
        """Remember the stored parameters (passthrough on save) and
        rebuild the per-instrument rows from the configured set."""
        self._params = dict(params or {})
        self._rebuild_rows()
        self._sync_from_hub()
