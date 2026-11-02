# -*- coding: utf-8 -*-
"""FCTTestConfigWidget — P3-B5 block 07 panel (four tabs).

Edits the `fct_test_config` product-YAML node (Console / Wi-Fi /
Bluetooth / Sequence) for the "Build FCT Test Work Flow Sequence"
module:

* Console tab   — Host PC Serial/SSH connection config ONLY: port
  (serial device dropdown), baudrate, SSH host / username (M22c);
* Wi-Fi tab     — base parameters (interface / driver load command)
  plus three independently enabled sub-tests, each with its own
  timeout (default 15 s): 1. Scan/RSSI (both DUT kinds), 2. Connect &
  Ping (Linux only, PASS on >=1 reply), 3. iPerf throughput (Linux
  only, Host server -> DUT client, iperf2/iperf3);
* Bluetooth tab — three independently enabled sub-tests: 1. RSSI
  discovery (both DUT kinds), 2. Pair & connect with optional L2CAP ping
  (Linux only), 3. Tone/music over A2DP with a wav Start/End segment, a
  local QtMultimedia preview + live level meter (Linux only, Host source
  -> DUT sink; NO automatic GUI confirm - the operator adds their own
  Message row);
* Sequence tab  — the step editor: the console test-commands table
  (one row = one test: Name / Console transport / WaitFor / SendTo /
  Capture / Retry, each with its own timeout; rows are add / remove /
  duplicate / reorder) plus the standard-operation / flash / Delay
  steps that run BEFORE that body (M22c).

The power / fixture spine (``setup:`` node: power_mode, use_fixture,
manual_on_message, manual_off_message) has NO editor tab any more: the
keys are still parsed on load and re-emitted untouched on save, so old
YAMLs keep their behaviour (MessageGoStop prompts, U2355A fixture ops).
A YAML without a ``setup:`` node gets the engine defaults.

`values()` returns the legacy module params preserved plus
``fct_test_config_yaml`` — the full node as YAML text — so the
Preview & Export shows the complete configuration (spec §3.4).
"""
from __future__ import annotations

import copy
import os
import time

import yaml
from PySide6.QtCore import QObject, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.engine.fct_test_config import (
    BAUDRATES,
    BT_MODES,
    BW_TOOLS,
    DEFAULT_FLASH_GUI_MESSAGE,
    WIFI_MODES,
    WIFI_SCAN_VIA,
    DIALOG_GOSTOP,
    DIALOG_OK,
    DIALOG_YESNO,
    KIND_HOST,
    KIND_MESSAGE,
    KIND_SFTP_GET,
    KIND_SFTP_PUT,
    KIND_OP,
    KIND_WIFI_TEST,
    KIND_BT_TEST,
    KIND_FLASH_GUI,
    KIND_DELAY,
    KIND_SERIAL_PUT,
    KIND_SERIAL_PULL,
    STEP_TYPE_OPERATION,
    STEP_TYPE_CONSOLE_SERIAL,
    STEP_TYPE_CONSOLE_SSH,
    STEP_TYPE_SFTP_PUT,
    STEP_TYPE_SFTP_GET,
    STEP_TYPE_CONSOLE_CLI,
    STEP_TYPE_MESSAGE_OK,
    STEP_TYPE_MESSAGE_YESNO,
    STEP_TYPE_MESSAGE_GOSTOP,
    STEP_TYPE_MESSAGE_OK_WAIT,
    STEP_TYPE_MESSAGE_YESNO_WAIT,
    STEP_TYPE_MESSAGE_GOSTOP_WAIT,
    STEP_TYPE_FLASH_GUI,
    STEP_TYPE_DELAY,
    STEP_TYPE_SERIAL_PUT,
    STEP_TYPE_SERIAL_PULL,
    STEP_TYPE_WIFI_SCAN,
    STEP_TYPE_WIFI_PING,
    STEP_TYPE_WIFI_IPERF,
    STEP_TYPE_BT_RSSI,
    STEP_TYPE_BT_PAIR,
    STEP_TYPE_BT_TONE,
    STEP_TYPE_LABELS,
    BluetoothCfg,
    ConsoleCfg,
    ConsoleCommand,
    FctSetupCfg,
    FctTestConfig,
    WifiCfg,
    console_command_for_label,
    default_assets_dir,
    rf_subtest_for_label,
    step_type_label,
)
from mtkgui.engine import DIO_OPS, FIXTURE_OPS, INSTRUMENT_OPS, OP_STEPS
from mtkgui.engine import host_platform
from mtkgui.engine.fct_templates import TEMPLATE_LABELS
from mtkgui.engine.steps import (LAN_SETUP_OP, NETWORK_OP_TYPES,
                                 NETWORK_OPS, WIFI_CONNECT_OP,
                                 op_summary as _op_summary)
from mtkgui.gui.dialog_sizing import apply_scroll_to_dialog, wrap_scrollable
from mtkgui.style import APP_NAME, APP_ORG

#: M40 Wi-Fi tab QSettings keys: the Host PC's current-association values
#: are a LOCAL user preference (password plaintext, owner-approved).
WIFI_KEY_SSID = "wifi/ap_ssid"
WIFI_KEY_AP_IP = "wifi/ap_ip"
WIFI_KEY_HOST_IP = "wifi/host_ip"
WIFI_KEY_PASSWORD = "wifi/ap_password"

#: M41 Console tab QSettings keys (local convenience values; the
#: DUT-side fields stay authoritative in the YAML).  The password is
#: plaintext by owner approval (same precedent as wifi/ap_password).
CONSOLE_KEY_PORT = "console/port"
CONSOLE_KEY_BAUD = "console/baudrate"
CONSOLE_KEY_SSH_HOST = "console/ssh_host"
CONSOLE_KEY_SSH_USER = "console/ssh_user"
CONSOLE_KEY_SSH_PASSWORD = "console/ssh_password"
CONSOLE_KEY_SCRIPTS_LOCAL = "console/scripts_local_dir"
CONSOLE_KEY_PULL_LOCAL = "console/pull_local_dir"


def _wifi_settings():
    """The QSettings store for the Wi-Fi tab keys (module-level so the
    tests monkeypatch it with an isolated settings.ini)."""
    from PySide6.QtCore import QSettings
    return QSettings(APP_ORG, APP_NAME)


def _console_settings():
    """The QSettings store for the M41 Console tab keys (module-level so
    the tests monkeypatch it with an isolated settings.ini)."""
    from PySide6.QtCore import QSettings
    return QSettings(APP_ORG, APP_NAME)


class _RefreshCombo(QComboBox):
    """Combo whose popup re-runs a refresh callback first (M41: every
    expansion of the Port dropdown re-scans ``list_ports.comports()``)."""

    def __init__(self, refresh, parent=None) -> None:
        super().__init__(parent)
        self._refresh = refresh

    def showPopup(self) -> None:            # noqa: N802 - Qt override
        try:
            self._refresh()
        except Exception:                   # noqa: BLE001 - optional
            pass
        super().showPopup()


# Each cmd_table row carries its full ConsoleCommand on the Name cell's
# UserRole so that advanced attributes (regex/case/expected/end line/
# per-stage timeouts) survive the table -> YAML round-trip; the visible
# cells are only a rendered summary.
_CMD_ROLE = Qt.UserRole + 1

#: Console-column choice that turns a row into a Console-domain operator
# dialog (MessageOKtoConsole / MessageYesNotoConsole /
# MessageGoStoptoConsole) instead of a console command - the row WAITS
# the expected console message, then pops the dialog at its sequence
# position (kept in sync with the Test Work Flow page so the standard
# ops there are no longer overwritten by a rebuild).
MESSAGE_CHOICE = "(message)"
#: Console-column display for a host CLI row: the command runs on the
#: TEST PC, not on the DUT, so serial/ssh would be misleading (M27 P6).
HOST_CHOICE = "(host PC)"

#: visible label per dialog style (Capture column of a message row)
_DIALOG_LABELS = {
    DIALOG_OK: "OK dialog",
    DIALOG_YESNO: "Yes-No dialog",
    DIALOG_GOSTOP: "Go-Stop dialog",
}

#: editor combo items, index -> ConsoleCommand.dialog_style
_DIALOG_ORDER = (DIALOG_OK, DIALOG_YESNO, DIALOG_GOSTOP)

#: merged "FCT test step" table column order (m30):
#:   # | Step | Type | WaitFor | SendTo | Capture | Timeout | cmd / params
_COL_HASH = 0
_COL_STEP = 1
_COL_TYPE = 2
_COL_WAIT = 3
_COL_SEND = 4
_COL_CAPTURE = 5
_COL_TIMEOUT = 6
_COL_CMD = 7

#: default step name per Type label for the Add dropdown
_ADD_ROW_NAMES = {
    STEP_TYPE_OPERATION: "New Operation",
    STEP_TYPE_CONSOLE_SERIAL: "Console serial step",
    STEP_TYPE_CONSOLE_SSH: "Console ssh step",
    STEP_TYPE_SFTP_PUT: "SFTP upload",
    STEP_TYPE_SFTP_GET: "SFTP download",
    STEP_TYPE_CONSOLE_CLI: "Host CLI",
    STEP_TYPE_MESSAGE_OK: "MessageOK",
    STEP_TYPE_MESSAGE_YESNO: "MessageYesNo",
    STEP_TYPE_MESSAGE_GOSTOP: "MessageGoStop",
    STEP_TYPE_MESSAGE_OK_WAIT: "MessageOKtoConsole",
    STEP_TYPE_MESSAGE_YESNO_WAIT: "MessageYesNotoConsole",
    STEP_TYPE_MESSAGE_GOSTOP_WAIT: "MessageGoStoptoConsole",
    STEP_TYPE_FLASH_GUI: "Flash_GUI",
    STEP_TYPE_DELAY: "Delay",
    STEP_TYPE_WIFI_SCAN: "Wi-Fi: Scan / RSSI",
    STEP_TYPE_WIFI_PING: "Wi-Fi: Ping",
    STEP_TYPE_WIFI_IPERF: "Wi-Fi: iPerf",
    STEP_TYPE_BT_RSSI: "Bluetooth: RSSI / discovery",
    STEP_TYPE_BT_PAIR: "Bluetooth: Pair & Connect",
    STEP_TYPE_BT_TONE: "Bluetooth: Tone / A2DP",
}

#: reference-row Timeout source per (kind, rf_subtest); the summary cell
#: reads the matching tab widget live (m30b)
_RF_SUBTEST_TIMEOUT_ATTRS = {
    ("wifi", "scan"): "wifi_scan_timeout",
    ("wifi", "ping"): "wifi_ping_timeout",
    ("wifi", "iperf"): "wifi_iperf_timeout",
    ("bluetooth", "rssi"): "bt_rssi_timeout",
    ("bluetooth", "pair"): "bt_pair_timeout",
    # M45: the Tone step has NO Timeout any more (its length is the
    # Start..End segment) - the reference row renders "-".
}

#: M45: default tone wav and the default Browse folder (the owner drops
#: music / custom wavs into resources/music/; the bundled
#: assets/resources/audio/ template stays browsable as reference).
DEFAULT_TONE_WAV = "resources/tones/tone_1khz_6s.wav"
TONE_BROWSE_DIR = os.path.join("resources", "music")
#: DUT-side BT driver probe markers (echo + shell output both contain
#: ``__BT_DONE__``; two occurrences = the shell actually ran the probe).
BT_PROBE_CMD = ("echo __BT_PING__; (ls /sys/class/bluetooth 2>/dev/null; "
                "hciconfig -a 2>/dev/null | head -8); echo __BT_DONE__")


def _fmt_num(value) -> str:
    """Compact number rendering: 10.0 -> '10', 10.5 -> '10.5'."""
    if isinstance(value, float) and float(value).is_integer():
        return str(int(value))
    return str(value)


def _serial_ports() -> list:
    """Available serial devices for THIS platform (pyserial list_ports;
    tolerant).  mac keeps only ``/dev/cu.*``, Windows only ``COM*``."""
    try:
        from serial.tools import list_ports
        devices = [p.device for p in list_ports.comports()]
    except Exception:                        # noqa: BLE001 - optional
        return []
    return host_platform.serial_port_devices(devices)


def _sequence_cases_from_param(raw) -> list:
    """Parse the stored FCT sequence steps: a YAML list of case dicts
    (the block-07 Sequence tab's standard ops / flash / Delay rows)."""
    if isinstance(raw, list):
        raw = "\n".join(str(ln) for ln in raw)
    text = str(raw or "")
    if not text.strip():
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, list):
        return []
    return [dict(c) for c in data if isinstance(c, dict)]


def _sequence_cases_to_lists(cases: list):
    """Case dicts -> the shared editor's parallel lists (name / enable /
    wait / timeout / kind / op_params)."""
    steps = [str(c.get("name", "")) for c in cases]
    enables = [bool(c.get("enable", True)) for c in cases]
    waits = [int(c.get("wait_ms", 100) or 100) for c in cases]
    timeouts = [int(c.get("timeout_ms", 5000) or 5000) for c in cases]
    kinds = [str(c.get("kind", "MessageOK")) for c in cases]
    op_params = [c.get("op_params") for c in cases]
    return steps, enables, waits, timeouts, kinds, op_params


def _sequence_lists_to_cases(result) -> list:
    """The shared editor's FCT result -> project-YAML case dicts."""
    steps, enables, waits, timeouts, kinds, op_params = result
    cases: list = []
    for i, name in enumerate(steps):
        cases.append({
            "name": str(name),
            "kind": (str(kinds[i]) if kinds and i < len(kinds)
                     else "MessageOK"),
            "enable": bool(enables[i]),
            "wait_ms": int(waits[i]),
            "timeout_ms": int(timeouts[i]),
            "op_params": (op_params[i] if op_params and i < len(op_params)
                          else None),
        })
    return cases


def _case_to_op_command(case: dict) -> ConsoleCommand:
    """A `fct_sequence_cases_yaml` case dict -> an Operation-typed
    ConsoleCommand row (m30 merged table)."""
    return ConsoleCommand(
        kind=KIND_OP,
        name=str(case.get("name", "")),
        enabled=bool(case.get("enable", True)),
        op_kind=str(case.get("kind", "op") or "op"),
        op_params=(dict(case.get("op_params"))
                   if case.get("op_params") else None),
        op_wait_ms=int(case.get("wait_ms", 100) or 100),
        op_timeout_ms=int(case.get("timeout_ms", 5000) or 5000))


def _op_command_to_case(cmd: ConsoleCommand) -> dict:
    """An Operation-typed ConsoleCommand -> `fct_sequence_cases_yaml`
    case dict (lossless for the fields the case shape carries)."""
    return {
        "name": str(cmd.name),
        "kind": str(cmd.op_kind or "op"),
        "enable": bool(cmd.enabled),
        "wait_ms": int(cmd.op_wait_ms or 100),
        "timeout_ms": int(cmd.op_timeout_ms or 5000),
        "op_params": (dict(cmd.op_params) if cmd.op_params else None),
    }


class _SshProbeWorker(QThread):
    """M29/M41 "Test Connection": stepwise SSH diagnosis OFF the UI
    thread using the CURRENT GUI values.

    Three layers, each with its own guidance when it fails:
      1. network: ping the DUT IPv4;
      2. reachability: TCP port 22 open on the DUT;
      3. authentication: paramiko connect (password / agent / key).
    Emits ok(<uname banner>) only when all three pass."""

    ok = Signal(str)
    fail = Signal(str)

    def __init__(self, host: str, username: str, password: str,
                 parent=None) -> None:
        super().__init__(parent)
        self._host, self._username = host, username
        # empty password -> fall back to the credential layer / agent
        # keys inside run() (agent/key auth is attempted first there)
        self._password = password

    def run(self) -> None:
        host = str(self._host or "").strip()
        # ---- layer 1: network reachability (ping) -----------------------
        if not host_platform.ping_host(host):
            self.fail.emit(
                f"network unreachable (ping {host} failed) - run the "
                "Wi-Fi/LAN network setup step first, or check LAN cable / "
                "AP association")
            return
        # ---- layer 2: TCP port 22 (sshd listening) ----------------------
        if not host_platform.tcp_port_open(host, 22):
            self.fail.emit(
                f"TCP port 22 closed on {host} - check DUT sshd is running")
            return
        # ---- layer 3: SSH authentication --------------------------------
        try:
            import paramiko
        except ImportError:
            self.fail.emit("paramiko is not installed "
                           "(pip install paramiko)")
            return
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict = dict(hostname=host, port=22,
                            username=self._username, timeout=8,
                            allow_agent=True, look_for_keys=True)
        if self._password:
            kwargs["password"] = self._password
        try:
            client.connect(**kwargs)
            _stdin, out, _err = client.exec_command(
                "uname -s -r", timeout=5)
            banner = out.read().decode(errors="replace").strip()[:80]
            self.ok.emit(banner)
        except Exception as exc:              # noqa: BLE001 - the REAL
            # auth / handshake error is the point of this button
            self.fail.emit(f"authentication failed: {exc} - check "
                           "username, password or key")
        finally:
            client.close()


class _SshTransferWorker(QThread):
    """M29 asset transfer (push / pull) OFF the UI thread over a fresh
    :class:`SshFctChannel` (password via the credential layer, ref
    ``fct_ssh_<host>`` - the same ref fct_exec uses).  Emits
    progress(done, total, path) per file, done(count) or fail(error)."""

    progress = Signal(int, int, str)
    done = Signal(int)
    fail = Signal(str)

    def __init__(self, direction: str, host: str, username: str,
                 local_dir: str, remote_dir: str, parent=None) -> None:
        super().__init__(parent)
        self._direction = direction          # "push" | "pull"
        self._host, self._username = host, username
        self._local_dir, self._remote_dir = local_dir, remote_dir

    def run(self) -> None:
        import os
        from ...engine.fct_channels import SshFctChannel
        channel = None
        try:
            channel = SshFctChannel(
                host=self._host, username=self._username,
                credential_ref=f"fct_ssh_{self._host}")
            if self._direction == "push":
                if os.path.isfile(self._local_dir):
                    target = channel.put_file(
                        self._local_dir,
                        remote_path=(f"{self._remote_dir.rstrip('/')}/"
                                     f"{os.path.basename(self._local_dir)}"
                                     if self._remote_dir else ""))
                    self.progress.emit(1, 1, target)
                    self.done.emit(1)
                    return
                files = channel.put_dir(
                    self._local_dir, self._remote_dir,
                    progress=lambda d, t, _lp, rp:
                        self.progress.emit(d, t, rp))
            else:
                files = channel.get_dir(
                    self._remote_dir, self._local_dir,
                    progress=lambda d, t, _rp, lp:
                        self.progress.emit(d, t, lp))
            self.done.emit(len(files))
        except Exception as exc:              # noqa: BLE001 - surfaced
            self.fail.emit(str(exc))
        finally:
            if channel is not None:
                try:
                    channel.close()
                except Exception:             # noqa: BLE001
                    pass


class _WifiLinkProbeWorker(QThread):
    """M31 Host PC <-> AP connection test OFF the UI thread.

    Delegates the actual command execution to
    ``host_platform.probe_host_ap_link`` (itself built on
    ``host_platform.run_link_cmd`` - monkeypatchable in tests).  Emits
    progress(done, total), line(text) per verdict line, then
    done(ok, summary)."""

    progress = Signal(int, int)
    line = Signal(str)
    done = Signal(bool, str)

    def __init__(self, gateway: str, expected_ssid: str | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._gateway = gateway
        self._expected_ssid = expected_ssid

    def run(self) -> None:
        try:
            result = host_platform.probe_host_ap_link(
                self._gateway,
                progress=lambda d, t: self.progress.emit(d, t),
                expected_ssid=self._expected_ssid)
            lines = [str(x) for x in result.get("lines", [])]
            for text in lines:
                self.line.emit(text)
            self.done.emit(bool(result.get("ok")), "\n".join(lines))
        except Exception as exc:              # noqa: BLE001 - surfaced as
            self.progress.emit(3, 3)          # the required FAILED verdict
            self.line.emit(f"Connection FAILED: {exc}")
            self.done.emit(False, f"Connection FAILED: {exc}")


class _BtScanWorker(QThread):
    """M32 Host PC Bluetooth scan OFF the UI thread.

    Delegates command execution to ``host_platform.run_link_cmd``
    (monkeypatchable in tests).  mac: ``blueutil --inquiry 10`` + a
    ``system_profiler`` pass for RSSI; Windows: ``Get-PnpDevice`` paired
    list (no 10 s wait).  Emits progress(done, total), result(text) for
    the device list, verdict(text) for the DUT-hit conclusion, then
    done()."""

    progress = Signal(int, int)
    result = Signal(str)
    verdict = Signal(str)
    done = Signal()

    def __init__(self, dut_name: str, parent=None) -> None:
        super().__init__(parent)
        self._dut_name = dut_name

    def run(self) -> None:
        try:
            is_windows = host_platform.platform_key() == "windows"
            self.progress.emit(1, 2)
            scan_out = host_platform.run_link_cmd(
                host_platform.host_bt_scan_cmd(), timeout_s=30)
            rssi_out = ""
            if not is_windows:
                rssi_out = host_platform.run_link_cmd(
                    host_platform.host_bt_devices_cmd(), timeout_s=20)
            self.progress.emit(2, 2)
            info = host_platform.format_bt_scan_result(
                scan_out, rssi_out, self._dut_name, is_windows)
            self.result.emit("\n".join(info["lines"]))
            self.verdict.emit(info["verdict"])
        except Exception as exc:              # noqa: BLE001 - shown in the
            self.progress.emit(2, 2)          # popup as the scan failure
            self.result.emit(f"Scan FAILED: {exc}")
            self.verdict.emit("")
        finally:
            self.done.emit()


def classify_bt_driver_probe(text: str) -> tuple:
    """Three-state DUT BT driver verdict from a console probe transcript.

    ``OK``         - the DUT shell ran the probe and exposed ``hci0``;
    ``needs-load`` - the shell answered but no BT adapter exists yet
                     (guidance: load the driver with a Console_serial
                     step from the project assets first);
    ``FAIL``       - the console never answered the probe.

    Read-only hint: nothing is injected into the sequence."""
    low = (text or "").lower()
    if low.count("__bt_done__") < 2:
        return ("FAIL", "DUT console did not answer the probe - check the "
                "Console Port / Baudrate and that the DUT shell is up.")
    if "hci0" in low:
        return ("OK", "DUT Bluetooth driver is loaded (hci0 present).")
    return ("needs-load", "No hci0 on the DUT - load the BT driver first "
            "with a Console_serial step (e.g. drivers/load_drivers.sh from "
            "the project assets), then run Pair & Connect / Tone.")


class _BtDriverProbeWorker(QThread):
    """M45: read-only DUT BT driver probe over the Console serial port.

    Sends :data:`BT_PROBE_CMD` (echo marker -> ``ls /sys/class/bluetooth``
    + ``hciconfig -a`` -> done marker) and classifies the transcript with
    :func:`classify_bt_driver_probe`.  Never injects a step."""

    result = Signal(str, str)              # (state, message)

    def __init__(self, port: str, baudrate: int, parent=None) -> None:
        super().__init__(parent)
        self._port = port
        self._baudrate = int(baudrate)

    def run(self) -> None:
        text = ""
        try:
            import serial

            with serial.Serial(self._port, self._baudrate, timeout=0.2,
                               write_timeout=2) as ser:
                ser.reset_input_buffer()
                ser.write((BT_PROBE_CMD + "\n").encode())
                deadline = time.monotonic() + 8.0
                while time.monotonic() < deadline:
                    chunk = ser.read(4096)
                    if chunk:
                        text += chunk.decode(errors="replace")
                    if text.lower().count("__bt_done__") >= 2:
                        break
        except Exception as exc:              # noqa: BLE001 - shown as FAIL
            self.result.emit("FAIL", f"DUT console probe failed: {exc}")
            return
        state, message = classify_bt_driver_probe(text)
        self.result.emit(state, message)


class _ToneRangeSlider(QWidget):
    """M45 dual-node Start/End slider over the whole wav (seconds).

    Two draggable nodes on one track: the left node is the played
    segment's Start, the right node its End.  Start <= End is enforced
    while dragging; ``changed`` carries ``(start_s, end_s)`` after every
    move.  Resolution is 0.1 s, matching the ``tone_start_s`` /
    ``tone_end_s`` step params."""

    changed = Signal(float, float)
    _MARGIN = 10

    def __init__(self, total_s: float = 6.0, parent=None) -> None:
        super().__init__(parent)
        self._total = max(float(total_s), 0.1)
        self._start = 0.0
        self._end = self._total
        self._drag = ""                    # "start" | "end" | ""
        self.setMinimumHeight(30)
        self.setMinimumWidth(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ---------------------------------------------------------------- api
    def total(self) -> float:
        return self._total

    def start_s(self) -> float:
        return self._start

    def end_s(self) -> float:
        return self._end

    def set_total(self, total_s: float) -> None:
        """New wav -> the segment resets to the WHOLE file."""
        total = max(float(total_s), 0.1)
        if abs(total - self._total) > 0.001:
            self._start, self._end = 0.0, total
        self._total = total
        self.update()

    def set_values(self, start_s: float, end_s: float) -> None:
        """Clamp the loaded Start/End into the current file length."""
        start = max(0.0, min(float(start_s or 0.0), self._total))
        end = float(end_s or 0.0) or self._total
        self._start = start
        self._end = max(start, min(end, self._total))
        if self._end <= 0.0:
            self._end = self._total
        self.update()

    def _seconds_at(self, x: float) -> float:
        span = max(self.width() - 2 * self._MARGIN, 1)
        ratio = min(max((x - self._MARGIN) / span, 0.0), 1.0)
        return round(ratio * self._total, 1)

    def _x_for(self, seconds: float) -> float:
        span = max(self.width() - 2 * self._MARGIN, 1)
        return self._MARGIN + span * min(max(seconds / self._total, 0.0), 1.0)

    # -------------------------------------------------------------- events
    def mousePressEvent(self, event) -> None:      # noqa: N802 - Qt
        x = event.position().x()
        self._drag = ("start" if abs(x - self._x_for(self._start))
                      <= abs(x - self._x_for(self._end)) else "end")
        self._move_to(x)

    def mouseMoveEvent(self, event) -> None:       # noqa: N802 - Qt
        if self._drag:
            self._move_to(event.position().x())

    def mouseReleaseEvent(self, event) -> None:    # noqa: N802 - Qt
        self._drag = ""

    def _move_to(self, x: float) -> None:
        value = self._seconds_at(x)
        if self._drag == "start":
            self._start = min(value, self._end)
        else:
            self._end = max(value, self._start)
        self.update()
        self.changed.emit(self._start, self._end)

    def paintEvent(self, event) -> None:           # noqa: N802 - Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = self.height() / 2.0
        groove = QRectF(self._MARGIN, mid - 3,
                        max(self.width() - 2 * self._MARGIN, 1), 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d1d5db"))
        painter.drawRoundedRect(groove, 3, 3)
        lo = self._x_for(self._start)
        hi = self._x_for(self._end)
        painter.setBrush(QColor("#2563eb"))
        painter.drawRoundedRect(QRectF(lo, mid - 3, max(hi - lo, 1), 6), 3, 3)
        for value in (lo, hi):
            painter.setBrush(QColor("#1d4ed8"))
            painter.drawEllipse(QRectF(value - 7, mid - 7, 14, 14))
        painter.end()


class _TonePreview(QObject):
    """M45 local WAV preview of the Start..End segment + live RMS meter.

    QtMultimedia (QMediaPlayer/QAudioOutput) is used so the SAME code
    plays on macOS and Windows; ``QAudioBufferOutput`` (Qt >= 6.8)
    feeds the decoded buffers to the RMS meter.  When the multimedia
    backend is missing the editor disables Preview with a status note
    (graceful degradation, never a crash)."""

    level = Signal(int)                     # 0..100
    status = Signal(str)
    playing = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._player = None
        self._buffer_out = None
        self._start_ms = 0
        self._end_ms = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._on_tick)

    @staticmethod
    def available() -> bool:
        try:
            from PySide6.QtMultimedia import (      # noqa: F401
                QAudioOutput, QMediaPlayer)
        except Exception:                           # noqa: BLE001
            return False
        return True

    def _ensure_player(self) -> bool:
        if self._player is not None:
            return True
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(QAudioOutput(self))
            self._player.playbackStateChanged.connect(self._on_state)
        except Exception as exc:                    # noqa: BLE001
            self._player = None
            self.status.emit(f"Preview unavailable: {exc}")
            return False
        try:
            from PySide6.QtMultimedia import QAudioBufferOutput

            self._buffer_out = QAudioBufferOutput(self)
            self._buffer_out.audioBufferReceived.connect(self._on_buffer)
            self._player.setAudioBufferOutput(self._buffer_out)
        except Exception:                           # noqa: BLE001
            self._buffer_out = None                 # meter stays at 0
        return True

    def is_playing(self) -> bool:
        """True between play() and stop() (drives the toggle button)."""
        return bool(self._timer.isActive())

    def play(self, path: str, start_s: float, end_s: float) -> None:
        if not self._ensure_player():
            return
        from PySide6.QtCore import QUrl

        self.stop()
        self._start_ms = max(0, int(round(float(start_s) * 1000)))
        self._end_ms = max(self._start_ms + 100, int(round(float(end_s) * 1000)))
        self._player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self._player.play()
        self._timer.start()
        self.playing.emit(True)
        self.status.emit("Previewing the selected segment locally...")

    def stop(self) -> None:
        self._timer.stop()
        if self._player is not None:
            self._player.stop()
        self.level.emit(0)                          # meter resets on stop
        if self.playing is not None:
            self.playing.emit(False)

    def _on_tick(self) -> None:
        if self._player is None:
            self.stop()
            return
        pos = int(self._player.position())
        if pos < self._start_ms:
            self._player.setPosition(self._start_ms)
        elif pos >= self._end_ms:
            self.stop()
            self.status.emit("Preview finished.")

    def _on_state(self, state) -> None:
        from PySide6.QtMultimedia import QMediaPlayer as _MP

        if state == _MP.PlaybackState.StoppedState and self._timer.isActive():
            self._timer.stop()
            self.level.emit(0)
            self.playing.emit(False)

    def _on_buffer(self, buffer) -> None:           # noqa: ANN001 - Qt object
        """RMS of the decoded buffer -> 0..100 meter value."""
        try:
            frames = buffer.constData()
            if frames is None or not len(frames):
                return
            data = frames.tobytes()
            count = len(data) // 2
            if count <= 0:
                return
            from array import array

            samples = array("h", data[:count * 2])
            peak = max(max(samples), -min(samples), 1)
            self.level.emit(min(100, int(round(peak * 100 / 32768))))
        except Exception:                           # noqa: BLE001
            return


class FCTTestConfigPanel(QWidget):
    """Block 07 config panel: ONE page (the FCT step sequence).

    M50: the former Console / Wi-Fi / Bluetooth tabs are gone.  Every
    row owns its own parameters; shared values are runtime references
    to the Equipment page (``equipment.dut.ssh.ip`` ...) with an
    optional step-level override.  The single tab holds the ordered
    step table + its Add menu.
    """

    #: (level, message) Event-Log mirror (T6 panel convention)
    task_log = Signal(str, str)

    def __init__(self, parent=None, equipment_provider=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(1100)
        self._legacy: dict = {}             # preserved module params
        self._setup_cfg = FctSetupCfg()
        #: full console node (connection fields + login sequence) kept
        #: from the loaded yaml; its values are now referenced from
        #: ``equipment.dut.*`` instead of edited on a separate tab
        self._console_cfg = ConsoleCfg()
        #: Wi-Fi / Bluetooth baseline (legacy values); each step owns
        #: its own tuning in ``ConsoleCommand.step_params``
        self._wifi_cfg = None
        self._bt_cfg = None
        self._guard = False
        #: M50: the project Equipment node (dict) for effective-value
        #: display / reference validation (None = not wired)
        self.equipment_provider = equipment_provider
        #: M37: standard operations usable with the configured resources
        #: (None = all of them; the Operation row editor grays the rest)
        self._available_ops: set[str] | None = None
        lay = QVBoxLayout(self)
        self.dut_type = QComboBox()
        self.dut_type.addItems(["linux", "bare_metal"])
        self.dut_type.currentTextChanged.connect(self._on_dut_type_changed)
        self.dut_hint = QLabel("")
        self.dut_hint.setWordWrap(True)
        self.dut_hint.setStyleSheet("color: #6b7280;")
        head = QHBoxLayout()
        head.addWidget(QLabel("DUT OS Firmware:"))
        head.addWidget(self.dut_type)
        head.addStretch(1)
        lay.addLayout(head)
        lay.addWidget(self.dut_hint)
        # the ONLY page (M50): the step table + toolbar
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_sequence_tab(), "Sequence")
        # one page only -> no tab selector (PySide6 has no
        # setTabBarHidden; hide the bar itself)
        self.tabs.tabBar().setVisible(False)
        lay.addWidget(self.tabs)
        self._on_dut_type_changed(self.dut_type.currentText())

    # ------------------------------------------------- equipment helpers
    def equipment_node(self) -> dict | None:
        """The current project Equipment node (None when not wired)."""
        provider = getattr(self, "equipment_provider", None)
        if not callable(provider):
            return None
        try:
            data = provider() or {}
        except Exception:                     # noqa: BLE001 - never crash
            return None
        if isinstance(data, dict) and "equipment" in data:
            return data.get("equipment") or {}
        return data if isinstance(data, dict) else None

    def _effective(self, refs: dict, overrides: dict, key: str):
        """Effective value of one referenced field (override wins)."""
        from mtkgui.engine.ref_resolver import effective
        overrides = overrides or {}
        return effective((refs or {}).get(key), overrides.get(key),
                         self.equipment_node())

    # ---------------------------------------------------------- DUT type
    def _on_dut_type_changed(self, dut: str) -> None:
        """DUT OS/firmware gates the available FCT items.

        Linux BSP DUT - full console set (Serial/SSH Wait->Send->Capture;
        SSH sftp_put/sftp_get); Wi-Fi host server -> DUT client, full-stack
        RSSI->Ping->iPerf or RSSI only; Bluetooth host source -> DUT A2DP
        sink (RSSI->Pair/Connect->Tone over BT).

        Bare Metal/RTOS DUT - serial-only console but the SAME
        Wait->Send->Capture flow (firmware prompts can be answered, e.g.
        Button/LED yes/no), no SSH/SFTP; Wi-Fi and Bluetooth are host ->
        DUT RSSI-only discovery scans."""
        is_linux = dut == "linux"
        self.dut_hint.setText(
            "Linux BSP DUT - Console: full set (Serial/SSH "
            "Wait->Send->Capture; SSH sftp_put/sftp_get). Wi-Fi: host "
            "server -> DUT client, full-stack RSSI->Ping->iPerf or RSSI "
            "only. Bluetooth: host source -> DUT A2DP sink, "
            "RSSI->Pair/Connect->Tone over BT."
            if is_linux else
            "Bare Metal/RTOS DUT - Console: serial only but the same "
            "Wait->Send->Capture flow (e.g. Button/LED: wait prompt -> "
            "send yes/no -> capture result); no SSH/SFTP. Wi-Fi: host -> "
            "DUT RSSI only. Bluetooth: host -> DUT RSSI only.")
        self._sync_add_menu()
        self._sync_op_submenu()

    def _sync_add_menu(self) -> None:
        """Bare-metal DUTs hide Console_ssh / SFTP_put / SFTP_get in the
        Add dropdown (no OS -> no SSH/SFTP) and the Linux-only RF rows
        (Wifi_Iperf / BT_Pair / BT_Tone); Console_serial, Console_cli,
        Wifi_Scan, BT_RSSI and the Message* / Operation rows stay
        available."""
        if not hasattr(self, "cmd_table"):
            return
        is_linux = self.dut_type.currentText() == "linux"
        actions = getattr(self, "_add_actions", {})
        for label in (STEP_TYPE_CONSOLE_SSH, STEP_TYPE_SFTP_PUT,
                      STEP_TYPE_SFTP_GET, STEP_TYPE_WIFI_IPERF,
                      STEP_TYPE_BT_PAIR, STEP_TYPE_BT_TONE):
            act = actions.get(label)
            if act is not None:
                act.setVisible(is_linux)

    # ----------------------------------------------------------- sequence
    def _build_sequence_tab(self) -> QWidget:
        """m30: ONE merged "FCT test step" table.

        Every step - standard operation, console interact (serial/ssh),
        SFTP transfer, host CLI (Windows only) and operator dialog -
        lives in one ordered table.  The merged table is the single
        sequence edit source: standard operations round-trip through
        ``fct_sequence_cases_yaml`` and every other row round-trips
        through ``console.test_commands``."""
        w = QWidget()
        lay = QVBoxLayout(w)
        cmd_hint = QLabel(
            "FCT test steps: one row = one step. Type selects the step "
            "kind (Operation / Console_serial / Console_ssh / SFTP / "
            "Console_cli / Message*); double-click a row to edit its "
            "patterns, timeouts, transfer paths, Windows command line or "
            "dialog text. Capture uses ONE rule every step: Expected must "
            "be found, Unexpected must NOT be found.")
        cmd_hint.setWordWrap(True)
        cmd_hint.setStyleSheet("color: #6b7280;")
        lay.addWidget(cmd_hint)
        lay.addWidget(QLabel("FCT test step:"))
        self.cmd_table = QTableWidget(0, 8)
        self.cmd_table.setHorizontalHeaderLabels(
            ["#", "Step", "Type", "WaitFor", "SendTo",
             "Capture", "Timeout", "cmd / params"])
        # m30: the short columns (# / Type / Timeout) are FIXED so the
        # Type column stays visible without a horizontal scrollbar; the
        # five content columns share the remaining width (Stretch).
        header = self.cmd_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for col, width in ((_COL_HASH, 40), (_COL_TYPE, 130),
                           (_COL_TIMEOUT, 70)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.cmd_table.setColumnWidth(col, width)
        for col in (_COL_STEP, _COL_WAIT, _COL_SEND, _COL_CAPTURE,
                    _COL_CMD):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        self.cmd_table.setMinimumHeight(180)
        # M47: multi-row selection (ctrl / shift + click) so "Remove
        # Selected" deletes several rows in one action; whole rows are
        # selected (the sequence is row-oriented).
        self.cmd_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.cmd_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        lay.addWidget(self.cmd_table, 1)
        self.cmd_table.cellDoubleClicked.connect(self._on_cmd_double_click)
        self.cmd_table.itemSelectionChanged.connect(
            self._sync_remove_buttons)
        lay.addLayout(self._cmd_row_buttons())
        # M34: the Sequence tab scrolls (small window) - no control squeeze
        return wrap_scrollable(w)

    def _insert_row(self, cmd: ConsoleCommand) -> None:
        """Append one row and render the given command on it (the
        shared scaffolding behind every Add entry)."""
        r = self.cmd_table.rowCount()
        self.cmd_table.insertRow(r)
        for col in range(8):
            self.cmd_table.setItem(r, col, QTableWidgetItem(""))
        self._save_row_cmd(r, cmd)

    def _add_row_for_label(self, label: str) -> None:
        """Add the default row for one of the direct Type labels."""
        cmd = console_command_for_label(
            label, _ADD_ROW_NAMES.get(label, ""))
        # M41: a new SFTP row starts from the Console SFTP submodule dirs
        self._prefill_sftp_dirs(cmd)
        self._insert_row(cmd)

    def _prefill_sftp_dirs(self, cmd: ConsoleCommand) -> None:
        """Fill EMPTY SFTP dir fields from the loaded console node
        (non-empty step values always win; M50 keeps no console page)."""
        c = self._console_cfg
        if cmd.kind == KIND_SFTP_PUT:
            cmd.local = cmd.local or str(c.scripts_local_dir or "").strip()
            cmd.remote = cmd.remote or str(c.scripts_remote_dir or "").strip()
        elif cmd.kind == KIND_SFTP_GET:
            cmd.remote = cmd.remote or str(c.pull_remote_dir or "").strip()
            cmd.local = cmd.local or str(c.pull_local_dir or "").strip()

    def _add_operation_row(self, op_name: str) -> None:
        """M43: add a standard-operation row DIRECTLY from the Operation
        submenu (no nested sequence-editor dialog opens).

        Args:
            op_name: one of ``OP_STEPS`` keys.
        """
        cmd = console_command_for_label(STEP_TYPE_OPERATION, op_name)
        cmd.op_params = dict(OP_STEPS.get(op_name) or {})
        # M50: the Wi-Fi connect row starts with the Equipment PC Wi-Fi
        # AP values (runtime reference; the row's override field still
        # lets the operator diverge from the shared value)
        if op_name == WIFI_CONNECT_OP:
            cmd.refs = {"ssid": "equipment.peripherals.wifi.ap_ssid",
                        "password": "equipment.peripherals.wifi.ap_password"}
            node = self.equipment_node() or {}
            wifi = ((node.get("peripherals") or {}).get("wifi") or {})
            cmd.op_params["ssid"] = str(wifi.get("ap_ssid") or "")
            cmd.op_params["password"] = str(wifi.get("ap_password") or "")
        self._insert_row(cmd)

    def _add_serial_transfer_row(self, direction: str) -> None:
        """M46: add a Serial Push / Pull row (Operation submenu)."""
        label = (STEP_TYPE_SERIAL_PUT if direction == "push"
                 else STEP_TYPE_SERIAL_PULL)
        cmd = console_command_for_label(label, label)
        if direction == "push":
            path, _hint = self._default_assets_dir()
            cmd.local = path
            cmd.remote = "/root/"
        else:
            cmd.local = self._default_outbox_dir()
            cmd.remote = "/root/"
        self._insert_row(cmd)

    def _default_assets_dir(self) -> tuple:
        """(path, hint) for the Push Browse default (M46)."""
        from mtkgui.gui.shell import resolve_tenant_base
        project = str(getattr(self, "_project_name", "") or "")
        if project:
            base = resolve_tenant_base()
        else:
            base = "projects"
        return default_assets_dir(project, base)

    def _default_outbox_dir(self) -> str:
        """Pull local default: the current project folder / outbox."""
        from mtkgui.gui.shell import resolve_tenant_base
        project = str(getattr(self, "_project_name", "") or "")
        if project:
            import os
            return os.path.join(resolve_tenant_base(), project, "outbox")
        return "outbox"

    # ------------------------------------------------------ M47 templates
    def _template_prefill(self) -> dict:
        """Shared parameters the loaded template rows are pre-filled from
        (Wi-Fi AP values + the project assets / outbox paths).  Whatever
        the project page does not carry keeps the template's own default."""
        assets, _hint = self._default_assets_dir()
        node = self.equipment_node() or {}
        wifi = ((node.get("peripherals") or {}).get("wifi") or {})
        dut_wifi = ((node.get("dut") or {}).get("wifi") or {})
        # M50: the Equipment config is the source; a LEGACY project without
        # Equipment values keeps pre-filling from its imported old config.
        legacy_wifi = self._wifi_cfg
        return {
            "wifi_ssid": str(wifi.get("ap_ssid")
                             or (legacy_wifi.ap_ssid if legacy_wifi else "")
                             or ""),
            "wifi_password": str(wifi.get("ap_password") or (
                legacy_wifi.ap_password if legacy_wifi else "") or ""),
            "wifi_interface": str(dut_wifi.get("interface") or (
                legacy_wifi.interface if legacy_wifi else "") or ""),
            "assets_dir": assets,
            "outbox_dir": self._default_outbox_dir(),
        }

    def _load_template(self, label: str) -> None:
        """Load Template: append one reference sequence as ORDINARY rows.

        Only the operator triggers this (the app never injects steps);
        nothing runs - the load is plain configuration.  The appended
        rows are editable / removable / reorderable like hand-added ones.
        """
        from mtkgui.engine.fct_templates import load_template_commands
        try:
            commands = load_template_commands(label, self._template_prefill())
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self.task_log.emit(
                "ERROR", f"Load Template '{label}' failed: {exc}")
            return
        for cmd in commands:
            self._insert_row(cmd)
        self._renumber_rows()
        self.task_log.emit(
            "INFO", f"Template '{label}': {len(commands)} step(s) appended "
                    "- edit, delete or reorder them like any other row")

    # ------------------------------------------------- M43 op submenu gate
    @staticmethod
    def _op_name_for_label(label: str) -> str | None:
        """Standard operation name behind an "Operation: <name>" entry
        (None for Custom / Delay entries)."""
        prefix = "Operation: "
        if not label.startswith(prefix):
            return None
        name = label[len(prefix):]
        return name if name in OP_STEPS else None

    def _op_usable(self, name: str) -> bool:
        """True when the operation may be added (M37 availability).

        M41: the network-setup operations need no external resource, so
        they are always usable (the bare-metal gate is applied separately
        in :meth:`_sync_op_submenu`)."""
        if name in NETWORK_OPS:
            return True
        return self._available_ops is None or name in self._available_ops

    @staticmethod
    def _op_blocked_tooltip(name: str) -> str:
        """Explain WHICH configuration makes one operation usable."""
        if name in DIO_OPS:
            return "Configure Control IO Nets (ICT module) first"
        if name in INSTRUMENT_OPS:
            return "Configure instruments (Equipment page) first"
        if name in FIXTURE_OPS:
            return "Configure fixture (Equipment page) first"
        return "Configure the required resource first"

    def _sync_op_submenu(self) -> None:
        """M37 gate on the shared Operation entries + M41 bare-metal gate
        on the shared Network entries (M48)."""
        combo = getattr(self, "dut_type", None)
        is_linux = combo is None or combo.currentText() == "linux"
        for text, act in getattr(self, "_op_add_actions", {}).items():
            name = self._op_name_for_label(text)
            blocked = name is not None and not self._op_usable(name)
            act.setEnabled(not blocked)
            act.setToolTip(self._op_blocked_tooltip(name) if blocked else "")
        for act in getattr(self, "_network_add_actions", {}).values():
            act.setEnabled(is_linux)
            act.setToolTip("" if is_linux else
                           ("Bare Metal: no network stack on the DUT - the "
                            "network setup steps need a Linux DUT"))

    def _add_entry_gate(self, entry):
        """M48: per-entry gate applied while the shared menu is built."""
        if not entry.op_name:
            return None
        if entry.group == "Network":
            combo = getattr(self, "dut_type", None)
            if combo is not None and combo.currentText() != "linux":
                return (False, "Bare Metal: no network stack on the DUT - "
                               "the network setup steps need a Linux DUT")
            return None
        if not self._op_usable(entry.op_name):
            return (False, self._op_blocked_tooltip(entry.op_name))
        return None

    def _add_for_entry(self, entry) -> None:
        """M48: one shared Add entry -> its row (direct, no dialog)."""
        key = str(entry.key)
        if key.startswith("op:"):
            self._add_operation_row(key[len("op:"):])
            return
        if key == "delay":
            self._add_row_for_label(STEP_TYPE_DELAY)
            return
        label = key[len("step:"):] if key.startswith("step:") else ""
        if label == STEP_TYPE_SERIAL_PUT:
            self._add_serial_transfer_row("push")
        elif label == STEP_TYPE_SERIAL_PULL:
            self._add_serial_transfer_row("pull")
        elif label:
            self._add_row_for_label(label)

    def _add_console_row(self) -> None:
        """Default interact row: Send enabled, Wait / Capture off."""
        self._add_row_for_label(STEP_TYPE_CONSOLE_SERIAL)

    def _add_message_row(self, style: str) -> None:
        """The three Console-domain operator-dialog presets (user
        direction 2026-10-18).  Every row WAITS the expected console
        message first (edit it in the row editor), then notifies the
        operator:

        - MessageOKtoConsole: OK notice - no console command, the
          Console is NOT blocked; answer timeout OFF.
        - MessageYesNotoConsole: Yes sends y, No sends n (PASS either
          way); answer timeout 4 s.
        - MessageGoStoptoConsole: GO sends y -> PASS, run continues;
          STOP sends n -> FAIL, run stops; answer timeout 4 s."""
        cmd = ConsoleCommand(
            kind=KIND_MESSAGE, dialog_style=style,
            wait_enabled=True, wait_timeout=10.0,
            capture_enabled=False,
            confirm_enabled=False, retries=0,
            timeout=4.0 if style in (DIALOG_YESNO, DIALOG_GOSTOP)
            else 0.0)
        cmd.send_enabled = style != DIALOG_OK
        if cmd.send_enabled:
            cmd.send = f"{cmd.send_yes} / {cmd.send_no}"
        cmd.name = {"ok": "MessageOKtoConsole",
                    "yesno": "MessageYesNotoConsole",
                    "gostop": "MessageGoStoptoConsole"}[style]
        self._insert_row(cmd)

    def _cmd_row_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        add = QPushButton("Add")
        # M48: the ONE shared Add menu (same grouped structure as the ICT
        # step editor).  Every submenu entry adds its row DIRECTLY - no
        # nested editor dialog; the ICT-only group stays visible but grayed.
        from mtkgui.gui.add_menu import NETWORK, OPERATION, build_add_menu
        built = build_add_menu(add, "fct", self._add_for_entry,
                               gate=self._add_entry_gate)
        self._add_menu = built.menu
        self._add_menu_groups = built.submenus
        self._add_actions = {}
        self._op_add_actions = {}
        self._network_add_actions = {}
        for entry, act in built.entries:
            if entry.domain == "ict":
                continue        # ICT-only: always disabled here
            self._add_actions[entry.label] = act
            if entry.group == OPERATION:
                self._op_add_actions[entry.label] = act
            elif entry.group == NETWORK:
                self._network_add_actions[entry.label] = act
        add.setMenu(built.menu)
        add.clicked.connect(self._add_console_row)

        # M47: Load Template appends one of the two reference sequences as
        # ORDINARY rows; nothing is injected without this operator click.
        template = QPushButton("Load Template")
        template_menu = QMenu(template)
        self._template_actions = {}
        for label in TEMPLATE_LABELS:
            act = template_menu.addAction(
                label, lambda _checked=False, l=label:
                self._load_template(l))
            self._template_actions[label] = act
        template.setMenu(template_menu)

        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_current)
        remove_sel = QPushButton("Remove selected")
        remove_sel.clicked.connect(self._remove_selected)
        duplicate = QPushButton("Duplicate")
        duplicate.clicked.connect(self._duplicate_row)
        edit = QPushButton("Edit")
        edit.clicked.connect(self._edit_current_row)
        move_up = QPushButton("Move Up")
        move_up.clicked.connect(self._move_up)
        move_down = QPushButton("Move Down")
        move_down.clicked.connect(self._move_down)
        row.addWidget(add)
        row.addWidget(template)
        row.addWidget(remove)
        row.addWidget(remove_sel)
        row.addWidget(duplicate)
        row.addWidget(edit)
        row.addWidget(move_up)
        row.addWidget(move_down)
        row.addStretch(1)
        self._remove_sel_btn = remove_sel
        self._sync_remove_buttons()
        return row

    def _sync_remove_buttons(self) -> None:
        """M47: "Remove selected" is enabled only when rows are selected."""
        button = getattr(self, "_remove_sel_btn", None)
        if button is None:
            return
        model = self.cmd_table.selectionModel()
        if model is None:
            return
        button.setEnabled(bool(model.selectedRows()))

    def _selected_rows(self) -> list:
        """The selected row indices, ascending, de-duplicated."""
        model = self.cmd_table.selectionModel()
        if model is None:
            return []
        return sorted({index.row() for index in model.selectedRows()})

    def _remove_current(self) -> None:
        """Remove the row under the cursor (single-row Remove)."""
        r = self.cmd_table.currentRow()
        if r >= 0:
            self.cmd_table.removeRow(r)
            self._renumber_rows()

    def _remove_selected(self) -> None:
        """M47: delete ALL selected rows in one action (no-op when the
        selection is empty)."""
        rows = self._selected_rows()
        if not rows:
            return
        for r in reversed(rows):
            self.cmd_table.removeRow(r)
        self._renumber_rows()

    def _duplicate_row(self) -> None:
        r = self.cmd_table.currentRow()
        if r < 0:
            return
        src = self._row_cmd(r)
        self.cmd_table.insertRow(r + 1)
        for col in range(8):
            self.cmd_table.setItem(r + 1, col, QTableWidgetItem(""))
        if src is not None:
            self._save_row_cmd(r + 1, copy.deepcopy(src))
        else:
            self._renumber_rows()

    def _move_up(self) -> None:
        r = self.cmd_table.currentRow()
        if r <= 0:
            return
        self._swap_rows(r, r - 1)
        self.cmd_table.setCurrentCell(r - 1, _COL_HASH)

    def _move_down(self) -> None:
        r = self.cmd_table.currentRow()
        if r < 0 or r >= self.cmd_table.rowCount() - 1:
            return
        self._swap_rows(r, r + 1)
        self.cmd_table.setCurrentCell(r + 1, _COL_HASH)

    def _swap_rows(self, r1: int, r2: int) -> None:
        """Swap two rows in cmd_table (full command + rendered cells)."""
        c1, c2 = self._row_cmd(r1), self._row_cmd(r2)
        if c1 is not None and c2 is not None:
            self._save_row_cmd(r1, copy.deepcopy(c2))
            self._save_row_cmd(r2, copy.deepcopy(c1))
            return
        # fallback: swap text cells
        for col in range(8):
            item1 = self.cmd_table.item(r1, col)
            item2 = self.cmd_table.item(r2, col)
            text1 = item1.text() if item1 else ""
            text2 = item2.text() if item2 else ""
            self.cmd_table.setItem(r1, col, QTableWidgetItem(text2))
            self.cmd_table.setItem(r2, col, QTableWidgetItem(text1))
        self._renumber_rows()

    def _on_cmd_double_click(self, row: int, col: int) -> None:
        """Double-click opens the per-Type editor."""
        if col == _COL_HASH:
            return
        self._edit_current_row(row)

    def _is_message_row(self, r: int) -> bool:
        """True when the row is an operator-dialog (message) row."""
        if r < 0 or r >= self.cmd_table.rowCount():
            return False
        cmd = self._row_cmd(r)
        return cmd is not None and cmd.kind == KIND_MESSAGE

    def _edit_current_row(self, row: int | None = None) -> None:
        """Open the per-Type editor for the selected / given row."""
        if row is None:
            row = self.cmd_table.currentRow()
        if row is None or row < 0 or row >= self.cmd_table.rowCount():
            return
        cmd = self._row_cmd(row)
        if cmd is None:
            return
        if self._is_rf_ref_row(cmd):
            self._edit_rf_row(row)
            return
        if cmd.kind == KIND_OP:
            if str((cmd.op_params or {}).get("type") or "") \
                    in NETWORK_OP_TYPES:
                self._edit_network_op_row(row)
            else:
                self._edit_operation_row(row)
        elif cmd.kind == KIND_DELAY:
            self._edit_delay_row(row)
        elif cmd.kind == KIND_FLASH_GUI:
            self._edit_flash_gui_row(row)
        elif cmd.kind in (KIND_SERIAL_PUT, KIND_SERIAL_PULL):
            self._edit_serial_transfer_row(row)
        elif cmd.kind == KIND_MESSAGE:
            self._edit_message_cell(row)
        else:
            self._edit_console_row(row)

    def _edit_delay_row(self, row: int) -> None:
        """Delay editor (M42): the fixed wait in ms.  Delay waits a fixed
        time and has NO timeout of its own - a plain wait of N ms, no
        console or instrument interaction."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel,
                                        QSpinBox, QDialogButtonBox)
        cmd = self._get_row_cmd(row)
        dlg = QDialog(self)
        dlg.setWindowTitle("Delay editor")
        # M42: single-column form - the wait is the only input
        dlg.setMinimumWidth(380)
        dlg.setMaximumWidth(400)
        outer = QVBoxLayout(dlg)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(
            "Plain wait of N ms - no console or instrument interaction, "
            "no timeout."))
        lay.addWidget(QLabel("Delay (wait):"))
        wait_spin = QSpinBox()
        wait_spin.setRange(0, 3_600_000)
        wait_spin.setSingleStep(100)
        wait_spin.setSuffix(" ms")
        wait_spin.setValue(int(cmd.wait_ms or 0))
        lay.addWidget(wait_spin)
        # M34: body scrolls, OK / Cancel stays outside (always visible)
        apply_scroll_to_dialog(dlg, body)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)
        if dlg.exec():
            cmd.kind = KIND_DELAY
            cmd.wait_ms = int(wait_spin.value())
            # M42: Delay has NO timeout of its own
            cmd.timeout = 0.0
            cmd.wait_enabled = False
            cmd.send_enabled = False
            cmd.capture_enabled = False
            self._save_row_cmd(row, cmd)
        dlg.deleteLater()

    def _edit_serial_transfer_row(self, row: int) -> None:
        """Serial Push / Pull editor (M46): Host PC path + DUT path +
        optional baudrate with a READ-ONLY estimated transfer time."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                        QFormLayout, QLabel, QLineEdit,
                                        QComboBox, QPushButton,
                                        QDialogButtonBox)
        from mtkgui.engine.serial_transfer import (BAUD_CHOICES,
                                                   dir_size, estimate_text)
        cmd = self._get_row_cmd(row)
        is_push = cmd.kind == KIND_SERIAL_PUT
        dlg = QDialog(self)
        dlg.setWindowTitle("Serial Push / Pull editor")
        dlg.setMinimumWidth(760)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        outer = QVBoxLayout(dlg)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(
            "Transfer over the SERIAL console: base64 chunks with marker "
            "ACKs, so console output cannot corrupt the data.  An empty "
            "baudrate uses the Console Serial rate; a raised rate is "
            "restored on BOTH sides afterwards (a restore failure fails "
            "the step explicitly)."))
        form = QFormLayout()
        local_edit = QLineEdit(cmd.local or "")
        local_edit.setPlaceholderText(
            "Host PC file or folder" if is_push else "Host PC destination")
        browse = QPushButton("Browse...")

        def _browse_local() -> None:
            from PySide6.QtWidgets import QFileDialog
            if is_push:
                path, _hint = self._default_assets_dir()
                picked = QFileDialog.getExistingDirectory(
                    self, "Local source folder (Host PC)",
                    path or (cmd.local or ""))
            else:
                path = cmd.local or self._default_outbox_dir()
                picked = QFileDialog.getExistingDirectory(
                    self, "Local destination folder (Host PC)", path)
            if picked:
                local_edit.setText(picked)

        browse.clicked.connect(_browse_local)
        local_row = QHBoxLayout()
        local_row.addWidget(local_edit, 1)
        local_row.addWidget(browse)
        form.addRow("Local (Host PC):", local_row)
        remote_edit = QLineEdit(cmd.remote or "/root/")
        remote_edit.setPlaceholderText(
            "DUT target path (file or folder)")
        form.addRow("Remote (DUT):", remote_edit)
        baud_combo = QComboBox()
        baud_combo.addItem("(Console Serial baudrate)", 0)
        for rate in BAUD_CHOICES:
            baud_combo.addItem(str(rate), rate)
        idx = baud_combo.findData(int(cmd.serial_baud or 0))
        baud_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Baudrate (optional):", baud_combo)
        est_label = QLabel("")
        form.addRow("Estimated time (read-only):", est_label)

        def _refresh_estimate() -> None:
            baud = int(baud_combo.currentData() or 0)
            rate = baud or 115200
            if is_push:
                size = dir_size(local_edit.text().strip())
                if size:
                    est_label.setText(f"{estimate_text(size, rate)} "
                                      f"({size} bytes @ {rate})")
                else:
                    est_label.setText("n/a (no local source yet)")
            else:
                est_label.setText("n/a (remote size unknown until run)")

        baud_combo.currentIndexChanged.connect(
            lambda _i: _refresh_estimate())
        local_edit.textChanged.connect(lambda _t: _refresh_estimate())
        _refresh_estimate()
        lay.addLayout(form)
        apply_scroll_to_dialog(dlg, body)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)
        if dlg.exec():
            cmd.local = local_edit.text().strip()
            cmd.remote = remote_edit.text().strip()
            cmd.serial_baud = int(baud_combo.currentData() or 0)
            cmd.wait_enabled = False
            cmd.send_enabled = False
            cmd.capture_enabled = False
            self._save_row_cmd(row, cmd)
        dlg.deleteLater()

    def _edit_flash_gui_row(self, row: int) -> None:
        """Flash_GUI editor (M33): the third-party flash GUI executable
        and the operator Go / Stop prompt."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
                                        QLabel, QLineEdit, QTextEdit,
                                        QDialogButtonBox)
        cmd = self._get_row_cmd(row)
        dlg = QDialog(self)
        dlg.setWindowTitle("Flash_GUI editor")
        dlg.setMinimumWidth(720)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        outer = QVBoxLayout(dlg)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(
            "Launches the third-party flash GUI (or reuses it when it is "
            "already running), then asks the operator: Go = flash "
            "success (run continues), Stop = flash failed (run stops). "
            "An empty GUI path fails the row."))
        form = QFormLayout()
        # M50: J-Link executable is a runtime reference (override wins)
        from mtkgui.engine.ref_resolver import describe
        refs = dict(cmd.refs or {})
        overrides = dict(cmd.overrides or {})
        refs.setdefault("jlink", "equipment.jlink.executable")
        ref_line = QLabel(f"ref: {refs['jlink']} - {describe(refs['jlink'])}")
        ref_line.setStyleSheet("color: #6b7280;")
        eff_line = QLabel("")
        eff_line.setStyleSheet("color: #111827;")
        jlink_override = QLineEdit(str(overrides.get("jlink") or ""))
        jlink_override.setPlaceholderText(
            "override (empty = use the referenced Equipment value)")

        def _sync_jlink(_t) -> None:
            value = self._effective({"v": refs["jlink"]},
                                    {"v": jlink_override.text()}, "v")
            eff_line.setText(f"effective: {value or '(not set)'}")

        jlink_override.textChanged.connect(_sync_jlink)
        _sync_jlink("")
        form.addRow("J-Link executable:", ref_line)
        form.addRow("", eff_line)
        form.addRow("", jlink_override)
        path_edit = QLineEdit(cmd.flash_gui_path or "")
        path_edit.setPlaceholderText(
            "Third-party flash GUI executable (full path)")
        form.addRow("GUI path:", path_edit)
        msg_edit = QTextEdit()
        msg_edit.setPlainText(cmd.flash_gui_message
                              or DEFAULT_FLASH_GUI_MESSAGE)
        msg_edit.setMaximumHeight(90)
        form.addRow("Message:", msg_edit)
        lay.addLayout(form)
        # M34: body scrolls, OK / Cancel stays outside (always visible)
        apply_scroll_to_dialog(dlg, body)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)
        if dlg.exec():
            cmd.kind = KIND_FLASH_GUI
            cmd.flash_gui_path = path_edit.text().strip()
            cmd.flash_gui_message = (
                msg_edit.toPlainText().strip() or DEFAULT_FLASH_GUI_MESSAGE)
            if jlink_override.text().strip():
                overrides["jlink"] = jlink_override.text().strip()
            else:
                overrides.pop("jlink", None)
            cmd.refs = refs
            cmd.overrides = overrides or None
            cmd.wait_enabled = False
            cmd.send_enabled = False
            cmd.capture_enabled = False
            self._save_row_cmd(row, cmd)
        dlg.deleteLater()

    def _edit_message_cell(self, row: int) -> None:
        """Operator-dialog editor (m30): one of the six Message* types
        (plain or *_to_Console), message text, wait pattern, yes/no
        payloads, answer timeout, and unified Capture (Expected /
        Unexpected)."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
                                        QLabel, QComboBox, QLineEdit,
                                        QDoubleSpinBox, QDialogButtonBox,
                                        QTextEdit)
        cmd = self._get_row_cmd(row)
        dlg = QDialog(self)
        dlg.setWindowTitle("Operator message editor")
        dlg.setMinimumWidth(620)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        outer = QVBoxLayout(dlg)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(
            "Operator dialog: MessageOK only acks; MessageYesNo sends "
            "yes / no (PASS either way); MessageGoStop GO continues and "
            "STOP stops the run.  The *_to_Console variants first WAIT "
            "the expected console message, then notify the operator. "
            "Capture uses the unified rule: Expected must be found, "
            "Unexpected must NOT be found."))
        form = QFormLayout()
        self._msg_style_items = (
            (STEP_TYPE_MESSAGE_OK, DIALOG_OK, False),
            (STEP_TYPE_MESSAGE_YESNO, DIALOG_YESNO, False),
            (STEP_TYPE_MESSAGE_GOSTOP, DIALOG_GOSTOP, False),
            (STEP_TYPE_MESSAGE_OK_WAIT, DIALOG_OK, True),
            (STEP_TYPE_MESSAGE_YESNO_WAIT, DIALOG_YESNO, True),
            (STEP_TYPE_MESSAGE_GOSTOP_WAIT, DIALOG_GOSTOP, True),
        )
        style = QComboBox()
        for label, _st, _w in self._msg_style_items:
            style.addItem(label)
        cur_label = step_type_label(cmd)
        try:
            style.setCurrentIndex(
                [lbl for lbl, _s, _w in self._msg_style_items]
                .index(cur_label))
        except ValueError:
            style.setCurrentIndex(1)
        form.addRow("Dialog:", style)
        msg = QLineEdit(cmd.confirm_message or "")
        msg.setPlaceholderText("Text shown to the operator "
                               "(empty = row name)")
        form.addRow("Message text:", msg)
        # the row WAITS this console message BEFORE the operator is
        # notified (empty = no wait; only meaningful for *_to_Console)
        expected = QLineEdit(cmd.expect_pass or "")
        expected.setPlaceholderText(
            "Console message to wait for (empty = wait disabled)")
        form.addRow("Expected (wait) message:", expected)
        wait_timeout = QDoubleSpinBox()
        wait_timeout.setRange(0.0, 3600.0)
        wait_timeout.setDecimals(0)
        wait_timeout.setSuffix(" s")
        wait_timeout.setSpecialValueText("off")
        wait_timeout.setValue(float(max(cmd.wait_timeout, 0.0)))
        form.addRow("Wait timeout:", wait_timeout)
        send_yes = QLineEdit(cmd.send_yes or "y")
        send_no = QLineEdit(cmd.send_no or "n")
        form.addRow("Send on Yes / GO:", send_yes)
        form.addRow("Send on No / STOP:", send_no)
        timeout = QDoubleSpinBox()
        timeout.setRange(0.0, 3600.0)
        timeout.setDecimals(0)
        timeout.setSuffix(" s")
        timeout.setSpecialValueText("off (wait forever)")
        timeout.setValue(float(max(cmd.timeout, 0.0)))
        form.addRow("Timeout:", timeout)
        # unified Capture (judged on the operator answer + console lines)
        cap_exp = QTextEdit()
        cap_exp.setPlainText(cmd.capture_expected or "")
        cap_exp.setMaximumHeight(60)
        cap_unexp = QTextEdit()
        cap_unexp.setPlainText(cmd.capture_unexpected or "")
        cap_unexp.setMaximumHeight(60)
        form.addRow("Capture Expected:", cap_exp)
        form.addRow("Capture Unexpected:", cap_unexp)
        lay.addLayout(form)
        # M34: body scrolls, OK / Cancel stays outside (always visible)
        apply_scroll_to_dialog(dlg, body)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)
        if dlg.exec():
            _lbl, dialog_style, _wait = self._msg_style_items[
                style.currentIndex()]
            is_wait_label = _wait
            cmd.dialog_style = dialog_style
            cmd.confirm_message = msg.text().strip()
            cmd.expect_pass = expected.text().strip()
            cmd.expect_pass_is_regex = False
            cmd.wait_enabled = is_wait_label or bool(cmd.expect_pass)
            cmd.wait_timeout = float(wait_timeout.value())
            cmd.send_enabled = dialog_style != DIALOG_OK
            if cmd.send_enabled:
                cmd.send_yes = send_yes.text().strip() or "y"
                cmd.send_no = send_no.text().strip() or "n"
                cmd.send = f"{cmd.send_yes} / {cmd.send_no}"
            else:
                cmd.send_yes = "y"
                cmd.send_no = "n"
                cmd.send = ""
            cmd.timeout = float(timeout.value())
            cmd.capture_expected = cap_exp.toPlainText().strip()
            cmd.capture_unexpected = cap_unexp.toPlainText().strip()
            cmd.capture_enabled = bool(cmd.capture_expected
                                       or cmd.capture_unexpected)
            self._save_row_cmd(row, cmd)

    def _edit_network_op_row(self, row: int) -> None:
        """M41: editor for the two DUT network-setup operations.

        ``wifi_connect`` (serial console): interface, AP SSID / password
        (auto-plugged from the Wi-Fi tab at row creation), DHCP or static
        IP, timeout.  ``lan_setup``: interface + DHCP / Static mode + the
        static IP / mask / gateway + timeout, with the "same subnet as
        the Host PC" hint.  Every command stays user-editable per step.
        """
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
                                        QLabel, QLineEdit, QCheckBox,
                                        QComboBox, QSpinBox,
                                        QDialogButtonBox)
        cmd = self._get_row_cmd(row)
        params = dict(cmd.op_params or {})
        is_wifi = str(params.get("type") or "") == "wifi_connect"
        title = WIFI_CONNECT_OP if is_wifi else LAN_SETUP_OP
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{title} editor")
        dlg.setMinimumWidth(620)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        outer = QVBoxLayout(dlg)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        note = QLabel(
            "Runs on the DUT SERIAL console (works before any network "
            "exists).  Recommended: right after Power On / Init / Fixture, "
            "before any Console_ssh / SFTP step - added manually, never "
            "automatic.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #6b7280;")
        lay.addWidget(note)
        form = QFormLayout()
        iface = QLineEdit(str(params.get("iface") or ""))
        iface.setPlaceholderText("wlan0" if is_wifi else "eth0")
        form.addRow("Interface:", iface)
        ssid = password = dhcp_cb = mode = None
        if is_wifi:
            ssid = QLineEdit(str(params.get("ssid") or ""))
            ssid.setPlaceholderText("AP SSID (auto-filled from Wi-Fi tab)")
            form.addRow("AP SSID:", ssid)
            password = QLineEdit(str(params.get("password") or ""))
            password.setPlaceholderText("leave empty for an open network")
            form.addRow("AP password:", password)
            dhcp_cb = QCheckBox("Use DHCP (uncheck = static IP)")
            dhcp_cb.setChecked(bool(params.get("dhcp", True)))
            form.addRow(dhcp_cb)
        else:
            mode = QComboBox()
            mode.addItems(["DHCP", "Static"])
            mode.setCurrentText("DHCP" if str(params.get("mode") or "dhcp")
                                .lower() != "static" else "Static")
            form.addRow("IP mode:", mode)
        dut_ip = QLineEdit(str(params.get("dut_ip") or ""))
        dut_ip.setPlaceholderText("e.g. 192.168.1.100")
        netmask = QLineEdit(str(params.get("netmask") or "255.255.255.0"))
        gateway = QLineEdit(str(params.get("gateway") or ""))
        form.addRow("DUT IP (static):", dut_ip)
        form.addRow("Netmask:", netmask)
        form.addRow("Gateway:", gateway)
        timeout = QSpinBox()
        timeout.setRange(1, 3600)
        timeout.setValue(int(params.get("timeout_s") or 60))
        timeout.setSuffix(" s")
        form.addRow("Timeout:", timeout)
        lay.addLayout(form)
        host_ip = str(((self.equipment_node() or {}).get("peripherals")
                       or {}).get("wifi", {}).get("host_ip") or "")
        subnet = QLabel(
            "Static IP must be in the same subnet as the Host PC "
            f"(Host PC IP: {host_ip or 'not detected'})")
        subnet.setWordWrap(True)
        subnet.setStyleSheet("color: #6b7280;")
        lay.addWidget(subnet)
        # M34: body scrolls, OK / Cancel stays outside (always visible)
        apply_scroll_to_dialog(dlg, body)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)
        if dlg.exec():
            params["type"] = "wifi_connect" if is_wifi else "lan_setup"
            params["stack"] = str(params.get("stack") or "wpa_supplicant")
            params["iface"] = (iface.text().strip()
                               or ("wlan0" if is_wifi else "eth0"))
            if is_wifi:
                params["ssid"] = ssid.text().strip()
                params["password"] = password.text()
                params["dhcp"] = dhcp_cb.isChecked()
            else:
                params["mode"] = ("dhcp" if mode.currentText() == "DHCP"
                                  else "static")
            params["dut_ip"] = dut_ip.text().strip()
            params["netmask"] = (netmask.text().strip()
                                 or "255.255.255.0")
            params["gateway"] = gateway.text().strip()
            params["timeout_s"] = int(timeout.value())
            cmd.kind = KIND_OP
            cmd.op_kind = "op"
            cmd.op_params = params
            self._save_row_cmd(row, cmd)
        dlg.deleteLater()

    def _edit_operation_row(self, row: int) -> None:
        """Operation row editor: reuse the shared op parameter editor
        via a transient StepsEditorDialog carrying the single row."""
        from PySide6.QtWidgets import QDialog
        from mtkgui.gui.steps_editor import StepsEditorDialog
        cmd = self._row_cmd(row)
        if cmd is None:
            return
        dlg = StepsEditorDialog(
            "fct", [cmd.name], [bool(cmd.enabled)],
            [int(cmd.op_wait_ms or 100)],
            [int(cmd.op_timeout_ms or 5000)],
            kinds=["op"],
            op_params=[dict(cmd.op_params) if cmd.op_params else None],
            available_ops=self._available_ops)
        if dlg.exec() == QDialog.Accepted:
            steps, enables, waits, timeouts, _kinds, op_params = \
                dlg.result_data()
            if steps:
                cmd.name = str(steps[0])
                cmd.enabled = bool(enables[0])
                cmd.op_wait_ms = int(waits[0])
                cmd.op_timeout_ms = int(timeouts[0])
                cmd.op_params = (dict(op_params[0])
                                 if op_params and op_params[0] else None)
                cmd.op_kind = "op"
                self._save_row_cmd(row, cmd)
        dlg.deleteLater()

    def _edit_console_row(self, row: int) -> None:
        """Console_serial / Console_ssh / SFTP / Console_cli editor with
        unified Expected + Unexpected Capture inputs."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
                                        QLabel, QLineEdit, QTextEdit,
                                        QCheckBox, QSpinBox,
                                        QDialogButtonBox, QWidget)
        cmd = self._get_row_cmd(row)
        typ = step_type_label(cmd)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{typ} editor")
        dlg.setMinimumWidth(720)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        outer = QVBoxLayout(dlg)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        # M50: the connection itself is a RUNTIME reference into the
        # Equipment DUT group; the override box wins when filled.
        from mtkgui.engine.ref_resolver import describe
        refs = dict(cmd.refs or {})
        overrides = dict(cmd.overrides or {})
        ref_editors: dict = {}
        conn_spec = []
        if typ == STEP_TYPE_CONSOLE_SERIAL:
            conn_spec = [
                ("port", "Serial port", "equipment.dut.console.port"),
                ("baud", "Baud rate", "equipment.dut.console.baud"),
                ("parity", "Parity", "equipment.dut.console.parity"),
            ]
        elif typ in (STEP_TYPE_CONSOLE_SSH, STEP_TYPE_SFTP_PUT,
                     STEP_TYPE_SFTP_GET):
            conn_spec = [
                ("host", "SSH host", "equipment.dut.ssh.ip"),
                ("username", "SSH username", "equipment.dut.ssh.username"),
                ("password", "SSH password", "equipment.dut.ssh.password"),
            ]
        if conn_spec:
            form.addRow(QLabel("Connection (runtime reference):"))
        for key, label, ref_path in conn_spec:
            refs.setdefault(key, ref_path)
            ref_line = QLabel(f"ref: {refs[key]} - "
                              f"{describe(refs[key])}")
            ref_line.setStyleSheet("color: #6b7280;")
            eff_line = QLabel("")
            eff_line.setStyleSheet("color: #111827;")
            override = QLineEdit(str(overrides.get(key) or ""))
            override.setPlaceholderText(
                "override (empty = use the referenced Equipment value)")

            def _sync_eff(_t, e=eff_line, r=ref_path, o=override) -> None:
                value = self._effective({"v": r}, {"v": o.text()}, "v")
                e.setText(f"effective: {value or '(not set)'}")

            override.textChanged.connect(_sync_eff)
            _sync_eff("")
            form.addRow(f"{label}:", ref_line)
            form.addRow("", eff_line)
            form.addRow("", override)
            ref_editors[key] = override

        wait_edit = None
        wait_cb = None
        wait_timeout = None
        if typ in (STEP_TYPE_CONSOLE_SERIAL, STEP_TYPE_CONSOLE_SSH):
            wait_cb = QCheckBox("Enable WaitFor")
            wait_cb.setChecked(cmd.wait_enabled)
            form.addRow(wait_cb)
            wait_edit = QLineEdit(cmd.expect_pass or "")
            wait_edit.setPlaceholderText(
                "Console message expected before sending")
            form.addRow("WaitFor:", wait_edit)
            wait_timeout = QSpinBox()
            wait_timeout.setRange(1, 3600)
            wait_timeout.setValue(int(cmd.wait_timeout or 10))
            wait_timeout.setSuffix(" s")
            form.addRow("Wait timeout:", wait_timeout)

        send_edit = None
        local_edit = remote_edit = None
        host_edit = None
        if typ in (STEP_TYPE_CONSOLE_SERIAL, STEP_TYPE_CONSOLE_SSH):
            send_cb = QCheckBox("Enable Send")
            send_cb.setChecked(cmd.send_enabled)
            form.addRow(send_cb)
            send_edit = QTextEdit()
            send_edit.setPlainText(cmd.send or "")
            send_edit.setMaximumHeight(90)
            form.addRow("SendTo:", send_edit)
        elif typ in (STEP_TYPE_SFTP_PUT, STEP_TYPE_SFTP_GET):
            # M41: EMPTY fields auto-fill from the Console SFTP submodule
            # dirs (non-empty step values keep their override)
            self._prefill_sftp_dirs(cmd)
            local_edit = QLineEdit(cmd.local or "")
            remote_edit = QLineEdit(cmd.remote or "")
            if typ == STEP_TYPE_SFTP_PUT:
                form.addRow("Local (Host):", local_edit)
                form.addRow("Remote (DUT):", remote_edit)
            else:
                form.addRow("Remote (DUT):", remote_edit)
                form.addRow("Local (Host):", local_edit)
        elif typ == STEP_TYPE_CONSOLE_CLI:
            host_edit = QTextEdit()
            host_edit.setPlainText(cmd.host_cmd_windows or cmd.host_cmd)
            host_edit.setMaximumHeight(110)
            form.addRow("Windows cmd:", host_edit)

        case_cb = QCheckBox("Case Sensitive (uncheck = ignore case)")
        case_cb.setChecked(cmd.case_sensitive)
        form.addRow(case_cb)
        cap_exp = QTextEdit()
        cap_exp.setPlainText(cmd.capture_expected or "")
        cap_exp.setMaximumHeight(60)
        cap_unexp = QTextEdit()
        cap_unexp.setPlainText(cmd.capture_unexpected or "")
        cap_unexp.setMaximumHeight(60)
        form.addRow("Capture Expected:", cap_exp)
        form.addRow("Capture Unexpected:", cap_unexp)
        timeout = QSpinBox()
        timeout.setRange(1, 3600)
        timeout.setValue(int(cmd.send_timeout if typ in (
            STEP_TYPE_SFTP_PUT, STEP_TYPE_SFTP_GET) else (cmd.timeout or 6)))
        timeout.setSuffix(" s")
        form.addRow("Timeout:", timeout)

        lay.addLayout(form)
        # M34: body scrolls, OK / Cancel stays outside (always visible)
        apply_scroll_to_dialog(dlg, body)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)
        if dlg.exec():
            if wait_cb is not None:
                cmd.wait_enabled = wait_cb.isChecked()
                cmd.expect_pass = (wait_edit.text().strip()
                                   if cmd.wait_enabled else "")
                cmd.wait_timeout = float(wait_timeout.value())
            if send_edit is not None:
                cmd.send_enabled = send_cb.isChecked()
                cmd.send = send_edit.toPlainText() if cmd.send_enabled else ""
                has_cap = bool(cap_exp.toPlainText().strip()
                               or cap_unexp.toPlainText().strip())
                if cmd.wait_enabled and not cmd.send_enabled:
                    cmd.kind = "wait"
                elif not cmd.send_enabled and has_cap:
                    cmd.kind = "capture"
                else:
                    cmd.kind = "send"
            elif typ in (STEP_TYPE_SFTP_PUT, STEP_TYPE_SFTP_GET):
                cmd.kind = (KIND_SFTP_PUT if typ == STEP_TYPE_SFTP_PUT
                            else KIND_SFTP_GET)
                cmd.send_enabled = True
                if typ == STEP_TYPE_SFTP_PUT:
                    cmd.local = local_edit.text().strip()
                    cmd.remote = remote_edit.text().strip()
                else:
                    cmd.remote = remote_edit.text().strip()
                    cmd.local = local_edit.text().strip()
                cmd.send_timeout = float(timeout.value())
                cmd.wait_enabled = False
                cmd.expect_pass = ""
            elif host_edit is not None:
                cmd.host_cmd_windows = host_edit.toPlainText().strip()
                cmd.host_cmd = cmd.host_cmd_windows
                cmd.timeout = float(timeout.value())
                cmd.wait_enabled = False
                cmd.send_enabled = bool(cmd.host_cmd_windows)
            cmd.case_sensitive = case_cb.isChecked()
            cmd.capture_expected = cap_exp.toPlainText().strip()
            cmd.capture_unexpected = cap_unexp.toPlainText().strip()
            cmd.capture_enabled = bool(cmd.capture_expected
                                       or cmd.capture_unexpected)
            if typ not in (STEP_TYPE_SFTP_PUT, STEP_TYPE_SFTP_GET,
                           STEP_TYPE_CONSOLE_CLI):
                cmd.timeout = float(timeout.value())
            for key, ov in ref_editors.items():
                text = ov.text().strip()
                if text:
                    overrides[key] = text
                else:
                    overrides.pop(key, None)
            if refs:
                cmd.refs = refs
            cmd.overrides = overrides or None
            self._save_row_cmd(row, cmd)

    def _edit_regex_cell(self, row: int, col: int, title: str) -> None:
        """Exact / Regex editor dialog with live match test."""
        if self._is_message_row(row):
            self._edit_message_cell(row)
            return
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                        QTextEdit, QPushButton, QLabel,
                                        QCheckBox, QWidget)
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(750)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        outer = QVBoxLayout(dlg)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        # load current state from the row's full ConsoleCommand
        cmd = self._row_cmd(row)
        cell_text = self.cmd_table.item(row, col).text() if self.cmd_table.item(row, col) else ""
        if cmd is not None:
            if title == "WaitFor":
                cur_pattern = cmd.expect_pass
                cur_regex = cmd.expect_pass_is_regex
                cur_enabled = cmd.wait_enabled
                cur_timeout = int(cmd.wait_timeout)
            else:
                cur_pattern = cmd.expect_fail
                cur_regex = cmd.expect_fail_is_regex
                cur_enabled = cmd.capture_enabled
                cur_timeout = int(cmd.timeout)
            cur_case = cmd.case_sensitive
            cur_expected = cmd.capture_is_expected
            cur_endline = cmd.capture_end_line
        else:
            is_off0 = cell_text.strip() == "(off)"
            cur_pattern = "" if is_off0 else cell_text
            cur_regex = False
            cur_enabled = not is_off0
            cur_case = True
            cur_expected = False
            cur_endline = ""
            cur_timeout = 10 if title == "WaitFor" else 6
        # Enable this step checkbox
        enable_cb = QCheckBox(f"Enable {title} step")
        enable_cb.setChecked(cur_enabled)
        lay.addWidget(enable_cb)
        # Use Regex checkbox (default off = exact match)
        regex_cb = QCheckBox("Use Regex (default off = exact substring match)")
        regex_cb.setChecked(cur_regex)
        lay.addWidget(regex_cb)
        # Case sensitive checkbox (default on)
        case_cb = QCheckBox("Case Sensitive (uncheck = ignore case, e.g. PASS=pass)")
        case_cb.setChecked(cur_case)
        lay.addWidget(case_cb)
        # Capture expected checkbox (only for Capture column)
        expect_cb = QCheckBox(
            "Expect to capture this message (yes = found is PASS; "
            "no = found is FAIL, use End line to bound the clean window)")
        if title == "Capture":
            expect_cb.setChecked(cur_expected)
            lay.addWidget(expect_cb)
        # End line input (always visible for Capture column)
        # Regex / Case Sensitive reuse the same checkboxes above
        end_line_label = QLabel("End line (marks end of range, same Regex/Case settings):")
        end_line_edit = QLineEdit()
        end_line_edit.setPlaceholderText("e.g. # TEST COMPLETE")
        end_line_edit.setText(cur_endline)
        if title == "Capture":
            lay.addWidget(end_line_label)
            lay.addWidget(end_line_edit)
        else:
            end_line_label.setVisible(False)
            end_line_edit.setVisible(False)
        # Timeout input
        from PySide6.QtWidgets import QSpinBox
        timeout_label = QLabel("Timeout (seconds, min 1):")
        lay.addWidget(timeout_label)
        timeout_spin = QSpinBox()
        timeout_spin.setRange(1, 3600)
        timeout_spin.setValue(cur_timeout)
        lay.addWidget(timeout_spin)
        # pattern text (3 lines)
        lay.addWidget(QLabel("Pattern text:"))
        pattern_edit = QTextEdit()
        pattern_edit.setPlainText(cur_pattern)
        pattern_edit.setMaximumHeight(70)
        lay.addWidget(pattern_edit)
        # test input (10 lines, disabled when not regex)
        lay.addWidget(QLabel("Regex match test (sample output per pattern):"))
        test_edit = QTextEdit()
        test_edit.setMinimumHeight(220)
        test_edit.setEnabled(False)
        lay.addWidget(test_edit)
        # Load sample from file button
        load_btn = QPushButton("Load sample from file...")
        load_btn.setEnabled(False)
        def _load_sample():
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(
                dlg, "Open log file", "",
                "Log files (*.log *.txt);;All files (*)")
            if path:
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        test_edit.setPlainText(f.read())
                except Exception as e:
                    result_label.setText(f"Load error: {e}")
        load_btn.clicked.connect(_load_sample)
        lay.addWidget(load_btn)
        test_btn = QPushButton("Test match")
        test_btn.setEnabled(False)
        lay.addWidget(test_btn)
        # result
        result_label = QLabel("")
        lay.addWidget(result_label)
        def _on_regex_changed(state):
            test_edit.setEnabled(state)
            test_btn.setEnabled(state)
            load_btn.setEnabled(state)
        regex_cb.toggled.connect(_on_regex_changed)
        _on_regex_changed(regex_cb.isChecked())
        def _test():
            import re
            pattern = pattern_edit.toPlainText()
            sample = test_edit.toPlainText()
            flags = 0 if case_cb.isChecked() else re.IGNORECASE
            try:
                if regex_cb.isChecked():
                    # regex mode
                    if re.search(pattern, sample, flags):
                        result_label.setText("✓ REGEX MATCH")
                        result_label.setStyleSheet("color: green")
                    else:
                        result_label.setText("✗ no regex match")
                        result_label.setStyleSheet("color: red")
                else:
                    # exact substring mode
                    if case_cb.isChecked():
                        hit = pattern in sample
                    else:
                        hit = pattern.lower() in sample.lower()
                    if hit:
                        result_label.setText("✓ EXACT MATCH")
                        result_label.setStyleSheet("color: green")
                    else:
                        result_label.setText("✗ no exact match")
                        result_label.setStyleSheet("color: red")
            except re.error as e:
                result_label.setText(f"Regex error: {e}")
                result_label.setStyleSheet("color: red")
        # common patterns hint
        lay.addWidget(QLabel("Regex common:  root@.*  |  login:  |  ERROR|FAIL  |  \\d+\\.\\d+"))
        # M34: body scrolls, OK / Cancel stays outside (always visible)
        apply_scroll_to_dialog(dlg, body)
        # buttons
        btn_row = QHBoxLayout()
        ok = QPushButton("OK")
        ok.clicked.connect(dlg.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        outer.addLayout(btn_row)
        if dlg.exec() == QDialog.Accepted:
            if cmd is None:
                cmd = self._get_row_cmd(row)
            pat = pattern_edit.toPlainText()
            enabled = enable_cb.isChecked()
            cmd.case_sensitive = case_cb.isChecked()
            if title == "WaitFor":
                cmd.wait_enabled = enabled
                cmd.expect_pass = pat if enabled else ""
                cmd.expect_pass_is_regex = regex_cb.isChecked()
                cmd.wait_timeout = float(timeout_spin.value())
            else:
                cmd.capture_enabled = enabled
                cmd.expect_fail = pat if enabled else ""
                cmd.expect_fail_is_regex = regex_cb.isChecked()
                cmd.capture_is_expected = expect_cb.isChecked()
                cmd.capture_end_line = end_line_edit.text()
                cmd.timeout = float(timeout_spin.value())
            # keep kind consistent for a wait-only row
            if cmd.wait_enabled and not cmd.send_enabled:
                cmd.kind = "wait"
            elif cmd.kind == "wait" and cmd.send_enabled:
                cmd.kind = "send"
            self._save_row_cmd(row, cmd)

    def _edit_host_cmd_cell(self, row: int, cmd: ConsoleCommand) -> None:
        """Host CLI action editor: the shell command run ON THE HOST PC
        (plus its timeout) - the counterpart of a console row's SendTo."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                        QTextEdit, QLabel, QPushButton,
                                        QSpinBox, QWidget)
        dlg = QDialog(self)
        dlg.setWindowTitle("Host CLI editor")
        dlg.setMinimumWidth(700)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        outer = QVBoxLayout(dlg)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(
            "Command run on the Host PC (test station shell).\n"
            "PASS = exit code 0. {{placeholders}} are rendered at run time."))
        edit = QTextEdit()
        edit.setMinimumHeight(120)
        edit.setPlainText(cmd.host_cmd)
        lay.addWidget(edit)
        t_row = QHBoxLayout()
        t_row.addWidget(QLabel("Timeout (seconds, min 1):"))
        t_spin = QSpinBox()
        t_spin.setRange(1, 3600)
        t_spin.setValue(int(cmd.timeout or 30))
        t_row.addWidget(t_spin)
        t_row.addStretch(1)
        lay.addLayout(t_row)
        # M34: body scrolls, OK / Cancel stays outside (always visible)
        apply_scroll_to_dialog(dlg, body)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        ok = QPushButton("OK")
        ok.clicked.connect(dlg.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        outer.addLayout(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        cmd.host_cmd = edit.toPlainText().strip()
        cmd.timeout = float(t_spin.value())
        cmd.wait_enabled = False
        cmd.capture_enabled = False
        cmd.send_enabled = bool(cmd.host_cmd)
        self._save_row_cmd(row, cmd)

    def _edit_sendto_cell(self, row: int, col: int) -> None:
        """SendTo editor: shell command (serial/ssh) or SFTP transfer (ssh only)."""
        if self._is_message_row(row):
            self._edit_message_cell(row)
            return
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                        QTextEdit, QLineEdit, QPushButton,
                                        QLabel, QComboBox, QFileDialog,
                                        QStackedWidget, QCheckBox,
                                        QSpinBox, QWidget, QFormLayout)
        transport = self.cmd_table.cellWidget(row, 1).currentText()
        current_text = self.cmd_table.item(row, col).text() if self.cmd_table.item(row, col) else ""
        cmd = self._row_cmd(row)
        if cmd is not None and cmd.kind == KIND_HOST:
            # ACTION row (host_cli): edit the command run on the Host PC
            # and its timeout - never convert it into a console send row
            self._edit_host_cmd_cell(row, cmd)
            return
        if cmd is not None:
            send_is_off = not cmd.send_enabled
        else:
            send_is_off = current_text.strip() == "(off)"

        dlg = QDialog(self)
        dlg.setWindowTitle("SendTo editor")
        dlg.setMinimumWidth(750)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        outer = QVBoxLayout(dlg)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)

        # Enable Send step checkbox
        send_enable_cb = QCheckBox("Enable Send step")
        send_enable_cb.setChecked(not send_is_off)
        lay.addWidget(send_enable_cb)

        # operation type (only for ssh)
        op_label = QLabel("Operation:")
        op_type = QComboBox()
        op_type.addItems(["shell_command", "sftp_put", "sftp_get"])
        lay.addWidget(op_label)
        lay.addWidget(op_type)

        # stacked widget for different operation types
        stack = QStackedWidget()

        # page 0: shell command
        page_cmd = QWidget()
        lay_cmd = QVBoxLayout(page_cmd)
        lay_cmd.addWidget(QLabel(
            "One line = one command. Multiple lines = multiple commands,\n"
            "sent in order. Newline auto-appended to each command (no need to type \\n)."))
        cmd_edit = QTextEdit()
        cmd_edit.setMinimumHeight(150)
        lay_cmd.addWidget(cmd_edit)
        # send timeout
        from PySide6.QtWidgets import QSpinBox
        timeout_row = QHBoxLayout()
        timeout_row.addWidget(QLabel("Send timeout (seconds, min 1):"))
        send_timeout_spin = QSpinBox()
        send_timeout_spin.setRange(1, 3600)
        send_timeout_spin.setValue(
            int(cmd.send_timeout) if cmd is not None else 4)
        timeout_row.addWidget(send_timeout_spin)
        timeout_row.addStretch(1)
        lay_cmd.addLayout(timeout_row)
        stack.addWidget(page_cmd)

        # page 1: sftp_put
        page_put = QWidget()
        lay_put = QFormLayout(page_put)
        put_local = QLineEdit()
        put_remote = QLineEdit()
        browse_put_local = QPushButton("Browse...")
        def _browse_put():
            path, _ = QFileDialog.getOpenFileName(dlg, "Select file to upload")
            if path:
                put_local.setText(path)
        browse_put_local.clicked.connect(_browse_put)
        lay_put.addRow("Local file:", put_local)
        lay_put.addRow("", browse_put_local)
        lay_put.addRow("Remote path:", put_remote)
        put_timeout = QSpinBox()
        put_timeout.setRange(1, 3600)
        put_timeout.setValue(30)
        lay_put.addRow("Timeout (seconds):", put_timeout)
        stack.addWidget(page_put)

        # page 2: sftp_get
        page_get = QWidget()
        lay_get = QFormLayout(page_get)
        get_remote = QLineEdit()
        get_local = QLineEdit()
        browse_get_local = QPushButton("Browse...")
        def _browse_get():
            path, _ = QFileDialog.getSaveFileName(dlg, "Save file as")
            if path:
                get_local.setText(path)
        browse_get_local.clicked.connect(_browse_get)
        lay_get.addRow("Remote file:", get_remote)
        lay_get.addRow("Local save:", get_local)
        lay_get.addRow("", browse_get_local)
        get_timeout = QSpinBox()
        get_timeout.setRange(1, 3600)
        get_timeout.setValue(30)
        lay_get.addRow("Timeout (seconds):", get_timeout)
        stack.addWidget(page_get)

        lay.addWidget(stack)

        # show/hide op type based on transport
        if transport == "serial":
            op_type.setVisible(False)
            stack.setCurrentIndex(0)
        else:
            op_type.setVisible(True)

        def _on_op_changed(idx):
            stack.setCurrentIndex(idx)
        op_type.currentIndexChanged.connect(_on_op_changed)

        # restore from the row's full command, fall back to cell text
        if cmd is not None and cmd.kind in ("sftp_put", "sftp_get"):
            if cmd.kind == "sftp_put":
                op_type.setCurrentIndex(1)
                put_local.setText(cmd.local)
                put_remote.setText(cmd.remote)
                put_timeout.setValue(int(cmd.send_timeout))
            else:
                op_type.setCurrentIndex(2)
                get_remote.setText(cmd.remote)
                get_local.setText(cmd.local)
                get_timeout.setValue(int(cmd.send_timeout))
        elif current_text.startswith("[PUT] "):
            op_type.setCurrentIndex(1)
            rest = current_text[6:]  # after "[PUT] "
            if " -> " in rest:
                put_local.setText(rest.split(" -> ")[0])
                put_remote.setText(rest.split(" -> ")[1])
        elif current_text.startswith("[GET] "):
            op_type.setCurrentIndex(2)
            rest = current_text[6:]  # after "[GET] "
            if " -> " in rest:
                get_remote.setText(rest.split(" -> ")[0])
                get_local.setText(rest.split(" -> ")[1])
        else:
            op_type.setCurrentIndex(0)
            cmd_edit.setPlainText(cmd.send if cmd is not None
                                  else current_text)

        # M34: body scrolls, OK / Cancel stays outside (always visible)
        apply_scroll_to_dialog(dlg, body)
        # buttons
        btn_row = QHBoxLayout()
        ok = QPushButton("OK")
        ok.clicked.connect(dlg.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        outer.addLayout(btn_row)

        if dlg.exec() == QDialog.Accepted:
            idx = op_type.currentIndex()
            if cmd is None:
                cmd = self._get_row_cmd(row)
            if not send_enable_cb.isChecked():
                # Send disabled
                cmd.send_enabled = False
                cmd.send = ""
                self._save_row_cmd(row, cmd)
                return
            cmd.send_enabled = True
            if idx == 0:
                # shell command (one or many lines; newline auto-appended)
                cmd.kind = "send"
                cmd.send = cmd_edit.toPlainText()
                cmd.send_timeout = float(send_timeout_spin.value())
                cmd.local = ""
                cmd.remote = ""
            elif idx == 1:
                # sftp_put: Wait/Capture are not used for a file transfer
                cmd.kind = "sftp_put"
                cmd.local = put_local.text()
                cmd.remote = put_remote.text()
                cmd.send_timeout = float(put_timeout.value())
                cmd.wait_enabled = False
                cmd.expect_pass = ""
                cmd.capture_enabled = False
                cmd.expect_fail = ""
            else:
                # sftp_get
                cmd.kind = "sftp_get"
                cmd.remote = get_remote.text()
                cmd.local = get_local.text()
                cmd.send_timeout = float(get_timeout.value())
                cmd.wait_enabled = False
                cmd.expect_pass = ""
                cmd.capture_enabled = False
                cmd.expect_fail = ""
            self._save_row_cmd(row, cmd)

    # -------------------------------------------------- RF step dialogs
    #: M50 per-sub-test owned fields: (key, label, kind, reference, default)
    _RF_FIELDS = {
        ("wifi", "scan"): (
            ("ap_ssid", "AP SSID", "text",
             "equipment.peripherals.wifi.ap_ssid", ""),
            ("dut_ssid", "DUT SSID", "text",
             "equipment.dut.wifi.ssid", ""),
            ("rssi_min", "AP RSSI min (dBm)", "int", None, -70),
            ("dut_rssi_min", "DUT RSSI min (dBm)", "int", None, -70),
            ("scan_via", "Scan via (host / dut_console)", "text", None,
             "host"),
            ("timeout_s", "Timeout", "int", None, 15),
        ),
        ("wifi", "ping"): (
            ("target", "Target IP", "text",
             "equipment.peripherals.router.dut_ip", ""),
            ("count", "Ping count", "int", None, 20),
            ("timeout_s", "Timeout", "int", None, 15),
        ),
        ("wifi", "iperf"): (
            ("target", "Host server IP", "text",
             "equipment.peripherals.wifi.host_ip", ""),
            ("tool", "Tool (iperf2 / iperf3)", "text", None, "iperf3"),
            ("min_mbps", "Min throughput (Mbps)", "float", None, 10.0),
            ("duration", "Duration", "int", None, 10),
            ("timeout_s", "Timeout", "int", None, 15),
        ),
        ("bluetooth", "rssi"): (
            # M50: the step name owns the YAML ``name`` key, so the DUT
            # Bluetooth name parameter is stored as ``bt_name``.
            ("bt_name", "DUT BT name", "text",
             "equipment.dut.bluetooth.name", ""),
            ("addr", "DUT BD address", "text",
             "equipment.dut.bluetooth.bd_addr", ""),
            ("rssi_min", "RSSI min", "int", None, -70),
            ("timeout_s", "Timeout", "int", None, 15),
        ),
        ("bluetooth", "pair"): (
            ("bt_name", "DUT BT name", "text",
             "equipment.dut.bluetooth.name", ""),
            ("script", "Pair script", "text", None, "bt_conn.sh"),
            ("l2ping", "L2CAP ping count", "int", None, 0),
            ("timeout_s", "Timeout", "int", None, 15),
        ),
        ("bluetooth", "tone"): (
            ("file", "Tone wav", "file", None, DEFAULT_TONE_WAV),
            ("start_s", "Start", "float", None, 0.0),
            ("end_s", "End", "float", None, 6.0),
        ),
    }

    def _rf_family(self, cmd: ConsoleCommand) -> tuple:
        """(family, rf_subtest) for an RF reference row, else ("", "")."""
        kind = str(getattr(cmd, "kind", "") or "")
        if kind == KIND_WIFI_TEST:
            return ("wifi", str(getattr(cmd, "rf_subtest", "") or ""))
        if kind == KIND_BT_TEST:
            return ("bluetooth", str(getattr(cmd, "rf_subtest", "") or ""))
        return ("", "")

    def _is_rf_ref_row(self, cmd: ConsoleCommand) -> bool:
        return bool(self._rf_family(cmd)[0])

    def _rf_summary(self, cmd: ConsoleCommand) -> str:
        """Compact cmd/params summary built from the step's own params
        (shared values shown as their EFFECTIVE referenced value)."""
        family, subtest = self._rf_family(cmd)
        p = dict(cmd.step_params or {})
        refs, ovr = cmd.refs or {}, cmd.overrides or {}

        def val(key, default=""):
            eff = self._effective(refs, ovr, key)
            return default if eff in (None, "") else eff

        if family == "wifi":
            if subtest == "scan":
                text = (f"AP={val('ap_ssid', '(AP SSID ref)')}, "
                        f"RSSI\u2265{p.get('rssi_min', -70)} dBm")
                dut = val("dut_ssid")
                if dut:
                    text += (f"; DUT={dut}, "
                             f"RSSI\u2265{p.get('dut_rssi_min', -70)} dBm")
                return text
            if subtest == "ping":
                return (f"target={val('target', '(router DUT IP ref)')}, "
                        f"ping\u00d7{p.get('count', 20)}, "
                        f"{p.get('timeout_s', 15)}s")
            if subtest == "iperf":
                return (f"{p.get('tool', 'iperf3')} "
                        f"\u2265{_fmt_num(p.get('min_mbps', 10))} Mbps, "
                        f"{p.get('duration', 10)}s")
            return ""
        if family == "bluetooth":
            if subtest == "rssi":
                return (f"DUT BT name={val('bt_name', '(BT name ref)')}, "
                        f"RSSI\u2265{p.get('rssi_min', -70)}")
            if subtest == "pair":
                return (f"{p.get('script', 'bt_conn.sh') or 'bt_conn.sh'}, "
                        f"L2CAP\u00d7{p.get('l2ping', 0)}")
            if subtest == "tone":
                tone = str(p.get("file") or DEFAULT_TONE_WAV)
                return (f"{os.path.basename(tone)}, "
                        f"{float(p.get('start_s', 0.0)):.1f}-"
                        f"{float(p.get('end_s', 6.0)):.1f}s")
            return ""
        return ""

    def _rf_timeout_text(self, cmd: ConsoleCommand) -> str:
        p = dict(cmd.step_params or {})
        if "timeout_s" in p:
            return f"{int(p.get('timeout_s') or 0)}s"
        return "-"

    def _edit_rf_row(self, row: int) -> None:
        """M50 per-test config dialog for an RF reference row.

        Every field shows its runtime reference (human label) and the
        EFFECTIVE value resolved from the current Equipment configuration,
        plus an override box (empty = use the referenced value).  Fields
        without a reference are owned by the step itself."""
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox,
                                        QFileDialog, QFormLayout,
                                        QLabel, QLineEdit, QVBoxLayout,
                                        QHBoxLayout, QPushButton)
        from mtkgui.engine.ref_resolver import describe
        cmd = self._get_row_cmd(row)
        family, subtest = self._rf_family(cmd)
        spec = self._RF_FIELDS.get((family, subtest))
        if not spec:
            return
        params = dict(cmd.step_params or {})
        refs = dict(cmd.refs or {})
        overrides = dict(cmd.overrides or {})
        dlg = QDialog(self)
        dlg.setWindowTitle(
            f"{step_type_label(cmd)} step config")
        dlg.setMinimumWidth(680)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        outer = QVBoxLayout(dlg)
        body = QWidget()
        form = QFormLayout(body)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        editors: dict = {}
        tone_parts = {}
        for key, label, kind, ref_path, default in spec:
            if ref_path:
                ref_line = QLabel("")
                ref_line.setStyleSheet("color: #6b7280;")
                eff_line = QLabel("")
                eff_line.setStyleSheet("color: #111827;")
                override = QLineEdit(str(overrides.get(key) or ""))
                override.setPlaceholderText(
                    "override (empty = use the referenced Equipment value)")
                override.textChanged.connect(
                    lambda _t, e=eff_line, r=ref_path, o=override:
                    e.setText(f"effective: {self._effective({'v': r}, {'v': o.text()}, 'v') or '(not set)'}"))
                eff = self._effective({key: ref_path}, overrides, key)
                if key not in refs:
                    refs[key] = ref_path
                ref_line.setText(f"ref: {ref_path} - "
                                 f"{describe(ref_path)}")
                eff_line.setText(f"effective: {eff or '(not set)'}")
                form.addRow(f"{label}:", ref_line)
                form.addRow("", eff_line)
                form.addRow("", override)
                editors[key] = override
                continue
            if kind in ("int", "float"):
                spin = QDoubleSpinBox()
                spin.setDecimals(1 if kind == "float" else 0)
                spin.setRange(-1_000_000.0, 1_000_000.0)
                spin.setValue(float(params.get(key, default) or 0))
                editors[key] = spin
                form.addRow(f"{label}:", spin)
            else:
                edit = QLineEdit(str(params.get(key, default) or ""))
                editors[key] = edit
                if kind == "file":
                    row_lay = QHBoxLayout()
                    row_lay.addWidget(edit, 1)
                    browse = QPushButton("Browse...")

                    def _browse(_f=False, e=edit) -> None:
                        picked, _hint = QFileDialog.getOpenFileName(
                            self, "Tone wav", e.text() or "resources/music")
                        if picked:
                            e.setText(picked)

                    browse.clicked.connect(_browse)
                    row_lay.addWidget(browse)
                    form.addRow(f"{label}:", row_lay)
                else:
                    form.addRow(f"{label}:", edit)
        # M45: BT Tone keeps the local Start/End segment preview
        if (family, subtest) == ("bluetooth", "tone"):
            slider = _ToneRangeSlider(float(params.get("end_s", 6.0) or 6.0))
            slider.set_values(float(params.get("start_s", 0.0) or 0.0),
                              float(params.get("end_s", 6.0) or 6.0))
            form.addRow("Segment:", slider)
            preview = _TonePreview(self)
            meter = QProgressBar()
            meter.setRange(0, 100)
            play = QPushButton("Play")
            stop_btn = QPushButton("Stop")

            def _play(_f=False) -> None:
                path = (editors["file"].text().strip()
                        or DEFAULT_TONE_WAV)
                preview.play(path, slider.start_s(), slider.end_s())

            play.clicked.connect(_play)
            stop_btn.clicked.connect(preview.stop)
            preview.level.connect(meter.setValue)
            preview.finished.connect(lambda: meter.setValue(0))
            prow = QHBoxLayout()
            prow.addWidget(play)
            prow.addWidget(stop_btn)
            prow.addWidget(meter, 1)
            form.addRow("Preview:", prow)
            tone_parts = {"slider": slider, "preview": preview}
        apply_scroll_to_dialog(dlg, body)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)
        if dlg.exec():
            for key, label, kind, ref_path, default in spec:
                if ref_path:
                    text = editors[key].text().strip()
                    if text:
                        overrides[key] = text
                    else:
                        overrides.pop(key, None)
                    continue
                widget = editors[key]
                if kind == "text":
                    params[key] = widget.text().strip()
                elif kind == "file":
                    params[key] = widget.text().strip() or default
                else:
                    value = widget.value()
                    params[key] = (float(value) if kind == "float"
                                   else int(value))
            if tone_parts:
                params["start_s"] = float(tone_parts["slider"].start_s())
                params["end_s"] = float(tone_parts["slider"].end_s())
                tone_parts["preview"].stop()
            cmd.step_params = params
            cmd.refs = refs
            cmd.overrides = overrides or None
            self._save_row_cmd(row, cmd)
        dlg.deleteLater()

    # ------------------------------------------------------- helpers
    # ------------------------------------------------- row model (UserRole)
    def _row_cmd(self, r: int):
        """The raw ConsoleCommand stored on the row (or None)."""
        item = self.cmd_table.item(r, _COL_HASH)
        return item.data(_CMD_ROLE) if item is not None else None

    def _set_cell(self, r: int, col: int, text: str,
                  editable: bool = True) -> None:
        item = self.cmd_table.item(r, col)
        if item is None:
            item = QTableWidgetItem()
            self.cmd_table.setItem(r, col, item)
        item.setText(text)
        if editable:
            item.setFlags(item.flags() | Qt.ItemIsEditable)
        else:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def _renumber_rows(self) -> None:
        """Refresh the read-only ``#`` column (row order = execution
        order in the merged table)."""
        for r in range(self.cmd_table.rowCount()):
            self._set_cell(r, _COL_HASH, str(r + 1), editable=False)

    def _capture_summary(self, cmd: ConsoleCommand) -> str:
        """Compact text for the Capture column (unified Expected /
        Unexpected)."""
        exp = cmd.capture_expected or ""
        unexp = cmd.capture_unexpected or ""
        if exp and unexp:
            return f'+ "{exp}"  - "{unexp}"'
        if exp:
            return f'+ "{exp}"'
        if unexp:
            return f'- "{unexp}"'
        return "(off)"

    def _render_row_cmd(self, r: int, cmd: ConsoleCommand) -> None:
        """Refresh the visible 8-column summary from cmd."""
        self._set_cell(r, _COL_HASH, str(r + 1), editable=False)
        self._set_cell(r, _COL_STEP, cmd.name)
        typ = step_type_label(cmd)
        self._set_cell(r, _COL_TYPE, typ, editable=False)
        if self._is_rf_ref_row(cmd):
            self._set_cell(r, _COL_WAIT, "\u2014", editable=False)
            self._set_cell(r, _COL_SEND, "\u2014", editable=False)
            self._set_cell(r, _COL_CAPTURE, "\u2014", editable=False)
            self._set_cell(r, _COL_TIMEOUT, self._rf_timeout_text(cmd),
                           editable=False)
            self._set_cell(r, _COL_CMD, self._rf_summary(cmd),
                           editable=False)
            return
        if cmd.kind == KIND_OP:
            self._set_cell(r, _COL_WAIT, "", editable=False)
            self._set_cell(r, _COL_SEND, "", editable=False)
            self._set_cell(r, _COL_CAPTURE, "", editable=False)
            self._set_cell(r, _COL_TIMEOUT,
                           f"{int(cmd.op_timeout_ms or 0)}ms",
                           editable=False)
            self._set_cell(r, _COL_CMD, _op_summary(cmd.op_params),
                           editable=False)
            return
        if cmd.kind == KIND_DELAY:
            self._set_cell(r, _COL_WAIT, "", editable=False)
            self._set_cell(r, _COL_SEND, "", editable=False)
            self._set_cell(r, _COL_CAPTURE, "", editable=False)
            # M42: Delay has no timeout input - the cell is read-only 0
            self._set_cell(r, _COL_TIMEOUT, "0", editable=False)
            self._set_cell(r, _COL_CMD, f"{int(cmd.wait_ms or 0)} ms",
                           editable=False)
            return
        if cmd.kind == KIND_MESSAGE:
            self._set_cell(
                r, _COL_WAIT,
                cmd.expect_pass if (cmd.wait_enabled and cmd.expect_pass)
                else "(off)", editable=False)
            if cmd.dialog_style == DIALOG_OK:
                self._set_cell(r, _COL_SEND, "(off)", editable=False)
                self._set_cell(
                    r, _COL_TIMEOUT,
                    (f"W:{int(cmd.wait_timeout)}s"
                     if cmd.wait_enabled else
                     (f"T:{int(cmd.timeout)}s" if cmd.timeout > 0
                      else "-")),
                    editable=False)
            else:
                self._set_cell(
                    r, _COL_SEND, f"YES='{cmd.send_yes}' / NO='{cmd.send_no}'",
                    editable=False)
                parts = []
                if cmd.wait_enabled:
                    parts.append(f"W:{int(cmd.wait_timeout)}s")
                if cmd.timeout > 0:
                    parts.append(f"S:{int(cmd.timeout)}s")
                self._set_cell(r, _COL_TIMEOUT, " ".join(parts) or "-",
                               editable=False)
            self._set_cell(r, _COL_CAPTURE, self._capture_summary(cmd),
                           editable=False)
            self._set_cell(r, _COL_CMD, cmd.confirm_message or "",
                           editable=False)
            return
        if cmd.kind in (KIND_SERIAL_PUT, KIND_SERIAL_PULL):
            self._set_cell(r, _COL_WAIT, "", editable=False)
            self._set_cell(r, _COL_SEND, "", editable=False)
            self._set_cell(r, _COL_CAPTURE, "", editable=False)
            self._set_cell(r, _COL_TIMEOUT,
                           f"{int(cmd.timeout or 0)}s", editable=False)
            arrow = ("%s -> %s" % (cmd.local or "(no source)",
                                   cmd.remote or "(no target)")
                     if cmd.kind == KIND_SERIAL_PUT
                     else "%s -> %s" % (cmd.remote or "(no source)",
                                        cmd.local or "(no target)"))
            baud = (f" @{int(cmd.serial_baud)}" if cmd.serial_baud else "")
            self._set_cell(r, _COL_CMD, f"{arrow}{baud}", editable=False)
            return
        if cmd.kind == KIND_FLASH_GUI:
            self._set_cell(r, _COL_WAIT, "", editable=False)
            self._set_cell(r, _COL_SEND, "", editable=False)
            self._set_cell(r, _COL_CAPTURE, "", editable=False)
            self._set_cell(r, _COL_TIMEOUT, "-", editable=False)
            self._set_cell(r, _COL_CMD,
                           cmd.flash_gui_path or "(no path)",
                           editable=False)
            return
        if typ in (STEP_TYPE_SFTP_PUT, STEP_TYPE_SFTP_GET):
            self._set_cell(r, _COL_WAIT, "", editable=False)
            self._set_cell(r, _COL_SEND, "", editable=False)
            self._set_cell(r, _COL_CAPTURE, self._capture_summary(cmd),
                           editable=False)
            self._set_cell(r, _COL_TIMEOUT,
                           f"S:{int(cmd.send_timeout or 0)}s",
                           editable=False)
            self._set_cell(
                r, _COL_CMD,
                (f"{cmd.local} -> {cmd.remote}"
                 if typ == STEP_TYPE_SFTP_PUT
                 else f"{cmd.remote} -> {cmd.local}"),
                editable=False)
            return
        if typ == STEP_TYPE_CONSOLE_CLI:
            self._set_cell(r, _COL_WAIT, "", editable=False)
            self._set_cell(r, _COL_SEND, "", editable=False)
            self._set_cell(r, _COL_CAPTURE, self._capture_summary(cmd),
                           editable=False)
            self._set_cell(r, _COL_TIMEOUT, f"{int(cmd.timeout or 0)}s",
                           editable=False)
            self._set_cell(r, _COL_CMD,
                           cmd.host_cmd_windows or cmd.host_cmd,
                           editable=False)
            return
        # Console_serial / Console_ssh interact rows
        self._set_cell(r, _COL_WAIT,
                       cmd.expect_pass if cmd.wait_enabled else "(off)")
        self._set_cell(r, _COL_SEND,
                       cmd.send if cmd.send_enabled else "(off)")
        self._set_cell(r, _COL_CAPTURE, self._capture_summary(cmd),
                       editable=False)
        parts = []
        if cmd.wait_enabled:
            parts.append(f"W:{int(cmd.wait_timeout)}s")
        if cmd.send_enabled:
            parts.append(f"S:{int(cmd.send_timeout)}s")
        if cmd.capture_enabled:
            parts.append(f"C:{int(cmd.timeout)}s")
        self._set_cell(r, _COL_TIMEOUT, " ".join(parts) if parts else "-",
                       editable=False)
        self._set_cell(r, _COL_CMD, "", editable=False)

    def _save_row_cmd(self, r: int, cmd: ConsoleCommand) -> None:
        """Persist the full command on the row and re-render."""
        item = self.cmd_table.item(r, _COL_HASH)
        if item is None:
            item = QTableWidgetItem()
            self.cmd_table.setItem(r, _COL_HASH, item)
        item.setData(_CMD_ROLE, cmd)
        self._render_row_cmd(r, cmd)

    def _get_row_cmd(self, r: int) -> ConsoleCommand:
        """Return the row's command; overlay the editable Step cell."""
        item = self.cmd_table.item(r, _COL_HASH)
        cmd = item.data(_CMD_ROLE) if item is not None else None
        if cmd is None:
            return ConsoleCommand()
        name_item = self.cmd_table.item(r, _COL_STEP)
        if name_item is not None:
            cmd.name = name_item.text()
        return cmd

    # ------------------------------------------------------- state in/out
    def set_available_ops(self, available_ops: set[str] | None) -> None:
        """M37: restrict the Operation row editor / M43 submenu entries
        to the operations whose resource is configured (None = all
        usable)."""
        self._available_ops = (set(available_ops)
                               if available_ops is not None else None)
        self._sync_op_submenu()


    def _report_ref_errors(self) -> None:
        """Report unresolvable references carried by the loaded rows."""
        from mtkgui.engine.ref_resolver import validate_refs
        data = []
        for r in range(self.cmd_table.rowCount()):
            cmd = self._get_row_cmd(r)
            if cmd.refs:
                data.append({"name": cmd.name, "ref": dict(cmd.refs)})
        errors = validate_refs(data, self.equipment_node()) if data else []
        if errors:
            self.task_log.emit(
                "ERROR", "FCT step references: " + "; ".join(errors[:10]))

    def _equipment_value(self, path: str, default=""):
        """Current Equipment value of one reference (default when unset)."""
        from mtkgui.engine.ref_resolver import RefError, resolve
        try:
            value = resolve(path, self.equipment_node())
        except RefError:
            return default
        return default if value in (None, "") else value

    def _default_refs(self, cmd: ConsoleCommand) -> dict:
        """Runtime references a step of this type uses by default (M50)."""
        label = step_type_label(cmd)
        if label == STEP_TYPE_CONSOLE_SERIAL:
            return {"port": "equipment.dut.console.port",
                    "baud": "equipment.dut.console.baud",
                    "parity": "equipment.dut.console.parity"}
        if label in (STEP_TYPE_CONSOLE_SSH, STEP_TYPE_SFTP_PUT,
                     STEP_TYPE_SFTP_GET):
            return {"host": "equipment.dut.ssh.ip",
                    "username": "equipment.dut.ssh.username",
                    "password": "equipment.dut.ssh.password"}
        if label == STEP_TYPE_FLASH_GUI:
            return {"jlink": "equipment.jlink.executable"}
        family, subtest = self._rf_family(cmd)
        spec = self._RF_FIELDS.get((family, subtest)) or ()
        return {key: ref for key, _label, _kind, ref, _default in spec
                if ref}

    def _runtime_node(self) -> dict:
        """The non-referenced shared settings the engine still needs
        (script folders / newline / Wi-Fi interface / setup spine)."""
        c = copy.deepcopy(self._console_cfg)
        wifi = copy.deepcopy(self._wifi_cfg)
        interface = ""
        if wifi is not None:
            interface = str(wifi.interface or "")
        interface = interface or str(
            self._equipment_value("equipment.dut.wifi.interface", "") or "")
        driver = str(wifi.driver_load_cmd or "") if wifi is not None else ""
        return {
            "console": {
                "newline": c.newline,
                "inter_cmd_delay_ms": int(c.inter_cmd_delay_ms),
                "scripts_local_dir": c.scripts_local_dir,
                "scripts_remote_dir": c.scripts_remote_dir,
                "pull_remote_dir": c.pull_remote_dir,
                "pull_local_dir": c.pull_local_dir,
                "serial_deploy": bool(c.serial_deploy),
                "serial_deploy_files": [dict(f) for f
                                        in c.serial_deploy_files],
            },
            "wifi": {"interface": interface,
                     "driver_load_cmd": driver},
            "bluetooth": {},
            "setup": self._setup_cfg.to_dict(),
        }

    def set_values(self, params: dict) -> None:
        """Restore from the module params.

        M50: the new ``fct_steps_yaml`` schema is the only saved source.
        An OLD ``fct_test_config_yaml`` (Console / Wi-Fi / Bluetooth
        pages) is imported best effort so existing projects keep their
        behaviour; unresolvable references are reported, never rewritten.
        """
        params = params or {}
        # M46: the current project name (project assets / outbox Browse
        # defaults); absent in most module params -> bundled template.
        self._project_name = str(params.get("project_name")
                                 or params.get("project") or "")
        self._legacy = {k: v for k, v in params.items()
                        if k not in ("fct_test_config_yaml",
                                     "fct_sequence_cases_yaml",
                                     "fct_steps_yaml")}
        self.cmd_table.setRowCount(0)
        self._console_cfg = ConsoleCfg()
        self._wifi_cfg = None
        self._bt_cfg = None
        text = str(params.get("fct_steps_yaml") or "")
        if text.strip():
            try:
                node = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                node = {}
                self.task_log.emit("ERROR",
                                   "fct_steps_yaml: invalid YAML "
                                   "- defaults loaded")
            fct = (node.get("fct") if isinstance(node, dict) else None) or {}
            runtime = fct.get("runtime") or {}
            self._guard = True
            try:
                self.dut_type.setCurrentText(
                    str(fct.get("dut_type") or "linux"))
                self._console_cfg = _cfg_from_dict(
                    ConsoleCfg, runtime.get("console"))
                self._wifi_cfg = _cfg_from_dict(
                    WifiCfg, runtime.get("wifi"))
                self._bt_cfg = _cfg_from_dict(
                    BluetoothCfg, runtime.get("bluetooth"))
                self._setup_cfg = FctSetupCfg.from_dict(
                    runtime.get("setup"))
                for step in (fct.get("steps") or []):
                    if not isinstance(step, dict):
                        continue
                    cmd = _command_from_step_dict(step)
                    if cmd is not None:
                        self._insert_row(cmd)
            finally:
                self._guard = False
            self._renumber_rows()
            self._report_ref_errors()
            return
        # ---- legacy import: OLD fct_test_config_yaml -> rows + runtime ----
        text = str(params.get("fct_test_config_yaml") or "")
        cases = _sequence_cases_from_param(
            params.get("fct_sequence_cases_yaml"))
        if not text.strip() and not cases:
            self._renumber_rows()
            return
        node = {}
        if text.strip():
            try:
                node = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                node = {}
                self.task_log.emit("ERROR",
                                   "fct_test_config_yaml: invalid YAML "
                                   "- defaults loaded")
        cfg = FctTestConfig.from_dict(
            (node.get("fct_test_config") if isinstance(node, dict)
             else None) or {})
        self._guard = True
        try:
            self.dut_type.setCurrentText(cfg.dut_type)
            # keep the full loaded console node: the remaining keys
            # (newline, inter-command delay, serial_deploy) round-trip
            # untouched (M22c)
            self._console_cfg = copy.deepcopy(cfg.console)
            self._wifi_cfg = copy.deepcopy(cfg.wifi)
            self._bt_cfg = copy.deepcopy(cfg.bluetooth)
            self._setup_cfg = copy.deepcopy(cfg.setup)
            for case in cases:
                self._insert_row(_case_to_op_command(case))
            for cmd in cfg.console.test_commands:
                self._insert_row(cmd)
            self._import_legacy_rf_rows(cfg)
        finally:
            self._guard = False
        self._renumber_rows()
        self._report_ref_errors()

    def _import_legacy_rf_rows(self, cfg) -> None:
        """M50 legacy import: an ENABLED Wi-Fi / Bluetooth sub-test that
        has no explicit reference row keeps running (old
        ``build_fct_steps`` appended it after the console body).

        The M49b row is added in the old fixed order, carrying the OLD
        snapshot as a step-level override (the shared value itself now
        lives on the Equipment page)."""
        present = {self._rf_family(self._get_row_cmd(r))
                   for r in range(self.cmd_table.rowCount())}
        w, b = cfg.wifi, cfg.bluetooth

        def add(label, family, subtest, params, overrides):
            if (family, subtest) in present:
                return
            cmd = console_command_for_label(label)
            cmd.step_params = dict(params)
            cmd.refs = self._default_refs(cmd) or None
            merged = {key: str(value).strip()
                      for key, value in overrides.items()
                      if str(value or "").strip()}
            cmd.overrides = merged or None
            self._insert_row(cmd)
            present.add((family, subtest))

        if w.scan_enabled:
            add(STEP_TYPE_WIFI_SCAN, "wifi", "scan",
                {"rssi_min": int(w.rssi_min),
                 "dut_rssi_min": int(w.dut_rssi_min),
                 "scan_via": str(w.scan_via or "host"),
                 "timeout_s": int(float(w.scan_timeout))},
                {"ap_ssid": w.ap_ssid, "dut_ssid": w.dut_ssid})
        if w.ping_enabled:
            add(STEP_TYPE_WIFI_PING, "wifi", "ping",
                {"count": int(w.ping_count),
                 "timeout_s": int(float(w.ping_timeout))},
                {"target": w.ap_ip})
        if w.iperf_enabled:
            add(STEP_TYPE_WIFI_IPERF, "wifi", "iperf",
                {"tool": str(w.iperf_tool or "iperf3"),
                 "min_mbps": float(w.iperf_min_mbps),
                 "duration": int(w.iperf_duration),
                 "timeout_s": int(float(w.iperf_timeout))},
                {"target": w.iperf_server_ip})
        if b.rssi_enabled:
            add(STEP_TYPE_BT_RSSI, "bluetooth", "rssi",
                {"rssi_min": int(b.rssi_min),
                 "timeout_s": int(float(b.rssi_timeout))},
                {"bt_name": b.expected_name, "addr": b.expected_addr})
        if b.pair_enabled:
            add(STEP_TYPE_BT_PAIR, "bluetooth", "pair",
                {"script": str(b.bt_pair_script or ""),
                 "l2ping": int(b.l2ping_count),
                 "timeout_s": int(float(b.pair_timeout))},
                {"bt_name": b.expected_name})
        if b.tone_enabled:
            add(STEP_TYPE_BT_TONE, "bluetooth", "tone",
                {"file": str(b.test_tone or DEFAULT_TONE_WAV),
                 "start_s": float(b.tone_start_s),
                 "end_s": float(b.tone_end_s)}, {})
        # post-RF teardown rows (old ``console.post_rf_commands``) run
        # AFTER the RF sections and even on an abort; they stay rows on
        # the single page, tagged so the emit puts them back in place.
        for old in (cfg.console.post_rf_commands or []):
            cmd = copy.deepcopy(old)
            cmd.step_params = dict(cmd.step_params or {})
            cmd.step_params["teardown"] = True
            if not cmd.refs:
                cmd.refs = self._default_refs(cmd) or None
            self._insert_row(cmd)

    def values(self) -> dict:
        """Module params: the new M50 ``fct`` step schema ONLY.

        Each row carries its own parameters inline plus optional ``ref``
        (runtime reference into ``equipment:``) and ``override`` maps.
        Shared equipment values are never copied into the step unless the
        operator sets an override.
        """
        from mtkgui.engine.ref_resolver import validate_refs
        steps = []
        for r in range(self.cmd_table.rowCount()):
            cmd = self._get_row_cmd(r)
            refs = dict(cmd.refs or {})
            for key, path in self._default_refs(cmd).items():
                refs.setdefault(key, path)
            cmd.refs = refs or None
            steps.append(_step_dict_from_command(cmd))
        ref_steps = [s for s in steps if isinstance(s.get("ref"), dict)]
        errors = []
        try:
            errors = validate_refs(ref_steps, self.equipment_node())
        except Exception as exc:                  # noqa: BLE001 - never crash
            errors = [str(exc)]
        if errors:
            self.task_log.emit(
                "ERROR", "FCT step references: " + "; ".join(errors[:10]))
        node = {"fct": {"dut_type": self.dut_type.currentText(),
                        "steps": steps,
                        "runtime": self._runtime_node()}}
        out = dict(self._legacy)
        out["fct_steps_yaml"] = yaml.safe_dump(
            node, sort_keys=False, allow_unicode=True)
        return out


def _rf_family(cmd: ConsoleCommand) -> tuple:
    """(family, rf_subtest) of an RF reference row, else ("", "")."""
    kind = str(getattr(cmd, "kind", "") or "")
    if kind == KIND_WIFI_TEST:
        return ("wifi", str(getattr(cmd, "rf_subtest", "") or ""))
    if kind == KIND_BT_TEST:
        return ("bluetooth", str(getattr(cmd, "rf_subtest", "") or ""))
    return ("", "")


def _cfg_from_dict(cls, data):
    """Build a config dataclass from a stored dict (unknown keys dropped)."""
    from dataclasses import fields as _fields
    allowed = {f.name for f in _fields(cls)}
    return cls(**{k: v for k, v in (data or {}).items() if k in allowed})


def _step_field_names() -> set:
    """ConsoleCommand fields stored inline in the new fct.steps schema."""
    from dataclasses import fields as _fields
    return {f.name for f in _fields(ConsoleCommand)} - {
        "kind", "name", "step_params", "refs", "overrides"}


def _step_dict_from_command(cmd: ConsoleCommand) -> dict:
    """One row -> the new ``fct.steps`` entry.

    ``type`` carries the user-facing Type label (``Wifi_Ping`` ...),
    every step-owned parameter is inline, and the shared equipment
    references travel in ``ref`` / ``override``.
    """
    d = cmd.to_dict()
    params = dict(d.get("step_params") or {})
    # M50 bug fix: ``type`` / ``name`` are schema keys - a step-owned
    # parameter of the same name must never overwrite them.
    params.pop("type", None)
    params.pop("name", None)
    out = dict(params)
    out["type"] = step_type_label(cmd)
    out["name"] = str(cmd.name or "")
    for key, value in d.items():
        if key in ("kind", "name", "step_params", "refs", "overrides"):
            continue
        out[key] = value
    if d.get("refs"):
        out["ref"] = dict(d["refs"])
    if d.get("overrides"):
        out["override"] = dict(d["overrides"])
    return out


def _command_from_step_dict(step: dict):
    """A new ``fct.steps`` entry -> the row model (None for unknown type)."""
    from mtkgui.engine.fct_test_config import normalize_step_type_label
    data = dict(step or {})
    label = normalize_step_type_label(str(data.pop("type", "") or ""))
    # M50 bug fix: Delay / Serial Push / Serial Pull are valid step kinds
    # that are NOT in the Add-menu Type tuple - they must round-trip.
    valid = set(STEP_TYPE_LABELS) | {STEP_TYPE_DELAY,
                                     STEP_TYPE_SERIAL_PUT,
                                     STEP_TYPE_SERIAL_PULL}
    if not label or label not in valid:
        return None
    name = str(data.pop("name", "") or "")
    refs = dict(data.pop("ref", None) or {})
    overrides = dict(data.pop("override", None) or {})
    cmd = console_command_for_label(label, name)
    known = _step_field_names()
    params = {}
    for key, value in data.items():
        if key in known and hasattr(cmd, key):
            setattr(cmd, key, value)
        else:
            params[key] = value
    cmd.step_params = params or None
    cmd.refs = refs or None
    cmd.overrides = overrides or None
    return cmd
