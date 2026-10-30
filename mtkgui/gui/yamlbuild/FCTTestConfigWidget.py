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
* Bluetooth tab — three independently enabled sub-tests, each with
  its own timeout: 1. RSSI discovery (both DUT kinds), 2. Pair &
  connect with optional L2CAP ping (Linux only), 3. Tone/music over
  A2DP with GUI confirm (Linux only, Host source -> DUT sink);
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

import yaml
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
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
    KIND_OP,
    KIND_WIFI_TEST,
    KIND_BT_TEST,
    KIND_FLASH_GUI,
    KIND_DELAY,
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
    STEP_TYPE_WIFI_SCAN,
    STEP_TYPE_WIFI_PING,
    STEP_TYPE_WIFI_IPERF,
    STEP_TYPE_BT_RSSI,
    STEP_TYPE_BT_PAIR,
    STEP_TYPE_BT_TONE,
    ConsoleCfg,
    ConsoleCommand,
    FctSetupCfg,
    FctTestConfig,
    console_command_for_label,
    rf_subtest_for_label,
    step_type_label,
)
from mtkgui.engine import DIO_OPS, FIXTURE_OPS, INSTRUMENT_OPS, OP_STEPS
from mtkgui.engine import host_platform
from mtkgui.engine.steps import op_summary as _op_summary
from mtkgui.gui.dialog_sizing import apply_scroll_to_dialog, wrap_scrollable

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
    ("bluetooth", "tone"): "bt_tone_timeout",
}


def _fmt_num(value) -> str:
    """Compact number rendering: 10.0 -> '10', 10.5 -> '10.5'."""
    if isinstance(value, float) and float(value).is_integer():
        return str(int(value))
    return str(value)


def _serial_ports() -> list:
    """Available serial devices (pyserial list_ports; tolerant)."""
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:                        # noqa: BLE001 - optional
        return []


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
    """M29 "Test Connection": one paramiko connect attempt OFF the UI
    thread using the CURRENT GUI values.  Emits ok(banner) or
    fail(real error message)."""

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
        try:
            import paramiko
        except ImportError:
            self.fail.emit("paramiko is not installed "
                           "(pip install paramiko)")
            return
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict = dict(hostname=self._host, port=22,
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
            # error (auth failed / timeout / name resolution / refused)
            # is the point of this button
            self.fail.emit(str(exc))
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

    def __init__(self, gateway: str, parent=None) -> None:
        super().__init__(parent)
        self._gateway = gateway

    def run(self) -> None:
        try:
            result = host_platform.probe_host_ap_link(
                self._gateway,
                progress=lambda d, t: self.progress.emit(d, t))
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


class FCTTestConfigPanel(QWidget):
    """Block 07 config panel: Console / Wi-Fi / Bluetooth tabs."""

    #: (level, message) Event-Log mirror (T6 panel convention)
    task_log = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(1100)
        self._legacy: dict = {}             # preserved module params
        self._setup_cfg = FctSetupCfg()     # power/fixture spine (no tab)
        #: full console node loaded from the YAML (connection fields +
        #: command table are edited; the rest is re-emitted untouched)
        self._console_cfg = ConsoleCfg()
        self._guard = False
        self._rf_summary_sigs: set = set()
        #: M37: standard operations usable with the configured resources
        #: (None = all of them; the Operation row editor grays the rest)
        self._available_ops: set[str] | None = None
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        self.tabs.addTab(self._build_console_tab(), "Console")
        self.wifi_tab = self._build_wifi_tab()
        self.tabs.addTab(self.wifi_tab, "Wi-Fi")
        self.bt_tab = self._build_bt_tab()
        self.tabs.addTab(self.bt_tab, "Bluetooth")
        # Sequence tab (task: single sequence source): the shared step
        # editor adds the standard operations / flash operations / Delay
        # steps that run BEFORE the console / Wi-Fi / Bluetooth body
        # generated by the other tabs
        self.tabs.addTab(self._build_sequence_tab(), "Sequence")
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
        lay.insertLayout(0, head)
        lay.insertWidget(1, self.dut_hint)
        self._on_dut_type_changed(self.dut_type.currentText())

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
        self._sync_wifi_groups()
        self._sync_bt_groups()
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
        self._sync_ssh_controls()
        self._sync_add_menu()

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
        lay.addWidget(self.cmd_table, 1)
        self.cmd_table.cellDoubleClicked.connect(self._on_cmd_double_click)
        lay.addLayout(self._cmd_row_buttons())
        # M34: the Sequence tab scrolls (small window) - no control squeeze
        return wrap_scrollable(w)

    # ------------------------------------------------------------ console
    def _build_console_tab(self) -> QWidget:
        """Host PC Serial/SSH connection config ONLY (M22c).

        Port / Baudrate / SSH endpoint (M36: no master enable switch -
        configuring the port is what activates the console).  The
        test-command table and its row buttons live in the Sequence tab.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        self.console_port = QComboBox()
        self.console_port.setEditable(True)
        ports = _serial_ports()
        if ports:
            self.console_port.addItems(ports)
        form.addRow("Port:", self.console_port)
        self.console_baud = QComboBox()
        self.console_baud.addItems([str(b) for b in BAUDRATES])
        form.addRow("Baudrate:", self.console_baud)
        self.console_ssh_host = QLineEdit()
        self.console_ssh_host.setPlaceholderText(
            "DUT SSH endpoint (used by ssh / SFTP rows), e.g. 192.168.1.20")
        form.addRow("SSH host:", self.console_ssh_host)
        self.console_ssh_user = QLineEdit()
        self.console_ssh_user.setPlaceholderText("root")
        form.addRow("SSH username:", self.console_ssh_user)
        self.console_ssh_password = QLineEdit()
        self.console_ssh_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.console_ssh_password.setPlaceholderText(
            "leave empty = agent/key auth (stored in the OS keyring, "
            "never in the YAML)")
        form.addRow("SSH password:", self.console_ssh_password)
        test_row = QHBoxLayout()
        self.ssh_test_btn = QPushButton("Test Connection")
        self.ssh_test_btn.clicked.connect(self._on_ssh_test)
        test_row.addWidget(self.ssh_test_btn)
        self.ssh_test_status = QLabel("")
        self.ssh_test_status.setWordWrap(True)
        test_row.addWidget(self.ssh_test_status, 1)
        form.addRow(test_row)
        self.console_ssh_host.textChanged.connect(
            self._on_ssh_endpoint_edited)
        self.console_ssh_host.textChanged.connect(
            self._sync_ssh_controls)
        self.console_ssh_user.textChanged.connect(
            self._on_ssh_endpoint_edited)
        lay.addLayout(form)

        # ---- SSH asset transfer (push / pull, M29) ------------------------
        self.ssh_transfer_box = QGroupBox("SSH asset transfer")
        tlay = QVBoxLayout(self.ssh_transfer_box)
        push_form = QFormLayout()
        local_row = QHBoxLayout()
        self.console_scripts_local = QLineEdit()
        self.console_scripts_local.setPlaceholderText(
            "local source folder on the Host PC")
        local_row.addWidget(self.console_scripts_local, 1)
        btn_local = QPushButton("Browse...")
        btn_local.clicked.connect(
            lambda: self._browse_dir(self.console_scripts_local))
        local_row.addWidget(btn_local)
        push_form.addRow("Local dir:", local_row)
        self.console_scripts_remote = QLineEdit()
        self.console_scripts_remote.setPlaceholderText("/root")
        push_form.addRow("Remote dir:", self.console_scripts_remote)
        tlay.addLayout(push_form)
        pull_form = QFormLayout()
        self.console_pull_remote = QLineEdit()
        self.console_pull_remote.setPlaceholderText("/tmp/results")
        pull_form.addRow("Pull remote dir:", self.console_pull_remote)
        pull_local_row = QHBoxLayout()
        self.console_pull_local = QLineEdit()
        self.console_pull_local.setPlaceholderText(
            "local destination folder for pulled results")
        pull_local_row.addWidget(self.console_pull_local, 1)
        btn_pull = QPushButton("Browse...")
        btn_pull.clicked.connect(
            lambda: self._browse_dir(self.console_pull_local))
        pull_local_row.addWidget(btn_pull)
        pull_form.addRow("Pull local dir:", pull_local_row)
        tlay.addLayout(pull_form)
        transfer_row = QHBoxLayout()
        self.ssh_transfer_direction = QComboBox()
        self.ssh_transfer_direction.addItems(
            ["Push (Local -> DUT)", "Pull (DUT -> Local)"])
        transfer_row.addWidget(self.ssh_transfer_direction)
        self.ssh_transfer_btn = QPushButton("Transfer")
        self.ssh_transfer_btn.clicked.connect(self._on_ssh_transfer)
        transfer_row.addWidget(self.ssh_transfer_btn)
        transfer_row.addStretch(1)
        tlay.addLayout(transfer_row)
        self.ssh_transfer_bar = QProgressBar()
        self.ssh_transfer_bar.setRange(0, 100)
        self.ssh_transfer_bar.setValue(0)
        self.ssh_transfer_bar.setVisible(False)
        tlay.addWidget(self.ssh_transfer_bar)
        self.ssh_transfer_status = QLabel("")
        self.ssh_transfer_status.setWordWrap(True)
        tlay.addWidget(self.ssh_transfer_status)
        lay.addWidget(self.ssh_transfer_box)

        hint = QLabel(
            "Connection settings only.  The console test commands "
            "(Wait->Send->Capture, SFTP, host CLI, operator dialogs) are "
            "edited in the Sequence tab.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6b7280;")
        lay.addWidget(hint)
        self.ssh_bare_hint = QLabel(
            "Bare Metal: serial console only, no SSH/SFTP.")
        self.ssh_bare_hint.setWordWrap(True)
        self.ssh_bare_hint.setStyleSheet("color: #b45309;")
        self.ssh_bare_hint.setVisible(False)
        lay.addWidget(self.ssh_bare_hint)
        lay.addStretch(1)
        # M34: the Console tab scrolls (small window) - no control squeeze
        return wrap_scrollable(w)

    @staticmethod
    def _browse_dir(edit: QLineEdit) -> None:
        """M29: pick a directory into `edit` (local dir fields)."""
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(
            edit, "Select directory", edit.text().strip() or "")
        if path:
            edit.setText(path)

    def _on_ssh_endpoint_edited(self) -> None:
        """Editing host/user clears the stale Test Connection result."""
        if self._guard:
            return
        self.ssh_test_status.setText("")
        self.ssh_test_status.setStyleSheet("")

    def _sync_ssh_controls(self) -> None:
        """M29 bare-metal gating: no OS -> no SSH at all.  Also the
        Test Connection button needs an endpoint."""
        is_linux = self.dut_type.currentText() == "linux"
        has_host = bool(self.console_ssh_host.text().strip())
        for w in (self.console_ssh_host, self.console_ssh_user,
                  self.console_ssh_password, self.ssh_test_btn,
                  self.ssh_transfer_box):
            w.setEnabled(is_linux)
        self.ssh_test_btn.setEnabled(is_linux and has_host)
        self.ssh_bare_hint.setVisible(not is_linux)
        if not is_linux:
            self.ssh_test_status.setText("")

    # -------------------------------------------------- SSH test/transfer
    _SSH_OK_STYLE = "color: #15803d; font-weight: bold;"
    _SSH_ERR_STYLE = "color: #b91c1c; font-weight: bold;"

    def _on_ssh_test(self) -> None:
        """M29 Test Connection: one paramiko probe OFF the UI thread."""
        host = self.console_ssh_host.text().strip()
        if not host or self.dut_type.currentText() != "linux":
            return
        if getattr(self, "_ssh_probe", None) is not None \
                and self._ssh_probe.isRunning():
            return
        self.ssh_test_status.setText("Connecting...")
        self.ssh_test_status.setStyleSheet("")
        self._ssh_probe = _SshProbeWorker(
            host, self.console_ssh_user.text().strip() or "root",
            self.console_ssh_password.text())
        self._ssh_probe.ok.connect(self._on_ssh_probe_ok)
        self._ssh_probe.fail.connect(self._on_ssh_probe_fail)
        self._ssh_probe.start()

    def _on_ssh_probe_ok(self, banner: str) -> None:
        user = self.console_ssh_user.text().strip() or "root"
        host = self.console_ssh_host.text().strip()
        text = f"SSH OK: {user}@{host}"
        if banner:
            text += f"  ({banner})"
        self.ssh_test_status.setText(text)
        self.ssh_test_status.setStyleSheet(self._SSH_OK_STYLE)

    def _on_ssh_probe_fail(self, error: str) -> None:
        self.ssh_test_status.setText(f"SSH FAILED: {error}")
        self.ssh_test_status.setStyleSheet(self._SSH_ERR_STYLE)

    def _on_ssh_transfer(self) -> None:
        """M29 Transfer: validate inputs, show the pre-front progress
        bar ("Connecting..."), then run push/pull in the worker."""
        host = self.console_ssh_host.text().strip()
        if not host or self.dut_type.currentText() != "linux":
            return
        if getattr(self, "_ssh_transfer", None) is not None \
                and self._ssh_transfer.isRunning():
            return
        direction = ("push" if self.ssh_transfer_direction.currentIndex() == 0
                     else "pull")
        remote = (self.console_scripts_remote.text().strip()
                  if direction == "push"
                  else self.console_pull_remote.text().strip())
        local = (self.console_scripts_local.text().strip()
                 if direction == "push"
                 else self.console_pull_local.text().strip())
        if direction == "push" and not local:
            self.ssh_transfer_status.setText(
                "Push needs a local dir (Deploy assets folder).")
            self.ssh_transfer_status.setStyleSheet(self._SSH_ERR_STYLE)
            return
        if direction == "pull" and not (remote and local):
            self.ssh_transfer_status.setText(
                "Pull needs a remote dir AND a local dir.")
            self.ssh_transfer_status.setStyleSheet(self._SSH_ERR_STYLE)
            return
        # the password lands in the credential layer FIRST so the
        # SshFctChannel (ref fct_ssh_<host>) can use it
        self._persist_ssh_password()
        # PRE-FRONT: the bar is visible and shows "Connecting..." BEFORE
        # the transfer thread starts
        self.ssh_transfer_bar.setVisible(True)
        self.ssh_transfer_bar.setValue(0)
        self.ssh_transfer_status.setText("Connecting...")
        self.ssh_transfer_status.setStyleSheet("")
        self.ssh_transfer_btn.setEnabled(False)
        self._ssh_transfer = _SshTransferWorker(
            direction, host, self.console_ssh_user.text().strip() or "root",
            local, remote)
        self._ssh_transfer.progress.connect(self._on_transfer_progress)
        self._ssh_transfer.done.connect(self._on_transfer_done)
        self._ssh_transfer.fail.connect(self._on_transfer_fail)
        self._ssh_transfer.start()

    def _on_transfer_progress(self, done: int, total: int,
                              path: str) -> None:
        total = max(total, 1)
        self.ssh_transfer_bar.setValue(int(100 * done / total))
        verb = ("Uploading" if self.ssh_transfer_direction.currentIndex() == 0
                else "Downloading")
        self.ssh_transfer_status.setText(f"{verb} {done}/{total}: {path}")

    def _on_transfer_done(self, count: int) -> None:
        self.ssh_transfer_bar.setValue(100)
        self.ssh_transfer_status.setText(f"Done: {count} files")
        self.ssh_transfer_status.setStyleSheet(self._SSH_OK_STYLE)
        self.ssh_transfer_btn.setEnabled(True)

    def _on_transfer_fail(self, error: str) -> None:
        self.ssh_transfer_status.setText(f"TRANSFER FAILED: {error}")
        self.ssh_transfer_status.setStyleSheet(self._SSH_ERR_STYLE)
        self.ssh_transfer_btn.setEnabled(True)

    def _persist_ssh_password(self) -> None:
        """GUI -> credential layer ONLY (M29): the password value NEVER
        reaches ConsoleCfg/YAML.  Empty field = clear the credential
        (falls back to agent/key auth)."""
        host = self.console_ssh_host.text().strip()
        if not host:
            return
        from mtkgui.engine import credentials
        ref = f"fct_ssh_{host}"
        password = self.console_ssh_password.text()
        if password:
            ok, warning = credentials.set_credential(ref, password)
            if not ok:
                self.task_log.emit("WARN", warning)
        else:
            credentials.delete_credential(ref)

    def _prefill_ssh_password(self, host: str) -> None:
        """YAML/GUI load: prefill from the credential layer (warnings
        suppressed - absence is normal)."""
        self.console_ssh_password.setText("")
        if not host:
            return
        from mtkgui.engine import credentials
        try:
            password, _warning = credentials.get_credential(
                f"fct_ssh_{host}")
            self.console_ssh_password.setText(password)
        except Exception:                     # noqa: BLE001 - absent
            pass

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
        self._insert_row(console_command_for_label(
            label, _ADD_ROW_NAMES.get(label, "")))

    def _add_operation_row(self, op_name: str | None = None) -> None:
        """M43: add a standard-operation row DIRECTLY from the Operation
        submenu (no nested sequence-editor dialog opens).

        Args:
            op_name: One of ``OP_STEPS`` keys; None -> the Custom row.
        """
        name = op_name or _ADD_ROW_NAMES[STEP_TYPE_OPERATION]
        cmd = console_command_for_label(STEP_TYPE_OPERATION, name)
        if op_name:
            cmd.op_params = dict(OP_STEPS.get(op_name) or {})
        self._insert_row(cmd)

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
        """True when the operation may be added (M37 availability)."""
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
        """M37 gate applied to the M43 Operation submenu entries: an
        operation whose resource is not configured is disabled with its
        "configure X first" tooltip."""
        for text, act in getattr(self, "_op_add_actions", {}).items():
            name = self._op_name_for_label(text)
            blocked = name is not None and not self._op_usable(name)
            act.setEnabled(not blocked)
            act.setToolTip(self._op_blocked_tooltip(name) if blocked else "")

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
        # M43: one Add dropdown = 18 direct Type items + the "Operation"
        # SUBMENU (11 standard operations + Custom + Delay).  Every
        # submenu entry adds its row DIRECTLY - no nested editor dialog.
        # The standalone Delay Type item is gone (Delay lives in the
        # Operation submenu).
        add_menu = QMenu(add)
        self._add_actions = {}
        self._op_add_actions = {}

        def _add_action(label: str):
            act = add_menu.addAction(label,
                                     lambda _checked=False, l=label:
                                     self._add_row_for_label(l))
            self._add_actions[label] = act
            return act

        add_menu.addSection("Operation")
        op_menu = add_menu.addMenu("Operation")

        def _op_action(text: str, handler) -> None:
            act = op_menu.addAction(text, handler)
            self._op_add_actions[text] = act

        for name in OP_STEPS:
            _op_action(f"Operation: {name}",
                       lambda _checked=False, n=name:
                       self._add_operation_row(n))
        _op_action("Operation: Custom",
                   lambda _checked=False: self._add_operation_row(None))
        _op_action("Delay — plain wait (ms)",
                   lambda _checked=False:
                   self._add_row_for_label(STEP_TYPE_DELAY))
        self._sync_op_submenu()
        add_menu.addSection("Console interact")
        _add_action(STEP_TYPE_CONSOLE_SERIAL)
        _add_action(STEP_TYPE_CONSOLE_SSH)
        add_menu.addSection("SFTP")
        _add_action(STEP_TYPE_SFTP_PUT)
        _add_action(STEP_TYPE_SFTP_GET)
        add_menu.addSection("Host CLI")
        _add_action(STEP_TYPE_CONSOLE_CLI)
        add_menu.addSection("Flash")
        _add_action(STEP_TYPE_FLASH_GUI)
        add_menu.addSection("Dialogs")
        for label in (STEP_TYPE_MESSAGE_OK, STEP_TYPE_MESSAGE_YESNO,
                      STEP_TYPE_MESSAGE_GOSTOP, STEP_TYPE_MESSAGE_OK_WAIT,
                      STEP_TYPE_MESSAGE_YESNO_WAIT,
                      STEP_TYPE_MESSAGE_GOSTOP_WAIT):
            _add_action(label)
        add_menu.addSection("Wi-Fi tests")
        _add_action(STEP_TYPE_WIFI_SCAN)
        _add_action(STEP_TYPE_WIFI_PING)
        _add_action(STEP_TYPE_WIFI_IPERF)
        add_menu.addSection("Bluetooth tests")
        _add_action(STEP_TYPE_BT_RSSI)
        _add_action(STEP_TYPE_BT_PAIR)
        _add_action(STEP_TYPE_BT_TONE)
        add.setMenu(add_menu)
        add.clicked.connect(self._add_console_row)

        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_selected)
        duplicate = QPushButton("Duplicate")
        duplicate.clicked.connect(self._duplicate_row)
        edit = QPushButton("Edit")
        edit.clicked.connect(self._edit_current_row)
        move_up = QPushButton("Move Up")
        move_up.clicked.connect(self._move_up)
        move_down = QPushButton("Move Down")
        move_down.clicked.connect(self._move_down)
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(duplicate)
        row.addWidget(edit)
        row.addWidget(move_up)
        row.addWidget(move_down)
        row.addStretch(1)
        return row

    def _remove_selected(self) -> None:
        r = self.cmd_table.currentRow()
        if r >= 0:
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
            self._jump_to_rf_tab(cmd)
            return
        if cmd.kind == KIND_OP:
            self._edit_operation_row(row)
        elif cmd.kind == KIND_DELAY:
            self._edit_delay_row(row)
        elif cmd.kind == KIND_FLASH_GUI:
            self._edit_flash_gui_row(row)
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

    # --------------------------------------------------------------- wifi
    @staticmethod
    def _tspin(value: int = 15) -> QSpinBox:
        """A per-sub-test timeout spin box (seconds, 1..600, default 15)."""
        s = QSpinBox()
        s.setRange(1, 600)
        s.setValue(int(value))
        s.setSuffix(" s")
        return s

    def _build_wifi_tab(self) -> QWidget:
        """Wi-Fi tab (M31): a scrollable, adaptive three-column body.

        Row 0 = the three config group boxes side by side (DUT | Hotspot
        AP | Host PC).  Row 1 = the three test boxes side by side
        (Scan/RSSI | Ping | iPerf).  Row 2 = the Host PC <-> AP connection
        test (span 3).  M36: no master enable checkbox - the three sub-test
        checkboxes are the source of truth.
        The QScrollArea guarantees no control overlap at any window size."""
        body = QWidget()
        grid = QGridLayout(body)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        # ---- DUT base ------------------------------------------------------
        self.wifi_base = QGroupBox("DUT")
        base = QFormLayout(self.wifi_base)
        self.wifi_interface = QLineEdit("mlan0")
        base.addRow("Interface:", self.wifi_interface)
        self.wifi_driver_cmd = QLineEdit()
        self.wifi_driver_cmd.setPlaceholderText("/root/load_rf_drivers.sh")
        self.wifi_driver_cmd.setToolTip(
            "Linux DUT only. Editable command sent over the console to "
            "load the Wi-Fi/BT drivers; the driver script itself is a "
            "BSP deliverable.")
        base.addRow("Driver load cmd:", self.wifi_driver_cmd)
        grid.addWidget(self.wifi_base, 1, 0)

        # ---- Hotspot AP (SSID/password the DUT joins) ----------------------
        self.wifi_ap_box = QGroupBox("Hotspot AP  (router / phone hotspot)")
        ap = QFormLayout(self.wifi_ap_box)
        self.wifi_ap_ssid = QLineEdit()
        self.wifi_ap_ssid.setPlaceholderText("SSID the DUT joins")
        ap.addRow("AP SSID:", self.wifi_ap_ssid)
        self.wifi_ap_password = QLineEdit()
        self.wifi_ap_password.setEchoMode(QLineEdit.Password)
        self.wifi_ap_password.setPlaceholderText("hotspot password")
        ap.addRow("AP password:", self.wifi_ap_password)
        self.wifi_ap_ip = QLineEdit()
        self.wifi_ap_ip.setPlaceholderText("AP/gateway IP - empty = auto-detect")
        self.wifi_ap_ip.setToolTip(
            "Hotspot AP / gateway IPv4 used by the ping stages "
            "(Host->AP, DUT->AP); empty = auto-detect at run time.")
        ap.addRow("AP IP (gateway):", self.wifi_ap_ip)
        grid.addWidget(self.wifi_ap_box, 1, 1)

        # ---- Host PC ------------------------------------------------------
        self.wifi_host_box = QGroupBox("Host PC")
        hp = QFormLayout(self.wifi_host_box)
        self.wifi_host_ip = QLineEdit()
        self.wifi_host_ip.setPlaceholderText("auto-detect from Host LAN")
        self.wifi_host_ip.setToolTip(
            "Host PC IPv4 used as the ping/SFTP/iperf target ({{host_ip}}). "
            "Empty = auto-detect at run time.")
        hp.addRow("Host IP:", self.wifi_host_ip)
        grid.addWidget(self.wifi_host_box, 1, 2)

        # ---- 1) scan / RSSI (both DUT kinds) --------------------------------
        self.wifi_scan_box = QGroupBox("1. Scan / RSSI test  (Linux + "
                                      "Bare-metal/RTOS)")
        self.wifi_scan_box.setCheckable(True)
        self.wifi_scan_box.setChecked(False)
        sc = QFormLayout(self.wifi_scan_box)
        self.wifi_rssi_min = QSpinBox()
        self.wifi_rssi_min.setRange(-100, 0)
        self.wifi_rssi_min.setValue(-70)
        sc.addRow("RSSI min (dBm):", self.wifi_rssi_min)
        self.wifi_scan_via = QComboBox()
        self.wifi_scan_via.addItems(list(WIFI_SCAN_VIA))
        self.wifi_scan_via.setToolTip(
            "host: Host PC scans the DUT AP/hotspot (default, works for "
            "AP-mode & bare-metal). dut_console: read the station-mode "
            "Linux DUT's own link RSSI over the console (iw dev).")
        sc.addRow("RSSI via:", self.wifi_scan_via)
        self.wifi_scan_timeout = self._tspin(15)
        sc.addRow("Timeout:", self.wifi_scan_timeout)
        grid.addWidget(self.wifi_scan_box, 2, 0)
        # ---- 2) connect & ping (Linux only) --------------------------------
        self.wifi_ping_box = QGroupBox("2. Ping test  (Linux only; "
                                      "Host->AP, DUT->AP, DUT->Host)")
        self.wifi_ping_box.setCheckable(True)
        self.wifi_ping_box.setChecked(False)
        pg = QFormLayout(self.wifi_ping_box)
        self.wifi_ping_count = QSpinBox()
        self.wifi_ping_count.setRange(1, 200)
        self.wifi_ping_count.setValue(20)
        pg.addRow("Ping count:", self.wifi_ping_count)
        self.wifi_ping_timeout = self._tspin(15)
        pg.addRow("Timeout:", self.wifi_ping_timeout)
        grid.addWidget(self.wifi_ping_box, 2, 1)

        # ---- 3) iperf throughput (Linux only) ------------------------------
        self.wifi_iperf_box = QGroupBox("3. iPerf throughput test  (Linux "
                                        "only; Host server / DUT client)")
        self.wifi_iperf_box.setCheckable(True)
        self.wifi_iperf_box.setChecked(False)
        ip = QFormLayout(self.wifi_iperf_box)
        self.wifi_iperf_tool = QComboBox()
        self.wifi_iperf_tool.addItems(list(BW_TOOLS)[::-1])  # iperf3 first
        ip.addRow("Tool:", self.wifi_iperf_tool)
        self.wifi_iperf_min = QDoubleSpinBox()
        self.wifi_iperf_min.setRange(0.0, 10000.0)
        self.wifi_iperf_min.setValue(10.0)
        ip.addRow("Min throughput (Mbps):", self.wifi_iperf_min)
        self.wifi_iperf_server = QLineEdit()
        self.wifi_iperf_server.setPlaceholderText(
            "Host PC server IP - leave empty to auto-detect")
        ip.addRow("Server IP (host):", self.wifi_iperf_server)
        self.wifi_iperf_duration = QSpinBox()
        self.wifi_iperf_duration.setRange(1, 600)
        self.wifi_iperf_duration.setValue(10)
        self.wifi_iperf_duration.setSuffix(" s")
        ip.addRow("Duration:", self.wifi_iperf_duration)
        self.wifi_iperf_timeout = self._tspin(15)
        ip.addRow("Timeout:", self.wifi_iperf_timeout)
        grid.addWidget(self.wifi_iperf_box, 2, 2)

        # ---- Host PC <-> AP connection test (M31) -------------------------
        self.wifi_conn_box = QGroupBox(
            "Test Host PC <-> Hotspot AP connection")
        conn = QVBoxLayout(self.wifi_conn_box)
        self.wifi_conn_test_btn = QPushButton(
            "Test Host PC <-> Hotspot AP connection")
        self.wifi_conn_test_btn.clicked.connect(self._on_wifi_conn_test)
        self.wifi_conn_status = QLabel("")
        self.wifi_conn_status.setWordWrap(True)
        self.wifi_conn_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.wifi_conn_progress = QProgressBar()
        self.wifi_conn_progress.setRange(0, 100)
        self.wifi_conn_progress.setValue(0)
        self.wifi_conn_progress.setVisible(False)
        conn.addWidget(self.wifi_conn_test_btn)
        conn.addWidget(self.wifi_conn_status)
        conn.addWidget(self.wifi_conn_progress)
        grid.addWidget(self.wifi_conn_box, 3, 0, 1, 3)

        self._sync_wifi_groups()
        self._connect_rf_summary_signals()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        return scroll

    def _sync_wifi_groups(self) -> None:
        """Capability gating only (M36: master Wi-Fi switch retired).

        The DUT OS/firmware kind decides which sub-tests exist: driver
        load / ping / iperf / DUT-console RSSI need a Linux shell;
        scan/RSSI works on both kinds."""
        if not hasattr(self, "wifi_scan_box") or not hasattr(
                self, "dut_type"):
            return
        is_linux = self.dut_type.currentText() == "linux"
        self.wifi_driver_cmd.setEnabled(is_linux)
        self.wifi_ping_box.setEnabled(is_linux)
        self.wifi_iperf_box.setEnabled(is_linux)
        # dut_console RSSI read needs a Linux shell; bare-metal = host scan
        if not is_linux and self.wifi_scan_via.currentText() != "host":
            self.wifi_scan_via.blockSignals(True)
            self.wifi_scan_via.setCurrentText("host")
            self.wifi_scan_via.blockSignals(False)
        self.wifi_scan_via.setEnabled(is_linux)
        if not self._guard:
            self._refresh_rf_ref_rows()

    # -------------------------------------------- wifi connection test (M31)
    def _on_wifi_conn_test(self) -> None:
        """M31: show the pre-front progress bar ("Connecting..."), then
        run the Host PC <-> AP connection probe in a worker thread."""
        if getattr(self, "_wifi_probe", None) is not None \
                and self._wifi_probe.isRunning():
            return
        gateway = self.wifi_ap_ip.text().strip()
        self.wifi_conn_progress.setVisible(True)
        self.wifi_conn_progress.setValue(0)
        self.wifi_conn_status.setText("Connecting...")
        self.wifi_conn_status.setStyleSheet("")
        self.wifi_conn_test_btn.setEnabled(False)
        self._wifi_probe = _WifiLinkProbeWorker(gateway)
        self._wifi_probe.progress.connect(self._on_wifi_probe_progress)
        self._wifi_probe.line.connect(self._on_wifi_probe_line)
        self._wifi_probe.done.connect(self._on_wifi_probe_done)
        self._wifi_probe.start()

    def _on_wifi_probe_progress(self, done: int, total: int) -> None:
        total = max(total, 1)
        self.wifi_conn_progress.setValue(int(100 * done / total))

    def _on_wifi_probe_line(self, text: str) -> None:
        current = self.wifi_conn_status.text()
        if current and current != "Connecting...":
            self.wifi_conn_status.setText(current + "\n" + text)
        else:
            self.wifi_conn_status.setText(text)

    def _on_wifi_probe_done(self, ok: bool, summary: str) -> None:
        self.wifi_conn_progress.setValue(100)
        self.wifi_conn_status.setText(summary)
        self.wifi_conn_status.setStyleSheet(
            self._SSH_OK_STYLE if ok else self._SSH_ERR_STYLE)
        self.wifi_conn_test_btn.setEnabled(True)

    # ---------------------------------------------------------- bluetooth
    def _build_bt_tab(self) -> QWidget:
        """Bluetooth tab (M32): a scrollable ONE-row three-column body.

        Module 1 = Host PC Bluetooth panel (RSSI/discovery test fields +
        Host adapter status / connected devices / scan).  Module 2 = Pair
        & Connect test (DUT -> Host).  Module 3 = Tone / Music over A2DP
        (not checkable).  The tab is ALWAYS enabled - gating moved to the
        per-module checkbox (rssi / pair) and the sequence reference rows."""
        body = QWidget()
        grid = QGridLayout(body)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        # ---- 1) Host PC Bluetooth (Host -> DUT) ----------------------------
        self.bt_rssi_box = QGroupBox("1. Host PC Bluetooth (Host -> DUT)")
        self.bt_rssi_box.setCheckable(True)
        self.bt_rssi_box.setChecked(False)
        m1 = QVBoxLayout(self.bt_rssi_box)
        rs = QFormLayout()
        self.bt_name = QLineEdit()
        self.bt_name.setPlaceholderText("DUT Bluetooth advertised name")
        rs.addRow("DUT BT name:", self.bt_name)
        self.bt_expected_addr = QLineEdit()
        self.bt_expected_addr.setPlaceholderText(
            "Optional, e.g. B8:F4:4F:59:51:A0 - leave blank to always "
            "discover by name")
        self.bt_expected_addr.setToolTip(
            "Optional fixed BD address. Pair/Tone connect straight to it "
            "if an inquiry happens to miss the DUT (classic-BT discovery "
            "is probabilistic). The RSSI step still does a real inquiry.")
        rs.addRow("Fixed BD addr (optional):", self.bt_expected_addr)
        self.bt_scan_retries = QSpinBox()
        self.bt_scan_retries.setRange(0, 10)
        self.bt_scan_retries.setValue(3)
        self.bt_scan_retries.setToolTip(
            "Extra inquiry rounds when the DUT is not found in one scan "
            "window (classic-BT discovery can miss a discoverable device).")
        rs.addRow("Scan retries:", self.bt_scan_retries)
        self.bt_rssi_min = QSpinBox()
        self.bt_rssi_min.setRange(-100, 0)
        self.bt_rssi_min.setValue(-70)
        rs.addRow("RSSI min (dBm):", self.bt_rssi_min)
        self.bt_rssi_timeout = self._tspin(15)
        rs.addRow("Timeout:", self.bt_rssi_timeout)
        m1.addLayout(rs)

        # Host PC adapter status / connected devices (read-only)
        host_form = QFormLayout()
        self.bt_host_status = QLabel("N/A")
        self.bt_host_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        host_form.addRow("Host PC BT status:", self.bt_host_status)
        self.bt_host_devices = QLabel("\u2014")
        self.bt_host_devices.setWordWrap(True)
        self.bt_host_devices.setTextInteractionFlags(Qt.TextSelectableByMouse)
        host_form.addRow("Connected devices:", self.bt_host_devices)
        host_hint = QLabel("Disconnect devices in Windows yourself; this "
                           "list is read-only.")
        host_hint.setWordWrap(True)
        host_hint.setStyleSheet("color: #6b7280;")
        host_form.addRow(host_hint)
        m1.addLayout(host_form)

        # Scan button + progress
        self.bt_scan_btn = QPushButton("Scan BT devices")
        self.bt_scan_btn.clicked.connect(self._on_bt_scan)
        self.bt_scan_status = QLabel("")
        self.bt_scan_status.setWordWrap(True)
        self.bt_scan_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.bt_scan_progress = QProgressBar()
        self.bt_scan_progress.setRange(0, 100)
        self.bt_scan_progress.setValue(0)
        self.bt_scan_progress.setVisible(False)
        m1.addWidget(self.bt_scan_btn)
        m1.addWidget(self.bt_scan_status)
        m1.addWidget(self.bt_scan_progress)
        m1.addStretch(1)
        grid.addWidget(self.bt_rssi_box, 0, 0)

        # ---- 2) pair & connect (Linux only, DUT -> Host) -------------------
        self.bt_pair_box = QGroupBox("2. Pair & Connect test  (DUT -> Host)")
        self.bt_pair_box.setCheckable(True)
        self.bt_pair_box.setChecked(False)
        pr = QFormLayout(self.bt_pair_box)
        self.bt_pair_timeout = self._tspin(15)
        pr.addRow("Timeout:", self.bt_pair_timeout)
        self.bt_l2ping = QSpinBox()
        self.bt_l2ping.setRange(0, 100)
        self.bt_l2ping.setValue(4)
        self.bt_l2ping.setToolTip(
            "Optional L2CAP ping DUT -> host PC (data-transfer proof, "
            "real echo both ways); 0 = off.")
        pr.addRow("L2CAP ping count (0=off):", self.bt_l2ping)
        self.bt_pair_script = QLineEdit()
        self.bt_pair_script.setPlaceholderText("/root/bt_conn.sh")
        self.bt_pair_script.setToolTip(
            "DUT Linux script that drives the pair/connect; the Host PC "
            "BT name and BD addr are passed as ARGUMENTS.")
        pr.addRow("DUT script path:", self.bt_pair_script)
        pair_hint = QLabel("Deploy the script Host -> DUT with an SFTP put "
                           "row earlier in the FCT sequence.")
        pair_hint.setWordWrap(True)
        pair_hint.setStyleSheet("color: #6b7280;")
        pr.addRow(pair_hint)
        grid.addWidget(self.bt_pair_box, 0, 1)

        # ---- 3) tone / music over A2DP (Linux only, NOT checkable) --------
        self.bt_tone_box = QGroupBox("3. Tone / Music over A2DP  (Linux "
                                     "only; Host source -> DUT sink)")
        tn = QFormLayout(self.bt_tone_box)
        tone_row = QHBoxLayout()
        self.bt_tone_file = QLineEdit("resources/tones/tone_1khz_6s.wav")
        self.bt_tone_file.setToolTip(
            "WAV test tone played over A2DP. The resources/tones/ folder "
            "accepts user-added wav files.")
        tone_row.addWidget(self.bt_tone_file, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._on_bt_browse)
        tone_row.addWidget(browse_btn)
        tn.addRow("WAV file:", tone_row)
        self.bt_tone_duration = QSpinBox()
        self.bt_tone_duration.setRange(1, 600)
        self.bt_tone_duration.setValue(6)
        self.bt_tone_duration.setSuffix(" s")
        tn.addRow("Play duration:", self.bt_tone_duration)
        self.bt_tone_timeout = self._tspin(15)
        tn.addRow("Timeout:", self.bt_tone_timeout)
        self.bt_audio_confirm = QCheckBox(
            "GUI_CONFIRM: operator confirms the tone is heard on the DUT")
        self.bt_audio_confirm.setChecked(True)
        tn.addRow(self.bt_audio_confirm)
        tone_hint = QLabel("Add a MessageYesNo row in the FCT sequence step "
                           "so the operator confirms the DUT heard the tone.")
        tone_hint.setWordWrap(True)
        tone_hint.setStyleSheet("color: #6b7280;")
        tn.addRow(tone_hint)
        grid.addWidget(self.bt_tone_box, 0, 2)

        self._sync_bt_groups()
        self._connect_rf_summary_signals()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        return scroll

    def _sync_bt_groups(self) -> None:
        if not hasattr(self, "bt_rssi_box") or not hasattr(
                self, "dut_type"):
            return
        is_linux = self.dut_type.currentText() == "linux"
        # The tab is always enabled; only the Linux-only modules gate on
        # the DUT OS/firmware kind. Module 1 fields stay available.
        self.bt_rssi_box.setEnabled(True)
        self.bt_pair_box.setEnabled(is_linux)
        self.bt_tone_box.setEnabled(is_linux)
        if not self._guard:
            self._refresh_rf_ref_rows()

    def _on_bt_browse(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        import os
        current = self.bt_tone_file.text().strip()
        start = os.path.dirname(current) if current else ""
        if not start or not os.path.isdir(start):
            start = os.path.join("resources", "tones")
        path, _ = QFileDialog.getOpenFileName(
            self, "Select test tone wav", start, "WAV files (*.wav)")
        if path:
            self.bt_tone_file.setText(path)

    def _on_bt_scan(self) -> None:
        """M32: pre-front progress bar ("Scanning..."), then run the Host
        PC Bluetooth scan in a worker; the popup lists devices + the DUT
        hit conclusion once it finishes."""
        self.bt_scan_progress.setVisible(True)
        self.bt_scan_progress.setValue(0)
        self.bt_scan_status.setText("Scanning...")
        self.bt_scan_btn.setEnabled(False)
        self._bt_scan_verdict = ""
        self._bt_scan_worker = _BtScanWorker(self.bt_name.text().strip())
        self._bt_scan_worker.progress.connect(self._on_bt_scan_progress)
        self._bt_scan_worker.result.connect(self._on_bt_scan_result)
        self._bt_scan_worker.verdict.connect(self._on_bt_scan_verdict)
        self._bt_scan_worker.done.connect(self._on_bt_scan_done)
        self._bt_scan_worker.start()

    def _on_bt_scan_progress(self, done: int, total: int) -> None:
        self.bt_scan_progress.setValue(
            int(100 * done / max(1, total)))

    def _on_bt_scan_result(self, text: str) -> None:
        self.bt_scan_status.setText(text)

    def _on_bt_scan_verdict(self, text: str) -> None:
        self._bt_scan_verdict = text

    def _on_bt_scan_done(self) -> None:
        self.bt_scan_progress.setValue(100)
        self.bt_scan_btn.setEnabled(True)
        text = self.bt_scan_status.text()
        verdict = getattr(self, "_bt_scan_verdict", "")
        if verdict:
            text = (text + "\n\n" + verdict).strip()
        if "Scan FAILED" in text or "devices" in text or verdict:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "BT scan result", text or "No "
                                    "Bluetooth devices found.")

    # ------------------------------------------------- RF reference rows
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

    def _rf_effective_enabled(self, cmd: ConsoleCommand) -> bool:
        """Mirror the Wi-Fi/BT module + sub-test checkboxes (m30b)."""
        family, subtest = self._rf_family(cmd)
        if not family:
            return True
        if family == "wifi":
            box = {"scan": "wifi_scan_box", "ping": "wifi_ping_box",
                   "iperf": "wifi_iperf_box"}.get(subtest)
        else:
            # BT tab is always enabled (no master switch); rssi / pair
            # keep their checkboxes, tone has no off switch.
            if subtest == "tone":
                return True
            box = {"rssi": "bt_rssi_box", "pair": "bt_pair_box"}.get(subtest)
        if not box or not hasattr(self, box):
            return False
        return bool(getattr(self, box).isChecked())

    def _rf_summary(self, cmd: ConsoleCommand) -> str:
        """Live cmd/params summary read from the Wi-Fi / Bluetooth tab."""
        family, subtest = self._rf_family(cmd)
        if family == "wifi":
            if subtest == "scan":
                return (f"SSID={self.wifi_ap_ssid.text().strip()}, "
                        f"RSSI\u2265{self.wifi_rssi_min.value()} dBm")
            if subtest == "ping":
                return (f"ping\u00d7{self.wifi_ping_count.value()}, "
                        f"{self.wifi_ping_timeout.value()}s")
            if subtest == "iperf":
                return (f"{self.wifi_iperf_tool.currentText()} "
                        f"\u2265{_fmt_num(self.wifi_iperf_min.value())} Mbps, "
                        f"{self.wifi_iperf_duration.value()}s")
            return ""
        if family == "bluetooth":
            if subtest == "rssi":
                return (f"DUT BT name={self.bt_name.text().strip()}, "
                        f"RSSI\u2265{self.bt_rssi_min.value()}")
            if subtest == "pair":
                script = self.bt_pair_script.text().strip() or "bt_conn.sh"
                return (f"{script}, L2CAP\u00d7{self.bt_l2ping.value()}")
            if subtest == "tone":
                import os
                tone = self.bt_tone_file.text().strip() or \
                    "resources/tones/tone_1khz_6s.wav"
                return (f"{os.path.basename(tone)}, "
                        f"{self.bt_tone_duration.value()}s")
            return ""
        return ""

    def _rf_timeout_text(self, cmd: ConsoleCommand) -> str:
        """Timeout cell from the matching sub-test timeout spin box."""
        family, subtest = self._rf_family(cmd)
        attr = _RF_SUBTEST_TIMEOUT_ATTRS.get((family, subtest))
        if attr and hasattr(self, attr):
            return f"{int(getattr(self, attr).value())}s"
        return "-"

    def _refresh_rf_ref_rows(self) -> None:
        """Re-render every RF reference row (summary / enabled mirror)."""
        if self._guard or not hasattr(self, "cmd_table"):
            return
        for r in range(self.cmd_table.rowCount()):
            cmd = self._row_cmd(r)
            if cmd is not None and self._is_rf_ref_row(cmd):
                self._render_row_cmd(r, cmd)

    def _connect_rf_summary_signals(self) -> None:
        """Wire every Wi-Fi / Bluetooth widget that changes an RF summary
        (or the enabled mirror) to re-render the reference rows live.

        Called at the end of both RF tab builders (each pass sees a
        partially-constructed tab set); a per-signal set makes the wiring
        idempotent so no widget fires twice."""
        def _hook(widget, signal_name):
            signal = getattr(widget, signal_name, None)
            if signal is not None and id(signal) not in self._rf_summary_sigs:
                self._rf_summary_sigs.add(id(signal))
                signal.connect(self._refresh_rf_ref_rows)

        for name in ("wifi_scan_box", "wifi_ping_box",
                     "wifi_iperf_box", "bt_rssi_box", "bt_pair_box"):
            if hasattr(self, name):
                _hook(getattr(self, name), "toggled")
        for name in ("wifi_ap_ssid", "bt_name", "bt_tone_file"):
            if hasattr(self, name):
                _hook(getattr(self, name), "textChanged")
        for name in ("wifi_rssi_min", "wifi_ping_count",
                     "wifi_ping_timeout", "wifi_iperf_min",
                     "wifi_iperf_duration", "wifi_iperf_timeout",
                     "bt_rssi_min", "bt_scan_retries", "bt_pair_timeout",
                     "bt_l2ping", "bt_tone_timeout", "bt_rssi_timeout",
                     "bt_tone_duration"):
            if hasattr(self, name):
                _hook(getattr(self, name), "valueChanged")
        if hasattr(self, "wifi_iperf_tool"):
            _hook(self.wifi_iperf_tool, "currentTextChanged")

    def _jump_to_rf_tab(self, cmd: ConsoleCommand) -> None:
        """Switch to the Wi-Fi / Bluetooth tab of an RF reference row and
        briefly highlight the matching module group box (no modal dialog)."""
        family, subtest = self._rf_family(cmd)
        if family == "wifi":
            target_tab = self.wifi_tab
            target_box = {"scan": self.wifi_scan_box,
                          "ping": self.wifi_ping_box,
                          "iperf": self.wifi_iperf_box}.get(subtest)
        else:
            target_tab = self.bt_tab
            target_box = {"rssi": self.bt_rssi_box,
                          "pair": self.bt_pair_box,
                          "tone": self.bt_tone_box}.get(subtest)
        if target_tab is None:
            return
        self.tabs.setCurrentWidget(target_tab)
        if target_box is None:
            return
        prev_style = target_box.styleSheet()
        target_box.setStyleSheet(
            "QGroupBox { border: 2px solid #f59e0b; "
            "background: #fff7e6; border-radius: 4px; }")
        QTimer.singleShot(
            1200, lambda: target_box.setStyleSheet(prev_style))

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
            step_item = self.cmd_table.item(r, _COL_STEP)
            if step_item is not None:
                step_item.setForeground(
                    QColor("#9ca3af") if not self._rf_effective_enabled(cmd)
                    else QColor("#111827"))
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

    def set_values(self, params: dict) -> None:
        """Restore from the module params (round-trip safe)."""
        self._legacy = {k: v for k, v in (params or {}).items()
                        if k not in ("fct_test_config_yaml",
                                     "fct_sequence_cases_yaml")}
        text = str((params or {}).get("fct_test_config_yaml", "") or "")
        data = {}
        if text.strip():
            try:
                node = yaml.safe_load(text) or {}
                data = node.get("fct_test_config") or {}
            except yaml.YAMLError:
                self.task_log.emit("ERROR",
                                   "fct_test_config_yaml: invalid YAML "
                                   "- defaults loaded")
        cfg = FctTestConfig.from_dict(data)
        self._guard = True
        try:
            self.dut_type.setCurrentText(cfg.dut_type)
            c = cfg.console
            # keep the full loaded console node: the panel only edits the
            # connection fields + the command table; the remaining keys
            # (newline, inter-command delay, serial_deploy,
            # post_rf_commands) must round-trip untouched (M22c)
            self._console_cfg = copy.deepcopy(c)
            self.console_ssh_host.setText(c.ssh_host)
            self.console_ssh_user.setText(c.ssh_username)
            # M29: the password comes from the CREDENTIAL layer
            # (fct_ssh_<host>) - never from the YAML
            self._prefill_ssh_password(c.ssh_host)
            self.console_scripts_local.setText(c.scripts_local_dir)
            self.console_scripts_remote.setText(c.scripts_remote_dir)
            self.console_pull_remote.setText(c.pull_remote_dir)
            self.console_pull_local.setText(c.pull_local_dir)
            if c.port:
                if self.console_port.findText(c.port) < 0:
                    self.console_port.addItem(c.port)
                self.console_port.setCurrentText(c.port)
            self.console_baud.setCurrentText(str(c.baudrate))
            self.cmd_table.setRowCount(0)
            # merged table (m30): standard operations FIRST (they run
            # before the console / Wi-Fi / Bluetooth body), then the
            # console test commands
            seq_cases = _sequence_cases_from_param(
                (params or {}).get("fct_sequence_cases_yaml"))
            for case in seq_cases:
                r = self.cmd_table.rowCount()
                self.cmd_table.insertRow(r)
                for col in range(8):
                    self.cmd_table.setItem(r, col, QTableWidgetItem(""))
                self._save_row_cmd(r, _case_to_op_command(case))
            for cmd in c.test_commands:
                r = self.cmd_table.rowCount()
                self.cmd_table.insertRow(r)
                for col in range(8):
                    self.cmd_table.setItem(r, col, QTableWidgetItem(""))
                self._save_row_cmd(r, cmd)
            self._renumber_rows()
            w = cfg.wifi
            self.wifi_interface.setText(w.interface)
            self.wifi_driver_cmd.setText(w.driver_load_cmd)
            self.wifi_ap_ssid.setText(w.ap_ssid)
            self.wifi_ap_password.setText(w.ap_password)
            self.wifi_ap_ip.setText(w.ap_ip)
            self.wifi_host_ip.setText(w.host_ip)
            self.wifi_scan_box.setChecked(w.scan_enabled)
            self.wifi_rssi_min.setValue(w.rssi_min)
            self.wifi_scan_via.setCurrentText(w.scan_via)
            self.wifi_scan_timeout.setValue(int(w.scan_timeout))
            self.wifi_ping_box.setChecked(w.ping_enabled)
            self.wifi_ping_count.setValue(w.ping_count)
            self.wifi_ping_timeout.setValue(int(w.ping_timeout))
            self.wifi_iperf_box.setChecked(w.iperf_enabled)
            self.wifi_iperf_tool.setCurrentText(w.iperf_tool)
            self.wifi_iperf_min.setValue(w.iperf_min_mbps)
            self.wifi_iperf_server.setText(w.iperf_server_ip)
            self.wifi_iperf_duration.setValue(w.iperf_duration)
            self.wifi_iperf_timeout.setValue(int(w.iperf_timeout))
            b = cfg.bluetooth
            # M36: the sub-test flags are the single source of truth - a
            # legacy ``bluetooth.enabled`` master key is ignored on load.
            self.bt_rssi_box.setChecked(b.rssi_enabled)
            self.bt_name.setText(b.expected_name)
            self.bt_expected_addr.setText(b.expected_addr)
            self.bt_scan_retries.setValue(b.scan_retries)
            self.bt_rssi_min.setValue(b.rssi_min)
            self.bt_rssi_timeout.setValue(int(b.rssi_timeout))
            self.bt_pair_box.setChecked(b.pair_enabled)
            self.bt_pair_timeout.setValue(int(b.pair_timeout))
            self.bt_l2ping.setValue(b.l2ping_count)
            self.bt_pair_script.setText(b.bt_pair_script)
            self.bt_audio_confirm.setChecked(b.audio_confirm)
            self.bt_tone_timeout.setValue(int(b.tone_timeout))
            self.bt_tone_file.setText(b.test_tone)
            self.bt_tone_duration.setValue(b.tone_duration_s)
            self._sync_wifi_groups()
            self._sync_bt_groups()
            # setup: there is no editor tab any more - keep the node that
            # was loaded so an old YAML round-trips with its power/fixture
            # behaviour intact
            self._setup_cfg = copy.deepcopy(cfg.setup)
        finally:
            self._guard = False
        # RF reference rows render from the Wi-Fi / Bluetooth tabs, whose
        # values were restored while _guard suppressed the live refresh;
        # render them once now that the widgets hold the YAML values.
        self._refresh_rf_ref_rows()

    def _table_lines(self, table: QTableWidget, width: int) -> list:
        rows = []
        for r in range(table.rowCount()):
            row = [(table.item(r, c).text() if table.item(r, c) else "")
                   for c in range(width)]
            if any(cell.strip() for cell in row):
                rows.append(row)
        return rows

    def values(self) -> dict:
        """Module params: legacy keys preserved + the full
        fct_test_config node as YAML text."""
        cfg = FctTestConfig(
            dut_type=self.dut_type.currentText(),
            console=None, wifi=None, bluetooth=None)
        from mtkgui.engine.fct_test_config import (
            BluetoothCfg,
            ConsoleCfg,
            ConsoleCommand,
            WifiCfg,
        )
        cfg.console = copy.deepcopy(self._console_cfg)
        cfg.console.port = self.console_port.currentText().strip()
        cfg.console.baudrate = int(self.console_baud.currentText())
        cfg.console.ssh_host = self.console_ssh_host.text().strip()
        cfg.console.ssh_username = self.console_ssh_user.text().strip()
        # M29: password -> credential layer ONLY; the fields below are
        # plain paths (YAML-safe)
        self._persist_ssh_password()
        cfg.console.scripts_local_dir = \
            self.console_scripts_local.text().strip()
        cfg.console.scripts_remote_dir = \
            self.console_scripts_remote.text().strip()
        cfg.console.pull_remote_dir = \
            self.console_pull_remote.text().strip()
        cfg.console.pull_local_dir = \
            self.console_pull_local.text().strip()
        # m30: split the merged table back into its two YAML owners -
        # Operation rows -> fct_sequence_cases_yaml, everything else ->
        # console.test_commands (semantics unchanged).
        op_cases: list = []
        test_commands: list = []
        for r in range(self.cmd_table.rowCount()):
            cmd = self._get_row_cmd(r)
            if cmd.kind == KIND_OP:
                op_cases.append(_op_command_to_case(cmd))
            else:
                test_commands.append(cmd)
        cfg.console.test_commands = test_commands
        # tone has no off switch: its YAML flag is derived from a bt_test
        # tone reference row (the row decides tone's place in the
        # sequence). (M36: no master ``enabled`` key any more - the
        # sub-test flags below are the only source of truth.)
        tone_ref = any(
            getattr(c, "kind", "") == KIND_BT_TEST
            and getattr(c, "rf_subtest", "") == "tone"
            for c in test_commands)
        bt_rssi = self.bt_rssi_box.isChecked()
        bt_pair = self.bt_pair_box.isChecked()
        cfg.wifi = WifiCfg(
            interface=self.wifi_interface.text().strip(),
            driver_load_cmd=self.wifi_driver_cmd.text().strip(),
            ap_ssid=self.wifi_ap_ssid.text().strip(),
            ap_password=self.wifi_ap_password.text(),
            ap_ip=self.wifi_ap_ip.text().strip(),
            host_ip=self.wifi_host_ip.text().strip(),
            scan_enabled=self.wifi_scan_box.isChecked(),
            rssi_min=self.wifi_rssi_min.value(),
            scan_via=self.wifi_scan_via.currentText(),
            scan_timeout=float(self.wifi_scan_timeout.value()),
            ping_enabled=self.wifi_ping_box.isChecked(),
            ping_count=self.wifi_ping_count.value(),
            ping_timeout=float(self.wifi_ping_timeout.value()),
            iperf_enabled=self.wifi_iperf_box.isChecked(),
            iperf_tool=self.wifi_iperf_tool.currentText(),
            iperf_min_mbps=self.wifi_iperf_min.value(),
            iperf_server_ip=self.wifi_iperf_server.text().strip(),
            iperf_duration=self.wifi_iperf_duration.value(),
            iperf_timeout=float(self.wifi_iperf_timeout.value()),
        )
        cfg.bluetooth = BluetoothCfg(
            rssi_enabled=bt_rssi,
            expected_name=self.bt_name.text().strip(),
            expected_addr=self.bt_expected_addr.text().strip(),
            scan_retries=self.bt_scan_retries.value(),
            rssi_min=self.bt_rssi_min.value(),
            rssi_timeout=float(self.bt_rssi_timeout.value()),
            pair_enabled=bt_pair,
            pair_timeout=float(self.bt_pair_timeout.value()),
            l2ping_count=self.bt_l2ping.value(),
            bt_pair_script=self.bt_pair_script.text().strip(),
            tone_enabled=tone_ref,
            audio_confirm=self.bt_audio_confirm.isChecked(),
            tone_timeout=float(self.bt_tone_timeout.value()),
            test_tone=self.bt_tone_file.text().strip(),
            tone_duration_s=self.bt_tone_duration.value(),
        )
        # setup: emitted verbatim from what was loaded (no editor tab)
        cfg.setup = copy.deepcopy(self._setup_cfg)
        errors = cfg.validate()
        if errors:
            # the dialog shows the error list from the schema pass; the
            # panel keeps the invalid text so nothing is silently lost
            self.task_log.emit("ERROR",
                               "FCT test config: " + "; ".join(errors))
        out = dict(self._legacy)
        out["fct_test_config_yaml"] = yaml.safe_dump(
            cfg.to_yaml_node(), sort_keys=False, allow_unicode=True)
        # Sequence tab: the Operation rows round-trip as a YAML list of
        # case dicts (single sequence source; every other row lives in
        # test_commands above)
        out["fct_sequence_cases_yaml"] = (
            yaml.safe_dump(op_cases, sort_keys=False, allow_unicode=True)
            if op_cases else "")
        return out
