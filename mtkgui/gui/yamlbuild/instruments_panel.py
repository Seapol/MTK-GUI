# -*- coding: utf-8 -*-
"""Configure Instruments panel (core standard section 6): per
instrument status table.

Per the unified equipment management rule, ALL instrument
configuration parameters live on the Equipment page.  This window
does NOTHING else than:

* list EVERY rack-ATE instrument, one row each (always all of them,
  configured or not - the configuration itself happens on the
  Equipment page);
* show the per-instrument connection status;
* offer ONE Connect / Disconnect button per row.

No parameter editors, no self-test column, no connection test or
self-test triggering here - GUI layer only, the instrument driver
and connection kernel are untouched.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.instrument_status import HUB

#: EVERY rack-ATE instrument, one row each - listed regardless of the
#: configuration state (the configuration lives on the Equipment page)
_ROW_SPECS = (
    ("daq_visa", "DAQ973A + 908A/907A"),
    ("psu_visa", "N5747A DC Power Supply"),
    ("dmm_visa", "DMM (optional)"),
)

_CONN_COLORS = {"Connected": "#16a34a", "Disconnected": "#6b7280",
                "Error": "#dc2626"}
STATUS_DISCONNECTED = "Disconnected"


class InstrumentsPanel(QWidget):
    """Block 03 embedded panel: the instrument status table (one row
    per rack-ATE instrument) with one Connect / Disconnect button
    each - nothing else."""

    #: (level, message) Event-Log mirror (T6)
    task_log = Signal(str, str)

    def __init__(self, parent: QWidget | None = None,
                 hub=HUB) -> None:
        super().__init__(parent)
        self._hub = hub
        self._params: dict = {}      # stored block 03 passthrough
        self._rows: dict[str, dict] = {}   # param key -> row widgets

        # adaptive layout - the panel grows with the dialog
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        note = QLabel(
            "All instrument configuration and connection validation "
            "is centralized on the Equipment page. This window only "
            "lists the instruments with their connection status and "
            "the Connect / Disconnect control.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        # header row of the instrument table + the bulk controls
        header = QHBoxLayout()
        for text, stretch in (("Instrument", 1), ("Status", 0)):
            lbl = QLabel(text)
            lbl.setObjectName("strong")
            header.addWidget(lbl, stretch)
        header.addSpacing(110)       # room for the row buttons
        lay.addLayout(header)

        self.rows_lay = QVBoxLayout()
        self.rows_lay.setSpacing(8)
        lay.addLayout(self.rows_lay)
        lay.addStretch(1)

        # bulk controls: Connect All / Disconnect All (user direction)
        bulk = QHBoxLayout()
        self.btn_connect_all = QPushButton("Connect All")
        self.btn_connect_all.setToolTip(
            "Connect every instrument in the table")
        self.btn_connect_all.clicked.connect(self._connect_all)
        self.btn_disconnect_all = QPushButton("Disconnect All")
        self.btn_disconnect_all.setToolTip(
            "Disconnect every connected instrument")
        self.btn_disconnect_all.clicked.connect(self._disconnect_all)
        bulk.addStretch(1)
        bulk.addWidget(self.btn_connect_all)
        bulk.addWidget(self.btn_disconnect_all)
        lay.addLayout(bulk)

        # one row per instrument - built ONCE (rebuilding with
        # deleteLater left overlapping ghost rows on screen)
        self._rebuild_rows()

    # ------------------------------------------------------------- rows
    def _rebuild_rows(self) -> None:
        """Build the fixed instrument table: one row per rack-ATE
        instrument, regardless of the configuration state.  The rows
        are built exactly once; set_params only refreshes tooltips."""
        if self._rows:
            self._refresh_row_tooltips()
            return
        for param_key, model_name in _ROW_SPECS:
            self._rows[param_key] = self._build_row(param_key,
                                                    model_name)

    def _refresh_row_tooltips(self) -> None:
        for key, state in self._rows.items():
            visa = str(self._params.get(key) or "").strip()
            state["name_lbl"].setToolTip(
                f"{state['name']} - configure the parameters on the "
                "Equipment page"
                + (f" (connection: {visa})" if visa
                   else " (not configured yet)"))

    def _build_row(self, param_key: str, model_name: str) -> dict:
        """Build one instrument row: name / connection status / one
        Connect / Disconnect button."""
        frame = QFrame()
        frame.setObjectName("instrument_row")
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)
        visa = str(self._params.get(param_key) or "").strip()
        lbl_name = QLabel(model_name)
        lbl_name.setToolTip(
            f"{model_name} - configure the parameters on the "
            "Equipment page"
            + (f" (connection: {visa})" if visa
               else " (not configured yet)"))
        lbl_conn = QLabel(STATUS_DISCONNECTED)
        lbl_conn.setToolTip(
            "Connection status (Connected / Disconnected)")
        lbl_conn.setMinimumWidth(90)
        lbl_conn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton("Connect")
        btn.setMinimumHeight(30)
        btn.setMinimumWidth(96)
        btn.setToolTip(
            f"Connect / disconnect {model_name} individually "
            "(one-by-one control)")
        row.addWidget(lbl_name, 1)
        row.addWidget(lbl_conn, 0)
        row.addWidget(btn, 0)
        self.rows_lay.addWidget(frame)
        state = {"key": param_key, "name": model_name,
                 "name_lbl": lbl_name,
                 "conn": lbl_conn, "btn": btn, "connected": False}
        btn.clicked.connect(lambda _c=False, s=state:
                            self._toggle_row(s))
        self._paint_row(state)
        return state

    def _toggle_row(self, state: dict) -> None:
        """Individual Connect / Disconnect for ONE instrument row
        (GUI layer only - the connection kernel is untouched)."""
        if state["connected"]:
            state["connected"] = False
            state["conn"].setText(STATUS_DISCONNECTED)
            self.task_log.emit(
                "INFO", f"{state['name']} disconnected")
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

    def _connect_all(self) -> None:
        """Connect every instrument in the table."""
        for state in self._rows.values():
            if not state["connected"]:
                state["btn"].click()

    def _disconnect_all(self) -> None:
        """Disconnect every connected instrument (the last disconnect
        resets the shared hub)."""
        for state in self._rows.values():
            if state["connected"]:
                state["btn"].click()

    def _paint_row(self, state: dict) -> None:
        """Apply the row status text + color + the dynamic button
        label (Connect <-> Disconnect)."""
        conn = state["conn"].text()
        state["conn"].setStyleSheet(
            f"color: {_CONN_COLORS.get(conn, '#6b7280')}; "
            "font-weight: bold;")
        state["btn"].setText(
            "Disconnect" if state["connected"] else "Connect")

    # ---------------------------------------------------------- values
    def values(self) -> dict:
        """Passthrough: the module owns NO instrument parameters
        (configuration is centralized on the Equipment page).  The
        stored block 03 parameters are returned unchanged."""
        return dict(self._params)

    def set_params(self, params: dict) -> None:
        """Remember the stored parameters (passthrough on save) and
        refresh the row tooltips (the rows themselves are fixed)."""
        self._params = dict(params or {})
        self._rebuild_rows()
