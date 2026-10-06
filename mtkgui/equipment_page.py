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
Demo mode: no real hardware is connected; all values are mock data.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

import random

from .permissions import MANUAL_FIXTURE_NOTICE

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
    ],
}

# Manual fixture mode (login dialog): these fixture-band blocks are
# globally disabled together with every IO-control entry
_MANUAL_FIXTURE_KEYS = ("fixture", "control_board", "cell_press",
                        "cell_inpos", "cell_presence", "cell_estop")

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
    "peripherals": ["Wi-Fi · Bluetooth · Router",
                    "Media converter · Display",
                    "Camera · Mic · Earphone · Speaker"],
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
                   "V/I readback ≈1% (trend)",
                   "J1: program + RI/FLT inhibit"],
    "fixture": ["128 pinhole pins", "single-point star ground plane"],
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
# mock configuration (demo mode - nothing is connected)
# --------------------------------------------------------------------------
def _mock_configs():
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
                ("Test SW", "mtk-gui v2.0.0"),
                ("OS", "Windows 11 Pro x64"),
                ("Functions", "ICT / FCT / Flash / Reports / Cloud"),
            ],
        },
        "peripherals": {
            "title": "Test Peripherals",
            "table": [
                ("PC Wi-Fi", "RF connectivity", "Not connected"),
                ("PC Bluetooth", "RF connectivity", "Not connected"),
                ("Ethernet Router", "LAN / iperf throughput", "Not connected"),
                ("Media Converter", "T1 / T1S media", "Not connected"),
                ("Display", "DSI-MIPI check", "Not connected"),
                ("Camera", "CSI-MIPI check", "Not connected"),
                ("Microphone / Earphone", "Audio path check", "Not connected"),
                ("Speaker", "Audio output check", "Not connected"),
            ],
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
                ("Status", "Available (demo)"),
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
                ("Status", "Available (demo)"),
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
                ("Status", "Available (demo)"),
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
                ("Status", "Available (demo)"),
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
                ("Status", "Available (demo)"),
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
                ("Status", "Available (demo)"),
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
            "title": "Fixture Probe Board",
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
                 mode="plain", abbr=None):
        super().__init__()
        self.key = key
        self.title = title
        self.lines = lines or []
        self.border = QColor(border)
        self.fill = QColor(fill)
        self.mode = mode
        self.abbr = abbr
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
        painter.setPen(QPen(QColor("#ffffff"), 1))
        font = QFont()
        font.setPointSizeF(11)
        font.setBold(True)
        painter.setFont(font)
        badge_w = 50 if self.abbr else 0
        painter.drawText(QRectF(rect.left() + 8, rect.top(),
                                rect.width() - 16 - badge_w, header_h),
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

        painter.setPen(QPen(self.border, 1))
        font = QFont()
        font.setPointSizeF(10.5)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(rect.left() + 5, rect.top() + 4,
                                rect.width() - 10, 22),
                         Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter, self.title)
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


# --------------------------------------------------------------------------
# view + line helpers
# --------------------------------------------------------------------------
class BlockDiagramView(QGraphicsView):
    zoomChanged = Signal()

    MIN_ZOOM, MAX_ZOOM = 0.1, 10.0

    def __init__(self, scene, on_block, parent=None):
        super().__init__(scene, parent)
        self._on_block = on_block
        self._auto_fit = True  # fit whole diagram until user zooms manually
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter)

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
def _form_dialog(parent, title, fields):
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"{title} - Configuration")
    dlg.setMinimumWidth(650)  # +50 % vs the original 430
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    for label, value in fields:
        edit = QLineEdit(value)
        edit.setReadOnly(True)
        form.addRow(f"{label}:", edit)
    layout.addLayout(form)
    note = QLabel("Demo mode - no hardware connected. "
                  "Configuration shown is mock data.")
    note.setObjectName("warn")
    layout.addWidget(note)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    return dlg


def _table_dialog(parent, title, rows):
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"{title} - Configuration")
    dlg.resize(900, 570)  # +50 % vs the original 600x380
    layout = QVBoxLayout(dlg)
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
    layout.addWidget(table)
    note = QLabel("Demo mode - no hardware connected.")
    note.setObjectName("warn")
    layout.addWidget(note)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    return dlg


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

    def __init__(self, parent, title, fields, key, virtual, manual=False):
        super().__init__(parent)
        self._key = key
        self._virtual = virtual
        self._manual = manual
        self._connected = False
        self.setWindowTitle(f"{title} - Configuration")
        self.resize(920, 720)
        root = QVBoxLayout(self)

        # 1 ---------------------------------------------------- information
        info = QGroupBox("Instrument Information")
        form = QFormLayout(info)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for label, value in fields:
            edit = QLineEdit(value)
            edit.setReadOnly(True)
            form.addRow(f"{label}:", edit)
        root.addWidget(info)

        # 2 ------------------------------------------------------ parameters
        params = QGroupBox("Parameter Configuration")
        pform = QFormLayout(params)
        pform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._param_edits = []
        for label, value in _INSTRUMENT_PARAMS[key]:
            edit = QLineEdit(value)
            self._param_edits.append(edit)
            pform.addRow(f"{label}:", edit)
        root.addWidget(params)

        # 3 ------------------------------------------------------- connection
        conn = QGroupBox("Connection")
        cv = QVBoxLayout(conn)
        cform = QFormLayout()
        cform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._iface = QComboBox()
        self._iface.addItems(list(_INSTRUMENT_CONN[key]))
        self._address = QLineEdit()
        self._address.setText(
            _INSTRUMENT_CONN[key][self._iface.currentText()])
        self._iface.currentTextChanged.connect(self._iface_changed)
        cform.addRow("Interface:", self._iface)
        cform.addRow("Address:", self._address)
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
        root.addWidget(conn)

        # 4 ------------------------------------------- control & simple tests
        ctl = QGroupBox("Control && Simple Tests")
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
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("Action results appear here ...")
        self._output.setFixedHeight(130)
        cl.addWidget(self._output)
        root.addWidget(ctl)

        note = QLabel("Demo mode - no hardware connected."
                      if not virtual else
                      "Virtual mode - connect / test succeed (simulated).")
        note.setObjectName("warn")
        root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.btn_test.clicked.connect(self._test_connection)

    # ------------------------------------------------------------ helpers
    def _iface_changed(self, text):
        self._address.setText(_INSTRUMENT_CONN[self._key].get(text, ""))

    def _log(self, text):
        self._output.appendPlainText(text)

    # -------------------------------------------------------- connection
    def _connect(self):
        addr = self._address.text().strip()
        self.btn_connect.setEnabled(False)
        self._conn_state.setText("Connecting ...")
        self._log(f"Connecting to {addr} ...")
        QTimer.singleShot(500, lambda: self._connect_done(addr))

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
        else:
            self._led.set_color("#ef4444")
            self._conn_state.setText("Error: no hardware (demo)")
            self._log("Error: instrument not found "
                      "(demo build has no VISA layer).")
            self.btn_connect.setEnabled(True)
            from mtkgui.gui.yamlbuild.instrument_status import HUB
            HUB.set_connected(False)
            HUB.set_test_connection("NOK")

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

    def _test_connection(self):
        self._log("*IDN? ...")
        QTimer.singleShot(
            400,
            lambda: self._log(
                f"*IDN? -> {_INSTRUMENT_IDN[self._key]}\n"
                f"Test Connection -> OK"))
        QTimer.singleShot(
            400,
            lambda: self._hub_test_result("OK"))

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
                    # T9: mirror the Self-Test result to the shared
                    # status hub (block 03 panel display)
                    from mtkgui.gui.yamlbuild.instrument_status import HUB
                    HUB.set_self_test(
                        "OK" if ("PASS" in out or "0 errors" in out)
                        else "NOK")
                return


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------
class EquipmentPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.configs = _mock_configs()
        self.blocks = {}
        # Virtual mode: the instrument dialog's Connect / Test Connection
        # succeed with a simulated link (set from MainWindow on login)
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

    def set_virtual_mode(self, virtual):
        """Virtual mode -> instrument connect / test succeed (simulated)."""
        self.virtual_mode = bool(virtual)

    def set_config_allowed(self, allowed):
        """Operator permission: open the equipment configuration dialogs."""
        self._config_allowed = bool(allowed)

    def _build(self):
        layout = QVBoxLayout(self)
        title = QLabel("Equipment - Block Diagram")
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

        hint = QLabel(
            "Click a block to open its configuration window - "
            "right-click to copy the diagram as an image. "
            "Final rack: DAQ973A + 2x DAQM908A + DAQM907A, U2355A, N5747A.")
        hint.setObjectName("muted")
        layout.addWidget(hint)

        self.scene = QGraphicsScene(0, 0, W, H)
        self.view = BlockDiagramView(self.scene, self._on_block_clicked)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setStyleSheet("background:#fbfdff; border:1px solid #d4d9e0;")
        layout.addWidget(self.view, 1)

        btn_out.clicked.connect(self.view.zoom_out)
        btn_in.clicked.connect(self.view.zoom_in)
        btn_reset.clicked.connect(self.view.zoom_reset)
        self.view.zoomChanged.connect(self._update_zoom_label)

        self._populate()
        # hug the actual content so fitInView can maximize the diagram
        rect = self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        self.scene.setSceneRect(rect)

    def _update_zoom_label(self):
        self.zoom_label.setText(f"{round(self.view.transform().m11() * 100)}%")

    # ------------------------------------------------------------------
    def _add_block(self, key, x, y, w, h, mode="plain", fill="#ffffff"):
        cfg = self.configs[key]
        block = BlockItem(key, cfg.get("short", cfg["title"]),
                          self._border_for(key),
                          lines=DIAGRAM_LINES.get(key), fill=fill, mode=mode)
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
        self._add_block("probes", 60, 18, 380, 86, fill=AMBER_FILL)
        self._add_block("host", 480, 18, 470, 86, mode="dark")
        self._add_block("peripherals", 1010, 18, 380, 86, fill="#f0f9ff")

        _polyline(self.scene, [QPointF(440, 61), QPointF(480, 61)], width=1.8)
        _text(self.scene, "USB", 449, 42, color=TEXT, size=10, bold=True)
        _polyline(self.scene, [QPointF(950, 61), QPointF(1010, 61)],
                  width=1.8)
        _text(self.scene, "USB/LAN", 953, 42, color=TEXT, size=10, bold=True)

        # SCPI control bus
        _polyline(self.scene, [QPointF(720, 104), QPointF(720, 150)],
                  arrow=False)
        _polyline(self.scene, [QPointF(310, 150), QPointF(1130, 150)],
                  arrow=False)
        _polyline(self.scene, [QPointF(310, 150), QPointF(310, 250)])
        _polyline(self.scene, [QPointF(720, 150), QPointF(720, 250)])
        _polyline(self.scene, [QPointF(1130, 150), QPointF(1130, 250)])
        _text(self.scene, "SCPI control bus", 585, 110, color=SUB, size=10.5)
        _text(self.scene, "GPIB", 272, 188, color=BLUE_DARK, size=11,
              bold=True)
        _text(self.scene, "USB", 690, 188, color=TEAL_DARK, size=11, bold=True)
        _text(self.scene, "LAN", 1100, 188, color=AMBER_DARK, size=11,
              bold=True)

        # ============ layer 2 containers ================================
        # DAQ973A + 2x DAQM908A + DAQM907A
        self._add_container("daq973a", 60, 250, 500, 220, BLUE, BLUE_FILL,
                            BLUE_DARK,
                            "DCV 0.003% - 2-wire Ω - frequency - LAN + GPIB",
                            abbr="DAQM")
        # U2355A
        self._add_container("u2355a", 600, 250, 360, 220, TEAL, TEAL_FILL,
                            TEAL_DARK,
                            "250 kSa/s - 16-bit - ±10 V - USB (USBTMC)",
                            abbr="DAQ")
        # N5747A
        self._add_container("psu", 1000, 250, 380, 220, AMBER, AMBER_FILL,
                            AMBER_DARK,
                            "60 V / 12.5 A / 750 W - remote sense - LAN/USB/GPIB",
                            abbr="PSU")

        # ============ layer 3: fixture band =============================
        fixture = self._add_block("fixture", 60, 560, 1320, 210,
                                  mode="band", fill=GRAY_FILL)
        fixture.setZValue(-2)
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
        _text(self.scene, "GND★", 762, 740, color=RED, size=10, bold=True)

        # ============ layer 4: DUT band =================================
        self._add_container("dut", 60, 840, 1320, 264, PURPLE, PURPLE_FILL,
                            "#6d28d9",
                            "via fixture probes -> test point pads "
                            "(>32 mils, typical 40 mils) - stress strain gauge")

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

        # free-space description (right side of the fixture band, clear of
        # the signal trunks)
        _text(self.scene, "Fixture Probe Board", 1145, 584, color=TEXT,
              size=12, bold=True)
        _text(self.scene, "128 pinhole pins", 1145, 612, color=SUB,
              size=10.5)
        _text(self.scene, "single-point star ground plane", 1145, 634,
              color=SUB, size=10.5)
        _text(self.scene, "power net points TP_P1 - TP_P80", 1145, 656,
              color=SUB, size=10.5)

        # ============ layer 2 children ==================================
        self._add_block("m908a_1", 76, 314, 152, 152)
        self._add_block("m908a_2", 238, 314, 152, 152)
        self._add_block("m907a", 400, 314, 152, 152)
        self._add_block("u_ai", 610, 314, 170, 152)
        self._add_block("u_ctr", 786, 314, 170, 152)
        self._add_block("psu_detail", 1012, 314, 360, 152)

        # ============ layer 3 children ==================================
        self._add_block("control_board", 160, 578, 490, 150)
        cells = (("cell_press", 170), ("cell_inpos", 288),
                 ("cell_presence", 406), ("cell_estop", 524))
        for key, x in cells:
            self._add_block(key, x, 646, 110, 68)

        # ============ layer 4 groups ====================================
        self._add_block("grp_power", 76, 902, 590, 112)
        self._add_block("grp_clocks", 726, 902, 172, 112)
        self._add_block("grp_adc", 906, 902, 154, 112)
        self._add_block("grp_vin", 1068, 902, 218, 112)
        self._add_block("grp_gnd", 1304, 902, 118, 112)
        self._add_block("grp_gpio", 76, 1026, 960, 72)

    def _add_container(self, key, x, y, w, h, border, fill, header,
                       subtitle, abbr=None):
        """Container block with a colored header band + subtitle line."""
        cfg = self.configs[key]
        block = BlockItem(key, cfg["title"], border, lines=[subtitle],
                          fill=fill, mode="header", abbr=abbr)
        block.setRect(x, y, w, h)
        # header color override: BlockItem uses self.border for the band
        block.setZValue(-2)
        self.scene.addItem(block)
        self.blocks[key] = block
        return block

    # ------------------------------------------------------------------
    def _on_block_clicked(self, item):
        if not isinstance(item, BlockItem):
            return
        if not self._config_allowed:
            QMessageBox.information(
                self, "Permission",
                "Operator account cannot open equipment configuration.\n"
                "Ask the supervisor to grant this permission.")
            return
        key = item.key
        if self._manual_fixture and key in _MANUAL_FIXTURE_KEYS:
            # Manual fixture mode: fixture hardware config is disabled
            QMessageBox.information(
                self, "Manual Fixture", MANUAL_FIXTURE_NOTICE)
            return
        cfg = self.configs[key]
        if key in _INSTRUMENT_CONN:
            # instruments: rich window with information / parameters /
            # connection / control-and-tests group boxes
            dlg = _InstrumentDialog(self, cfg["title"], cfg["fields"], key,
                                    self.virtual_mode,
                                    manual=self._manual_fixture)
        elif "table" in cfg:
            dlg = _table_dialog(self, cfg["title"], cfg["table"])
        else:
            dlg = _form_dialog(self, cfg["title"], cfg["fields"])
        dlg.exec()
