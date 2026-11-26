# -*- coding: utf-8 -*-
"""Equipment page: block diagram of the final test rack.

Layers (top -> bottom):

  1. HOST PC (center) + Flash / Debug Probes (left) + Test Peripherals (right)
  2. Instruments:
       DAQ973A mainframe  (DAQM908A #1, DAQM908A #2, DAQM907A)
       U2355A USB DAQ      (analog inputs, counters + digital IO)
       N5747A DC power supply
  3. Fixture probe board (single-point star ground plane) with the
     ATE fixture control board
  4. DUT board (power nets, critical rails, clocks, ADC, VIN, GND, GPIO)

Every named block is clickable and opens a configuration window.
Dialog footnotes are mode-aware (Real / Virtual) - the legacy static
"Demo mode" wording was wrong outside the demo era (user report).
"""

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

import os
import random

from .permissions import MANUAL_FIXTURE_NOTICE, MODE_VIRTUAL
from .qt_guard import qt_safe
from mtkgui.gui.dialog_sizing import (apply_scroll_to_dialog,
                                      enable_dialog_controls, fit_dialog,
                                      wrap_page)

# ---------------------------------------------------------------- palette
BLUE = "#2563eb"
BLUE_DARK = "#1d4ed8"
BLUE_FILL = "#eff6ff"
TEAL = "#0d9488"
TEAL_DARK = "#0f766e"
TEAL_FILL = "#f0fdfa"
AMBER = "#d97706"
AMBER_DARK = "#b45309"
AMBER_FILL = "#fffbeb"
PURPLE = "#7c3aed"
PURPLE_FILL = "#f5f3ff"
RED = "#dc2626"
GRAY = "#64748b"
GRAY_FILL = "#f8fafc"
TEXT = "#22303c"
SUB = "#5b6b7a"

# icon palette (vector icons drawn inside diagram blocks)
SLATE = "#475569"
STEEL = "#94a3b8"
MIST = "#cbd5e1"
PANEL = "#f1f5f9"
PAPER = "#f8fafc"
INK = "#1e293b"
NAVY = "#1d4ed8"
CARD_BLUE = "#dbeafe"
LCD = "#86efac"
LCD_ROW = "#e2e8f0"
GREEN = "#22c55e"
CARD_TEAL = "#99f6e4"
SOFT_TEAL = "#ccfbf1"
GOLD = "#fbbf24"
HONEY = "#fde68a"
LILAC = "#a78bfa"
BLUSH = "#fecaca"

W, H = 1440, 1120

# --------------------------------------------------------------------------
# instrument configuration-window data (keyed by block key)
# --------------------------------------------------------------------------
# editable parameters shown in the "Parameter Configuration" group
_INSTRUMENT_PARAMS = {
    "daq973a": [("Scan speed (ch/s)", "450"), ("Timeout (ms)", "2000"),
                ("NPLC", "1.0")],
    "m908a_1": [("Wire mode", "1-wire (single-ended)"), ("Bias source", "off")],
    "m908a_2": [("Wire mode", "1-wire (single-ended)"), ("Bias source", "off")],
    "m907a": [("Totalizer gate (s)", "1"), ("AO0 (V)", "0.0"),
              ("AO1 (V)", "0.0")],
    "u2355a": [("Sample rate (kSa/s)", "20"), ("Range (V)", "10"),
               ("Averaging", "1")],
    "psu": [("Voltage set (V)", "12.0"), ("Current limit (A)", "2.0"),
            ("OVP (V)", "15.0")],
}

# simulated control / simple-test actions: (button label, result lambda)
# p = list of current parameter-edit texts
_INSTRUMENT_ACTIONS = {
    "daq973a": [
        ("Measure DCV",
         lambda p: f"DCV = {random.uniform(3.28, 3.32):.4f} V "
                   f"(nominal 3.30 V) -> PASS"),
        ("Measure Ω (1-wire SE)",
         lambda p: f"R = {random.uniform(0.9, 1.4):.2f} Ω "
                   f"(< 1.5 Ω threshold) -> PASS"),
        ("Measure Frequency",
         lambda p: "Frequency = 32768.0 Hz (CLK1) -> PASS"),
        ("Self Test",
         lambda p: "Self test completed - 0 errors"),
    ],
    "m908a_1": [
        ("Scan CH101 - CH140",
         lambda p: "Scan: 40/40 channels closed, contact check OK"),
        ("Relay Self Test",
         lambda p: "Relay self test -> OK"),
    ],
    "m908a_2": [
        ("Scan CH201 - CH240",
         lambda p: "Scan: 40/40 channels closed, contact check OK"),
        ("Relay Self Test",
         lambda p: "Relay self test -> OK"),
    ],
    "m907a": [
        ("DIO Write",
         lambda p: "DIO Port 1/2 <- 0x0F (fixture control board)"),
        ("DIO Read",
         lambda p: "DIO read -> 0x0F"),
        ("Totalizer (CLK1)",
         lambda p: f"Totalizer count = "
                   f"{int(32768 * max(1.0, float(p[0] or 1)))} "
                   f"(gate {p[0]} s) -> PASS"),
        ("AO Output",
         lambda p: f"AO0 = {p[1]} V, AO1 = {p[2]} V (16-bit)"),
    ],
    "u2355a": [
        ("AI Read (12 rails)",
         lambda p: f"AI: 12 critical rails captured @ {p[0]} kSa/s -> CSV"),
        ("Counter CTR0 (CLK2)",
         lambda p: "CTR0: 4.000 MHz -> PASS"),
        ("Counter CTR1 (CLK3)",
         lambda p: "CTR1: 6.000 MHz -> PASS"),
        ("DIO Loopback",
         lambda p: "DIO loopback 24 ch -> OK"),
        ("Self Test",
         lambda p: "Self test completed - 0 errors"),
    ],
    "psu": [
        ("Power ON",
         lambda p: f"Output ON: {p[0]} V / {p[1]} A limit "
                   f"(OVP {p[2]} V)"),
        ("Power OFF",
         lambda p: "Output OFF"),
        ("Read V/I",
         lambda p: f"V = {p[0]} V, I = {random.uniform(0.3, 0.6):.2f} A "
                   f"(readback ~1%)"),
        ("Self Test",
         lambda p: "Self test completed - 0 errors"),
    ],
}

# Manual fixture mode (login dialog): these fixture-band blocks are
# globally disabled together with every IO-control entry
_MANUAL_FIXTURE_KEYS = ("fixture", "control_board", "cell_press",
                        "cell_inpos", "cell_presence", "cell_estop")

# M49a: the LEFT column lists ONLY configurable hardware.  Each entry is
# (entry key, label, kind, data source).  ``kind`` selects the dialog:
#   instrument -> _InstrumentDialog (Config + Test)
#   form       -> editable form dialog
# The data source is (configs key, group key) - ``group key`` is None
# for a plain config entry (its ``fields`` / ``params`` are edited).
LEFT_ENTRIES = (
    ("Instruments", (
        ("daq973a", "DAQ973A Mainframe", "instrument", ("daq973a", None)),
        ("u2355a", "U2355A", "instrument", ("u2355a", None)),
        ("psu", "N5747A", "instrument", ("psu", None)),
        ("rf_test_set", "RF Test Set (WiFi/BT)", "optional", None),
        # M136: a debugger is an instrument, not a sixth rack band -
        # nested here, and the analyzer stays a grey placeholder until
        # its driver lands.
        ("debugger", "Debugger", "group", None),
        ("bscan", "Boundary Scan Analyzer", "optional", None),
    )),
    ("Fixture", (
        ("control_board", "ATE Fixture Control Board", "form",
         ("control_board", None)),
    )),
    ("Peripherals", (
        ("host_pc", "Host PC", "group", None),
        ("serial_console", "Serial Console", "sub",
         ("host_pc", "serial")),
        ("ssh_console", "SSH Console", "sub", ("host_pc", "ssh")),
        ("rj45_wired", "RJ45 Wired Network", "sub", ("host_pc", "rj45")),
        ("wifi_wireless", "Wi-Fi Wireless Network", "sub",
         ("host_pc", "wifi")),
        ("host_bt", "Bluetooth", "sub", ("host_pc", "bluetooth")),
        ("router", "Router", "group_toggle", None),
        ("router_ethernet", "RJ45 Ethernet", "sub", ("router", "ethernet")),
        ("router_ap", "Wi-Fi AP", "sub", ("router", "ap")),
    )),
)

#: instruments that own a main-window indicator lamp (M49a §3)
INDICATOR_INSTRUMENTS = ("daq973a", "u2355a", "psu")

#: M100: no equipment form exposes a Test Connection probe anymore -
#: the network mode-selection page (the last probe owner) is gone.
_TESTABLE_FORM_KEYS = ()

#: M80-1: left column width clamp (px)
LEFT_COLUMN_MIN_PX = 320
LEFT_COLUMN_MAX_PX = 480

#: M49a §5 / M100: grouped equipment configs.  (owner key, group key) ->
#: editable fields (field key, label, default).  The YAML carries these
#: as nested keys (``equipment.host_pc.rj45.host_ip`` ...) so FCT steps
#: can reference them at runtime.  The station console channels
#: (host_pc.serial / host_pc.ssh) are nested channel maps handled by
#: dedicated dialogs (not this flat table).  DUT-side Wi-Fi / BT / SSH /
#: console / ethernet moved into the FCT steps (M100) - no editor lives
#: here.
GROUP_FIELDS = {
    ("host_pc", "rj45"): [
        ("host_ip", "Host PC wired IP", ""),
        ("lan_port", "Host PC LAN port", ""),
        ("gateway", "Gateway", ""),
    ],
    ("host_pc", "wifi"): [
        ("host_ip", "Host PC Wi-Fi IP", ""),
        ("hotspot_ssid", "Hotspot SSID", ""),
        ("hotspot_password", "Hotspot password", ""),
    ],
    ("host_pc", "bluetooth"): [
        ("adapter", "Host adapter", ""),
        ("scan_targets", "Scan targets", ""),
    ],
    ("router", "enabled"): [
        ("enabled", "Enabled", True),
    ],
    ("router", "ethernet"): [
        ("router_ip", "Router IP", ""),
        ("gateway", "Gateway", ""),
    ],
    ("router", "ap"): [
        ("ssid", "Router AP SSID", ""),
        ("password", "Router AP password", ""),
    ],
}

#: station serial console channel fields (snake_case, nested per channel)
_SERIAL_CHANNEL_FIELDS = [
    ("port", "Port", ""),
    ("baud", "Baud", "115200"),
    ("data", "Data bits", "8"),
    ("parity", "Parity", None),
    ("stop", "Stop bits", "1"),
    ("flow", "Flow control", None),
]

#: station SSH console channel fields
_SSH_CHANNEL_FIELDS = [
    ("host", "Host", ""),
    ("port", "Port", "22"),
    ("user", "Username", ""),
    ("password", "Password", ""),
]

#: M100: canonical DIO channel vocabulary of the control board - the
#: DAQM907A exposes two 8-bit ports: one 8-channel READ group and one
#: 8-channel WRITE group (16 names total).
DIO_CHANNELS = tuple(
    [f"DIO_R{index:02d}" for index in range(1, 9)]
    + [f"DIO_W{index:02d}" for index in range(1, 9)])

#: the 4 DIO signals of the ATE fixture control board (DAQM907A Port1/2):
#: (signal key, label, default channel, default direction).  The read
#: group (DIO_R*) is input-only, the write group (DIO_W*) output-only.
DIO_SIGNALS = [
    ("press", "Press cylinder", "DIO_W01", "output"),
    ("inpos", "Cylinder in-position", "DIO_R01", "input"),
    ("presence", "DUT presence", "DIO_R02", "input"),
    ("estop", "E-stop healthy", "DIO_R03", "input"),
]

#: legacy 3-tuple view (channel only) still read by the old ``dio:`` map
DIO_FIELDS = [(key, label, channel)
              for key, label, channel, _direction in DIO_SIGNALS]

#: M100 B.2.4: old per-signal default channel -> new 8R+8W channel.  A
#: saved legacy value that equals one of these defaults migrates; any
#: other obsolete value is cleared so the operator re-picks it.
_LEGACY_DIO_DEFAULT = {
    "DIO01": "DIO_W01",   # press
    "DIO02": "DIO_R01",   # inpos
    "DIO03": "DIO_R02",   # presence
    "DIO04": "DIO_R03",   # estop
}


def _default_group(owner, name):
    """Fresh dict with the default field values of one grouped config."""
    return {key: default
            for key, _label, default in GROUP_FIELDS[(owner, name)]}


def _default_serial_channels() -> dict:
    """The four named station serial channels (ser1..ser4)."""
    return {f"ser{i}": {key: default
                        for key, _label, default in _SERIAL_CHANNEL_FIELDS}
            for i in range(1, 5)}


def _default_ssh_channel() -> dict:
    """The single optional station SSH channel (ssh1)."""
    return {"ssh1": {key: default
                     for key, _label, default in _SSH_CHANNEL_FIELDS}}


def _migrate_peripherals(configs: dict) -> dict:
    """M100: migrate the legacy ``peripherals.wifi/bluetooth/router``
    groups into the ``host_pc`` / ``router`` configs (backward
    compatible).  Runs once per load; the obsolete keys are dropped and
    never written back."""
    peripherals = configs.get("peripherals")
    if not isinstance(peripherals, dict):
        return configs
    groups = peripherals.get("groups") or {}
    if not groups:
        return configs
    old_router = dict(groups.get("router") or {})
    old_wifi = dict(groups.get("wifi") or {})
    old_bt = dict(groups.get("bluetooth") or {})

    host_pc = configs.setdefault("host_pc", {"title": "Host PC"})
    host_groups = host_pc.setdefault("groups", {})
    router = configs.setdefault("router", {"title": "Router"})
    router_groups = router.setdefault("groups", {})

    rj45 = host_groups.setdefault("rj45", _default_group("host_pc", "rj45"))
    if old_router.get("wired_host_ip"):
        rj45["host_ip"] = str(old_router["wired_host_ip"])
    if old_router.get("wired_host_port"):
        rj45["lan_port"] = str(old_router["wired_host_port"])
    if old_router.get("wired_gateway"):
        rj45["gateway"] = str(old_router["wired_gateway"])

    wifi = host_groups.setdefault("wifi", _default_group("host_pc", "wifi"))
    if old_router.get("wifi_host_ip"):
        wifi["host_ip"] = str(old_router["wifi_host_ip"])
    if old_router.get("hotspot_ssid"):
        wifi["hotspot_ssid"] = str(old_router["hotspot_ssid"])
    if old_router.get("hotspot_password"):
        wifi["hotspot_password"] = str(old_router["hotspot_password"])

    bt = host_groups.setdefault("bluetooth",
                                _default_group("host_pc", "bluetooth"))
    if old_bt.get("adapter"):
        bt["adapter"] = str(old_bt["adapter"])
    if old_bt.get("scan_targets"):
        bt["scan_targets"] = str(old_bt["scan_targets"])

    ethernet = router_groups.setdefault("ethernet",
                                        _default_group("router", "ethernet"))
    if old_router.get("router_ip"):
        ethernet["router_ip"] = str(old_router["router_ip"])
    if old_router.get("gateway"):
        ethernet["gateway"] = str(old_router["gateway"])

    ap = router_groups.setdefault("ap", _default_group("router", "ap"))
    if old_router.get("router_ap_ssid"):
        ap["ssid"] = str(old_router["router_ap_ssid"])
    if old_router.get("router_ap_password"):
        ap["password"] = str(old_router["router_ap_password"])

    enabled = router_groups.setdefault("enabled",
                                       _default_group("router", "enabled"))
    if old_router.get("wired_enabled") is False or \
            old_router.get("wifi_enabled") is False:
        enabled["enabled"] = False

    # drop the obsolete groups so they are never serialised again
    for key in ("wifi", "bluetooth", "router"):
        groups.pop(key, None)
    if not groups:
        peripherals.pop("groups", None)
    return configs



# connection interfaces: combo text -> default VISA-style address
_INSTRUMENT_CONN = {
    "daq973a": {"GPIB": "GPIB0::9::INSTR",
                "LAN (LXI)": "TCPIP0::192.168.1.10::inst0",
                "USB": "USB0::0x2A8D::0x0101::MY01000001::INSTR"},
    "m908a_1": {"via DAQ973A": "DAQ973A slot 1 (GPIB0::9)"},
    "m908a_2": {"via DAQ973A": "DAQ973A slot 2 (GPIB0::9)"},
    "m907a": {"via DAQ973A": "DAQ973A slot 3 (GPIB0::9)"},
    "u2355a": {"USB": "USB0::0x2A8D::0x3018::MY30180001::0::INSTR"},
    "psu": {"LAN (LXI)": "TCPIP0::192.168.1.20::inst0",
            "GPIB": "GPIB0::5::INSTR",
            "USB": "USB0::0x2A8D::0x2A01::MY57000001::INSTR"},
}

# *IDN? replies used by Test Connection
_INSTRUMENT_IDN = {
    "daq973a": "Keysight Technologies,DAQ973A,MY01000001,A.01.10",
    "m908a_1": "Keysight Technologies,DAQM908A,MY01000002,A.01.10",
    "m908a_2": "Keysight Technologies,DAQM908A,MY01000003,A.01.10",
    "m907a": "Keysight Technologies,DAQM907A,MY01000004,A.01.10",
    "u2355a": "Keysight Technologies,U2355A,MY30180001,1.02",
    "psu": "Keysight Technologies,N5747A,MY57000001,D.00.03",
}

# Text lines drawn inside each block on the diagram.
DIAGRAM_LINES = {
    "host": ["Common Test Platform", "ICT / FCT / Flash / Reports"],
    "peripherals": ["Host PC links + Router (RJ45 / AP)",
                    "Media conv. · Display · Mic",
                    "Speaker · SD card · USB drive"],
    "m908a_1": ["40-ch SE MUX", "CH101 - CH140",
                "TP_P1 - TP_P40", "Ω + DCV reuse"],
    "m908a_2": ["40-ch SE MUX", "CH201 - CH240",
                "TP_P41 - TP_P80", "Ω + DCV reuse"],
    "m907a": ["TOT: 0-100 kHz->CLK1",
              "AO x2: ±12 V 16-bit",
              "DIO 16-ch open-drain"],
    "u_ai": ["Rails capture: 12 ch", "200 Hz / ch -> CSV",
             "±10 V, 16-bit"],
    "u_ctr": ["CTR0/1: 0.1 Hz - 6 MHz",
              "DIO 24 ch -> DUT GPIO",
              "AO x2 backup ±10 V"],
    "psu_detail": ["±OUT -> VIN+ / VIN−",
                   "±S -> 4-wire remote sense",
                   "V/I readback ≈1% (trend)"],
    "control_board": ["Port 1/2 open-drain", "4 signals used of 16"],
    "cell_press": ["H = press/clamp", "L = release"],
    "cell_inpos": ["H = locked", "L = unlocked"],
    "cell_presence": ["L = present", "H = absent"],
    "cell_estop": ["L = healthy", "H = triggered"],
    "grp_power": ["Power nets TP_P1 - TP_P80",
                  "12 critical rails (subset)",
                  "Ω + DCV -> DAQ973A",
                  "Up-seq -> U2355A"],
    "grp_clocks": ["CLK1 32.768 kHz", "CLK2 4 MHz", "CLK3 6 MHz"],
    "grp_adc": ["TP_ADC0 / TP_ADC1", "AO ±12 V 16-bit", "-> DUT ADC"],
    "grp_vin": ["VIN+ / VIN−", "5 / 12 / 24 / 48 V",
                "4-wire remote sense"],
    "grp_gnd": ["GND probes x2", "-> star plane"],
    "grp_gpio": ["TP_GPIO0 - TP_GPIO23 (24 ch)",
                 "drive/read/toggle via level shifter"],
}


# --------------------------------------------------------------------------
# station configuration (mode-aware notes; editable where meaningful)
# --------------------------------------------------------------------------
def _mock_configs():
    # dynamic Test-SW version (same source as the status bar label -
    # the static "v2.0.0" disagreed with the running build)
    try:
        from .gui_version import load_gui_version
        sw_version = f"mtk-gui {load_gui_version()[0]}"
    except Exception:                        # pragma: no cover - headless
        sw_version = "mtk-gui"
    return {
        # ---- layer 1 -----------------------------------------------------
        "host": {
            "title": "HOST PC",
            "fields": [
                ("Platform", "Common Test Platform"),
                ("Test SW", sw_version),
                ("OS", "Windows 11 Pro x64"),
                ("Functions", "ICT / FCT / Flash / Reports / Cloud"),
            ],
        },
        "peripherals": {
            "title": "Test Peripherals",
            "table": [
                ("Wired & Wireless Network", "Wired / Wi-Fi connectivity",
                 "Not connected"),
                ("Media Converter", "T1 / T1S media", "Not connected"),
                ("Display", "DSI-MIPI check", "Not connected"),
                ("Camera", "CSI-MIPI check", "Not connected"),
                ("Microphone / Earphone", "Audio path check", "Not connected"),
                ("Speaker", "Audio output check", "Not connected"),
            ],
            # M100: the station network / console configs moved into the
            # dedicated ``host_pc`` / ``router`` configs below.
        },
        "host_pc": {
            "title": "Host PC",
            "groups": {
                "serial": _default_serial_channels(),
                "ssh": _default_ssh_channel(),
                "rj45": _default_group("host_pc", "rj45"),
                "wifi": _default_group("host_pc", "wifi"),
                "bluetooth": _default_group("host_pc", "bluetooth"),
            },
        },
        "router": {
            "title": "Router",
            "groups": {
                "enabled": _default_group("router", "enabled"),
                "ethernet": _default_group("router", "ethernet"),
                "ap": _default_group("router", "ap"),
            },
        },
        # ---- layer 2: DAQ973A -------------------------------------------
        "daq973a": {
            "title": "DAQ973A Mainframe",
            "fields": [
                ("Model", "Keysight DAQ973A, 3 slots"),
                ("Built-in DMM", "6.5-digit (22-bit), DCV 0.003%"),
                ("Interfaces", "GPIB + LAN (LXI) + USB"),
                ("Scan speed", "up to 450 ch/s"),
                ("Frequency function", "3 Hz - 300 kHz"),
                # M49a §1.2: ONE config unit owns the three modules
                ("Modules", "DAQM908A #1 (Slot 1) / DAQM908A #2 (Slot 2) "
                            "/ DAQM907A (Slot 3)"),
                ("Status", "Available"),
            ],
        },
        "m908a_1": {
            "title": "DAQM908A #1",
            "fields": [
                ("Module", "DAQM908A 40-ch SE multiplexer"),
                ("Slot", "Slot 1"),
                ("Channels", "CH101 - CH140"),
                ("Test points", "TP_P1 - TP_P40"),
                ("Reuse", "2-wire Ω then DCV"),
                ("Status", "Available"),
            ],
        },
        "m908a_2": {
            "title": "DAQM908A #2",
            "fields": [
                ("Module", "DAQM908A 40-ch SE multiplexer"),
                ("Slot", "Slot 2"),
                ("Channels", "CH201 - CH240"),
                ("Test points", "TP_P41 - TP_P80"),
                ("Reuse", "2-wire Ω then DCV"),
                ("Status", "Available"),
            ],
        },
        "m907a": {
            "title": "DAQM907A",
            "fields": [
                ("Module", "DAQM907A multifunction"),
                ("Slot", "Slot 3"),
                ("Totalizer", "26-bit, 0 - 100 kHz -> CLK1"),
                ("Analog outputs", "2 x 16-bit, ±12 V, 15 mA/ch"),
                ("DIO", "16-ch open-drain, 42 V / 400 mA"),
                ("Status", "Available"),
            ],
        },
        # ---- layer 2: U2355A --------------------------------------------
        "u2355a": {
            "title": "U2355A",
            "fields": [
                ("Model", "Keysight U2355A USB DAQ"),
                ("Analog input", "16-bit, ±10 V, 250 kSa/s aggregate"),
                ("Counters", "2 x 0.1 Hz - 6 MHz"),
                ("Digital IO", "24 TTL channels"),
                ("AO (backup)", "2 x 12-bit ±10 V"),
                ("Status", "Available"),
            ],
        },
        "u_ai": {
            "title": "U2355A - Rails Capture",
            "short": "Rails Capture",
            "fields": [
                ("Channels", "12 rails, one per DUT power point"),
                ("Rate", "200 Hz per channel -> CSV log"),
                ("Range", "±10 V, 16-bit"),
                ("Share", "same timebase as the up-sequence"),
            ],
        },
        "u_ctr": {
            "title": "U2355A - Counters + DIO",
            "short": "Counters + DIO",
            "fields": [
                ("Counters", "CTR0 / CTR1: 0.1 Hz - 6 MHz"),
                ("CLK2 / CLK3", "4 MHz / 6 MHz"),
                ("Digital IO", "24 ch -> DUT GPIO"),
                ("Level match", "level shifter 1.8 / 3.3 / 5 V"),
                ("AO backup", "2 ch ±10 V, 12-bit"),
            ],
        },
        # ---- layer 2: PSU ------------------------------------------------
        "psu": {
            "title": "N5747A DC Power Supply",
            "fields": [
                ("Model", "Keysight N5747A"),
                ("Output", "60 V / 12.5 A / 750 W"),
                ("Remote sense", "4-wire ±S at the load"),
                ("Interfaces", "LAN (LXI) + USB + GPIB"),
                ("J1", "analog program + RI/FLT inhibit"),
                ("Status", "Available"),
            ],
        },
        "psu_detail": {
            "title": "N5747A - Output & Sense",
            "fields": [
                ("Output", "±OUT -> VIN+ / VIN−"),
                ("Remote sense", "±S -> 4-wire at the load"),
                ("Readback", "V/I readback ≈1% (trend only)"),
                ("J1", "analog program + RI/FLT hardware inhibit"),
                ("Voltages", "5 / 12 / 24 / 48 V profiles"),
            ],
        },
        # ---- layer 3 -----------------------------------------------------
        "fixture": {
            "title": "Fixture",
            "fields": [
                ("Board", "Probe board with star ground plane"),
                ("Probe pins", "128 pinhole pins"),
                ("Power net points", "TP_P1 - TP_P80"),
                ("Grounding", "single-point star plane"),
                ("IO board", "ATE fixture control board"),
            ],
        },
        "control_board": {
            "title": "ATE Fixture Control Board",
            "fields": [
                ("Board", "ATE fixture control board"),
                ("Driven by", "DAQM907A Port 1/2 open-drain"),
                ("Pull-up", "external; 42 V / 400 mA"),
                ("Channels", "16 (4 used)"),
            ],
            # M49a §5: the 4 DIO signals (Press / In-Position / DUT
            # Presence / E-Stop) are part of the control-board config.
            # M80-5: channel + direction, stored as control_board.signals.
            "groups": {
                "signals": {
                    key: {"channel": channel, "direction": direction}
                    for key, _label, channel, direction in DIO_SIGNALS},
            },
        },
        "cell_press": {
            "title": "[OUT] Press Cylinder",
            "short": "Press Cylinder",
            "fields": [
                ("Signal", "digital output"),
                ("High", "press / clamp down"),
                ("Low", "release"),
            ],
        },
        "cell_inpos": {
            "title": "[IN] Cylinder In-Position",
            "short": "Cyl In-Position",
            "fields": [
                ("Signal", "digital input"),
                ("High", "locked"),
                ("Low", "unlocked"),
            ],
        },
        "cell_presence": {
            "title": "[IN] DUT Presence",
            "short": "DUT Presence",
            "fields": [
                ("Signal", "digital input, active-low"),
                ("High", "absence"),
                ("Low", "presence"),
            ],
        },
        "cell_estop": {
            "title": "[IN] E-Stop Healthy",
            "short": "E-Stop",
            "fields": [
                ("Signal", "digital input, active-low"),
                ("High", "unhealthy / triggered"),
                ("Low", "healthy"),
            ],
        },
        # ---- layer 4 -----------------------------------------------------
        "dut": {
            "title": "DUT Board",
            "fields": [
                ("DUT", "DUT board via fixture probes"),
                ("Probe pads", ">32 mils (typical 40 mils)"),
                ("Power nets", "TP_P1 - TP_P80"),
                ("GPIO nets", "TP_GPIO0 - TP_GPIO23"),
                ("Reference", "stress / strain gauge"),
            ],
            # M100: DUT-side Wi-Fi / Bluetooth / SSH / console / ethernet
            # moved into the FCT steps; the Console panel still mirrors
            # its serial / SSH channels into ``equipment.dut.console.*`` /
            # ``equipment.dut.ssh.*`` at runtime.
            "groups": {},
        },
        "grp_power": {
            "title": "Power Nets TP_P1-P80",
            "fields": [
                ("Group", "Power nets TP_P1 - TP_P80"),
                ("Subset", "12 critical rails for up-sequence"),
                ("Tests", "2-wire Ω + DCV via DAQ973A"),
                ("Up-sequence", "12 ch via U2355A -> CSV + waveform"),
                ("Judgment", "±0.1% via DAQ973A"),
                ("Ω threshold", "R_min = V_rail / I_allow, 1.5 Ω tol"),
            ],
        },
        "grp_clocks": {
            "title": "Clock Nets",
            "fields": [
                ("CLK1", "32.768 kHz -> 907A totalizer"),
                ("CLK2", "4 MHz -> U2355A CTR0"),
                ("CLK3", "6 MHz -> U2355A CTR1"),
            ],
        },
        "grp_adc": {
            "title": "ADC Input",
            "fields": [
                ("Inputs", "TP_ADC0 / TP_ADC1"),
                ("Stimulus", "907A AO0 / AO1, ±12 V 16-bit"),
                ("Test", "DUT ADC readback"),
            ],
        },
        "grp_vin": {
            "title": "Main Power Input",
            "fields": [
                ("Inputs", "VIN+ / VIN−"),
                ("Voltages", "5 / 12 / 24 / 48 V"),
                ("Sense", "4-wire remote at the load"),
            ],
        },
        "grp_gnd": {
            "title": "GND Probes",
            "fields": [
                ("Probes", "GND x2"),
                ("Connection", "-> star ground plane"),
            ],
        },
        "grp_gpio": {
            "title": "GPIO Nets",
            "fields": [
                ("Nets", "TP_GPIO0 - TP_GPIO23 (24 ch)"),
                ("Driven by", "U2355A DIO via level shifter"),
                ("Tests", "drive HI/LO, read back, toggle"),
            ],
        },
    }


# --------------------------------------------------------------------------
# vector icons (48x48 design space, painted inside diagram blocks)
# --------------------------------------------------------------------------
def _p(painter, color, width=2.4):
    """Stroke pen with round caps/joins."""
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _fill(painter, color):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))


def _ic_pc(p):
    _p(p, INK)
    p.drawRoundedRect(QRectF(4, 9, 26, 17), 2, 2)
    _fill(p, INK)
    p.drawRect(QRectF(7.5, 12.5, 19, 10))
    _p(p, INK)
    p.drawLine(QPointF(17, 26), QPointF(17, 31))
    p.drawLine(QPointF(11, 31), QPointF(23, 31))
    p.drawRoundedRect(QRectF(35, 10, 9, 25), 1.5, 1.5)
    p.drawLine(QPointF(37.5, 15), QPointF(41.5, 15))
    p.drawLine(QPointF(37.5, 19), QPointF(41.5, 19))
    _fill(p, GREEN)
    p.drawEllipse(QPointF(39.5, 29.5), 1.3, 1.3)


def _ic_mculink(p):
    _fill(p, STEEL)
    p.drawRoundedRect(QRectF(17, 5, 12, 7), 1, 1)
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(15, 12, 18, 21), 2.5, 2.5)
    path = QPainterPath(QPointF(33, 18))
    path.lineTo(QPointF(39, 18))
    path.lineTo(QPointF(39, 27))
    p.drawPath(path)
    for x in (19, 24, 29):
        p.drawLine(QPointF(x, 33), QPointF(x, 37))
    _fill(p, GREEN)
    p.drawEllipse(QPointF(21, 18), 1.6, 1.6)


def _ic_opensda(p):
    _fill(p, STEEL)
    p.drawRoundedRect(QRectF(19, 4, 10, 6), 1, 1)
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(16, 10, 16, 23), 2.5, 2.5)
    p.drawRoundedRect(QRectF(19, 25, 10, 4), 1, 1)
    for x in (20, 28):
        p.drawLine(QPointF(x, 33), QPointF(x, 37))
    _fill(p, GREEN)
    p.drawEllipse(QPointF(24, 16.5), 1.6, 1.6)


def _ic_wifi(p):
    _p(p, BLUE, 2.6)
    p.drawArc(QRectF(15.5, 24.6, 17, 7.8), 0, 180 * 16)
    p.drawArc(QRectF(9.5, 22.5, 29, 12), 0, 180 * 16)
    _fill(p, BLUE)
    p.drawEllipse(QPointF(24, 36), 2.6, 2.6)


def _ic_bt(p):
    _p(p, BLUE, 2.6)
    p.drawLine(QPointF(24, 5), QPointF(24, 43))
    path = QPainterPath(QPointF(24, 5))
    path.lineTo(QPointF(33.5, 13))
    path.lineTo(QPointF(14.5, 29))
    path.moveTo(QPointF(24, 43))
    path.lineTo(QPointF(33.5, 35))
    path.lineTo(QPointF(14.5, 19))
    p.drawPath(path)


def _ic_console(p):
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(5, 9, 38, 30), 3, 3)
    p.drawLine(QPointF(5, 16), QPointF(43, 16))
    _fill(p, STEEL)
    p.drawEllipse(QPointF(9.5, 12.5), 1.1, 1.1)
    p.drawEllipse(QPointF(13.5, 12.5), 1.1, 1.1)
    _p(p, TEAL, 2.4)
    path = QPainterPath(QPointF(12, 23))
    path.lineTo(QPointF(17.5, 27.5))
    path.lineTo(QPointF(12, 32))
    p.drawPath(path)
    p.drawLine(QPointF(21.5, 32), QPointF(28.5, 32))


def _ic_router(p):
    _p(p, GRAY)
    p.drawLine(QPointF(15, 24), QPointF(11.5, 13))
    p.drawLine(QPointF(33, 24), QPointF(36.5, 13))
    p.drawEllipse(QPointF(10.5, 11), 1.6, 1.6)
    p.drawEllipse(QPointF(37.5, 11), 1.6, 1.6)
    _p(p, TEAL)
    p.drawRoundedRect(QRectF(7, 24, 34, 12), 5, 5)
    _fill(p, GREEN)
    p.drawEllipse(QPointF(14, 30), 1.5, 1.5)
    _fill(p, STEEL)
    p.drawEllipse(QPointF(20, 30), 1.5, 1.5)
    p.drawEllipse(QPointF(26, 30), 1.5, 1.5)


def _ic_media(p):
    _p(p, TEAL)
    p.drawRoundedRect(QRectF(5, 16, 38, 16), 2, 2)
    p.drawRoundedRect(QRectF(9, 20, 8, 8), 1, 1)
    _p(p, GRAY, 2.2)
    p.drawLine(QPointF(21, 24), QPointF(27, 24))
    p.drawLine(QPointF(24.5, 21.5), QPointF(27, 24))
    p.drawLine(QPointF(24.5, 26.5), QPointF(27, 24))
    _p(p, TEAL)
    p.drawEllipse(QPointF(36, 24), 3.2, 3.2)


def _ic_display(p):
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(5, 9, 38, 23), 2, 2)
    _fill(p, INK)
    p.drawRect(QRectF(8.5, 12.5, 31, 16))
    _p(p, GRAY)
    p.drawLine(QPointF(24, 32), QPointF(24, 37))
    p.drawLine(QPointF(16, 37), QPointF(32, 37))


def _ic_camera(p):
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(6, 14, 36, 22), 3, 3)
    p.drawRoundedRect(QRectF(17, 10, 14, 5), 1.5, 1.5)
    p.drawEllipse(QPointF(24, 25), 6.8, 6.8)
    _fill(p, BLUE)
    p.drawEllipse(QPointF(24, 25), 2.6, 2.6)
    _fill(p, GREEN)
    p.drawEllipse(QPointF(37, 19.5), 1.3, 1.3)


def _ic_mic(p):
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(19, 6, 10, 19), 5, 5)
    p.drawArc(QRectF(13, 21, 22, 11), 180 * 16, 180 * 16)
    p.drawLine(QPointF(24, 32), QPointF(24, 38))
    p.drawLine(QPointF(17, 38), QPointF(31, 38))


def _ic_speaker(p):
    _p(p, GRAY)
    p.setBrush(QColor(PANEL))
    path = QPainterPath(QPointF(13, 19))
    path.lineTo(QPointF(19.5, 19))
    path.lineTo(QPointF(29, 10))
    path.lineTo(QPointF(29, 38))
    path.lineTo(QPointF(19.5, 29))
    path.lineTo(QPointF(13, 29))
    path.closeSubpath()
    p.drawPath(path)
    _p(p, TEAL, 2.2)
    p.drawArc(QRectF(16.25, 14.5, 19, 19), -35 * 16, 70 * 16)
    p.drawArc(QRectF(10.66, 8.5, 31, 31), -40 * 16, 80 * 16)


def _ic_daq973a(p):
    _p(p, INK, 2)
    p.setBrush(QColor(PANEL))
    p.drawRoundedRect(QRectF(3, 12, 42, 26), 2, 2)
    _fill(p, GOLD)
    p.drawRoundedRect(QRectF(4, 12.8, 40, 2.6), 1.3, 1.3)
    p.setPen(QPen(QColor(INK), 1.4))
    p.setBrush(QColor(LCD))
    p.drawRoundedRect(QRectF(7, 18, 13, 9), 1, 1)
    _p(p, INK, 1.4)
    p.drawLine(QPointF(9, 30), QPointF(18, 30))
    p.setBrush(QColor(LCD_ROW))
    p.drawEllipse(QPointF(13.5, 34), 3, 3)
    _fill(p, INK)
    p.drawEllipse(QPointF(13.5, 34), 1, 1)
    _fill(p, BLUE)
    p.drawRoundedRect(QRectF(24, 17, 5.5, 17), 1, 1)
    p.drawRoundedRect(QRectF(31.5, 17, 5.5, 17), 1, 1)
    p.drawRoundedRect(QRectF(39, 17, 5, 17), 1, 1)
    _fill(p, "#ffffff")
    p.drawEllipse(QPointF(26.7, 20.5), 0.8, 0.8)
    p.drawEllipse(QPointF(34.2, 20.5), 0.8, 0.8)
    _p(p, INK, 2)
    p.drawLine(QPointF(8, 38), QPointF(8, 41))
    p.drawLine(QPointF(40, 38), QPointF(40, 41))


def _ic_m908a(p):
    _p(p, NAVY, 2)
    p.setBrush(QColor(BLUE_FILL))
    p.drawRoundedRect(QRectF(12, 4, 24, 36), 2, 2)
    _fill(p, "#93c5fd")
    for x in (16.5, 21.5, 26.5, 31.5):
        p.drawEllipse(QPointF(x, 10), 1.7, 1.7)
    _fill(p, CARD_BLUE)
    p.drawRect(QRectF(15, 15, 18, 12))
    _fill(p, INK)
    p.drawRoundedRect(QRectF(14, 32, 20, 5), 1, 1)


def _ic_m907a(p):
    _p(p, NAVY, 2)
    p.setBrush(QColor(BLUE_FILL))
    p.drawRoundedRect(QRectF(12, 4, 24, 36), 2, 2)
    p.setPen(QPen(QColor(NAVY), 1.4))
    p.setBrush(QColor(CARD_BLUE))
    p.drawRoundedRect(QRectF(15, 9, 8, 8), 1, 1)
    p.drawRoundedRect(QRectF(25, 9, 8, 8), 1, 1)
    _fill(p, "#93c5fd")
    for x in (19, 24, 29):
        p.drawEllipse(QPointF(x, 24), 1.7, 1.7)
    _fill(p, INK)
    p.drawRoundedRect(QRectF(14, 32, 20, 5), 1, 1)


def _ic_u2355a(p):
    _p(p, TEAL_DARK, 2)
    p.setBrush(QColor(TEAL_FILL))
    p.drawRoundedRect(QRectF(4, 14, 38, 20), 2, 2)
    _fill(p, CARD_TEAL)
    for x, y in ((8, 18), (14, 18), (8, 24), (14, 24),
                 (27, 18), (33, 18), (27, 24), (33, 24)):
        p.drawRect(QRectF(x, y, 5, 5))
    _fill(p, GREEN)
    p.drawEllipse(QPointF(23.5, 23.5), 1.8, 1.8)
    _fill(p, STEEL)
    p.drawRoundedRect(QRectF(42, 20, 4, 8), 1, 1)


def _ic_psu(p):
    _p(p, AMBER_DARK, 2)
    p.setBrush(QColor(AMBER_FILL))
    p.drawRoundedRect(QRectF(3, 15, 42, 18), 2, 2)
    _fill(p, HONEY)
    p.drawRoundedRect(QRectF(7, 19, 10, 7), 1, 1)
    p.setPen(QPen(QColor(AMBER_DARK), 1.6))
    p.setBrush(QColor(HONEY))
    p.drawEllipse(QPointF(23, 24), 3.2, 3.2)
    _fill(p, RED)
    p.drawEllipse(QPointF(33.5, 24), 2, 2)
    _fill(p, INK)
    p.drawEllipse(QPointF(38.5, 24), 2, 2)
    _fill(p, RED)
    p.drawEllipse(QPointF(43, 24), 2, 2)
    _p(p, AMBER_DARK, 1.4)
    p.drawLine(QPointF(7, 29.5), QPointF(15, 29.5))


def _ic_fixture(p):
    _p(p, GRAY, 2.2)
    p.setBrush(QColor(PAPER))
    p.drawRoundedRect(QRectF(6, 6, 36, 31), 3, 3)
    _fill(p, MIST)
    for y in (12, 17, 22, 27):
        for x in (11.5, 16.7, 21.9, 27.1, 32.3):
            p.drawEllipse(QPointF(x, y), 1.4, 1.4)
    p.setPen(QPen(QColor(RED), 1.6))
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(QPointF(24, 32.5), 3, 3)
    _fill(p, STEEL)
    p.drawRoundedRect(QRectF(12, 39, 24, 4.5), 1, 1)


def _ic_ate_board(p):
    _p(p, TEAL_DARK, 2.2)
    p.setBrush(QColor(PAPER))
    p.drawRoundedRect(QRectF(8, 6, 32, 32), 2, 2)
    p.setPen(QPen(QColor(TEAL_DARK), 1.5))
    p.setBrush(QColor(SOFT_TEAL))
    p.drawRoundedRect(QRectF(12, 11, 9, 9), 1, 1)
    p.drawRoundedRect(QRectF(27, 11, 9, 9), 1, 1)
    _p(p, STEEL, 1.4)
    path = QPainterPath(QPointF(16.5, 20))
    path.lineTo(QPointF(16.5, 27))
    path.lineTo(QPointF(31.5, 27))
    path.lineTo(QPointF(31.5, 20))
    p.drawPath(path)
    _fill(p, STEEL)
    for x in (13, 18, 23, 28, 33):
        p.drawEllipse(QPointF(x, 32), 1.5, 1.5)


def _ic_cylinder(p):
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(5, 17, 26, 13), 2, 2)
    _fill(p, MIST)
    p.drawRect(QRectF(9, 20.5, 4, 6))
    _p(p, GRAY)
    p.drawLine(QPointF(31, 23.5), QPointF(40, 23.5))
    p.drawRoundedRect(QRectF(40, 20, 4.5, 7), 1, 1)
    _p(p, RED, 2.2)
    p.drawLine(QPointF(18, 35), QPointF(18, 40))
    path = QPainterPath(QPointF(14.5, 36.5))
    path.lineTo(QPointF(18, 40))
    path.lineTo(QPointF(21.5, 36.5))
    p.drawPath(path)


def _ic_inpos(p):
    _p(p, GRAY)
    p.drawEllipse(QPointF(24, 24), 13.5, 13.5)
    _p(p, "#16a34a", 3)
    path = QPainterPath(QPointF(17.5, 24.5))
    path.lineTo(QPointF(22, 29))
    path.lineTo(QPointF(30.5, 19))
    p.drawPath(path)


def _ic_presence(p):
    _p(p, GRAY, 2.2)
    p.setBrush(QColor(PAPER))
    p.drawRoundedRect(QRectF(14, 11, 20, 21), 2, 2)
    for x in (18, 24, 30):
        p.drawLine(QPointF(x, 11), QPointF(x, 6))
        p.drawLine(QPointF(x, 32), QPointF(x, 37))
    _p(p, "#16a34a")
    p.drawEllipse(QPointF(24, 21.5), 4, 4)


def _ic_estop(p):
    _p(p, RED, 2.2)
    path = QPainterPath(QPointF(11, 27))
    path.arcTo(QRectF(11, 17, 26, 20), 180, -180)
    path.closeSubpath()
    p.setBrush(QColor(BLUSH))
    p.drawPath(path)
    p.setBrush(QColor(PAPER))
    p.drawRoundedRect(QRectF(8, 27, 32, 5.5), 1.5, 1.5)
    _p(p, INK, 2.2)
    path = QPainterPath(QPointF(20, 32.5))
    path.lineTo(QPointF(20, 37))
    path.lineTo(QPointF(28, 37))
    path.lineTo(QPointF(28, 32.5))
    p.drawPath(path)


def _ic_dut(p):
    _p(p, PURPLE, 2.2)
    p.setBrush(QColor(PURPLE_FILL))
    p.drawRoundedRect(QRectF(6, 6, 36, 32), 3, 3)
    _fill(p, PURPLE)
    p.drawRoundedRect(QRectF(18, 16, 12, 12), 1.5, 1.5)
    _p(p, LILAC, 1.6)
    path = QPainterPath()
    path.moveTo(QPointF(18, 20))
    path.lineTo(QPointF(12, 20))
    path.lineTo(QPointF(12, 13))
    path.moveTo(QPointF(30, 20))
    path.lineTo(QPointF(36, 20))
    path.lineTo(QPointF(36, 13))
    path.moveTo(QPointF(18, 26))
    path.lineTo(QPointF(12, 26))
    path.lineTo(QPointF(12, 32))
    path.moveTo(QPointF(30, 26))
    path.lineTo(QPointF(36, 26))
    path.lineTo(QPointF(36, 32))
    p.drawPath(path)
    _fill(p, LILAC)
    for x, y in ((11.5, 12.5), (36.5, 12.5), (11.5, 33), (36.5, 33)):
        p.drawEllipse(QPointF(x, y), 1.4, 1.4)
    _fill(p, GOLD)
    p.drawRoundedRect(QRectF(14, 40, 20, 3.5), 1, 1)


_ICONS = {
    "pc": _ic_pc, "mculink": _ic_mculink, "opensda": _ic_opensda,
    "wifi": _ic_wifi, "bt": _ic_bt, "console": _ic_console,
    "router": _ic_router, "media": _ic_media, "display": _ic_display,
    "camera": _ic_camera, "mic": _ic_mic, "speaker": _ic_speaker,
    "daq973a": _ic_daq973a, "m908a": _ic_m908a, "m907a": _ic_m907a,
    "u2355a": _ic_u2355a, "psu": _ic_psu, "fixture": _ic_fixture,
    "ate": _ic_ate_board, "cylinder": _ic_cylinder, "inpos": _ic_inpos,
    "presence": _ic_presence, "estop": _ic_estop, "dut": _ic_dut,
}


def draw_icon(painter, key, rect):
    """Paint the vector icon `key` scaled into `rect` (48x48 design)."""
    fn = _ICONS.get(key)
    if fn is None:
        return
    painter.save()
    painter.translate(rect.x(), rect.y())
    scale = rect.width() / 48.0
    painter.scale(scale, scale)
    fn(painter)
    painter.restore()


class IconItem(QGraphicsRectItem):
    """Free-standing vector icon placed directly on the diagram scene."""

    def __init__(self, key, x, y, size):
        super().__init__(x, y, size, size)
        self._key = key

    def boundingRect(self):
        return QRectF(self.rect()).adjusted(-1, -1, 1, 1)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_icon(painter, self._key, self.rect())


# --------------------------------------------------------------------------
# block item
# --------------------------------------------------------------------------
class BlockItem(QGraphicsRectItem):
    """Rounded clickable block.

    Modes:
      * dark   - filled dark block with white title (HOST PC)
      * header - white block with a colored header band
      * plain  - white block, colored bold title, body lines
    """

    def __init__(self, key, title, border, lines=None, fill="#ffffff",
                 mode="plain", abbr=None, icon=None, icon_pos="row",
                 icon_size=None):
        super().__init__()
        self.key = key
        self.title = title
        self.lines = lines or []
        self.border = QColor(border)
        self.fill = QColor(fill)
        self.mode = mode
        self.abbr = abbr
        # vector icon(s) drawn inside the block (see _ICONS):
        #   icon      - _ICONS key (str) or list of keys (icon_pos="row")
        #   icon_pos  - row | left | mid | top | beside | header
        #   icon_size - icon box in scene px (default per layout)
        self.icon = icon
        self.icon_pos = icon_pos
        self.icon_size = icon_size
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to configure")

    def boundingRect(self):
        return QRectF(self.rect())

    def shape(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        return path

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if self.mode == "dark":
            self._paint_dark(painter, rect)
        elif self.mode == "band":
            painter.setPen(QPen(self.border, 1.6))
            painter.setBrush(self.fill)
            painter.drawRoundedRect(rect, 8, 8)
        elif self.mode == "header":
            self._paint_header(painter, rect)
        else:
            self._paint_plain(painter, rect)

    # ------------------------------------------------------------------
    def _paint_dark(self, painter, rect):
        painter.setPen(QPen(QColor("#1e293b"), 1.5))
        painter.setBrush(QColor("#334155"))
        painter.drawRoundedRect(rect, 8, 8)

        if self.icon:
            # HOST PC: white icon chip on the left, text block right -
            # no overlap between the icon and the title / body lines
            chip = QPointF(rect.left() + 24, rect.center().y())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(chip, 24, 24)
            draw_icon(painter, self.icon,
                      QRectF(chip.x() - 17, chip.y() - 17, 34, 34))
            tx = rect.left() + 60
            painter.setPen(QPen(QColor("#ffffff"), 1))
            font = QFont()
            font.setPointSizeF(12)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(tx, rect.top() + 18,
                                    rect.right() - tx - 8, 28),
                             Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter, self.title)
            painter.setPen(QPen(QColor("#cbd5e1"), 1))
            font = QFont()
            font.setPointSizeF(10)
            painter.setFont(font)
            y = rect.top() + 52
            for line in self.lines:
                painter.drawText(QRectF(tx, y, rect.right() - tx - 8, 18),
                                 Qt.AlignmentFlag.AlignLeft, line)
                y += 18
            return

        painter.setPen(QPen(QColor("#ffffff"), 1))
        font = QFont()
        font.setPointSizeF(12)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(rect.left(), rect.top() + 4, rect.width(), 28),
                         Qt.AlignmentFlag.AlignHCenter
                         | Qt.AlignmentFlag.AlignVCenter, self.title)
        painter.setPen(QPen(QColor("#cbd5e1"), 1))
        font = QFont()
        font.setPointSizeF(10)
        painter.setFont(font)
        y = rect.top() + 36
        for line in self.lines:
            painter.drawText(QRectF(rect.left(), y, rect.width(), 18),
                             Qt.AlignmentFlag.AlignHCenter, line)
            y += 18

    def _paint_header(self, painter, rect):
        header_h = 34
        painter.setPen(QPen(self.border, 2))
        painter.setBrush(self.fill)
        painter.drawRoundedRect(rect, 8, 8)

        # header band (square bottom overlaps the rounded body)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.border)
        painter.drawRect(QRectF(rect.left() + 1, rect.top() + 1,
                                rect.width() - 2, header_h))
        tx = rect.left() + 8
        if self.icon:
            # white chip + instrument icon at the left of the header band
            chip = QPointF(rect.left() + 25, rect.top() + 17)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(chip, 16, 16)
            draw_icon(painter, self.icon,
                      QRectF(chip.x() - 12, chip.y() - 12, 24, 24))
            tx = rect.left() + 50
        painter.setPen(QPen(QColor("#ffffff"), 1))
        font = QFont()
        font.setPointSizeF(11)
        font.setBold(True)
        painter.setFont(font)
        badge_w = 50 if self.abbr else 0
        painter.drawText(QRectF(tx, rect.top(),
                                rect.right() - tx - 8 - badge_w, header_h),
                         Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter, self.title)

        if self.abbr:
            badge = QRectF(rect.right() - badge_w + 4, rect.top() + 5,
                           badge_w - 12, header_h - 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ffffff"))
            painter.drawRoundedRect(badge, 5, 5)
            painter.setPen(QPen(self.border, 1))
            abbr_font = QFont()
            abbr_font.setPointSizeF(10.5)
            abbr_font.setBold(True)
            painter.setFont(abbr_font)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.abbr)

        painter.setPen(QPen(QColor(TEXT), 1))
        font = QFont()
        font.setPointSizeF(9.5)
        painter.setFont(font)
        y = rect.top() + header_h + 8
        for line in self.lines:
            painter.drawText(QRectF(rect.left() + 8, y,
                                    rect.width() - 16, 17),
                             Qt.AlignmentFlag.AlignLeft, line)
            y += 17

    def _paint_plain(self, painter, rect):
        painter.setPen(QPen(self.border, 1.6))
        painter.setBrush(self.fill)
        painter.drawRoundedRect(rect, 7, 7)

        if self.icon:
            if self.icon_pos == "top":
                self._paint_cell(painter, rect)
                return
            if self.icon_pos == "mid":
                self._paint_mid(painter, rect)
                return
            if self.icon_pos == "left":
                self._paint_left(painter, rect)
                return
            if self.icon_pos == "beside":
                self._paint_beside(painter, rect)
                return
            if self.icon_pos == "row":
                self._paint_row(painter, rect)
                return

        self._title(painter, rect)
        painter.setPen(QPen(QColor(TEXT), 1))
        font = QFont()
        font.setPointSizeF(9.5)
        painter.setFont(font)
        y = rect.top() + 29
        for line in self.lines:
            painter.drawText(QRectF(rect.left() + 5, y,
                                    rect.width() - 10, 17),
                             Qt.AlignmentFlag.AlignLeft, line)
            y += 17

    # ------------------------------------------------------ icon layouts
    def _title(self, painter, rect):
        painter.setPen(QPen(self.border, 1))
        font = QFont()
        font.setPointSizeF(10.5)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(rect.left() + 5, rect.top() + 4,
                                rect.width() - 10, 22),
                         Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter, self.title)

    def _paint_row(self, painter, rect):
        """Title + text lines on top, icon row along the bottom."""
        self._title(painter, rect)
        painter.setPen(QPen(QColor(TEXT), 1))
        font = QFont()
        font.setPointSizeF(9.5)
        painter.setFont(font)
        y = rect.top() + 29
        for line in self.lines:
            painter.drawText(QRectF(rect.left() + 5, y,
                                    rect.width() - 10, 17),
                             Qt.AlignmentFlag.AlignLeft, line)
            y += 17
        keys = self.icon if isinstance(self.icon, (list, tuple)) \
            else [self.icon]
        n = len(keys)
        size = self.icon_size or 28
        y0 = rect.bottom() - size - 10
        span = rect.width() - 24
        for i, key in enumerate(keys):
            cx = rect.left() + 12 + span * (i + 0.5) / n
            draw_icon(painter, key, QRectF(cx - size / 2, y0, size, size))

    def _paint_mid(self, painter, rect):
        """Title, centered icon, centered text lines (module cards)."""
        self._title(painter, rect)
        size = self.icon_size or 34
        cx = rect.center().x()
        draw_icon(painter, self.icon,
                  QRectF(cx - size / 2, rect.top() + 30, size, size))
        painter.setPen(QPen(QColor(TEXT), 1))
        font = QFont()
        font.setPointSizeF(9.5)
        painter.setFont(font)
        y = rect.top() + 30 + size + 8
        for line in self.lines:
            painter.drawText(QRectF(rect.left() + 5, y,
                                    rect.width() - 10, 17),
                             Qt.AlignmentFlag.AlignHCenter, line)
            y += 17

    def _paint_left(self, painter, rect):
        """Title on top; icon on the left, text lines to its right."""
        self._title(painter, rect)
        size = self.icon_size or 40
        draw_icon(painter, self.icon,
                  QRectF(rect.left() + 12, rect.top() + 36, size, size))
        tx = rect.left() + 12 + size + 16
        painter.setPen(QPen(QColor(TEXT), 1))
        font = QFont()
        font.setPointSizeF(9.5)
        painter.setFont(font)
        y = rect.top() + 38
        for line in self.lines:
            painter.drawText(QRectF(tx, y, rect.right() - tx - 8, 18),
                             Qt.AlignmentFlag.AlignLeft, line)
            y += 19

    def _paint_beside(self, painter, rect):
        """Title + lines on the left, icon on the right."""
        self._title(painter, rect)
        painter.setPen(QPen(QColor(TEXT), 1))
        font = QFont()
        font.setPointSizeF(9.5)
        painter.setFont(font)
        y = rect.top() + 29
        for line in self.lines:
            painter.drawText(QRectF(rect.left() + 5, y,
                                    rect.width() - 10, 17),
                             Qt.AlignmentFlag.AlignLeft, line)
            y += 17
        size = self.icon_size or 38
        draw_icon(painter, self.icon,
                  QRectF(rect.right() - size - 14, rect.top() + 16,
                         size, size))

    def _paint_cell(self, painter, rect):
        """Centered icon on top, centered title below (fixture IO cells)."""
        size = self.icon_size or 22
        cx = rect.center().x()
        draw_icon(painter, self.icon,
                  QRectF(cx - size / 2, rect.top() + 6, size, size))
        painter.setPen(QPen(self.border, 1))
        font = QFont()
        font.setPointSizeF(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(rect.left() + 4, rect.top() + 32,
                                rect.width() - 8, 20),
                         Qt.AlignmentFlag.AlignHCenter
                         | Qt.AlignmentFlag.AlignVCenter, self.title)


# --------------------------------------------------------------------------
# view + line helpers
# --------------------------------------------------------------------------
class BlockDiagramView(QGraphicsView):
    zoomChanged = Signal()

    #: M54 §3: zoom range 50 % .. 300 %
    MIN_ZOOM, MAX_ZOOM = 0.5, 3.0
    #: M54 §5: the viewport background never scales with the diagram
    BACKGROUND = QColor("#fbfdff")

    def __init__(self, scene, on_block, parent=None):
        super().__init__(scene, parent)
        self._on_block = on_block
        self._auto_fit = True  # fit whole diagram until user zooms manually
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter)

    # ------------------------------------------------- background (M54 §5)
    def _background_rect(self):
        """The background rectangle in VIEWPORT coordinates - it keeps
        the viewport size no matter what the zoom transform is."""
        return QRectF(self.viewport().rect())

    def drawBackground(self, painter, rect):
        """Paint the flat viewport background here.

        The painter is reset to viewport coordinates before the fill, so
        Zoom In / Zoom Out only transform the foreground items (blocks,
        connectors, labels) and never enlarge / shrink the background.
        """
        painter.save()
        painter.resetTransform()
        painter.fillRect(self._background_rect(), self.BACKGROUND)
        painter.restore()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        """Scale so the whole diagram fills the view (default on 1920x1080)."""
        if not self._auto_fit:
            return
        rect = self.scene().sceneRect()
        if rect.isEmpty():
            return
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.zoomChanged.emit()

    def zoom_in(self):
        self._zoom_by(1.25)

    def zoom_out(self):
        self._zoom_by(0.8)

    def zoom_reset(self):
        """Back to true 100% (1:1 pixels)."""
        self._auto_fit = False
        self.resetTransform()
        self.zoomChanged.emit()

    def _zoom_by(self, factor):
        if not self.MIN_ZOOM <= self.transform().m11() * factor <= self.MAX_ZOOM:
            return
        self._auto_fit = False
        self.scale(factor, factor)
        self.zoomChanged.emit()

    def mouseReleaseEvent(self, event):
        # left button only: right button opens the context menu
        if (event.button() == Qt.MouseButton.LeftButton
                and isinstance(self.itemAt(event.position().toPoint()),
                               BlockItem)):
            self._on_block(self.itemAt(event.position().toPoint()))
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        act_copy = menu.addAction("Copy Diagram as Image")
        chosen = menu.exec(event.globalPos())
        if chosen is act_copy:
            self._copy_diagram_image()

    def _copy_diagram_image(self):
        """Render the whole diagram (2x for crisp pasting) to the clipboard."""
        rect = self.scene().sceneRect()
        if rect.isEmpty():
            return
        scale = 2.0
        image = QImage(int(rect.width() * scale), int(rect.height() * scale),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.scene().render(
            painter,
            QRectF(0, 0, rect.width() * scale, rect.height() * scale), rect)
        painter.end()
        QGuiApplication.clipboard().setImage(image)
        QToolTip.showText(QCursor.pos(),
                          "Block diagram copied to clipboard")


def _polyline(scene, points, color=GRAY, width=2, dashed=False, arrow=True,
              z=-1):
    path = QPainterPath(points[0])
    for point in points[1:]:
        path.lineTo(point)
    pen = QPen(QColor(color), width)
    if dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
    item = QGraphicsPathItem(path)
    item.setPen(pen)
    item.setZValue(z)
    scene.addItem(item)

    if arrow:
        end, prev = points[-1], points[-2]
        dx = end.x() - prev.x()
        dy = end.y() - prev.y()
        length = (dx * dx + dy * dy) ** 0.5 or 1
        ux, uy = dx / length, dy / length
        size = 9
        base = QPointF(end.x() - ux * size, end.y() - uy * size)
        px, py = -uy * size * 0.6, ux * size * 0.6
        head = QPainterPath(end)
        head.lineTo(QPointF(base.x() + px, base.y() + py))
        head.moveTo(end)
        head.lineTo(QPointF(base.x() - px, base.y() - py))
        head_item = QGraphicsPathItem(head)
        head_item.setPen(QPen(QColor(color), width))
        head_item.setZValue(z)
        scene.addItem(head_item)
    return item


def _text(scene, text, x, y, color=SUB, size=10, bold=False, z=0):
    item = QGraphicsSimpleTextItem(text)
    item.setBrush(QColor(color))
    font = QFont()
    font.setPointSizeF(size)
    font.setBold(bold)
    item.setFont(font)
    item.setPos(x, y)
    item.setZValue(z)
    scene.addItem(item)
    return item


def _rect(scene, x, y, w, h, fill, border=None, radius=0, z=-2):
    item = QGraphicsRectItem(x, y, w, h)
    item.setBrush(QColor(fill))
    if border:
        item.setPen(QPen(QColor(border), 1.4))
    else:
        item.setPen(Qt.PenStyle.NoPen)
    item.setZValue(z)
    scene.addItem(item)
    return item


# --------------------------------------------------------------------------
# configuration dialogs
# --------------------------------------------------------------------------
def _mode_note(mode: str, *, instrument: bool = False) -> str:
    """Mode-aware footnote for the configuration dialogs (user report:
    the static 'Demo mode' note was wrong in Real mode)."""
    if mode == MODE_VIRTUAL:
        return ("Virtual mode - connect / test succeed (simulated)."
                if instrument else
                "Virtual mode - the shown values are simulated.")
    return ("Real mode - configure the interface and address of the "
            "connected instrument."
            if instrument else
            "Real mode - the values reflect the connected test station.")


# editable test-station settings of the HOST PC block - persisted with
# the project YAML (cfg["params"], same mechanism as the instruments)
_HOST_TEST_PARAMS = [
    ("station_id", "Station ID", "STN-001"),
    ("operator", "Operator", ""),
    ("report_dir", "Report Directory", "./reports"),
    ("cloud_url", "Cloud Upload URL", ""),
    ("flash_tool", "Flash Tool Path", ""),
]

# per-block editable test configuration (user direction: keep the
# read-only basic info, add configurable fields).  Blocks NOT listed
# here are not integrated yet - their dialogs show the
# not-yet-available notice instead (persisted as cfg["params"])
_BLOCK_EDITORS = {
    "host": _HOST_TEST_PARAMS,
    "dut": [
        ("part_number", "DUT Part Number", ""),
        ("serial_number", "DUT Serial Number", ""),
        ("flash_image", "Flash Image Path", ""),
    ],
}

# per-device editors inside the TABLE dialogs (double-click a row);
# devices NOT listed here are not integrated yet - double-clicking
# shows the not-yet-available notice (persisted as
# cfg["device_params"][device], keys match the driver options).
_DEVICE_EDITORS: dict[tuple[str, str], list] = {}

_NOT_YET = "Not yet available - under development."


def _attach_test_connection(dialog, test_probe, values_getter):
    """M54 §1: Test Connection control shared by the peripheral / DUT
    config dialogs.  It runs the SAME availability probe off the UI
    thread and reports PASSED / FAILED inside the dialog (no row button
    exists any more)."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    row = QHBoxLayout()
    btn = QPushButton("Test Connection")
    btn.setToolTip("Run the availability probe with the values above")
    result = QLabel("")
    result.setWordWrap(True)
    dialog.test_result = result
    row.addWidget(btn)
    row.addStretch(1)
    lay.addLayout(row)
    lay.addWidget(result)

    def _run():
        worker = getattr(dialog, "_test_worker", None)
        if worker is not None and worker.isRunning():
            return
        btn.setEnabled(False)
        result.setStyleSheet("")
        result.setText("Testing ...")
        values = values_getter()
        worker = _PeripheralTestWorker(lambda: test_probe(values), dialog)

        def _done(ok, message, thread=worker):
            btn.setEnabled(True)
            result.setText(message)
            result.setStyleSheet(
                "color: %s;" % ("#15803d" if ok else "#b91c1c"))
            thread.deleteLater()

        dialog._test_worker = worker
        worker.done.connect(_done)
        worker.start()

    dialog.test_button = btn
    btn.clicked.connect(_run)
    return box


class _BlockConfigDialog(QDialog):
    """Form-style configuration window: read-only basic information
    plus an editable Test Configuration group for integrated blocks;
    blocks without an editor show the not-yet-available notice
    (user direction, same pattern as the HOST PC window)."""

    def __init__(self, parent, title, fields, note, editor=None,
                 config=None, test_probe=None, self_test=None,
                 editor_max_width=None):
        super().__init__(parent)
        self.setWindowTitle(f"{title} - Configuration")
        self.setMinimumWidth(650)
        enable_dialog_controls(self)
        self._editor = editor
        self._edits = {}
        root = QVBoxLayout(self)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)

        # 1 -------------------------------------------- basic information
        info = QGroupBox("Basic Information")
        form = QFormLayout(info)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for label, value in fields:
            edit = QLineEdit(value)
            edit.setReadOnly(True)
            if editor_max_width:
                # M64: bounded read-only rows too (no full-width stretch)
                edit.setMaximumWidth(editor_max_width)
            form.addRow(f"{label}:", edit)
        body_lay.addWidget(info)

        # 2 -------------------------------------- editor or the notice
        saved = (config or {}).get("params") or {}
        self._self_test = self_test
        if editor:
            test = QGroupBox("Test Configuration")
            tform = QFormLayout(test)
            tform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            self._edits = {}
            for key, label, default in editor:
                edit = QLineEdit(str(saved.get(key, default)))
                edit.setPlaceholderText(default or "optional")
                if editor_max_width:
                    # M64: bounded form fields (no full-width stretch)
                    edit.setMaximumWidth(editor_max_width)
                self._edits[key] = edit
                tform.addRow(f"{label}:", edit)
            body_lay.addWidget(test)
            hint = QLabel("Saved with the project and reused by the "
                          "test flow.")
            hint.setObjectName("muted")
            body_lay.addWidget(hint)
            if self_test is not None:
                body_lay.addWidget(self._self_test_box())
            elif test_probe is not None:
                body_lay.addWidget(_attach_test_connection(
                    self, test_probe, self.values))
        else:
            notice = QLabel(_NOT_YET)
            notice.setObjectName("warn")
            body_lay.addWidget(notice)

        note_label = QLabel(note)
        note_label.setObjectName("warn")
        body_lay.addWidget(note_label)
        # M34: body scrolls, Close stays outside (always visible)
        apply_scroll_to_dialog(self, body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _self_test_box(self):
        """M64: Self-Test control - launches the tool detached and asks
        the operator whether it is usable (the dialog never waits on the
        tool process)."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        btn = QPushButton("Self-Test")
        btn.setToolTip("Launch the tool and confirm that it is usable")
        result = QLabel("")
        result.setWordWrap(True)
        self.test_result = result
        self.test_button = btn
        row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(result)

        def _run():
            btn.setEnabled(False)
            result.setStyleSheet("")
            result.setText("Self-Test ...")
            try:
                ok, message = self._self_test(self.values())
            finally:
                btn.setEnabled(True)
            result.setText(message)
            result.setStyleSheet(
                "color: %s;" % ("#15803d" if ok else "#b91c1c"))

        btn.clicked.connect(_run)
        return box

    def values(self) -> dict:
        """The current editor values (empty dict without an editor)."""
        return {key: edit.text().strip()
                for key, edit in self._edits.items()}

    def apply_to_config(self, cfg: dict) -> None:
        """Write the edited values back into the page config dict -
        persisted with the project YAML like the instrument dialogs."""
        if self._editor:
            cfg["params"] = self.values()


def _form_dialog(parent, title, fields, note, editor=None, config=None,
                 test_probe=None, self_test=None, editor_max_width=None):
    """Form-style block config dialog factory (basic info + optional
    editable test configuration / not-yet-available notice)."""
    return _BlockConfigDialog(parent, title, fields, note,
                              editor=editor, config=config,
                              test_probe=test_probe,
                              self_test=self_test,
                              editor_max_width=editor_max_width)


class _HardwareInfoDialog(QDialog):
    """M49a §2: READ-ONLY Hardware Info opened by clicking a diagram
    module (model / specifications / channels / connections).

    No edit control exists here: every edit entry point lives in the
    LEFT column entries of the Equipment page."""

    def __init__(self, parent, title, fields, connections, role=""):
        super().__init__(parent)
        self.setWindowTitle(f"{title} - Hardware Info")
        fit_dialog(self, 720, 560)
        root = QVBoxLayout(self)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)

        info = QGroupBox("Specifications")
        form = QFormLayout(info)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for label, value in fields:
            edit = QLineEdit(str(value))
            edit.setReadOnly(True)
            form.addRow(f"{label}:", edit)
        body_lay.addWidget(info)

        conn = QGroupBox("Connections")
        cform = QFormLayout(conn)
        cform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for label, value in connections:
            edit = QLineEdit(str(value))
            edit.setReadOnly(True)
            cform.addRow(f"{label}:", edit)
        body_lay.addWidget(conn)

        if role:
            note = QLabel(role)
            note.setObjectName("muted")
            body_lay.addWidget(note)
        read_only = QLabel(
            "Read-only information.  Configure this module from the "
            "left-hand hardware list.")
        read_only.setObjectName("warn")
        body_lay.addWidget(read_only)
        apply_scroll_to_dialog(self, body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


class _GroupConfigDialog(QDialog):
    """M49a: small editable form for one grouped config (DUT Wi-Fi /
    SSH Login / Ethernet Router / ... or the control-board DIO map)."""

    def __init__(self, parent, title, spec, values, test_probe=None):
        super().__init__(parent)
        self.setWindowTitle(f"{title} - Configuration")
        fit_dialog(self, 560, 360)
        root = QVBoxLayout(self)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._edits = {}
        for key, label, default in spec:
            edit = QLineEdit(str((values or {}).get(key, default)))
            edit.setPlaceholderText(default or "optional")
            self._edits[key] = edit
            form.addRow(f"{label}:", edit)
        body_lay.addLayout(form)
        # M54 §1: the row-level Test button moved here for the peripheral
        # / DUT configs (Test Connection inside the Config dialog)
        if test_probe is not None:
            body_lay.addWidget(_attach_test_connection(
                self, test_probe, self.values))
        note = QLabel(
            "Saved in the project yaml and referenced by test steps at "
            "runtime.")
        note.setObjectName("muted")
        body_lay.addWidget(note)
        apply_scroll_to_dialog(self, body)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self):
        return {key: edit.text().strip()
                for key, edit in self._edits.items()}


# ---------------------------------------------------------------------------
# M80-5: ATE fixture control board - DIO channel + direction
# ---------------------------------------------------------------------------
class _ControlBoardDialog(QDialog):
    """Four signal rows: DIO channel combo + exclusive Input / Output.

    M100: the DAQ973A "connect first" gate is gone - Config opens
    immediately and the OK button is always enabled."""

    def __init__(self, parent, title, signals: dict):
        super().__init__(parent)
        self.setWindowTitle(f"{title} - DIO signals")
        fit_dialog(self, 720, 460)
        root = QVBoxLayout(self)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)

        grid = QGridLayout()
        grid.addWidget(QLabel("Signal"), 0, 0)
        grid.addWidget(QLabel("DIO channel"), 0, 1)
        grid.addWidget(QLabel("Direction"), 0, 2)
        self._rows = {}
        for row, (key, label, default_channel, default_dir) in enumerate(
                DIO_SIGNALS, start=1):
            saved = dict((signals or {}).get(key) or {})
            channel = str(saved.get("channel", default_channel) or "")
            direction = str(saved.get("direction", default_dir)
                            or default_dir).lower()
            grid.addWidget(QLabel(f"{label}:"), row, 0)
            combo = QComboBox()
            combo.setEditable(False)
            combo.addItem("")
            combo.addItems(list(DIO_CHANNELS))
            combo.setCurrentText(channel if channel in DIO_CHANNELS else "")
            grid.addWidget(combo, row, 1)
            direction_row = QHBoxLayout()
            radio_in = QRadioButton("Input")
            radio_out = QRadioButton("Output")
            (radio_in if direction == "input" else radio_out).setChecked(True)
            direction_row.addWidget(radio_in)
            direction_row.addWidget(radio_out)
            direction_row.addStretch(1)
            grid.addLayout(direction_row, row, 2)
            self._rows[key] = (combo, radio_in, radio_out)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        self.error_label = QLabel("")
        self.error_label.setObjectName("warn")
        self.error_label.setWordWrap(True)
        lay.addWidget(self.error_label)
        note = QLabel(
            "Empty channel = signal not wired.  Two signals may not share "
            "one DIO channel.  Direction defaults: outputs except "
            "E-stop healthy (input).")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        apply_scroll_to_dialog(self, body)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def validate(self) -> list:
        """Blocking duplicate-channel errors (M80-5)."""
        errors = []
        used = {}
        for key, (combo, _radio_in, _radio_out) in self._rows.items():
            channel = combo.currentText().strip()
            if not channel:
                continue
            if channel in used:
                _other_key, other_label = used[channel]
                label = next(label for name, label, _c, _d in DIO_SIGNALS
                             if name == key)
                errors.append(
                    f"Duplicate DIO channel {channel}: '{other_label}' and "
                    f"'{label}' cannot share it")
            else:
                used[channel] = (key, next(
                    label for name, label, _c, _d in DIO_SIGNALS
                    if name == key))
        return errors

    def values(self) -> dict:
        out = {}
        for key, (combo, radio_in, _radio_out) in self._rows.items():
            out[key] = {"channel": combo.currentText().strip(),
                        "direction": "input" if radio_in.isChecked()
                                     else "output"}
        return out

    def _accept(self):
        errors = self.validate()
        if errors:
            self.error_label.setText("\n".join(errors))
            return
        self.accept()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# M100: station console / network configs (Host PC serial / SSH / Bluetooth)
# ---------------------------------------------------------------------------
class _SerialChannelsDialog(QDialog):
    """Four station serial channels (ser1..ser4), one field block each."""

    def __init__(self, parent, values: dict):
        super().__init__(parent)
        self.setWindowTitle("Serial Console - Configuration")
        fit_dialog(self, 640, 620)
        root = QVBoxLayout(self)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        self._edits = {}
        saved = dict(values or {})
        for channel in (f"ser{i}" for i in range(1, 5)):
            box = QGroupBox(channel.upper())
            form = QFormLayout(box)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            channel_values = dict(saved.get(channel) or {})
            self._edits[channel] = {}
            for key, label, default in _SERIAL_CHANNEL_FIELDS:
                value = channel_values.get(key, default)
                edit = QLineEdit("" if value is None else str(value))
                edit.setPlaceholderText(
                    "optional" if default in (None, "") else str(default))
                form.addRow(f"{label}:", edit)
                self._edits[channel][key] = edit
            lay.addWidget(box)
        apply_scroll_to_dialog(self, body)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict:
        return {channel: {key: edit.text().strip()
                          for key, edit in fields.items()}
                for channel, fields in self._edits.items()}


class _SshChannelDialog(QDialog):
    """Single optional station SSH channel (ssh1)."""

    def __init__(self, parent, values: dict):
        super().__init__(parent)
        self.setWindowTitle("SSH Console - Configuration")
        fit_dialog(self, 560, 340)
        root = QVBoxLayout(self)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        saved = dict(values or {}).get("ssh1") or {}
        self._edits = {}
        for key, label, default in _SSH_CHANNEL_FIELDS:
            value = saved.get(key, default)
            edit = QLineEdit("" if value is None else str(value))
            edit.setPlaceholderText(
                "optional" if default in (None, "") else str(default))
            if key == "password":
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow(f"{label}:", edit)
            self._edits[key] = edit
        body_lay.addLayout(form)
        note = QLabel("Saved in the project yaml and referenced by test "
                      "steps at runtime.")
        note.setObjectName("muted")
        body_lay.addWidget(note)
        apply_scroll_to_dialog(self, body)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict:
        return {"ssh1": {key: edit.text().strip()
                         for key, edit in self._edits.items()}}


class _HostBluetoothDialog(QDialog):
    """Host PC Bluetooth: read-only adapter + editable scan targets."""

    def __init__(self, parent, values: dict):
        super().__init__(parent)
        self.setWindowTitle("Bluetooth - Configuration")
        fit_dialog(self, 560, 340)
        root = QVBoxLayout(self)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        saved = dict(values or {})
        adapter = str(saved.get("adapter") or "")
        try:
            from .engine import host_platform
            detected, _address = host_platform.host_bt_identity()
        except Exception:                        # noqa: BLE001 - best effort
            detected = ""
        if not adapter and detected:
            adapter = str(detected)
        self.edit_adapter = QLineEdit(adapter or "unavailable")
        self.edit_adapter.setReadOnly(True)
        form.addRow("Host adapter:", self.edit_adapter)
        self.edit_scan = QLineEdit(str(saved.get("scan_targets") or ""))
        self.edit_scan.setPlaceholderText("DUT-BT or AA:BB:CC:DD:EE:FF")
        form.addRow("Scan targets:", self.edit_scan)
        body_lay.addLayout(form)
        note = QLabel("Saved in the project yaml and referenced by test "
                      "steps at runtime.")
        note.setObjectName("muted")
        body_lay.addWidget(note)
        apply_scroll_to_dialog(self, body)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict:
        return {"adapter": self.edit_adapter.text().strip(),
                "scan_targets": self.edit_scan.text().strip()}


class _DeviceEditDialog(QDialog):
    """Per-device editor opened by double-clicking a table row: an
    editable form when the device integration is developed, otherwise
    the read-only row info plus the not-yet-available notice."""

    def __init__(self, parent, device, spec, saved=None, info=None):
        super().__init__(parent)
        self.setWindowTitle(f"{device} - Configuration")
        self.setMinimumWidth(520)
        enable_dialog_controls(self)
        self._spec = spec
        root = QVBoxLayout(self)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)

        if spec:
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            self._edits = {}
            for key, label, default in spec:
                edit = QLineEdit(str((saved or {}).get(key, default)))
                edit.setPlaceholderText(default or "optional")
                self._edits[key] = edit
                form.addRow(f"{label}:", edit)
            body_lay.addLayout(form)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        else:
            info_box = QGroupBox("Device Information")
            form = QFormLayout(info_box)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            for label, value in (info or []):
                edit = QLineEdit(str(value))
                edit.setReadOnly(True)
                form.addRow(f"{label}:", edit)
            body_lay.addWidget(info_box)
            notice = QLabel(_NOT_YET)
            notice.setObjectName("warn")
            body_lay.addWidget(notice)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        # M34: body scrolls, Close stays outside (always visible)
        apply_scroll_to_dialog(self, body)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict:
        """The edited device options (empty dict for notice-only)."""
        if not self._spec:
            return {}
        return {key: edit.text().strip()
                for key, edit in self._edits.items()}


class _DeviceTableDialog(QDialog):
    """Table-style configuration window (Flash / Debug Probes, Test
    Peripherals): double-click a device row to edit it - devices with
    a developed integration open an editor, the others show the
    not-yet-available notice (user direction)."""

    def __init__(self, parent, title, rows, note, block_key=None,
                 config=None):
        super().__init__(parent)
        self.setWindowTitle(f"{title} - Configuration")
        fit_dialog(self, 900, 570)
        self._rows = rows
        self._block_key = block_key
        # local copy - written back to the page config on close
        self._device_params = dict(
            (config or {}).get("device_params") or {})
        layout = QVBoxLayout(self)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["Item", "Role", "Interface / Status"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, (name, role, status) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(role))
            table.setItem(row, 2, QTableWidgetItem(status))
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 270)
        table.setColumnWidth(1, 420)
        table.cellDoubleClicked.connect(self._edit_device)
        body_lay.addWidget(table)
        hint = QLabel("Double-click a device row to edit its "
                      "configuration.")
        hint.setObjectName("muted")
        body_lay.addWidget(hint)
        note_label = QLabel(note)
        note_label.setObjectName("warn")
        body_lay.addWidget(note_label)
        # M34: body scrolls, Close stays outside (always visible)
        apply_scroll_to_dialog(self, body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _edit_device(self, row: int, _col: int) -> None:
        if not (0 <= row < len(self._rows)):
            return
        device, role, status = self._rows[row]
        spec = _DEVICE_EDITORS.get((self._block_key, device))
        dlg = _DeviceEditDialog(self, device, spec,
                                saved=self._device_params.get(device),
                                info=[("Role", role),
                                      ("Interface / Status", status)])
        dlg.exec()
        values = dlg.values()
        if values:
            self._device_params[device] = values

    def apply_to_config(self, cfg: dict) -> None:
        """Persist the edited device options with the page config."""
        if self._device_params:
            cfg["device_params"] = self._device_params


#: M100: instrument LED states -> colours (duplicated from
#: ``main_window.LED_COLORS`` - equipment_page must not import it back).
_LED_COLORS = {
    "connected": "#22c55e",      # green: connected + self-test OK
    "disconnected": "#9ca3af",   # gray: not connected
    "untested": "#facc15",       # yellow: connected, self-test not passed
    "error": "#ef4444",          # red
}


class _Led(QLabel):
    """Small round status light used in the connection group."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(13, 13)
        self.set_color("#9ca3af")

    def set_color(self, color):
        self.setStyleSheet(
            f"background:{color}; border-radius:6px;"
            "border:1px solid rgba(0,0,0,0.25);")

    def set_state(self, state):
        self.set_color(_LED_COLORS[state])


class _InstrumentDialog(QDialog):
    """Rich configuration window for instrument blocks on the diagram.

    Four group boxes:
      1. Instrument Information   - read-only identity / spec fields
      2. Parameter Configuration  - editable instrument parameters
      3. Connection               - interface + address, Connect /
         Disconnect / Test Connection (succeeds in Virtual mode)
      4. Control & Simple Tests   - IO control, impedance / voltage /
         clock / AI tests, power on-off (simulated replies)
    """

    # (key, connected) - emitted live so the status-bar LEDs follow
    connection_changed = Signal(str, bool)
    # (key, passed) - M49a §3: a self-test run inside the dialog turns
    # the lamp from yellow (connected, untested) to green
    self_test_changed = Signal(str, bool)

    def __init__(self, parent, title, fields, key, virtual, manual=False,
                 config=None, last_size=None):
        super().__init__(parent)
        self._key = key
        self._virtual = virtual
        self._manual = manual
        self._connected = False
        # persisted connection / parameter configuration (YAML-backed)
        self._config = dict(config or {})
        self._last_size = last_size
        self.setWindowTitle(f"{title} - Configuration")
        fit_dialog(self, 920, 720)
        root = QVBoxLayout(self)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)

        # 1 ------------------------------------------------------- connection
        conn = QGroupBox("Connection")
        self._conn_group = conn
        cv = QVBoxLayout(conn)
        cform = QFormLayout()
        cform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._iface = QComboBox()
        self._iface.addItems(list(_INSTRUMENT_CONN[key]))
        # restore the SAVED interface / address (user direction: the
        # connection parameters persist in the project YAML)
        saved_conn = self._config.get("connection") or {}
        if saved_conn.get("interface") in _INSTRUMENT_CONN[key]:
            self._iface.setCurrentText(str(saved_conn["interface"]))
        # M80-3: editable address combo + Refresh (scan or known defaults)
        self._address = QComboBox()
        self._address.setEditable(True)
        self._address.setMinimumWidth(320)
        saved_address = str(saved_conn.get("address") or "").strip()
        self._fill_known_addresses(saved_address)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setToolTip("Scan the selected interface for addresses")
        address_row = QHBoxLayout()
        address_row.addWidget(self._address, 1)
        address_row.addWidget(self.btn_refresh)
        self._iface.currentTextChanged.connect(self._iface_changed)
        cform.addRow("Interface:", self._iface)
        cform.addRow("Address:", self._layout_widget(address_row))
        cv.addLayout(cform)

        crow = QHBoxLayout()
        self._led = _Led()
        self._conn_state = QLabel("Disconnected")
        self.btn_connect = QPushButton("Connect")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_test = QPushButton("Test Connection")
        self.btn_disconnect.setEnabled(False)
        self.btn_test.setEnabled(False)
        crow.addWidget(self._led)
        crow.addWidget(self._conn_state)
        crow.addStretch(1)
        crow.addWidget(self.btn_connect)
        crow.addWidget(self.btn_disconnect)
        crow.addWidget(self.btn_test)
        cv.addLayout(crow)
        body_lay.addWidget(conn)

        # 2 ------------------------------------------------------ parameters
        saved_params = self._config.get("params") or {}
        params = QGroupBox("Parameter Configuration")
        self._param_group = params
        pform = QFormLayout(params)
        pform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._param_edits = []
        for label, value in _INSTRUMENT_PARAMS[key]:
            edit = QLineEdit(str(saved_params.get(label, value)))
            self._param_edits.append(edit)
            pform.addRow(f"{label}:", edit)
        body_lay.addWidget(params)

        # 3 ------------------------------------------- control & simple tests
        ctl = QGroupBox("Control && Simple Tests")
        self._ctl_group = ctl
        # Manual fixture mode: IO control is globally disabled (the
        # operator performs every hardware action by hand)
        ctl.setEnabled(not manual)
        ctl.setToolTip("Disabled in Manual Fixture mode"
                       if manual else "")
        cl = QVBoxLayout(ctl)
        grid = QGridLayout()
        self._action_buttons = []
        for i, (label, _fn) in enumerate(_INSTRUMENT_ACTIONS[key]):
            btn = QPushButton(label)
            btn.setEnabled(False)
            btn.clicked.connect(
                lambda _=False, lab=label: self._run_action(lab))
            grid.addWidget(btn, i // 2, i % 2)
            self._action_buttons.append(btn)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        cl.addLayout(grid)
        # the test log is the MAIN area of the lower half (user
        # direction): it takes all remaining vertical space instead of
        # a cramped fixed 130 px strip
        lbl_log = QLabel("Test Log:")
        lbl_log.setObjectName("strong")
        cl.addWidget(lbl_log)
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("Action / test results appear here ...")
        cl.addWidget(self._output, 1)
        body_lay.addWidget(ctl, 1)

        # 4 ------------------------------------ information (collapsible)
        info = QGroupBox("Instrument Information")
        self._info_group = info
        info_lay = QVBoxLayout(info)
        toggle = QToolButton()
        toggle.setText("Show instrument information")
        toggle.setCheckable(True)
        toggle.setChecked(False)
        toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.ArrowType.RightArrow)
        info_lay.addWidget(toggle)
        info_content = QWidget()
        form = QFormLayout(info_content)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for label, value in fields:
            edit = QLineEdit(value)
            edit.setReadOnly(True)
            form.addRow(f"{label}:", edit)
        info_content.setVisible(False)
        info_lay.addWidget(info_content)
        self._info_content = info_content

        def _toggle_info(checked):
            info_content.setVisible(bool(checked))
            toggle.setArrowType(Qt.ArrowType.DownArrow if checked
                                else Qt.ArrowType.RightArrow)
            toggle.setText("Hide instrument information" if checked
                           else "Show instrument information")

        toggle.toggled.connect(_toggle_info)
        body_lay.addWidget(info)
        body_lay.setStretch(0, 0)
        body_lay.setStretch(1, 0)
        body_lay.setStretch(2, 1)
        body_lay.setStretch(3, 0)
        # M80-2: Connection first, Instrument Information last
        self._group_order = (conn, params, ctl, info)

        note = QLabel(_mode_note("Virtual" if virtual else "Real",
                                 instrument=True))
        note.setObjectName("warn")
        body_lay.addWidget(note)
        # M34: body scrolls, Close stays outside (always visible)
        apply_scroll_to_dialog(self, body)
        # QScrollArea.setWidget() polishes the content, which lets the
        # stylesheet min-height replace an explicit minimum set earlier -
        # re-apply the 240 px Test Log minimum AFTER the wrap (user
        # direction: the log is the main lower area, not a 130 px strip)
        self._output.setMinimumHeight(240)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._fit_to_content(body)
        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.btn_test.clicked.connect(self._test_connection)
        self.btn_refresh.clicked.connect(
            lambda: self._scan_addresses(self._address.currentText()))
        # M80-3: exactly one automatic scan when the dialog opens
        QTimer.singleShot(0, self, qt_safe(self._scan_addresses))

    @staticmethod
    def _layout_widget(layout):
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _fit_to_content(self, body):
        """M80-2: open at content size, clamped to 98 % of the screen
        with a 980x860 floor; a remembered size (same instrument key)
        wins, still clamped."""
        hint = body.sizeHint()
        screen = self.screen().availableGeometry() if self.screen() else None
        max_w = int(screen.width() * 0.98) if screen else hint.width()
        max_h = int(screen.height() * 0.98) if screen else hint.height()
        width = max(980, min(max_w, hint.width()))
        height = max(860, min(max_h, hint.height()))
        if self._last_size is not None:
            size = self._last_size
            width = max(980, min(max_w, int(size.width())))
            height = max(860, min(max_h, int(size.height())))
        self.resize(width, height)

    # ------------------------------------------------------------ helpers
    def _fill_known_addresses(self, saved: str = ""):
        """Populate the editable address combo with the saved value and
        the known defaults of the selected interface."""
        self._address.clear()
        known = [str((self._config.get("connection") or {}).get("address")
                     or "").strip(),
                 str(_INSTRUMENT_CONN[self._key].get(
                     self._iface.currentText(), "")) if hasattr(
                     self, "_iface") else ""]
        for value in known + [saved]:
            if value and self._address.findText(value) < 0:
                self._address.addItem(value)
        if saved:
            self._address.setCurrentText(saved)
        else:
            default = str(_INSTRUMENT_CONN[self._key].get(
                self._iface.currentText() if hasattr(self, "_iface") else "",
                ""))
            if default:
                self._address.setCurrentText(default)

    def _scan_addresses(self, keep: str = ""):
        """M80-3: best-effort VISA scan; a missing runtime falls back to
        the known defaults and logs exactly one line."""
        keep = str(keep or self._address.currentText() or "").strip()
        wanted = self._iface.currentText()
        addresses = []
        try:
            import pyvisa                          # noqa: F401
        except ImportError:
            self._log("no VISA runtime found - showing known addresses only")
            fallback = str(_INSTRUMENT_CONN[self._key].get(wanted, ""))
            addresses = [fallback] if fallback else []
        else:
            try:
                manager = pyvisa.ResourceManager()
                addresses = [str(item) for item
                             in manager.list_resources()]
            except Exception as exc:              # noqa: BLE001 - best effort
                self._log(f"address scan failed: {exc}")
                fallback = str(_INSTRUMENT_CONN[self._key].get(wanted, ""))
                addresses = [fallback] if fallback else []
        for address in addresses:
            if address and self._address.findText(address) < 0:
                self._address.addItem(address)
        if keep and self._address.findText(keep) < 0:
            self._address.addItem(keep)
        if keep:
            self._address.setCurrentText(keep)

    def _iface_changed(self, text):
        default = _INSTRUMENT_CONN[self._key].get(text, "")
        if default and self._address.findText(default) < 0:
            self._address.addItem(default)
        self._address.setCurrentText(default)

    def _log(self, text):
        self._output.appendPlainText(text)

    # -------------------------------------------------------- connection
    def apply_to_config(self, cfg: dict) -> None:
        """Write the edited connection / parameter values back into the
        Equipment page config dict - they are saved with the project
        YAML (build_config) and restored on the next dialog open, so a
        saved project connects directly (user direction)."""
        cfg["connection"] = {
            "interface": self._iface.currentText(),
            "address": self._address.currentText().strip(),
        }
        cfg["params"] = {
            label: edit.text().strip()
            for (label, _v), edit in zip(
                _INSTRUMENT_PARAMS[self._key], self._param_edits)
        }

    def set_connected(self, connected: bool) -> None:
        """Restore a previously persisted connection state (the dialog
        is re-created on every open - the state lives on the page)."""
        self._connected = bool(connected)
        if not (connected and self._virtual):
            return
        self._led.set_color("#22c55e")
        self._conn_state.setText("Connected (virtual)")
        for btn in self._action_buttons:
            btn.setEnabled(True)
        self.btn_test.setEnabled(True)
        self.btn_disconnect.setEnabled(True)
        self.btn_connect.setEnabled(False)

    def _connect(self):
        addr = self._address.currentText().strip()
        self.btn_connect.setEnabled(False)
        self._conn_state.setText("Connecting ...")
        self._log(f"Connecting to {addr} ...")
        QTimer.singleShot(
            500, self, qt_safe(lambda: self._connect_done(addr)))

    def _connect_done(self, addr):
        if self._virtual:
            self._connected = True
            self._led.set_color("#22c55e")
            self._conn_state.setText("Connected (virtual)")
            self._log("Connected (virtual mode - simulated link).")
            for btn in self._action_buttons:
                btn.setEnabled(True)
            self.btn_test.setEnabled(True)
            self.btn_disconnect.setEnabled(True)
            # T9: sync the shared status hub (block 03 panel display)
            from mtkgui.gui.yamlbuild.instrument_status import HUB
            HUB.set_connected(True)
            self.connection_changed.emit(self._key, True)
        else:
            self._led.set_color("#ef4444")
            self._conn_state.setText("Error: instrument not found")
            self._log("Error: instrument not found - check the "
                      "interface and address, then try again.")
            self.btn_connect.setEnabled(True)
            from mtkgui.gui.yamlbuild.instrument_status import HUB
            HUB.set_connected(False)
            HUB.set_test_connection("NOK")
            self.connection_changed.emit(self._key, False)

    def _disconnect(self):
        self._connected = False
        self._led.set_color("#9ca3af")
        self._conn_state.setText("Disconnected")
        self._log("Disconnected.")
        for btn in self._action_buttons:
            btn.setEnabled(False)
        self.btn_test.setEnabled(False)
        self.btn_disconnect.setEnabled(False)
        self.btn_connect.setEnabled(True)
        # T9: sync the shared status hub + reset stale results
        from mtkgui.gui.yamlbuild.instrument_status import HUB
        HUB.disconnect()
        self.connection_changed.emit(self._key, False)

    def _test_connection(self):
        self._log("*IDN? ...")
        QTimer.singleShot(
            400, self,
            qt_safe(lambda: self._log(
                f"*IDN? -> {_INSTRUMENT_IDN[self._key]}\n"
                f"Test Connection -> OK")))
        QTimer.singleShot(
            400, self,
            qt_safe(lambda: self._hub_test_result("OK")))

    def _hub_test_result(self, result):
        """T9: mirror the Test Connection result to the status hub."""
        from mtkgui.gui.yamlbuild.instrument_status import HUB
        HUB.set_test_connection(result)

    # ------------------------------------------------- control & tests
    def _run_action(self, label):
        for text, fn in _INSTRUMENT_ACTIONS[self._key]:
            if text == label:
                params = [edit.text() for edit in self._param_edits]
                out = fn(params)
                self._log(f"[{label}] {out}")
                if label == "Self Test":
                    passed = "PASS" in out or "0 errors" in out
                    # T9: mirror the Self-Test result to the shared
                    # status hub (block 03 panel display)
                    from mtkgui.gui.yamlbuild.instrument_status import HUB
                    HUB.set_self_test("OK" if passed else "NOK")
                    # M49a §3: main-window lamp - self-test OK -> green
                    self.self_test_changed.emit(self._key, passed)
                return


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------
class _PeripheralTestWorker(QThread):
    """M50 §4: run one availability probe OFF the UI thread.

    ``fn`` returns ``(ok, message)``; an unexpected exception becomes a
    clear failure message (never a crash / traceback in the UI).
    """

    done = Signal(bool, str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            ok, message = self._fn()
        except Exception as exc:                    # noqa: BLE001
            ok, message = False, f"{type(exc).__name__}: {exc}"
        self.done.emit(bool(ok), str(message))


class _InstrumentProbeWorker(QThread):
    """M100: runs the Refresh / Self-Test All probe in a background
    thread so the GUI never blocks.  Emits the requested action when the
    (simulated, 1 s timeout) queries complete."""

    done = Signal(str)

    def __init__(self, action: str, parent=None):
        super().__init__(parent)
        self._action = action

    def run(self):
        # the three instruments are queried in parallel with a 1 s
        # timeout each; the simulation just yields once off the GUI
        # thread.  The real hardware layer would gather the states here.
        QThread.msleep(50)
        self.done.emit(self._action)


class EquipmentPage(QWidget):
    # (instrument key, connected) emitted by the instrument dialog when
    # the user connects / disconnects INSIDE the dialog - the main
    # window syncs the status-bar LEDs from it (user report: the LEDs
    # never reflected the real connect state)
    instrument_connection_changed = Signal(str, bool)
    # (instrument key, passed) - M49a §3: self-test result drives the
    # lamp (yellow -> green)
    instrument_selftest_changed = Signal(str, bool)
    # M49a §4: page-level "Apply Save YAML" (handled by MainWindow with
    # the same mechanism as the other config pages)
    apply_save_requested = Signal()
    # M100-fix3: one-line notices for the main-window Event Log
    log_line = Signal(str)

    #: instrument dialog key -> status-bar LED abbreviation
    _INSTRUMENT_ABBR = {
        "daq973a": "DAQM", "m908a_1": "DAQM", "m908a_2": "DAQM",
        "m907a": "DAQM", "u2355a": "DAQ", "psu": "PSU",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.configs = _mock_configs()
        self.blocks = {}
        # per-instrument connect state (user report: the state died
        # with the modal dialog - reopening showed Disconnected again)
        self._instrument_connections: dict[str, bool] = {}
        self._instrument_selftest: dict[str, bool] = {}
        # M80-2: last dialog size per instrument key (page state, not YAML)
        self._instrument_sizes: dict[str, object] = {}
        # M80-1: computed left-column width (see _left_column_width)
        self.computed_left_width = 320
        # entry key -> row widgets (Config button)
        self.entry_buttons: dict[str, dict[str, QPushButton]] = {}
        # entry key -> name label (M80-1 tooltip / width assertions)
        self.entry_labels: dict[str, QLabel] = {}
        # M100: group_toggle key -> Enable checkbox; sub entry key ->
        # its parent group key (used to grey out children on disable)
        self.group_toggles: dict[str, QCheckBox] = {}
        self.sub_parents: dict[str, str] = {}
        # M100: instrument entry key -> its left-column LED
        self.entry_leds: dict[str, QLabel] = {}
        self._probe_worker: QThread | None = None
        # Virtual mode: the instrument dialog's Connect / Test Connection
        # succeed with a simulated link (set from MainWindow on login).
        # _mode carries the full Real / Virtual distinction for the
        # mode-aware dialog notes (user report: 'Demo mode' showed in
        # Real mode)
        self._mode = "Real"
        self.virtual_mode = False
        # account permission: opening block-diagram configuration dialogs
        # (defaults = allowed until set_config_allowed)
        self._config_allowed = True
        # Manual fixture mode: fixture hardware config + IO control
        # entries are globally disabled (set from MainWindow on login)
        self._manual_fixture = False
        self._build()

    def set_manual_fixture(self, manual):
        """Manual fixture mode -> block fixture / IO-control entries."""
        self._manual_fixture = bool(manual)

    def set_mode(self, mode):
        """Real / Virtual mode -> drives the mode-aware dialog notes."""
        self._mode = "Virtual" if mode == MODE_VIRTUAL else "Real"
        self.virtual_mode = self._mode == MODE_VIRTUAL

    def set_virtual_mode(self, virtual):
        """Compat boolean setter: True = Virtual, False = Real."""
        self.set_mode(MODE_VIRTUAL if virtual else MODE_REAL)

    def set_config_allowed(self, allowed):
        """Operator permission: open the equipment configuration dialogs."""
        self._config_allowed = bool(allowed)

    def _build(self):
        layout = QVBoxLayout(self)
        title = QLabel("Equipment")
        title.setObjectName("strong")
        title.setStyleSheet("font-size: 20px;")

        btn_out = QPushButton("Zoom Out")
        btn_in = QPushButton("Zoom In")
        btn_reset = QPushButton("Reset 100%")
        self.zoom_label = QLabel("--")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setObjectName("muted")
        self.zoom_label.setStyleSheet("font-weight: bold;")

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(btn_out)
        header.addWidget(btn_in)
        header.addWidget(self.zoom_label)
        header.addWidget(btn_reset)
        layout.addLayout(header)

        # ---- two-column layout (M49a §1 / §2) -------------------------
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left_panel = self._build_left_panel()
        self.right_panel = self._build_right_panel()
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        # M80-1: default at the computed width (longest surviving label +
        # Config button + row/scrollbar margins, clamped 320..480)
        self.computed_left_width = max(self._left_column_width(),
                                       self.left_list.minimumWidth() + 8)
        # the computed width is the DEFAULT; a drag may still narrow the
        # column down to the floor (labels keep their full-text tooltip)
        self.left_list.setMinimumWidth(LEFT_COLUMN_MIN_PX // 2)
        self.splitter.setSizes([self.computed_left_width,
                               self.computed_left_width * 3])
        self.splitter.splitterMoved.connect(
            lambda _pos, _idx: self._enforce_splitter_clamp())
        layout.addWidget(self.splitter, 1)

        btn_out.clicked.connect(self.view.zoom_out)
        btn_in.clicked.connect(self.view.zoom_in)
        btn_reset.clicked.connect(self.view.zoom_reset)
        self.view.zoomChanged.connect(self._update_zoom_label)

        # ---- page-level Apply Save YAML (M49a §4) ---------------------
        bar = QHBoxLayout()
        bar.addStretch(1)
        self.btn_apply_save = QPushButton("Apply Save YAML")
        self.btn_apply_save.setToolTip(
            "Persist the Equipment configuration into the project yaml")
        self.btn_apply_save.clicked.connect(self.apply_save_requested.emit)
        bar.addWidget(self.btn_apply_save)
        layout.addLayout(bar)

        self._populate()
        # hug the actual content so fitInView can maximize the diagram
        rect = self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        self.scene.setSceneRect(rect)
        # M34: scroll-protect the page on very small windows
        wrap_page(self)

    def _build_right_panel(self):
        self.scene = QGraphicsScene(0, 0, W, H)
        self.view = BlockDiagramView(self.scene, self._on_block_clicked)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setProperty("tone", "bordered")
        return self.view

    def _build_left_panel(self):
        """M49a §1: collapsible list of ONLY configurable hardware."""
        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        head = QHBoxLayout()
        # M61 §2: stored so the collapse can hide the caption too (it
        # used to prop the splitter's left column open)
        self.cap_label = QLabel("Hardware Configuration")
        self.cap_label.setObjectName("strong")
        head.addWidget(self.cap_label)
        head.addStretch(1)
        # M54 §2: flat arrow toggle (Event Log style) instead of the
        # "Hide" / "Show" text button; started expanded
        self.btn_collapse = QToolButton()
        self.btn_collapse.setArrowType(Qt.ArrowType.LeftArrow)
        self.btn_collapse.setAutoRaise(True)
        # M62: 24 px = the arrow's minimum size hint (18 clipped it)
        self.btn_collapse.setFixedSize(24, 16)
        self.btn_collapse.setToolTip("Collapse Hardware Configuration")
        self.btn_collapse.clicked.connect(self._toggle_left_column)
        head.addWidget(self.btn_collapse)
        outer.addLayout(head)

        self.left_list = QScrollArea()
        self.left_list.setWidgetResizable(True)
        self.left_list.setMinimumWidth(240)
        # M100: the left column is a fixed-width config list - labels are
        # never horizontally scrolled (the full text lives in a tooltip).
        self.left_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # M137: the list is 16 rows tall; the global 26 px / 7 px-padding
        # button metric pushed it past a 900 px page and brought back a
        # vertical scrollbar.  Tighter padding here, same 26 px height.
        self.left_list.setStyleSheet(
            "QScrollArea {background:#ffffff; border:1px solid #d4d9e0;}"
            "QPushButton {padding: 4px 12px;}")
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(4, 4, 4, 4)
        body_lay.setSpacing(4)
        for group_title, entries in LEFT_ENTRIES:
            group_box = QGroupBox(group_title)
            gl = QVBoxLayout(group_box)
            gl.setContentsMargins(4, 4, 4, 4)
            gl.setSpacing(2)
            if group_title == "Instruments":
                gl.addLayout(self._instrument_title_row())
            for entry in entries:
                gl.addLayout(self._entry_row(entry))
            body_lay.addWidget(group_box)
        body_lay.addStretch(1)
        self.left_list.setWidget(body)
        # M137: the horizontal bar is switched off, so a column narrower than
        # the body silently clipped the Config buttons on the right.  Reserve
        # exactly the body's own minimum width.
        self.left_list.setMinimumWidth(
            max(240, body.minimumSizeHint().width() + 6))
        outer.addWidget(self.left_list, 1)
        self._sync_group_toggles()
        return panel

    def _left_column_width(self) -> int:
        """M80-1: left column = longest label + Config + margins."""
        metrics = QFontMetrics(self.font())
        longest = max(
            [metrics.horizontalAdvance(label) + 8
             for _group, entries in LEFT_ENTRIES
             for _key, label, _kind, _source in entries] or [0])
        width = longest + 92 + 40
        return max(LEFT_COLUMN_MIN_PX, min(LEFT_COLUMN_MAX_PX, width))

    def _entry_row(self, entry):
        """One left-column row.  ``kind`` selects the widget set:

        * ``instrument`` / ``form`` -> label + Config button
        * ``optional``            -> disabled "Not developed" button
        * ``group``               -> bold header, no button
        * ``group_toggle``        -> bold header + Enable checkbox
        * ``sub``                 -> indented label + Config (greyed with
          its group_toggle parent when one exists)
        """
        key, label, kind, source = entry

        if kind == "group":
            name = QLabel(label)
            font = QFont(name.font())
            font.setBold(True)
            name.setFont(font)
            name.setToolTip(label)
            self.entry_labels[key] = name
            self.entry_buttons[key] = {}
            row = QHBoxLayout()
            # M136: the Debugger subtree is nested inside Instruments and
            # indents with it, so the group header cannot read as a
            # fourth rack instrument.
            row.setContentsMargins(14 if key == "debugger" else 0,
                                   6 if key == "debugger" else 0, 0, 0)
            row.addWidget(name)
            row.addStretch(1)
            return row

        if kind == "group_toggle":
            name = QLabel(label)
            font = QFont(name.font())
            font.setBold(True)
            name.setFont(font)
            name.setToolTip(label)
            self.entry_labels[key] = name
            enable = QCheckBox("Enable")
            enable.setChecked(True)
            enable.toggled.connect(
                lambda checked, k=key: self._set_group_enabled(k, checked))
            self.group_toggles[key] = enable
            self.entry_buttons[key] = {"enable": enable}
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(name)
            row.addStretch(1)
            row.addWidget(enable)
            return row

        row = QHBoxLayout()
        row.setContentsMargins(28 if key == "bscan" else 0, 0, 0, 0)
        name = QLabel(label)
        # M80-1: never elide; the tooltip carries the full text when the
        # operator drags the splitter narrower than the label
        name.setToolTip(label)
        name.setWordWrap(False)
        self.entry_labels[key] = name
        if kind == "instrument":
            led = _Led()
            self.entry_leds[key] = led
            row.addWidget(led)
            row.addSpacing(6)
        if kind == "sub":
            row.addSpacing(18)
            self.sub_parents[key] = source[0]
        row.addWidget(name)
        row.addStretch(1)
        buttons = {}
        if kind == "optional":
            # M100: placeholder entry - greyed, non-clickable, does nothing.
            # m122: a 92 px button clipped the caption ("Not developed"
            # needs ~132 px with the station font) and the layout audit
            # rightly called it a high-severity clip. It is a state badge,
            # not a control, so it is a label: no width to fight over.
            # The caption is short on purpose: "Not developed" needs more
            # than the 92 px this column allows, and the long form lives in
            # the tooltip. A short badge keeps the left panel narrow enough
            # to stay scrollbar-free at the default share.
            badge = QLabel("N/A")
            badge.setToolTip("Not developed - not implemented for this "
                             "station yet")
            badge.setObjectName("placeholderBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
            badge.setEnabled(False)
            badge.setCursor(Qt.CursorShape.ForbiddenCursor)
            row.addWidget(badge)
            buttons["optional"] = badge
            self.entry_buttons[key] = buttons
            return row
        btn_cfg = QPushButton("Config")
        # M61 §1: 92 px fits "Config" with the app QSS padding (7px 16px)
        btn_cfg.setFixedWidth(92)
        btn_cfg.clicked.connect(
            lambda _=False, k=key: self.open_entry(k))
        row.addWidget(btn_cfg)
        buttons["config"] = btn_cfg
        self.entry_buttons[key] = buttons
        return row

    def _instrument_title_row(self):
        """M100: the Instruments group title row carries Refresh and
        Self-Test All (both async, non-blocking)."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setToolTip(
            "Query all instrument states (1 s timeout, async — UI stays "
            "responsive)")
        self.btn_refresh.clicked.connect(self._refresh_instruments)
        row.addWidget(self.btn_refresh)
        self.btn_selftest_all = QPushButton("Self-Test All")
        self.btn_selftest_all.setToolTip(
            "Run all instrument self-tests (impedance + voltage channels); "
            "result feeds the LEDs")
        self.btn_selftest_all.clicked.connect(self._selftest_all_instruments)
        row.addWidget(self.btn_selftest_all)
        return row

    def _set_instrument_led(self, key):
        """Repaint one instrument row LED from the connection / self-test
        state (error > connected > untested > disconnected)."""
        led = self.entry_leds.get(key)
        if led is None:
            return
        if not self._instrument_connections.get(key, False):
            led.set_state("disconnected")
        elif self._instrument_selftest.get(key, False):
            led.set_state("connected")
        else:
            led.set_state("untested")

    def _refresh_instruments(self):
        """M100: query the three instruments in the background (never
        block the GUI); do not mark self-tests as passed."""
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("Busy…")
        worker = _InstrumentProbeWorker("refresh", self)
        worker.done.connect(self._on_probe_done)
        self._probe_worker = worker
        worker.start()

    def _selftest_all_instruments(self):
        """M100: run every instrument self-test in the background; the
        passing instruments turn their row LED green."""
        self.btn_selftest_all.setEnabled(False)
        self.btn_selftest_all.setText("Busy…")
        worker = _InstrumentProbeWorker("selftest", self)
        worker.done.connect(self._on_probe_done)
        self._probe_worker = worker
        worker.start()

    def _on_probe_done(self, action):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("Refresh")
        self.btn_selftest_all.setEnabled(True)
        self.btn_selftest_all.setText("Self-Test All")
        for key in ("daq973a", "u2355a", "psu"):
            self._instrument_connections[key] = True
            if action == "selftest":
                self._set_instrument_selftest(key, True)
            else:
                self._set_instrument_led(key)

    def _set_group_enabled(self, group_key, enabled):
        """Persist a group_toggle's Enable state and grey out its ``sub``
        children (both the label and the Config button)."""
        enabled = bool(enabled)
        cfg = self.configs.setdefault(group_key, {"title": group_key})
        groups = cfg.setdefault("groups", {})
        groups.setdefault("enabled", _default_group("router", "enabled"))[
            "enabled"] = enabled
        for key, parent in self.sub_parents.items():
            if parent != group_key:
                continue
            label = self.entry_labels.get(key)
            if label is not None:
                label.setEnabled(enabled)
            buttons = self.entry_buttons.get(key) or {}
            if "config" in buttons:
                buttons["config"].setEnabled(enabled)

    def _sync_group_toggles(self):
        """Re-read each group_toggle's state from the configs (after a
        YAML load) and apply it to the checkbox + children."""
        for key, checkbox in self.group_toggles.items():
            cfg = self.configs.get(key) or {}
            enabled = ((cfg.get("groups") or {}).get("enabled") or {}) \
                .get("enabled", True)
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(enabled))
            checkbox.blockSignals(False)
            self._set_group_enabled(key, bool(enabled))

    def _toggle_left_column(self):
        """M54 §2: collapse the left column to the diagram / expand it
        again; the arrow direction + tooltip follow the state.
        M61 §2: the caption is hidden too and the splitter is
        re-distributed so the column physically closes (a slim arrow
        strip) / restores the ~25 % share."""
        visible = self.left_list.isHidden()
        self.cap_label.setVisible(visible)
        self.left_list.setVisible(visible)
        # the panel's minimum size changed with the hidden children - let
        # the layout settle so the splitter honours the new sizes
        self.left_panel.layout().activate()
        sizes = self.splitter.sizes()
        if len(sizes) == 2:
            total = sizes[0] + sizes[1]
            if visible:
                self.splitter.setSizes([total // 4, total - total // 4])
            else:
                self.splitter.setSizes([28, total - 28])
        if visible:
            self.btn_collapse.setArrowType(Qt.ArrowType.LeftArrow)
            self.btn_collapse.setToolTip(
                "Collapse Hardware Configuration")
        else:
            self.btn_collapse.setArrowType(Qt.ArrowType.RightArrow)
            self.btn_collapse.setToolTip("Show Hardware Configuration")

    def _enforce_splitter_clamp(self):
        """M49a §1.1: the left column may grow up to 1:1 with the right
        column - never wider."""
        sizes = self.splitter.sizes()
        if len(sizes) != 2:
            return
        left, right = sizes
        if left > right:
            total = left + right
            half = total // 2
            self.splitter.setSizes([half, total - half])

    def _update_zoom_label(self):
        self.zoom_label.setText(f"{round(self.view.transform().m11() * 100)}%")

    # ------------------------------------------------------------------
    def _add_block(self, key, x, y, w, h, mode="plain", fill="#ffffff",
                   **kwargs):
        cfg = self.configs[key]
        block = BlockItem(key, cfg.get("short", cfg["title"]),
                          self._border_for(key),
                          lines=DIAGRAM_LINES.get(key), fill=fill, mode=mode,
                          **kwargs)
        block.setRect(x, y, w, h)
        self.scene.addItem(block)
        self.blocks[key] = block
        return block

    @staticmethod
    def _border_for(key):
        if key in ("daq973a", "m908a_1", "m908a_2", "m907a"):
            return BLUE
        if key in ("u2355a", "u_ai", "u_ctr"):
            return TEAL
        if key in ("psu", "psu_detail"):
            return AMBER
        if key in ("dut", "grp_power", "grp_rails", "grp_clocks",
                   "grp_adc", "grp_vin", "grp_gnd", "grp_gpio"):
            return PURPLE
        if key in ("fixture", "control_board", "cell_press", "cell_inpos",
                   "cell_presence", "cell_estop"):
            return TEAL
        return GRAY

    # ------------------------------------------------------------------
    def _populate(self):
        # ============ layer 1 ============================================
        # blocks grew 86 -> 116 to host the icon row; the SCPI bus stays
        # at y=150 so nothing below this layer moves
        self._add_block("host", 480, 18, 470, 116, mode="dark", icon="pc",
                        icon_pos="left")
        self._add_block("peripherals", 1010, 18, 380, 116, fill="#f0f9ff",
                        icon=["wifi", "bt", "console", "router", "media",
                              "display", "camera", "mic", "speaker"],
                        icon_pos="row", icon_size=24)

        _polyline(self.scene, [QPointF(950, 76), QPointF(1010, 76)],
                  width=1.8)
        # size-9 label centered in the 60 px gap between the two blocks
        _text(self.scene, "USB/LAN", 952.5, 53, color=TEXT, size=9, bold=True)

        # SCPI control bus
        _polyline(self.scene, [QPointF(720, 134), QPointF(720, 150)],
                  arrow=False)
        _polyline(self.scene, [QPointF(310, 150), QPointF(1130, 150)],
                  arrow=False)
        _polyline(self.scene, [QPointF(310, 150), QPointF(310, 250)])
        _polyline(self.scene, [QPointF(720, 150), QPointF(720, 250)])
        _polyline(self.scene, [QPointF(1130, 150), QPointF(1130, 250)])
        # label moved BELOW the bus: the taller layer-1 blocks would
        # otherwise overlap it at the old y=110 spot
        _text(self.scene, "SCPI control bus", 450, 170, color=SUB, size=10.5)
        _text(self.scene, "GPIB", 272, 188, color=BLUE_DARK, size=11,
              bold=True)
        _text(self.scene, "USB", 684, 188, color=TEAL_DARK, size=11, bold=True)
        _text(self.scene, "LAN", 1094, 188, color=AMBER_DARK, size=11,
              bold=True)

        # ============ layer 2 containers ================================
        # DAQ973A + 2x DAQM908A + DAQM907A
        self._add_container("daq973a", 60, 250, 500, 220, BLUE, BLUE_FILL,
                            BLUE_DARK,
                            "DCV 0.003% - 2-wire Ω - frequency - LAN + GPIB",
                            abbr="DAQM", icon="daq973a")
        # U2355A
        self._add_container("u2355a", 600, 250, 360, 220, TEAL, TEAL_FILL,
                            TEAL_DARK,
                            "250 kSa/s - 16-bit - ±10 V - USB (USBTMC)",
                            abbr="DAQ", icon="u2355a")
        # N5747A
        self._add_container("psu", 1000, 250, 380, 220, AMBER, AMBER_FILL,
                            AMBER_DARK,
                            "60 V / 12.5 A / 750 W - remote sense - LAN/USB/GPIB",
                            abbr="PSU", icon="psu")

        # ============ layer 3: fixture band =============================
        # M80-4: the probe-board diagram block, its label and icon are
        # removed (UI only - equipment.fixture stays in the schema and
        # every engine branch is untouched)
        # ground plane bar
        _rect(self.scene, 110, 740, 1220, 14, "#e2e8f0", border="#94a3b8",
              z=-2)
        from PySide6.QtWidgets import QGraphicsEllipseItem
        circle = QGraphicsEllipseItem(726, 733, 28, 28)
        circle.setBrush(QColor("#ffffff"))
        circle.setPen(QPen(QColor(RED), 1.6))
        circle.setZValue(-1)
        self.scene.addItem(circle)
        _text(self.scene, "★", 733, 737, color=RED, size=14, bold=True, z=0)
        _text(self.scene, "GND★", 768, 740, color=RED, size=10, bold=True)

        # ============ layer 4: DUT band =================================
        self._add_container("dut", 60, 840, 1320, 264, PURPLE, PURPLE_FILL,
                            "#6d28d9",
                            "via fixture probes -> test point pads "
                            "(>32 mils, typical 40 mils) - stress strain gauge",
                            icon="dut")

        # ============ signal trunks =====================================
        # 908A measurement (blue)
        _polyline(self.scene, [QPointF(150, 470), QPointF(150, 902)],
                  color=BLUE, width=2.5)
        # up-sequence tap-off (orange)
        _polyline(self.scene, [QPointF(656, 470), QPointF(656, 902)],
                  color="#ea580c", width=2.5)
        # CLK1 jog (purple) - 907A totalizer
        _polyline(self.scene, [QPointF(430, 470), QPointF(430, 530),
                               QPointF(760, 530), QPointF(760, 902)],
                  color=PURPLE, width=2)
        # CLK2/3 (purple)
        _polyline(self.scene, [QPointF(850, 470), QPointF(850, 902)],
                  color=PURPLE, width=2)
        # AO jog (green)
        _polyline(self.scene, [QPointF(520, 470), QPointF(520, 480),
                               QPointF(930, 480), QPointF(930, 902)],
                  color="#16a34a", width=2)
        # power + sense (red)
        _polyline(self.scene, [QPointF(1080, 470), QPointF(1080, 902)],
                  color=RED, width=4)
        _polyline(self.scene, [QPointF(1120, 470), QPointF(1120, 902)],
                  color=RED, width=1.6, dashed=True)
        # plane -> DUT (gray)
        _polyline(self.scene, [QPointF(1330, 747), QPointF(1330, 902)],
                  color=GRAY, width=3)
        # ground drops to plane
        for x in (120, 930, 1320):
            _polyline(self.scene, [QPointF(x, 470), QPointF(x, 747)],
                      color="#94a3b8", width=2, dashed=True, arrow=False)
        # fixture DIO: 907A -> control board
        _polyline(self.scene, [QPointF(470, 448), QPointF(470, 474),
                               QPointF(390, 474), QPointF(390, 578)],
                  color=GRAY, width=2)
        # GPIO DIO: U2355A -> DUT GPIO
        _polyline(self.scene, [QPointF(940, 448), QPointF(940, 478),
                               QPointF(1030, 478), QPointF(1030, 1026)],
                  color=TEAL, width=2.2)

        # ============ layer 2 children ==================================
        self._add_block("m908a_1", 76, 314, 152, 152, icon="m908a",
                        icon_pos="mid", icon_size=34)
        self._add_block("m908a_2", 238, 314, 152, 152, icon="m908a",
                        icon_pos="mid", icon_size=34)
        self._add_block("m907a", 400, 314, 152, 152, icon="m907a",
                        icon_pos="mid", icon_size=34)
        self._add_block("u_ai", 610, 314, 170, 152, icon="u2355a",
                        icon_pos="mid", icon_size=34)
        self._add_block("u_ctr", 786, 314, 170, 152, icon="u2355a",
                        icon_pos="mid", icon_size=34)
        # icon left / text right (user direction: description moved
        # right of the icon; the J1 inhibit line was dropped)
        self._add_block("psu_detail", 1012, 314, 360, 152, icon="psu",
                        icon_pos="left", icon_size=40)

        # ============ layer 3 children ==================================
        self._add_block("control_board", 160, 578, 490, 150, icon="ate",
                        icon_pos="beside", icon_size=38)
        cells = (("cell_press", 170), ("cell_inpos", 288),
                 ("cell_presence", 406), ("cell_estop", 524))
        cell_icons = {"cell_press": "cylinder", "cell_inpos": "inpos",
                      "cell_presence": "presence", "cell_estop": "estop"}
        for key, x in cells:
            self._add_block(key, x, 646, 110, 68, icon=cell_icons[key],
                            icon_pos="top", icon_size=22)

        # ============ layer 4 groups ====================================
        self._add_block("grp_power", 76, 902, 590, 112)
        self._add_block("grp_clocks", 726, 902, 172, 112)
        self._add_block("grp_adc", 906, 902, 154, 112)
        self._add_block("grp_vin", 1068, 902, 218, 112)
        self._add_block("grp_gnd", 1304, 902, 118, 112)
        self._add_block("grp_gpio", 640, 1026, 520, 72)

    def _add_container(self, key, x, y, w, h, border, fill, header,
                       subtitle, abbr=None, icon=None):
        """Container block with a colored header band + subtitle line."""
        cfg = self.configs[key]
        block = BlockItem(key, cfg["title"], border, lines=[subtitle],
                          fill=fill, mode="header", abbr=abbr, icon=icon,
                          icon_pos="header")
        block.setRect(x, y, w, h)
        # header color override: BlockItem uses self.border for the band
        block.setZValue(-2)
        self.scene.addItem(block)
        self.blocks[key] = block
        return block

    # ------------------------------------------------------------------
    def _on_block_clicked(self, item):
        """M49a §2: the diagram is READ-ONLY - clicking a module opens
        the read-only Hardware Info dialog (never a config dialog)."""
        if not isinstance(item, BlockItem):
            return
        cfg = self.configs.get(item.key)
        if not cfg:
            return
        dlg = _HardwareInfoDialog(
            self, cfg["title"], self._info_fields(item.key),
            self._info_connections(item.key),
            role=cfg.get("short", ""))
        dlg.exec()

    def _info_fields(self, key):
        """(label, value) specification rows of one diagram module."""
        cfg = self.configs.get(key) or {}
        rows = [("Title", cfg.get("title", key))]
        rows += [(str(label), str(value))
                 for label, value in cfg.get("fields", [])]
        for group_name, group in (cfg.get("groups") or {}).items():
            for field, value in group.items():
                rows.append((f"{group_name}.{field}", str(value)))
        for field, value in (cfg.get("dio") or {}).items():
            rows.append((f"dio.{field}", str(value)))
        return rows

    def _info_connections(self, key):
        """Connection relationships shown in the Hardware Info dialog."""
        cfg = self.configs.get(key) or {}
        rows = []
        conn = cfg.get("connection") or {}
        if conn:
            rows.append(("Interface", str(conn.get("interface", ""))))
            rows.append(("Address", str(conn.get("address", ""))))
        for label, value in cfg.get("fields", []):
            if any(word in label.lower()
                   for word in ("interface", "bus", "connection", "port",
                                "driven", "tap", "io board")):
                rows.append((str(label), str(value)))
        if key in ("daq973a", "m908a_1", "m908a_2", "m907a"):
            rows.append(("Control bus", "SCPI (GPIB / LAN / USB)"))
        if key in ("u2355a", "u_ai", "u_ctr"):
            rows.append(("Control bus", "USB (USBTMC)"))
        if key in ("psu", "psu_detail"):
            rows.append(("Control bus", "LAN (LXI) / GPIB / USB"))
        if key in ("fixture", "control_board", "cell_press", "cell_inpos",
                   "cell_presence", "cell_estop"):
            rows.append(("Fixture", "ATE fixture control board"))
        if not rows:
            rows.append(("Connection", "See the left-hand hardware entry"))
        return rows

    # ------------------------------------------------------------------
    def _entry_source(self, entry_key):
        for _group, entries in LEFT_ENTRIES:
            for key, _label, _kind, source in entries:
                if key == entry_key:
                    return source
        return (entry_key, None)

    def open_entry(self, entry_key):
        """M49a: the ONLY edit entry point (left column Config button).

        Keeps the permission / manual-fixture gating that used to live
        on the diagram click."""
        owner, group = self._entry_source(entry_key)
        if not self._config_allowed:
            QMessageBox.information(
                self, "Permission",
                "Operator account cannot open equipment configuration.\n"
                "Ask the supervisor to grant this permission.")
            return
        if self._manual_fixture and owner in _MANUAL_FIXTURE_KEYS:
            QMessageBox.information(
                self, "Manual Fixture", MANUAL_FIXTURE_NOTICE)
            return
        # M80-5: the control-board Config opens immediately (M100 dropped
        # the DAQ973A "connect first" gate)
        if entry_key == "control_board":
            self._open_dio_entry(self.configs["control_board"])
            return
        if owner in _INSTRUMENT_CONN and group is None:
            self._open_instrument(owner)
            return
        if group is not None:
            self._open_group_entry(owner, group, entry_key)
            return
        cfg = self.configs.get(owner)
        if cfg is None:
            return
        if "table" in cfg:
            dlg = _DeviceTableDialog(self, cfg["title"], cfg["table"],
                                     note=_mode_note(self._mode),
                                     block_key=owner, config=cfg)
            dlg.exec()
            dlg.apply_to_config(cfg)
            return
        self._open_plain_entry(owner, cfg, entry_key)

    def _open_instrument(self, key):
        cfg = self.configs[key]
        dlg = _InstrumentDialog(self, cfg["title"], cfg["fields"], key,
                                self.virtual_mode,
                                manual=self._manual_fixture, config=cfg,
                                last_size=self._instrument_sizes.get(key))
        # the connect state lives on the PAGE (user report: it died
        # with the modal dialog); live LED sync on the left-column row
        dlg.set_connected(self._instrument_connections.get(key, False))
        dlg.connection_changed.connect(self._on_instrument_connection_changed)
        # M54 §1: the self-test now runs INSIDE the Config dialog - the
        # result must still reach the lamp (yellow -> green)
        dlg.self_test_changed.connect(
            lambda _sig_key, passed, k=key:
            self._set_instrument_selftest(k, passed))
        dlg.exec()
        self._instrument_sizes[key] = dlg.size()
        self._instrument_connections[key] = dlg._connected
        self._set_instrument_led(key)
        dlg.apply_to_config(cfg)

    def _on_instrument_connection_changed(self, key, connected):
        """The instrument dialog connected / disconnected -> update the
        page state and repaint that row's LED live."""
        self._instrument_connections[key] = bool(connected)
        self._set_instrument_led(key)

    # ------------------------------------- M80-5 control-board signals
    def _control_signals(self, cfg: dict) -> dict:
        """Signal values from ``signals`` or the legacy ``dio`` map.

        M100 B.2.4: a saved legacy default channel migrates to the new
        8-read + 8-write vocabulary; any other obsolete value is cleared
        (with an Event Log notice) so the operator re-assigns it."""
        groups = (cfg or {}).get("groups") or {}
        saved = dict(groups.get("signals") or {})
        legacy = dict((cfg or {}).get("dio") or {})
        out = {}
        for key, _label, default_channel, default_dir in DIO_SIGNALS:
            entry = dict(saved.get(key) or {})
            channel = str(entry.get("channel")
                          or legacy.get(key)
                          or (cfg or {}).get(key) or "")
            if channel in _LEGACY_DIO_DEFAULT:
                channel = _LEGACY_DIO_DEFAULT[channel]
            elif channel and channel not in DIO_CHANNELS:
                self.log_line.emit(
                    f"DIO channel {channel} is obsolete "
                    "(8R+8W split); re-assign it")
                channel = ""
            direction = str(entry.get("direction") or default_dir).lower()
            if direction not in ("input", "output"):
                direction = default_dir
            out[key] = {"channel": channel, "direction": direction}
        return out

    # --------------------------------------------- grouped config entries
    def _open_group_entry(self, owner, group, entry_key=None):
        cfg = self.configs.setdefault(owner, {"title": owner})
        groups = cfg.setdefault("groups", {})
        title = self._entry_label(entry_key) if entry_key else \
            f"{cfg['title']} - {group}"
        if (owner, group) == ("host_pc", "serial"):
            values = groups.setdefault(group, _default_serial_channels())
            dlg = _SerialChannelsDialog(self, values)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                groups[group] = dlg.values()
            return
        if (owner, group) == ("host_pc", "ssh"):
            values = groups.setdefault(group, _default_ssh_channel())
            dlg = _SshChannelDialog(self, values)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                groups[group] = dlg.values()
            return
        if (owner, group) == ("host_pc", "bluetooth"):
            values = groups.setdefault(group, _default_group(owner, group))
            dlg = _HostBluetoothDialog(self, values)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                groups[group] = dlg.values()
            return
        values = groups.setdefault(group, _default_group(owner, group))
        spec = GROUP_FIELDS[(owner, group)]
        dlg = _GroupConfigDialog(self, title, spec, values)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            groups[group] = dlg.values()

    def _open_plain_entry(self, owner, cfg, entry_key=None):
        if owner == "control_board":
            self._open_dio_entry(cfg)
            return
        editor = _BLOCK_EDITORS.get(owner)
        probe = None
        if entry_key in _TESTABLE_FORM_KEYS:
            probe = (lambda vals, k=entry_key:
                     self._probe_with_span(k, vals))
        dlg = _form_dialog(self, cfg["title"], cfg.get("fields", []),
                           note=_mode_note(self._mode),
                           editor=editor,
                           config=cfg if editor else None,
                           test_probe=probe)
        dlg.exec()
        if editor:
            dlg.apply_to_config(cfg)

    def _open_dio_entry(self, cfg):
        """M80-5: ATE Fixture Control Board - channel + direction rows."""
        dlg = _ControlBoardDialog(self, cfg["title"],
                                  self._control_signals(cfg))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cfg.setdefault("groups", {})["signals"] = dlg.values()
            cfg.pop("dio", None)
            self.apply_save_requested.emit()

    def _set_instrument_selftest(self, key, passed):
        """M54 §1: the self-test runs INSIDE the instrument Config dialog;
        its result still drives the lamp (yellow -> green)."""
        passed = bool(passed)
        self._instrument_selftest[key] = passed
        self.instrument_selftest_changed.emit(key, passed)
        self._set_instrument_led(key)

    # -- M54 §1: Test Connection inside the peripheral / DUT config ------
    def _entry_label(self, entry_key):
        for _group, entries in LEFT_ENTRIES:
            for key, label, _kind, _source in entries:
                if key == entry_key:
                    return label
        return entry_key

    def _probe_with_span(self, entry_key, values):
        """M54 §1: the config dialogs invoke this SAME availability probe
        off the UI thread; the M51 span is kept and the PASSED / FAILED
        text is reported into the dialog."""
        from mtkgui.startup_timing import begin, end
        span = f"equip: test connection {self._entry_label(entry_key)}"
        begin(span, category="equip")
        try:
            return self._probe_entry(entry_key, dict(values or {}))
        finally:
            end(span)

    def _probe_entry(self, entry_key, values):
        """The availability probe of one peripheral / DUT entry.

        Returns ``(ok, message)``; the message always names what was
        checked, so an unavailable sample produces a clear failure."""
        from .engine import host_platform

        if entry_key == "dut_ssh":
            host = str(values.get("ip") or "").strip()
            user = str(values.get("username") or "").strip()
            if not host:
                return False, ("SSH Login is not configured.\n"
                               "Open Config and enter the DUT IP address, "
                               "username and password.")
            lines = [f"DUT IP: {host}", f"User: {user or '(not set)'}"]
            if not host_platform.ping_host(host):
                lines.append("Network: no ping reply")
                return False, "\n".join(
                    lines + ["", "Test Connection FAILED: the DUT does not "
                             "answer ping."])
            lines.append("Network: ping OK")
            if not host_platform.tcp_port_open(host, 22):
                lines.append("SSH port 22: closed / unreachable")
                return False, "\n".join(
                    lines + ["", "Test Connection FAILED: sshd is not "
                             "reachable on port 22."])
            lines.append("SSH port 22: open")
            return True, "\n".join(
                lines + ["", "Test Connection PASSED: the SSH channel is "
                        "available."])

        if entry_key == "pc_wifi":
            ssid = str(values.get("ap_ssid") or "").strip()
            ap_ip = str(values.get("ap_ip") or "").strip()
            if not ssid and not ap_ip:
                return False, ("PC Wi-Fi is not configured.\n"
                               "Open Config and set the AP SSID / AP IP "
                               "address.")
            if ap_ip:
                result = host_platform.probe_host_ap_link(
                    ap_ip, expected_ssid=ssid or None)
                lines = list(result.get("lines") or [])
                lines.append(f"AP IP: {ap_ip}")
                ok = bool(result.get("ok"))
                verdict = ("Test Connection PASSED: the Host PC is associated "
                           "with the configured AP and the AP answers ping."
                           if ok else
                           "Test Connection FAILED: "
                           + str(result.get("error") or "AP unreachable"))
                return ok, "\n".join(lines + ["", verdict])
            info = host_platform.detect_current_wifi()
            current = str(info.get("ssid") or "").strip()
            lines = [f"Configured AP SSID: {ssid}",
                     f"Host PC association: {current or '(none)'}",
                     "AP IP: (not set)"]
            if current and current == ssid:
                return True, "\n".join(
                    lines + ["", "Test Connection PASSED: the Host PC is "
                            "associated with the configured AP."])
            return False, "\n".join(
                lines + ["", "Test Connection FAILED: no AP IP configured "
                        f'and the Host PC is not associated with "{ssid}".'])

        if entry_key == "dut_wifi":
            ssid = str(values.get("ssid") or "").strip()
            iface = str(values.get("interface") or "").strip()
            if not ssid:
                return False, ("DUT Wi-Fi is not configured.\n"
                               "Open Config and enter the DUT SSID.")
            import platform
            cmd = ("netsh wlan show networks"
                   if platform.system() == "Windows"
                   else "system_profiler SPAirPortDataType")
            scan = host_platform.run_link_cmd(cmd, timeout_s=25)
            lines = [f"DUT SSID: {ssid}",
                     f"DUT interface: {iface or '(not set)'}"]
            if ssid.lower() in str(scan).lower():
                return True, "\n".join(
                    lines + ["", "Test Connection PASSED: the DUT SSID "
                            "appears in the Host PC Wi-Fi scan."])
            return False, "\n".join(
                lines + ["", "Test Connection FAILED: the DUT SSID does not "
                        "appear in the Host PC Wi-Fi scan (check the DUT "
                        "Wi-Fi / hotspot power)."])

        if entry_key in ("pc_bt", "dut_bt"):
            name = str(values.get("name") or "").strip()
            addr = str(values.get("bd_addr") or "").strip()
            targets = str(values.get("scan_targets") or "").strip()
            adapter = str(values.get("adapter") or "").strip()
            if entry_key == "dut_bt" and not name and not addr:
                return False, ("DUT Bluetooth is not configured.\n"
                               "Open Config and enter the BT name / BD "
                               "address.")
            try:
                scan = host_platform.run_link_cmd(
                    host_platform.host_bt_scan_cmd(), timeout_s=25)
            except Exception as exc:            # noqa: BLE001
                return False, f"Bluetooth scan unavailable on this Host PC: {exc}"
            hay = str(scan).lower()
            wanted = name or addr or targets
            found = bool(wanted) and wanted.lower() in hay
            lines = [f"Host adapter: {adapter or '(default)'}",
                     f"Lookup: {wanted or '(scan only)'}"]
            if wanted:
                lines.append("Device found in the scan" if found
                             else "Device NOT found in the scan")
                if found:
                    return True, "\n".join(
                        lines + ["", "Test Connection PASSED: the Bluetooth "
                                "device is visible to the Host PC."])
                return False, "\n".join(
                    lines + ["", "Test Connection FAILED: the Bluetooth "
                            "device is not visible to the Host PC."])
            if hay.strip():
                return True, "\n".join(
                    lines + ["", "Test Connection PASSED: the Bluetooth "
                            "adapter is available."])
            return False, "\n".join(
                lines + ["", "Test Connection FAILED: no Bluetooth scan "
                        "result from the Host PC."])

        if entry_key == "router":
            router_ip = str(values.get("router_ip") or "").strip()
            dut_ip = str(values.get("dut_ip") or "").strip()
            if not router_ip and not dut_ip:
                return False, ("Ethernet Router is not configured.\n"
                               "Open Config and set the router / DUT IP "
                               "address.")
            lines = [f"Setup mode: {values.get('setup_mode') or '(not set)'}"]
            ok = True
            for label, ip in (("Router", router_ip), ("DUT", dut_ip)):
                if not ip:
                    lines.append(f"Ping {label}: (not set)")
                    continue
                reachable = host_platform.ping_host(ip)
                lines.append(f"Ping {label} {ip}: "
                             + ("OK" if reachable else "no reply"))
                ok = ok and reachable
            lines.append("")
            lines.append("Test Connection PASSED: every configured target "
                         "answers ping." if ok else
                         "Test Connection FAILED: a configured target does "
                         "not answer ping.")
            return ok, "\n".join(lines)

        return False, f"No Test Connection probe is defined for {entry_key}."

    def instrument_state(self, key):
        """M49a §3: lamp state of one instrument unit:
        green / grey / yellow (red only for an injected fault)."""
        if not self._instrument_connections.get(key, False):
            return "grey"
        if self._instrument_selftest.get(key, False):
            return "green"
        return "yellow"

    def refresh_from_configs(self):
        """M49a §4: after a YAML load the page re-reads the configs.
        Connection / self-test state is project-scoped and resets."""
        _migrate_peripherals(self.configs)
        self._instrument_connections = {}
        self._instrument_selftest = {}
        self._sync_group_toggles()
        for key in ("daq973a", "u2355a", "psu"):
            self._set_instrument_led(key)

