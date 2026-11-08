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
    "m908a_1": [("Wire mode", "2-wire"), ("Bias source", "off")],
    "m908a_2": [("Wire mode", "2-wire"), ("Bias source", "off")],
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
        ("Measure 2-wire Ω",
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
    )),
    ("Fixture", (
        ("control_board", "ATE Fixture Control Board", "form",
         ("control_board", None)),
    )),
    ("DUT", (
        ("dut_interface", "DUT Interface", "form", ("dut", "interface")),
        ("dut_console", "DUT Console", "form", ("dut", "console")),
    )),
    ("Peripherals", (
        ("router", "Wired & Wireless Network", "form",
         ("peripherals", "router")),
        ("jlink", "Flash Tool/Programmer", "form", ("jlink", None)),
    )),
)

#: instruments that own a main-window indicator lamp (M49a §3); the flash
#: tool is a third-party GUI and deliberately has NO lamp.
INDICATOR_INSTRUMENTS = ("daq973a", "u2355a", "psu")

#: M50 §4 / M80: peripheral configs that expose a Test Connection button
#: (availability check for a SAMPLE DUT / host setup - the real per-unit
#: verification runs inside the FCT Sequence steps).  M80-6c/9 dropped
#: the DUT Wi-Fi / Bluetooth / PC Wi-Fi / PC Bluetooth probes; the
#: network dialog owns its own probe.
_TESTABLE_FORM_KEYS = ("router",)

#: M80-1: left column width clamp (px)
LEFT_COLUMN_MIN_PX = 320
LEFT_COLUMN_MAX_PX = 480

#: M49a §5: grouped DUT / peripheral configs.  (owner key, group key) ->
#: editable fields (field key, label, default).  The YAML carries these
#: as nested keys (``equipment.dut.ssh.ip`` ...) so FCT steps can
#: reference them at runtime (M50).
GROUP_FIELDS = {
    ("dut", "wifi"): [
        ("ssid", "DUT SSID", ""), ("interface", "Interface", "mlan0")],
    ("dut", "bluetooth"): [
        ("name", "BT name", ""), ("bd_addr", "BD address", "")],
    ("dut", "ssh"): [
        ("ip", "IP address", ""), ("username", "Username", ""),
        ("password", "Password", "")],
    ("dut", "console"): [
        ("channel", "Console channel", ""), ("port", "Serial port", ""),
        ("baud", "Baud rate", "115200"), ("parity", "Parity", "None")],
    # M80-6b: one DUT Interface dialog edits Wi-Fi / Bluetooth / LAN
    ("dut", "interface"): [
        ("ssid", "DUT SSID", ""), ("wifi_interface", "DUT Wi-Fi interface",
                                   "mlan0"),
        ("bt_name", "BT name", ""), ("bd_addr", "BD address", ""),
        ("ethernet_ports", "Ethernet port(s)", "")],
    ("peripherals", "wifi"): [
        ("ap_ssid", "AP SSID", ""), ("ap_ip", "AP IP", ""),
        ("host_ip", "Host IP", ""), ("ap_password", "AP password", "")],
    ("peripherals", "bluetooth"): [
        ("adapter", "Host adapter", ""),
        ("scan_targets", "Scan targets", "")],
    ("peripherals", "router"): [
        ("setup_mode", "Setup mode", "direct"),
        ("router_ip", "Router IP", ""), ("dut_ip", "DUT IP", ""),
        # M55: runtime sources for the LAN Setup / Wi-Fi Connect static
        # addressing (the step dialogs no longer edit these)
        ("netmask", "Netmask", "255.255.255.0"), ("gateway", "Gateway", ""),
        # M65: the two network modules (see NETWORK_FIELDS below)
    ],
}

#: user-visible name of the combined wired / wireless peripheral
NETWORK_TITLE = "Wired & Wireless Network"

#: M65: per-module fields of the "Wired & Wireless Network" peripheral.
#: Names are part of the YAML contract (plain scalars, snake_case).
NETWORK_FIELDS = [
    ("wired_enabled", "Wired module enabled", True),
    ("wifi_enabled", "Wireless module enabled", True),
    ("wired_mode", "Wired mode", "direct"),
    ("wired_dut_ports", "DUT port(s)", ""),
    ("wired_host_port", "Host PC LAN port", ""),
    ("wired_eth_ports", "Ethernet port(s)", ""),
    ("wired_host_ip", "Host PC wired IP", ""),
    ("wired_gateway", "Router gateway IP", ""),
    ("wifi_mode", "Wireless mode", "hotspot"),
    ("wifi_dut_iface", "DUT Wi-Fi interface", "mlan0"),
    ("hotspot_ssid", "Hotspot SSID", ""),
    ("hotspot_password", "Hotspot password", ""),
    ("router_ap_ssid", "Router AP SSID", ""),
    ("router_ap_password", "Router AP password", ""),
    ("wifi_host_ip", "Host PC Wi-Fi IP", ""),
    ("wifi_gateway", "Router gateway IP (Wi-Fi)", ""),
]

#: the network module fields join the legacy router group (YAML contract)
GROUP_FIELDS[("peripherals", "router")] = (
    GROUP_FIELDS[("peripherals", "router")] + NETWORK_FIELDS)

#: module -> [(mode key, mode name, one-line description)]
NETWORK_MODES = {
    "wired": [
        ("direct", "Direct (no router)",
         "DUT -- RJ45 -- Host PC LAN port"),
        ("lan", "LAN via router",
         "DUT -> Ethernet switch/router -> Host PC RJ45"),
    ],
    "wifi": [
        ("hotspot", "Host PC hotspot (no router)",
         "DUT (mlan0) ~~ Wi-Fi ~~ Host PC AP (netsh)"),
        ("router", "Wi-Fi router",
         "DUT (mlan0) ~~ Wi-Fi ~~ Router AP ~~ Wi-Fi ~~ Host PC"),
    ],
}

#: M80-5: canonical DIO channel vocabulary of the control board
#: (same set as steps.py "DIO01-DIO08")
DIO_CHANNELS = tuple(f"DIO{index:02d}" for index in range(1, 9))

#: the 4 DIO signals of the ATE fixture control board (DAQM907A Port1/2):
#: (signal key, label, default channel, default direction)
DIO_SIGNALS = [
    ("press", "Press cylinder", "DIO01", "output"),
    ("inpos", "Cylinder in-position", "DIO02", "output"),
    ("presence", "DUT presence", "DIO03", "output"),
    ("estop", "E-stop healthy", "DIO04", "input"),
]

#: legacy 3-tuple view (channel only) still read by the old ``dio:`` map
DIO_FIELDS = [(key, label, channel)
              for key, label, channel, _direction in DIO_SIGNALS]

#: M64: the third-party GUI flash tool as a CATEGORY ("J-Link" is only
#: one concrete tool of it).  The config carries the FULL executable
#: path, the optional CLI arguments and the operator prompt; "Self-Test"
#: launches the tool and asks the operator whether it is usable.
FLASH_TOOL_NAME = "Flash Tool/Programmer"

#: default operator prompt of the Flash_GUI step (tool-agnostic)
DEFAULT_FLASH_TOOL_PROMPT = (
    "Flash Tool/Programmer started. Please perform the flashing yourself "
    "and judge the result: click Pass = flashing success, click Fail = "
    "flashing failed - the flash step is marked FAIL and the test program "
    "stops immediately.")

JLINK_FIELDS = [
    ("executable_path", "Executable path", ""),
    ("arguments", "Arguments", ""),
    ("prompt", "Prompt message", DEFAULT_FLASH_TOOL_PROMPT),
]


def _default_group(owner, name):
    """Fresh dict with the default field values of one grouped config."""
    return {key: default
            for key, _label, default in GROUP_FIELDS[(owner, name)]}



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
    "probes": ["J-Link · PE Micro · Lauterbach",
               "CMSIS-DAP · MCU-LINK · OpenSDA"],
    "host": ["Common Test Platform", "ICT / FCT / Flash / Reports"],
    "peripherals": ["Wi-Fi · Bluetooth · Router · Media converter",
                    "Display · Camera · Mic · Earphone · Speaker"],
    "m908a_1": ["40-ch SE MUX", "CH101 - CH140",
                "TP_P1 - TP_P40", "Ω + DCV reuse"],
    "m908a_2": ["40-ch SE MUX", "CH201 - CH240",
                "TP_P41 - TP_P80", "Ω + DCV reuse"],
    "m907a": ["TOT: 0-100 kHz->CLK1",
              "AO x2: ±12 V 16-bit",
              "DIO 16-ch open-drain"],
    "u_ai": ["AI x16 (max)", "12 critical rails",
             "≈20 kSa/s/ch -> CSV"],
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
        "probes": {
            "title": "Flash / Debug Probes",
            "table": [
                ("J-Link", "ARM flash / debug", "USB"),
                ("PE Micro", "NXP flash / debug", "USB"),
                ("Lauterbach", "TRACE32 debug / trace", "USB"),
                ("CMSIS-DAP", "CMSIS standard probe", "USB HID"),
                ("MCU-LINK", "NXP MCU probe", "USB HID"),
                ("OpenSDA", "NXP OpenSDA", "USB"),
            ],
        },
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
                ("PC Wi-Fi", "RF connectivity", "Not connected"),
                ("PC Bluetooth", "RF connectivity", "Not connected"),
                ("Wired & Wireless Network", "Wired / Wi-Fi connectivity",
                 "Not connected"),
                ("Media Converter", "T1 / T1S media", "Not connected"),
                ("Display", "DSI-MIPI check", "Not connected"),
                ("Camera", "CSI-MIPI check", "Not connected"),
                ("Microphone / Earphone", "Audio path check", "Not connected"),
                ("Speaker", "Audio output check", "Not connected"),
            ],
            # M49a §5: shared PC-side parameters (runtime-referenced by
            # FCT steps in M50).  Router setup mode: direct | via_ap.
            "groups": {
                "wifi": _default_group("peripherals", "wifi"),
                "bluetooth": _default_group("peripherals", "bluetooth"),
                "router": _default_group("peripherals", "router"),
            },
        },
        "jlink": {
            "title": FLASH_TOOL_NAME,
            "fields": [
                ("Role", "Third-party flash GUI (Flash_GUI step)"),
                ("Managed by", "MTK launches the GUI; operator judges"),
                ("Self-test", "Launches the tool and asks the operator to "
                              "confirm usability"),
            ],
            "params": {key: default
                       for key, _label, default in JLINK_FIELDS},
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
            "title": "U2355A - Analog Inputs",
            "short": "Analog Inputs",
            "fields": [
                ("Resource", "AI x16 (max)"),
                ("Used", "12 critical rails"),
                ("Rate", "≈20 kSa/s/ch -> CSV"),
                ("Range", "±10 V, 16-bit"),
                ("Tap", "parallel at power net points"),
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
            # M49a §5: the DUT group (Wi-Fi / Bluetooth / SSH login /
            # console).  M80: board OS and the separate Wi-Fi / Bluetooth
            # entries are gone - "interface" edits all three blocks.
            "groups": {
                "wifi": _default_group("dut", "wifi"),
                "bluetooth": _default_group("dut", "bluetooth"),
                "ssh": _default_group("dut", "ssh"),
                "console": _default_group("dut", "console"),
                "interface": {"ethernet": {"ports": ""}},
            },
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


def _ic_jlink(p):
    _fill(p, STEEL)
    p.drawRoundedRect(QRectF(18.5, 4, 11, 7), 1, 1)
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(15, 11, 18, 20), 3, 3)
    p.drawLine(QPointF(19, 31), QPointF(19, 36))
    p.drawLine(QPointF(24, 31), QPointF(24, 36))
    p.drawLine(QPointF(29, 31), QPointF(29, 36))
    _fill(p, GREEN)
    p.drawEllipse(QPointF(24, 18), 2, 2)


def _ic_pemicro(p):
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(10, 14, 28, 15), 3, 3)
    path = QPainterPath(QPointF(10, 21))
    path.cubicTo(QPointF(6, 21), QPointF(5, 17), QPointF(8, 15))
    p.drawPath(path)
    p.drawRoundedRect(QRectF(13, 29, 22, 5), 1, 1)
    for x in (16, 20, 24, 28, 32):
        p.drawLine(QPointF(x, 34), QPointF(x, 38))
    _fill(p, GREEN)
    p.drawEllipse(QPointF(32, 20), 1.8, 1.8)


def _ic_lauterbach(p):
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(5, 17, 38, 15), 2, 2)
    p.drawEllipse(QPointF(12, 24.5), 2.6, 2.6)
    p.drawEllipse(QPointF(20, 24.5), 2.6, 2.6)
    p.drawLine(QPointF(28, 21.5), QPointF(39, 21.5))
    p.drawLine(QPointF(28, 27.5), QPointF(39, 27.5))
    p.drawLine(QPointF(10, 32), QPointF(10, 36))
    p.drawLine(QPointF(38, 32), QPointF(38, 36))


def _ic_cmsisdap(p):
    _fill(p, STEEL)
    p.drawRoundedRect(QRectF(19, 4, 10, 6), 1, 1)
    _p(p, GRAY)
    p.drawRoundedRect(QRectF(16, 10, 16, 22), 2.5, 2.5)
    for x in (20, 24, 28):
        p.drawLine(QPointF(x, 32), QPointF(x, 37))
    _fill(p, GREEN)
    p.drawEllipse(QPointF(24, 16.5), 1.6, 1.6)


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
    "pc": _ic_pc, "jlink": _ic_jlink, "pemicro": _ic_pemicro,
    "lauterbach": _ic_lauterbach, "cmsisdap": _ic_cmsisdap,
    "mculink": _ic_mculink, "opensda": _ic_opensda,
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
# user direction 2026-10-17: the Flash / Debug Probes rows ARE the
# third-party flash tools - each row edits that tool's CLI profile
# (executable, command templates, the output patterns the engine
# judges on, timeout).  Keeping the rules in the project YAML means
# they are field-maintainable without a rebuild.
def _flash_tool_spec(exe: str) -> list:
    """CLI profile fields for one Flash / Debug Probe row.  The keys
    match the driver options; ``{image}`` in a command template is
    substituted with the step's firmware image."""
    return [
        ("exe", "Executable path", exe),
        ("device", "Device", ""),
        ("interface", "Interface", "SWD"),
        ("speed_khz", "Speed (kHz)", "4000"),
        ("write_cmd", "Write command", "loadfile {image}"),
        ("verify_cmd", "Verify command", "verifyfile {image}"),
        ("reset_cmd", "Reset & run command", "r|g|exit"),
        ("ok_regex", "OK pattern", r"O\.K\."),
        ("verify_regex", "Verify OK pattern", r"O\.K\."),
        ("fail_regex", "Fail pattern", "Error|Cannot connect|FAILED"),
        ("timeout_s", "Timeout (s)", "120"),
    ]


_DEVICE_EDITORS: dict[tuple[str, str], list] = {
    ("probes", tool): _flash_tool_spec(
        "C:/Program Files/SEGGER/JLink/JLink.exe" if tool == "J-Link"
        else "")
    for tool in ("J-Link", "PE Micro", "Lauterbach", "CMSIS-DAP",
                 "MCU-LINK", "OpenSDA")
}

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


def _flash_tool_self_test(values, launch=None, ask=None):
    """M64: real Self-Test of the third-party flash tool.

    Launches the configured executable DETACHED (the config dialog never
    waits for the tool process), then asks the operator whether it
    started and is usable.  ``launch`` / ``ask`` are injectable so the
    headless tests can prove the async contract.

    Returns ``(ok, message)`` - PASSED / FAILED text for the dialog.
    """
    path = str((values or {}).get("executable_path") or "").strip()
    if not path or not os.path.isabs(path):
        return False, (f"{FLASH_TOOL_NAME} is not configured. Open Config "
                       "and set the Executable path.")
    args = str((values or {}).get("arguments") or "").strip()
    if launch is None:
        from .engine.flash_tool import launch_tool_gui as launch
    started, detail = launch(path, args)
    if not started:
        return False, (f"Self-Test FAILED: {FLASH_TOOL_NAME} could not be "
                       f"started ({detail}).")
    prompt = (str((values or {}).get("prompt") or "").strip()
              or DEFAULT_FLASH_TOOL_PROMPT)
    question = f"{prompt}\n\nDid the tool start and is it usable?"
    if ask is None:
        def ask(text):                       # pragma: no cover - Qt dialog
            answer = QMessageBox.question(
                None, f"{FLASH_TOOL_NAME} Self-Test", text,
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            return answer == QMessageBox.StandardButton.Yes
    if ask(question):
        return True, f"Self-Test PASSED: {FLASH_TOOL_NAME} is usable."
    return False, ("Self-Test FAILED: operator reports the tool is not "
                   "usable.")


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
# M80-6b: one "DUT Interface" dialog editing Wi-Fi / Bluetooth / Ethernet
# ---------------------------------------------------------------------------
def normalise_dut_ports(text) -> str:
    """Comma list of RJ45 port names: trim, drop empties, de-duplicate
    and keep only ``[A-Za-z0-9._-]``.  Empty is legal (= no wired link)."""
    import re
    seen = []
    for token in str(text or "").split(","):
        token = token.strip()
        if not token or not re.fullmatch(r"[A-Za-z0-9._-]+", token):
            continue
        if token not in seen:
            seen.append(token)
    return ",".join(seen)


class DutInterfaceDialog(QDialog):
    """M80-6b: DUT Wi-Fi + Bluetooth + Ethernet in one dialog.

    The three blocks keep their existing YAML paths (``dut.wifi.*`` /
    ``dut.bluetooth.*`` / ``dut.interface.ethernet.ports``); the DUT IP
    is single-sourced in ``peripherals.router.dut_ip`` and only shown
    read-only here."""

    def __init__(self, parent, wifi: dict, bluetooth: dict,
                 ethernet_ports: str, dut_ip: str):
        super().__init__(parent)
        self.setWindowTitle(f"DUT Interface - Configuration")
        fit_dialog(self, 640, 520)
        root = QVBoxLayout(self)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)

        self._wifi = {}
        wifi_box = QGroupBox("DUT Wi-Fi")
        wform = QFormLayout(wifi_box)
        wform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for key, label, default in GROUP_FIELDS[("dut", "wifi")]:
            edit = QLineEdit(str((wifi or {}).get(key, default) or ""))
            edit.setPlaceholderText(default or "optional")
            self._wifi[key] = edit
            wform.addRow(f"{label}:", edit)
        lay.addWidget(wifi_box)

        self._bt = {}
        bt_box = QGroupBox("DUT Bluetooth")
        bform = QFormLayout(bt_box)
        bform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for key, label, default in GROUP_FIELDS[("dut", "bluetooth")]:
            edit = QLineEdit(str((bluetooth or {}).get(key, default) or ""))
            edit.setPlaceholderText(default or "optional")
            self._bt[key] = edit
            bform.addRow(f"{label}:", edit)
        lay.addWidget(bt_box)

        lan_box = QGroupBox("DUT Ethernet (RJ45)")
        lform = QFormLayout(lan_box)
        lform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_ports = QLineEdit(str(ethernet_ports or ""))
        self.edit_ports.setPlaceholderText("eth0,eth1")
        lform.addRow("Ethernet port(s):", self.edit_ports)
        dut_ip_edit = QLineEdit(str(dut_ip or ""))
        dut_ip_edit.setReadOnly(True)
        dut_ip_edit.setPlaceholderText("set on Wired & Wireless Network")
        lform.addRow("DUT IP (read-only):", dut_ip_edit)
        lay.addWidget(lan_box)

        note = QLabel(
            "DUT IP stays single-sourced on the Wired & Wireless Network "
            "page; this dialog only edits the DUT-side identifiers.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        apply_scroll_to_dialog(self, body)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict:
        return {
            "wifi": {key: edit.text().strip()
                     for key, edit in self._wifi.items()},
            "bluetooth": {key: edit.text().strip()
                          for key, edit in self._bt.items()},
            "ethernet_ports": normalise_dut_ports(self.edit_ports.text()),
        }


# ---------------------------------------------------------------------------
# M80-5: ATE fixture control board - DIO channel + direction
# ---------------------------------------------------------------------------
class _ControlBoardDialog(QDialog):
    """Four signal rows: DIO channel combo + exclusive Input / Output.

    Gated by the instrument status hub: the Config button and this
    dialog's OK stay disabled until DAQ973A is connected and its Test
    Connection result is OK."""

    #: exact gating tooltip required by the directive
    GATE_TOOLTIP = "Connect DAQ973A Mainframe first"

    def __init__(self, parent, title, signals: dict, ready: bool):
        super().__init__(parent)
        self.setWindowTitle(f"{title} - DIO signals")
        fit_dialog(self, 720, 460)
        self._ready = bool(ready)
        root = QVBoxLayout(self)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)

        self.gate_label = QLabel(self.GATE_TOOLTIP)
        self.gate_label.setObjectName("warn")
        self.gate_label.setVisible(not self._ready)
        lay.addWidget(self.gate_label)

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
        self.btn_ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_ok.setEnabled(self._ready)
        self.btn_ok.setToolTip("" if self._ready else self.GATE_TOOLTIP)
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
# M80-8: read-only Host PC Bluetooth information
# ---------------------------------------------------------------------------
def host_bluetooth_block(parent=None) -> QGroupBox:
    """Read-only Host PC Bluetooth name / address; never raises and
    never writes YAML.  A failed probe renders ``unavailable``."""
    box = QGroupBox("Host PC Bluetooth")
    lay = QFormLayout(box)
    lay.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    name_edit = QLineEdit("")
    addr_edit = QLineEdit("")
    for edit in (name_edit, addr_edit):
        edit.setReadOnly(True)
    try:
        from .engine import host_platform
        name, address = host_platform.host_bt_identity()
    except Exception:                        # noqa: BLE001 - read-only info
        name, address = "", ""
    name_edit.setText(str(name or "") or "unavailable")
    addr_edit.setText(str(address or "") or "unavailable")
    lay.addRow("Host Bluetooth name:", name_edit)
    lay.addRow("Host Bluetooth address:", addr_edit)
    return box


# ---------------------------------------------------------------------------
# M65: "Wired & Wireless Network" - mode-selection page + per-mode dialogs
# ---------------------------------------------------------------------------
class _TopologyDiagram(QWidget):
    """Small schematic topology drawing of one network mode."""

    #: M80-7: minimum topology font size (pt)
    FONT_PT = 10.0

    def __init__(self, topology: str, parent=None):
        super().__init__(parent)
        self._topology = topology
        self.setMinimumHeight(86)
        self.setToolTip("Schematic topology of this mode")

    def _nodes(self):
        if self._topology == "lan":
            return ["DUT", "Router / switch", "Host PC"]
        if self._topology == "router":
            return ["DUT", "Router AP", "Host PC"]
        if self._topology == "hotspot":
            return ["DUT", "Host PC (AP)"]
        return ["DUT", "Host PC"]

    def paintEvent(self, _event):                    # noqa: N802 - Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        nodes = self._nodes()
        n = len(nodes)
        margin = 8
        gap = 8
        box_w = max(40, int((w - 2 * margin - gap * (n - 1)) / n))
        box_h = 30
        top = 12
        centers = []
        for i, name in enumerate(nodes):
            x = margin + i * (box_w + gap)
            painter.setPen(QPen(QColor("#8a94a6"), 1.2))
            painter.setBrush(QColor("#f3f5f8"))
            painter.drawRoundedRect(x, top, box_w, box_h, 6, 6)
            painter.setPen(QColor("#2b3445"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            font = QFont(self.font())
            font.setPointSizeF(self.FONT_PT)
            painter.setFont(font)
            painter.drawText(x, top, box_w, box_h,
                             Qt.AlignmentFlag.AlignCenter, name)
            centers.append((x + box_w // 2, top + box_h // 2))
        wireless = self._topology in ("hotspot", "router")
        pen = QPen(QColor("#2f6fb3" if not wireless else "#b45309"), 1.4)
        if wireless:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        for (x1, y1), (x2, _y2) in zip(centers, centers[1:]):
            painter.drawLine(x1 + box_w // 2, y1, x2 - box_w // 2, y1)
        font = QFont(self.font())
        font.setPointSizeF(self.FONT_PT)
        painter.setFont(font)
        painter.setPen(QColor("#6b7280"))
        caption = {
            "direct": "RJ45 (no router)",
            "lan": "RJ45 - router gateway",
            "hotspot": "Wi-Fi (netsh hotspot)",
            "router": "Wi-Fi - router gateway",
        }.get(self._topology, "")
        painter.drawText(0, h - 18, w, 16, Qt.AlignmentFlag.AlignCenter,
                         caption)


class _ModeCard(QFrame):
    """Clickable radio-style mode card (diagram + name + description)."""

    clicked = Signal(str)
    doubleClicked = Signal(str)

    def __init__(self, mode_key: str, name: str, description: str,
                 topology: str, parent=None):
        super().__init__(parent)
        self.mode_key = mode_key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(240)
        # M80-7: 12 px card padding, 12 px inter-card spacing and a real
        # minimum height so a maximised dialog grows the cards
        self.setMinimumHeight(170)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)
        lay.addWidget(_TopologyDiagram(topology))
        title = QLabel(name)
        font = QFont(title.font())
        font.setBold(True)
        title.setFont(font)
        title.setWordWrap(True)
        lay.addWidget(title)
        desc = QLabel(description)
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        self._selected = False
        self._apply_style()

    def _apply_style(self):
        if self._selected:
            self.setStyleSheet(
                "QFrame { border: 2px solid #2f6fb3; border-radius: 8px; "
                "background: #eaf2fb; }")
        else:
            self.setStyleSheet(
                "QFrame { border: 1px solid #c9d1dc; border-radius: 8px; "
                "background: #ffffff; }")

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self._apply_style()

    def mousePressEvent(self, event):                # noqa: N802 - Qt
        self.clicked.emit(self.mode_key)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):          # noqa: N802 - Qt
        self.doubleClicked.emit(self.mode_key)
        super().mouseDoubleClickEvent(event)


#: (field key, shown label) per network mode
_MODE_FIELD_LABELS = {
    "direct": [("wired_dut_ports", "DUT Port"),
               ("wired_host_port", "Host PC LAN Port"),
               ("wired_host_ip", "Host PC IP")],
    "lan": [("wired_dut_ports", "DUT Port(s)"),
            ("wired_host_port", "Host PC RJ45 Port"),
            ("wired_host_ip", "Host PC wired IP"),
            ("wifi_host_ip", "Host PC Wi-Fi IP"),
            ("wired_gateway", "Router gateway IP")],
    "hotspot": [("wifi_dut_iface", "DUT Wi-Fi interface"),
                ("hotspot_ssid", "Host PC AP SSID"),
                ("hotspot_password", "Host PC AP password"),
                ("wifi_host_ip", "Host PC Wi-Fi IP")],
    "router": [("wifi_dut_iface", "DUT Wi-Fi interface"),
               ("router_ap_ssid", "Router AP SSID"),
               ("router_ap_password", "Router AP password"),
               ("wifi_host_ip", "Host PC Wi-Fi IP"),
               ("wifi_gateway", "Router gateway IP")],
}

#: M80-12: exact mode dialog titles (wired vs wireless distinguished)
MODE_TITLES = {
    "direct": "Wired (RJ45) - Direct (no router)",
    "lan": "Wired (RJ45) - LAN via router",
    "hotspot": "Wireless (AP hotspot) - Host PC hotspot (no router)",
    "router": "Wireless (AP hotspot) - Wi-Fi router",
}

#: M80-10: exact field hints
_MODE_FIELD_HINTS = {
    "router_ap_password": "the DUT also uses it when joining the same AP",
    "wifi_dut_iface": "login to the DUT and run 'ifconfig' to read the "
                      "interface name (e.g. mlan0)",
}

_MODE_NAMES = {"direct": "Direct (no router)", "lan": "LAN via router",
               "hotspot": "Host PC hotspot (no router)",
               "router": "Wi-Fi router"}

_MODE_GATEWAY_KEY = {"lan": "wired_gateway", "router": "wifi_gateway"}


class _RouterModeDialog(QDialog):
    """Pure-field configuration dialog of ONE network mode."""

    def __init__(self, parent, mode: str, values: dict, on_save=None):
        super().__init__(parent)
        self._mode = mode
        self._values = dict(values or {})
        self._on_save = on_save
        self._auto_detected = set()
        self.setWindowTitle(MODE_TITLES.get(mode, f"{NETWORK_TITLE} - "
                                            f"{_MODE_NAMES.get(mode, mode)}"))
        fit_dialog(self, 640, 540)
        root = QVBoxLayout(self)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)

        hint = QLabel({
            "direct": "Direct RJ45 link between the DUT and the Host PC "
                      "(no router in between).",
            "lan": "The Host PC reaches the DUT through the router / switch.",
            "hotspot": "The Host PC runs the Wi-Fi access point (netsh "
                       "Hosted Network); the DUT joins it.",
            "router": "The Host PC joins the Router AP; the DUT joins the "
                      "same router.",
        }.get(mode, ""))
        hint.setWordWrap(True)
        lay.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._edits = {}
        for key, label in _MODE_FIELD_LABELS.get(mode, []):
            edit = QLineEdit(str(self._values.get(key, "") or ""))
            # bounded fields: two modules fit side by side without a
            # horizontal scrollbar / oversized stretched rows
            edit.setMaximumWidth(400)
            if key in _MODE_FIELD_HINTS:
                edit.setToolTip(_MODE_FIELD_HINTS[key])
            if key in ("wired_dut_ports", "wired_eth_ports",
                       "wifi_dut_iface"):
                edit.setPlaceholderText("typed by hand from the DUT (ifconfig)")
            elif key.endswith("password"):
                edit.setPlaceholderText("empty = open hotspot")
            else:
                edit.setPlaceholderText("empty = not configured")
            self._edits[key] = edit
            form.addRow(f"{label}:", edit)
        if mode in ("direct", "hotspot"):
            gw = QLineEdit("— not applicable")
            gw.setReadOnly(True)
            gw.setMaximumWidth(400)
            form.addRow("Gateway:", gw)
        lay.addLayout(form)

        if mode in _MODE_GATEWAY_KEY:
            router_hint = QLabel(
                "Host PC wired RJ45 and Wi-Fi are both assumed connected to "
                "the router.")
            router_hint.setObjectName("muted")
            router_hint.setWordWrap(True)
            lay.addWidget(router_hint)
            warn = QLabel(
                "Configure the Host PC <-> Router link in the system "
                "network settings first; otherwise fill the fields in by "
                "hand.")
            warn.setObjectName("warn")
            warn.setWordWrap(True)
            lay.addWidget(warn)

        buttons = QHBoxLayout()
        self.btn_detect = QPushButton("Auto Detect")
        buttons.addWidget(self.btn_detect)
        self.btn_test = None
        if mode in _MODE_GATEWAY_KEY:
            self.btn_test = QPushButton("Test Connection")
            buttons.addWidget(self.btn_test)
        buttons.addStretch(1)
        lay.addLayout(buttons)

        if mode == "hotspot":
            lay.addWidget(self._hotspot_block())

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        lay.addWidget(self.result_label)

        apply_scroll_to_dialog(self, body)
        bottom = QHBoxLayout()
        self.btn_apply = QPushButton("Apply && Save YAML")
        bottom.addWidget(self.btn_apply)
        bottom.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        bottom.addWidget(close)
        root.addLayout(bottom)

        self.btn_detect.clicked.connect(self._detect)
        if self.btn_test is not None:
            self.btn_test.clicked.connect(self._test_connection)
        self.btn_apply.clicked.connect(self._apply_save)
        # M80-10/11: run the detect path once when the dialog opens
        QTimer.singleShot(0, self, qt_safe(self._auto_detect_on_open))

    # --------------------------------------------- M80-10/11 auto-detect
    def _auto_detect_on_open(self):
        from .engine import host_platform
        try:
            self._fill_auto(host_platform.detect_host_network() or {})
        except Exception:                    # noqa: BLE001 - best effort
            pass

    def _mark_auto(self, key):
        edit = self._edits.get(key)
        if edit is None:
            return
        self._auto_detected.add(key)
        tooltip = edit.toolTip().strip()
        edit.setToolTip(f"{tooltip} - auto-detected" if tooltip
                        else "auto-detected")

    def _fill_auto(self, info: dict):
        """Fill the auto-detected fields from one detect result."""
        if self._mode == "router":
            ssid = str((info or {}).get("wifi_ssid") or "").strip()
            edit = self._edits.get("router_ap_ssid")
            if ssid and edit is not None:
                if not edit.text().strip():
                    edit.setText(ssid)
                self._mark_auto("router_ap_ssid")
        if self._mode == "lan":
            for key, source in (("wired_host_port", "wired_port"),
                                ("wired_host_ip", "wired_ip"),
                                ("wired_gateway", "gateway")):
                value = str((info or {}).get(source) or "").strip()
                edit = self._edits.get(key)
                if value and edit is not None:
                    edit.setText(value)
                    self._mark_auto(key)

    # ---------------------------------------------------------- helpers
    def _report(self, ok: bool, message: str):
        self.result_label.setText(message)
        self.result_label.setStyleSheet(
            "color: %s;" % ("#15803d" if ok else "#b91c1c"))

    def _run_async(self, fn, on_done):
        worker = _PeripheralTestWorker(fn, self)
        worker.done.connect(lambda ok, msg: (worker.deleteLater(),
                                             on_done(ok, msg)))
        worker.start()

    def values(self) -> dict:
        return {key: edit.text().strip()
                for key, edit in self._edits.items()}

    def collected_values(self) -> dict:
        """The whole group dict with this mode's edits applied."""
        data = dict(self._values)
        data.update(self.values())
        return data

    def _detect(self):
        self.btn_detect.setEnabled(False)
        self.result_label.setStyleSheet("")
        self.result_label.setText("Auto Detect ...")
        self._detected = {}

        def work():
            from .engine import host_platform
            info = host_platform.detect_host_network()
            self._detected = dict(info or {})
            return bool(any(str(v or "").strip()
                            for v in self._detected.values())), \
                "Auto Detect finished"

        def done(_ok, _message):
            self.btn_detect.setEnabled(True)
            info = dict(self._detected or {})
            wired = str(info.get("wired_ip") or "")
            wifi = str(info.get("wifi_ip") or "")
            gw = str(info.get("gateway") or "")
            port = str(info.get("wired_port") or "")
            if self._mode in ("direct", "lan") and port:
                if "wired_host_port" in self._edits:
                    self._edits["wired_host_port"].setText(port)
                    self._mark_auto("wired_host_port")
            if self._mode in ("direct", "lan") and wired:
                if "wired_host_ip" in self._edits:
                    self._edits["wired_host_ip"].setText(wired)
                    self._mark_auto("wired_host_ip")
            if self._mode in ("lan", "hotspot", "router") and wifi:
                if "wifi_host_ip" in self._edits:
                    self._edits["wifi_host_ip"].setText(wifi)
                    self._mark_auto("wifi_host_ip")
            gateway_key = _MODE_GATEWAY_KEY.get(self._mode)
            if gateway_key and gw:
                self._edits[gateway_key].setText(gw)
                self._mark_auto(gateway_key)
            ssid = str(info.get("wifi_ssid") or "").strip()
            if self._mode == "router" and ssid and \
                    "router_ap_ssid" in self._edits \
                    and not self._edits["router_ap_ssid"].text().strip():
                self._edits["router_ap_ssid"].setText(ssid)
                self._mark_auto("router_ap_ssid")
            if not (wired or wifi or gw or port):
                self._report(False, "Auto Detect found nothing - fill the "
                                    "Host PC fields in by hand.")
            else:
                self._report(True, "Auto Detect: host values updated "
                                   "(empty fields were not detected).")

        self._run_async(work, done)

    def _test_connection(self):
        gateway_key = _MODE_GATEWAY_KEY.get(self._mode)
        if not gateway_key:
            return
        gateway = self._edits[gateway_key].text().strip()
        self.btn_test.setEnabled(False)
        self.result_label.setStyleSheet("")
        self.result_label.setText("Test Connection ...")

        def work():
            from .engine import host_platform
            return host_platform.test_router_gateway(gateway)

        def done(ok, message):
            self.btn_test.setEnabled(True)
            self._report(ok, message)

        self._run_async(work, done)

    def _hotspot_block(self):
        box = QGroupBox("Hosted Network")
        lay = QVBoxLayout(box)
        self.hotspot_status = QLabel("Status: not checked")
        self.hotspot_status.setObjectName("muted")
        lay.addWidget(self.hotspot_status)
        row = QHBoxLayout()
        self.btn_hotspot_start = QPushButton("Start Hotspot")
        self.btn_hotspot_stop = QPushButton("Stop Hotspot")
        row.addWidget(self.btn_hotspot_start)
        row.addWidget(self.btn_hotspot_stop)
        row.addStretch(1)
        lay.addLayout(row)
        explain = QLabel(
            "Requires Windows 11 with a Wi-Fi driver that reports "
            '"Hosted network supported: Yes" and administrator rights. '
            "PASS = hotspot up and the DUT can scan/join the SSID; "
            "FAIL = check driver support and administrator rights.")
        explain.setObjectName("muted")
        explain.setWordWrap(True)
        lay.addWidget(explain)
        self.btn_hotspot_start.clicked.connect(self._start_hotspot)
        self.btn_hotspot_stop.clicked.connect(self._stop_hotspot)
        self._refresh_hotspot_status()
        return box

    def _refresh_hotspot_status(self):
        def work():
            from .engine import host_platform
            return True, host_platform.hostednetwork_status() or "(unknown)"

        def done(_ok, message):
            self.hotspot_status.setText(f"Status: {message}")

        self._run_async(work, done)

    def _start_hotspot(self):
        ssid = self._edits["hotspot_ssid"].text().strip()
        key = self._edits["hotspot_password"].text().strip()
        self.btn_hotspot_start.setEnabled(False)

        def work():
            from .engine import host_platform
            return host_platform.start_hotspot(ssid, key)

        def done(ok, message):
            self.btn_hotspot_start.setEnabled(True)
            self._report(ok, message)
            self._refresh_hotspot_status()

        self._run_async(work, done)

    def _stop_hotspot(self):
        self.btn_hotspot_stop.setEnabled(False)

        def work():
            from .engine import host_platform
            return host_platform.stop_hotspot()

        def done(ok, message):
            self.btn_hotspot_stop.setEnabled(True)
            self._report(ok, message)
            self._refresh_hotspot_status()

        self._run_async(work, done)

    def _apply_save(self):
        data = self.collected_values()
        self._values = data
        if self._on_save is not None:
            self._on_save(data)
        self.accept()


class RouterNetworkDialog(QDialog):
    """Mode-selection page of the "Wired & Wireless Network" peripheral.

    Two modules side by side; each module shows two schematic mode cards
    (radio-style, mutually exclusive).  Clicking a card selects the mode
    and opens its pure-field configuration dialog.
    """

    def __init__(self, parent, values, save_callback=None):
        super().__init__(parent)
        # M80-C3: snapshot BEFORE any mode edit can clear a sibling field
        self._initial_values = dict(values or {})
        self._values = dict(values or {})
        self._save_callback = save_callback
        self.setWindowTitle(f"{NETWORK_TITLE} - Configuration")
        fit_dialog(self, 700, 620)
        root = QVBoxLayout(self)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)

        note = QLabel(
            "Wired (RJ45) and Wireless (AP hotspot) are independent: use "
            "either or both.  Mode selection only affects topology and the "
            "Host PC IP/gateway detection - FCT Wi-Fi steps remain Host "
            "PC <-> DUT end-to-end tests.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        # M80-7: the wrapped note must not swallow the spare height
        note.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Maximum)
        lay.addWidget(note)

        modules = QHBoxLayout()
        self._panels = {}
        self._cards = {"wired": {}, "wifi": {}}
        self._hints = {}
        self._edit_buttons = {}
        for module in ("wired", "wifi"):
            panel = QGroupBox("Wired (RJ45)" if module == "wired"
                              else "Wireless (AP hotspot)")
            pl = QVBoxLayout(panel)
            enabled = QCheckBox("Module enabled")
            enabled.setChecked(bool(self._values.get(
                f"{module}_enabled", True)))
            pl.addWidget(enabled)
            self._panels[module] = enabled
            current = self._current_mode(module)
            cards = QVBoxLayout()
            for key, name, desc in NETWORK_MODES[module]:
                card = _ModeCard(key, name, desc, key)
                card.set_selected(key == current)
                card.clicked.connect(
                    lambda chosen, m=module: self._select(m, chosen))
                card.doubleClicked.connect(
                    lambda chosen, m=module: self._open_mode(m, chosen))
                self._cards[module][key] = card
                cards.addWidget(card, 1)
            pl.addLayout(cards, 1)
            hint = QLabel(
                f"Current selection: {_MODE_NAMES.get(current, current)}")
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            self._hints[module] = hint
            pl.addWidget(hint)
            edit_btn = QPushButton("Edit")
            edit_btn.setToolTip("Open the selected mode's configuration")
            edit_btn.clicked.connect(
                lambda _=False, m=module: self._open_mode(
                    m, self._current_mode(m)))
            self._edit_buttons[module] = edit_btn
            pl.addWidget(edit_btn)
            modules.addWidget(panel, 1)
        lay.addLayout(modules, 2)

        # M80-8/9: read-only Host PC Bluetooth identity + the one editable
        # scan-target field (peripherals.bluetooth.scan_targets)
        lay.addWidget(host_bluetooth_block(self))
        scan_box = QGroupBox("Host PC Bluetooth scan targets")
        scan_form = QFormLayout(scan_box)
        scan_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_scan_targets = QLineEdit(
            str(self._values.get("bt_scan_targets") or ""))
        self.edit_scan_targets.setPlaceholderText("DUT-BT or AA:BB:CC:DD:EE:FF")
        scan_form.addRow("Scan targets:", self.edit_scan_targets)
        lay.addWidget(scan_box)

        apply_scroll_to_dialog(self, body)
        # M80-7: no empty band above the note / under the cards
        lay.addStretch(1)
        bottom = QHBoxLayout()
        btn_save = QPushButton("Apply && Save YAML")
        btn_save.setToolTip(
            "Persist the network configuration into the project yaml")
        btn_save.clicked.connect(self._apply_save)
        bottom.addWidget(btn_save)
        bottom.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

    # ---------------------------------------------------------- helpers
    def _current_mode(self, module):
        value = str(self._values.get(f"{module}_mode") or "").strip()
        if value:
            return value
        # legacy projects only know setup_mode -> map it onto the wired mode
        if module == "wired" and str(
                self._values.get("setup_mode") or "").strip() == "via_ap":
            return "lan"
        return NETWORK_MODES[module][0][0]

    def _select(self, module, mode):
        self._values[f"{module}_mode"] = mode
        for key, card in self._cards[module].items():
            card.set_selected(key == mode)
        self._hints[module].setText(
            f"Current selection: {_MODE_NAMES.get(mode, mode)}")

    def _select_and_open(self, module, mode):
        self._select(module, mode)
        self._open_mode(module, mode)

    def _open_mode(self, module, mode):
        """M80-12: open one mode's dialog; the sibling mode inside the
        same module is mutually exclusive, so its fields are cleared
        before editing."""
        self._select(module, mode)
        for other_key, _name, _desc in NETWORK_MODES[module]:
            if other_key == mode:
                continue
            for key, _label in _MODE_FIELD_LABELS.get(other_key, []):
                self._values[key] = ""
        dlg = _RouterModeDialog(self, mode, self._values,
                                on_save=self._absorb_values)
        dlg.exec()

    def scan_targets(self) -> str:
        return self.edit_scan_targets.text().strip()

    def _absorb_values(self, data):
        self._values.update(dict(data or {}))
        if self._save_callback is not None:
            self._save_callback(self.values())

    def _apply_save(self):
        if self._save_callback is not None:
            self._save_callback(self.values())
        self.accept()

    def values(self) -> dict:
        # M80-12: the saved dict carries the SELECTED mode's fields only
        # (plus the enabled flags); unselected mode keys are not written.
        # Non-mode group keys (dut_ip / netmask / legacy router_ip ...)
        # pass through, so old YAML values stay untouched.
        data = {}
        mode_keys = {key for labels in _MODE_FIELD_LABELS.values()
                     for key, _label in labels}
        for key, value in self._values.items():
            if key not in mode_keys and key != "bt_scan_targets":
                data[key] = value
        for module in ("wired", "wifi"):
            mode = self._current_mode(module)
            data[f"{module}_enabled"] = bool(
                self._panels[module].isChecked())
            data[f"{module}_mode"] = mode
            for key, _label in _MODE_FIELD_LABELS.get(mode, []):
                data[key] = self._values.get(key, "")
        # M80-C3: keep the sibling mode's stored keys.  A mode edit clears
        # them in self._values, so copy back from the __init__ snapshot -
        # only keys that came from the project YAML and that the selected
        # mode does not write itself.
        for module in ("wired", "wifi"):
            selected = data[f"{module}_mode"]
            selected_keys = {key for key, _label
                             in _MODE_FIELD_LABELS.get(selected, [])}
            for mode_key, _name, _desc in NETWORK_MODES[module]:
                if mode_key == selected:
                    continue
                for key, _label in _MODE_FIELD_LABELS.get(mode_key, []):
                    if key in selected_keys:
                        continue
                    if key in self._initial_values:
                        data[key] = self._initial_values[key]
        # legacy compatibility for the FCT LAN Setup / Wi-Fi Connect steps
        data["setup_mode"] = ("direct"
                              if data.get("wired_mode") == "direct"
                              else "via_ap")
        gateway = ""
        if data.get("wired_mode") == "lan":
            gateway = str(data.get("wired_gateway") or "").strip()
        elif data.get("wifi_mode") == "router":
            gateway = str(data.get("wifi_gateway") or "").strip()
        if gateway:
            data["router_ip"] = gateway
            data["gateway"] = gateway
        return data


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
        # M80-5: the control-board gate follows the shared hub
        from mtkgui.gui.yamlbuild.instrument_status import HUB
        HUB.subscribe(self._refresh_control_board_gate)
        self.destroyed.connect(
            lambda *_: HUB.unsubscribe(self._refresh_control_board_gate))
        self._refresh_control_board_gate()

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
        self.computed_left_width = self._left_column_width()
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
        self.view.setStyleSheet("border:1px solid #d4d9e0;")
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
        self.left_list.setStyleSheet(
            "QScrollArea {background:#ffffff; border:1px solid #d4d9e0;}")
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(6, 6, 6, 6)
        body_lay.setSpacing(6)
        for group_title, entries in LEFT_ENTRIES:
            group_box = QGroupBox(group_title)
            gl = QVBoxLayout(group_box)
            gl.setContentsMargins(6, 6, 6, 6)
            gl.setSpacing(4)
            for entry in entries:
                gl.addLayout(self._entry_row(entry))
            body_lay.addWidget(group_box)
        body_lay.addStretch(1)
        self.left_list.setWidget(body)
        outer.addWidget(self.left_list, 1)
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
        """One left-column row: label + Config only (M54 §1 - the Test /
        self-test actions live INSIDE the Config dialogs)."""
        key, label, _kind, _source = entry
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        name = QLabel(label)
        # M80-1: never elide; the tooltip carries the full text when the
        # operator drags the splitter narrower than the label
        name.setToolTip(label)
        name.setWordWrap(False)
        self.entry_labels[key] = name
        row.addWidget(name)
        row.addStretch(1)
        buttons = {}
        btn_cfg = QPushButton("Config")
        # M61 §1: 92 px fits "Config" with the app QSS padding (7px 16px)
        btn_cfg.setFixedWidth(92)
        btn_cfg.clicked.connect(
            lambda _=False, k=key: self.open_entry(k))
        row.addWidget(btn_cfg)
        buttons["config"] = btn_cfg
        self.entry_buttons[key] = buttons
        return row

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
        self._add_block("probes", 60, 18, 380, 116, fill=AMBER_FILL,
                        icon=["jlink", "pemicro", "lauterbach", "cmsisdap",
                              "mculink", "opensda"], icon_pos="row",
                        icon_size=30)
        self._add_block("host", 480, 18, 470, 116, mode="dark", icon="pc",
                        icon_pos="left")
        self._add_block("peripherals", 1010, 18, 380, 116, fill="#f0f9ff",
                        icon=["wifi", "bt", "console", "router", "media",
                              "display", "camera", "mic", "speaker"],
                        icon_pos="row", icon_size=24)

        _polyline(self.scene, [QPointF(440, 76), QPointF(480, 76)], width=1.8)
        _text(self.scene, "USB", 449, 53, color=TEXT, size=10, bold=True)
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
        self._add_block("grp_gpio", 76, 1026, 960, 72)

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
        # M80-5/6b/6e: the merged / pointer entries have their own dialogs
        if entry_key == "control_board":
            if not self._control_board_ready():
                QMessageBox.information(
                    self, "ATE Fixture Control Board",
                    _ControlBoardDialog.GATE_TOOLTIP)
                return
            self._open_dio_entry(self.configs["control_board"])
            return
        if entry_key == "dut_interface":
            self._open_dut_interface()
            return
        if entry_key == "dut_console":
            self._open_console_pointer()
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
        # with the modal dialog); live LED sync to the status bar
        dlg.set_connected(self._instrument_connections.get(key, False))
        dlg.connection_changed.connect(self.instrument_connection_changed)
        # M54 §1: the self-test now runs INSIDE the Config dialog - the
        # result must still reach the lamp (yellow -> green)
        dlg.self_test_changed.connect(
            lambda _sig_key, passed, k=key:
            self._set_instrument_selftest(k, passed))
        dlg.exec()
        self._instrument_sizes[key] = dlg.size()
        self._instrument_connections[key] = dlg._connected
        dlg.apply_to_config(cfg)

    # ------------------------------------- M80-5 control-board gating
    @staticmethod
    def _control_board_ready() -> bool:
        """DAQ973A connected AND its Test Connection result is OK."""
        from mtkgui.gui.yamlbuild.instrument_status import HUB
        snapshot = HUB.snapshot()
        return (bool(snapshot.get("connected"))
                and snapshot.get("test_connection") == "OK")

    def _refresh_control_board_gate(self) -> None:
        try:
            button = (self.entry_buttons.get("control_board")
                      or {}).get("config")
            if button is None:
                return
            ready = self._control_board_ready()
            button.setEnabled(ready)
            button.setToolTip("" if ready
                              else _ControlBoardDialog.GATE_TOOLTIP)
        except RuntimeError:                 # page already deleted
            pass

    @staticmethod
    def _control_signals(cfg: dict) -> dict:
        """Signal values from ``signals`` or the legacy ``dio`` map."""
        groups = (cfg or {}).get("groups") or {}
        saved = dict(groups.get("signals") or {})
        legacy = dict((cfg or {}).get("dio") or {})
        out = {}
        for key, _label, default_channel, default_dir in DIO_SIGNALS:
            entry = dict(saved.get(key) or {})
            channel = str(entry.get("channel")
                          or legacy.get(key)
                          or (cfg or {}).get(key) or "")
            direction = str(entry.get("direction") or default_dir).lower()
            if direction not in ("input", "output"):
                direction = default_dir
            out[key] = {"channel": channel, "direction": direction}
        return out

    # --------------------------------------------- M80-6b DUT Interface
    def _router_group(self) -> dict:
        return (((self.configs.get("peripherals") or {}).get("groups")
                 or {}).get("router") or {})

    def _dut_groups(self) -> dict:
        cfg = self.configs.setdefault("dut", {"title": "DUT Board"})
        return cfg.setdefault("groups", {})

    def apply_dut_interface(self, wifi: dict, bluetooth: dict,
                            ports: str) -> None:
        """Write the three DUT Interface blocks on their existing paths."""
        groups = self._dut_groups()
        groups["wifi"] = {
            key: str((wifi or {}).get(key, default) or "")
            for key, _label, default in GROUP_FIELDS[("dut", "wifi")]}
        groups["bluetooth"] = {
            key: str((bluetooth or {}).get(key, default) or "")
            for key, _label, default in GROUP_FIELDS[("dut", "bluetooth")]}
        groups["interface"] = {
            "ethernet": {"ports": normalise_dut_ports(ports)}}
        self.apply_save_requested.emit()

    def _open_dut_interface(self):
        groups = self._dut_groups()
        wifi = dict(groups.get("wifi") or _default_group("dut", "wifi"))
        bluetooth = dict(groups.get("bluetooth")
                         or _default_group("dut", "bluetooth"))
        ports = str(((groups.get("interface") or {}).get("ethernet")
                     or {}).get("ports") or "")
        dut_ip = str(self._router_group().get("dut_ip") or "")
        dlg = DutInterfaceDialog(self, wifi, bluetooth, ports, dut_ip)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            values = dlg.values()
            self.apply_dut_interface(values["wifi"], values["bluetooth"],
                                     values["ethernet_ports"])

    # --------------------------------------------- M80-6e DUT Console
    def _open_console_pointer(self):
        """DUT Console is a pointer to the Test Work Flow Console panel."""
        QMessageBox.information(
            self, "DUT Console",
            "Configure the DUT console in Test Work Flow -> Console.")
        window = self.window()
        tabs = getattr(window, "tabs", None)
        workflow = getattr(window, "workflow_page", None)
        if tabs is not None and workflow is not None:
            tabs.setCurrentWidget(workflow)

    def _open_group_entry(self, owner, group, entry_key=None):
        cfg = self.configs.setdefault(owner, {"title": owner})
        groups = cfg.setdefault("groups", {})
        values = groups.setdefault(group, _default_group(owner, group))
        if (owner, group) == ("peripherals", "router"):
            self._open_network_entry(groups, group, values)
            return
        spec = GROUP_FIELDS[(owner, group)]
        probe = None
        if entry_key in _TESTABLE_FORM_KEYS:
            probe = (lambda vals, k=entry_key:
                     self._probe_with_span(k, vals))
        dlg = _GroupConfigDialog(self, f"{cfg['title']} - {group}",
                                 spec, values, test_probe=probe)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            groups[group] = dlg.values()

    def _open_network_entry(self, groups, group, values):
        """M65: mode-selection page + per-mode dialogs (replaces the flat
        Ethernet Router form)."""
        # old projects carry only the legacy fields: fill the new module
        # fields with their defaults, the saved values always win
        saved = dict(values or {})
        merged = dict(_default_group("peripherals", "router"))
        merged.update(saved)
        if not str(saved.get("wired_mode") or "").strip():
            # legacy setup_mode "via_ap" -> the LAN mode (kept intact)
            merged["wired_mode"] = (
                "lan" if str(merged.get("setup_mode") or "") == "via_ap"
                else "direct")
        # M80-9: the one editable scan-target field lives in the dialog
        saved_bt = ((self.configs.get("peripherals") or {}).get("groups")
                    or {}).get("bluetooth") or {}
        merged["bt_scan_targets"] = str(saved_bt.get("scan_targets") or "")
        groups[group] = merged
        holder = {}

        def save(new_values):
            groups[group].update(dict(new_values))
            dialog = holder.get("dlg")
            scan = dialog.scan_targets() if dialog is not None else ""
            self._mirror_network_peripherals(groups[group], scan)
            self.apply_save_requested.emit()

        dlg = RouterNetworkDialog(self, merged, save_callback=save)
        holder["dlg"] = dlg
        dlg.exec()
        if dlg.result() == QDialog.DialogCode.Accepted:
            groups[group].update(dict(dlg.values()))
            self._mirror_network_peripherals(groups[group],
                                             dlg.scan_targets())

    def _mirror_network_peripherals(self, router_values: dict,
                                    scan_targets: str = "") -> None:
        """M80-9: one-way mirror from the network dialog into the legacy
        reference paths (``peripherals.wifi.*`` /
        ``peripherals.bluetooth.*``).  No ref is rewired."""
        cfg = self.configs.setdefault("peripherals",
                                      {"title": "Test Peripherals"})
        groups = cfg.setdefault("groups", {})
        wifi = dict(groups.get("wifi")
                    or _default_group("peripherals", "wifi"))
        wifi["ap_ssid"] = str(router_values.get("hotspot_ssid") or "")
        wifi["ap_password"] = str(router_values.get("hotspot_password") or "")
        wifi["host_ip"] = str(router_values.get("wifi_host_ip") or "")
        groups["wifi"] = wifi
        bluetooth = dict(groups.get("bluetooth")
                         or _default_group("peripherals", "bluetooth"))
        if scan_targets:
            bluetooth["scan_targets"] = str(scan_targets)
        try:
            from .engine import host_platform
            adapter, _address = host_platform.host_bt_identity()
        except Exception:                    # noqa: BLE001 - derived only
            adapter = ""
        if adapter:
            bluetooth["adapter"] = str(adapter)
        groups["bluetooth"] = bluetooth

    def _open_plain_entry(self, owner, cfg, entry_key=None):
        if owner == "control_board":
            self._open_dio_entry(cfg)
            return
        editor = _BLOCK_EDITORS.get(owner)
        self_test = None
        max_width = None
        if owner == "jlink":
            editor = JLINK_FIELDS
            # M64: the flash tool launches itself for the availability
            # check - the generic Test Connection probe is gone
            self_test = _flash_tool_self_test
            max_width = 420          # bounded fields, no full-width stretch
        probe = None
        if entry_key in _TESTABLE_FORM_KEYS:
            probe = (lambda vals, k=entry_key:
                     self._probe_with_span(k, vals))
        dlg = _form_dialog(self, cfg["title"], cfg.get("fields", []),
                           note=_mode_note(self._mode),
                           editor=editor,
                           config=cfg if editor else None,
                           test_probe=probe,
                           self_test=self_test,
                           editor_max_width=max_width)
        dlg.exec()
        if editor:
            dlg.apply_to_config(cfg)

    def _open_dio_entry(self, cfg):
        """M80-5: ATE Fixture Control Board - channel + direction rows."""
        dlg = _ControlBoardDialog(self, cfg["title"],
                                  self._control_signals(cfg),
                                  self._control_board_ready())
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

        if entry_key == "dut_console":
            port = str(values.get("port") or "").strip()
            baud = str(values.get("baud") or "115200").strip()
            parity = str(values.get("parity") or "None").strip()
            if not port:
                return False, ("DUT Console is not configured.\n"
                               "Open Config and select the serial port.")
            try:
                from serial.tools import list_ports
                devices = host_platform.serial_port_devices(
                    [p.device for p in list_ports.comports()])
            except Exception:                   # noqa: BLE001
                devices = []
            if port not in devices:
                available = ", ".join(devices) if devices else "(none)"
                return False, (f"Serial port {port} is not present.\n"
                               f"Available ports: {available}\n"
                               "Test Connection FAILED: the serial port "
                               "cannot be opened.")
            try:
                import serial
                with serial.Serial(port=port, baudrate=int(baud),
                                   timeout=1):
                    pass
            except Exception as exc:            # noqa: BLE001
                return False, (f"Serial port {port} could not be opened: "
                               f"{exc}")
            return True, (f"Serial port: {port}\nBaud rate: {baud}\n"
                          f"Parity: {parity}\n\nTest Connection PASSED: "
                          "the serial port opens.")

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
        self._instrument_connections = {}
        self._instrument_selftest = {}

