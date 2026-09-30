# -*- coding: utf-8 -*-
"""Configurable simulated DUT behind the virtual serial console.

In Virtual mode every serial channel opened in the Console group is
backed by a simulated DUT (Device Under Test) instead of the idle
connection used before.  The DUT is defined by a profile persisted in
config/virtual_dut.json (supervisor editable via Settings > Virtual
DUT...):

* ``boot_lines``      - log emitted right after the connection is open
  (the FCT CapturefromConsole / WaitforConsole steps search it)
* ``prompt``          - shell prompt emitted after the boot log and
  after every command reply
* ``boot_delay_ms`` / ``line_delay_ms`` / ``cmd_delay_ms`` - timing
* ``rules``           - command match -> reply lines, first match wins
  (match is case-insensitive "contains")
* ``unknown_response``- reply for unmatched commands (``{cmd}`` is
  substituted); empty = stay silent

The default profile matches the FRDM-IMX93 demo project: the boot log
carries "Linux version ... 1.1.0.0 ... OK" and wifi_test / bt_test
commands reply with Pass / Success, so every console based FCT test
method (SendtoConsole, WaitforConsole, CapturefromConsole, SendtoCLI,
WaitforCLI, CapturefromCLI) can run against real console traffic.

Virtual fault injection hooks in as well: the Test Work Flow page arms
``no_response`` (random equipment error -> the step times out with no
reply -> Error) or ``wrong_reply`` (random test fail -> the reply misses
the expected keyword -> FAIL) on the worker before it sends.
"""

import json
import re
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

DEFAULT_PROFILE = {
    "boot_lines": [
        "U-Boot 2023.04-frdm (Sep 29 2026 - 10:00:00)",
        "CPU: i.MX 93 rev 1.1, Boot: eMMC",
        "Starting kernel ...",
        "Linux version 1.1.0.0 (build@mtk-gui) #1 SMP PREEMPT",
        "Machine model: FRDM-IMX93",
        "EXT4-fs (mmcblk1p2): mounted filesystem",
        "systemd: reached target Network",
        "Board self-test: OK",
        "frdm-imx93 login: root (automatic)",
    ],
    "prompt": "root@frdm-imx93:~# ",
    "boot_delay_ms": 250,
    "line_delay_ms": 40,
    "cmd_delay_ms": 150,
    "rules": [
        {"match": "wifi_test", "response": [
            "wifi_test: wlan0 up, MAC 00:1a:7d:da:00:01",
            "wifi_test: scan on wlan0 ... 3 networks found",
            "wifi_test: associated with SSID 'MTK-TEST-AP' "
            "(ch 6, 2412 MHz)",
            "wifi_test: RSSI -42 dBm, link rate 72.2 Mbit/s, ping OK",
            "Success",
        ]},
        {"match": "bt_test", "response": [
            "bt_test: hci0 up, controller ready",
            "bt_test: inquiry scan ... 2 devices found",
            "bt_test: RSSI -55 dBm / -61 dBm, pairing OK",
            "Pass",
        ]},
        {"match": "iperf", "response": [
            "iperf3: connecting to 192.168.1.1 ...",
            "[  5] 0.00-10.00 sec  110 MBytes  92.4 Mbits/sec",
            "iperf3: throughput test complete",
            "Success",
        ]},
        {"match": "ping", "response": [
            "PING 192.168.1.1: 56 data bytes, 0% packet loss",
            "rtt min/avg/max = 0.8/1.2/3.1 ms",
            "Success",
        ]},
        {"match": "uname", "response": [
            "Linux frdm-imx93 1.1.0.0 #1 SMP PREEMPT aarch64",
        ]},
        {"match": "help", "response": [
            "Commands: help, uname, wifi_test, bt_test, iperf3, "
            "ping, version",
        ]},
        {"match": "version", "response": ["1.1.0.0"]},
    ],
    "unknown_response": ["sh: {cmd}: command not found"],
}

# reply lines used when the Test Work Flow page arms a "wrong_reply"
# fault (random test fail): guaranteed to miss the usual keywords
WRONG_REPLY_LINES = [
    "ERROR: simulated fault (virtual) - unexpected reply",
]

# reply cap so a huge profile cannot flood the console
MAX_RULES = 32
MAX_LINES = 20
MAX_TEXT = 200


def candidate_paths():
    yield Path(__file__).resolve().parent / "config" / "virtual_dut.json"
    yield Path.cwd() / "config" / "virtual_dut.json"
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        yield Path(sys.executable).resolve().parent / "config" / "virtual_dut.json"


def _clean_lines(lines):
    out = []
    for line in lines or []:
        text = str(line).replace("\r", " ").replace("\n", " ").strip()
        if text:
            out.append(text[:MAX_TEXT])
        if len(out) >= MAX_LINES:
            break
    return out


def sanitize_profile(cfg):
    """Validate a profile dict; missing / invalid fields fall back to
    the defaults so a broken config file can never hang the console."""
    p = dict(DEFAULT_PROFILE)
    if not isinstance(cfg, dict):
        return dict(p)
    p["boot_lines"] = _clean_lines(cfg.get("boot_lines"))
    prompt = str(cfg.get("prompt") or DEFAULT_PROFILE["prompt"])
    p["prompt"] = prompt.replace("\r", " ").replace("\n", " ")[:MAX_TEXT]
    for key in ("boot_delay_ms", "line_delay_ms", "cmd_delay_ms"):
        try:
            p[key] = int(min(5000, max(0, int(cfg.get(key, p[key])))))
        except (TypeError, ValueError):
            pass
    rules = []
    for rule in (cfg.get("rules") or [])[:MAX_RULES]:
        if not isinstance(rule, dict):
            continue
        match = str(rule.get("match") or "").strip()[:MAX_TEXT]
        response = _clean_lines(rule.get("response"))
        if match and response:
            rules.append({"match": match, "response": response})
    p["rules"] = rules
    p["unknown_response"] = str(
        cfg.get("unknown_response") or "").strip()[:MAX_TEXT]
    return p


def load_dut_profile():
    """Return the stored DUT profile (defaults when missing/corrupt)."""
    for path in candidate_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return sanitize_profile(data)
    return sanitize_profile(None)


def save_dut_profile(cfg):
    """Persist the DUT profile to config/virtual_dut.json."""
    payload = sanitize_profile(cfg)
    path = next(candidate_paths())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


# =================================================================== worker
class VirtualDutWorker(QThread):
    """Simulated DUT behind one virtual serial channel.

    Behaves like a small Linux board: a boot log is emitted after the
    connection is established, then a shell prompt.  Bytes written by
    the GUI are collected into lines; every complete command line is
    matched against the profile rules (first match wins,
    case-insensitive contains) and answered with the configured reply
    lines followed by the prompt.  Stop reacts within ~10 ms."""

    data_received = Signal(bytes)
    error_occurred = Signal(str)
    connection_changed = Signal(bool)

    def __init__(self, profile, detail, parent=None):
        super().__init__(parent)
        self._profile = sanitize_profile(profile)
        self._detail = detail
        self._stop = False
        self._lock = threading.Lock()
        self._inbuf = bytearray()
        self._fault = None  # "no_response" / "wrong_reply", next command

    # ------------------------------------------------------- GUI side API
    def write(self, data: bytes) -> int:
        """Called from the UI thread; queue bytes for the DUT."""
        if self._stop:
            return -1
        with self._lock:
            self._inbuf.extend(data)
        return len(data)

    def inject_fault(self, kind):
        """Arm a fault for the next command ("no_response" or
        "wrong_reply"); used by the Virtual fault injection.  The fault
        is one-shot: the worker consumes and clears it when the next
        command line is answered, so it can never latch onto every later
        command.  Pass None to disarm."""
        with self._lock:
            self._fault = kind

    def stop(self):
        self._stop = True
        self.wait(3000)

    # ------------------------------------------------------------ helpers
    def _msleep(self, ms):
        """Interruptible sleep (reacts to stop() within ~10 ms)."""
        end = time.monotonic() + max(0, int(ms)) / 1000.0
        while not self._stop and time.monotonic() < end:
            self.msleep(min(10, max(1, int((end - time.monotonic()) * 1000))))

    def _emit(self, text):
        if not self._stop:
            self.data_received.emit((text + "\r\n").encode("utf-8"))

    # ----------------------------------------------------------- DUT side
    def run(self):
        self.connection_changed.emit(True)
        self._emit(f"Virtual DUT: simulated DUT on {self._detail}")
        p = self._profile
        self._msleep(p["boot_delay_ms"])
        for line in p["boot_lines"]:
            if self._stop:
                break
            self._emit(line)
            self._msleep(p["line_delay_ms"])
        if not self._stop:
            self._emit_prompt()
            self._serve()
        self.connection_changed.emit(False)

    def _emit_prompt(self):
        if self._profile["prompt"]:
            self.data_received.emit(
                self._profile["prompt"].encode("utf-8"))

    def _serve(self):
        """Main loop: collect written bytes into lines and answer the
        complete ones.  A line without terminator is flushed after
        300 ms of silence (manual Send without CR/LF still works)."""
        linebuf = b""
        last_rx = time.monotonic()
        while not self._stop:
            with self._lock:
                chunk = bytes(self._inbuf)
                self._inbuf.clear()
            if chunk:
                linebuf += chunk
                last_rx = time.monotonic()
            complete = b"\n" in linebuf or b"\r" in linebuf
            idle = bool(linebuf) and time.monotonic() - last_rx > 0.3
            if complete or idle:
                # atomically take-and-clear the armed fault once for
                # this batch of command lines (one-shot: an injected
                # fault must never latch onto later commands)
                with self._lock:
                    fault = self._fault
                    self._fault = None
                parts = re.split(rb"\r\n|\n|\r", linebuf)
                linebuf = parts.pop()  # trailing (incomplete) remainder
                for raw in parts:
                    cmd = raw.decode("utf-8", "replace").strip()
                    if cmd:
                        self._respond(cmd, fault)
                        fault = None  # armed fault applies to first line only
            self.msleep(20)

    def _respond(self, cmd, fault):
        """Answer one command line with the matching rule's reply."""
        p = self._profile
        self._msleep(p["cmd_delay_ms"])
        if self._stop:
            return
        if fault == "no_response":
            return  # simulated serial fault: the DUT stays silent
        if fault == "wrong_reply":
            lines = list(WRONG_REPLY_LINES)
        else:
            rule = next(
                (r for r in p["rules"]
                 if r["match"].lower() in cmd.lower()), None)
            if rule is not None:
                lines = list(rule["response"])
            elif p["unknown_response"]:
                lines = [p["unknown_response"].replace("{cmd}", cmd)]
            else:
                lines = []
        for line in lines:
            if self._stop:
                return
            self._emit(line)
            self._msleep(p["line_delay_ms"])
        self._emit_prompt()


# =================================================================== dialog
class VirtualDutDialog(QDialog):
    """Edit the simulated DUT profile (Settings > Virtual DUT...)."""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Virtual DUT (Simulated Console Device)")
        self._cfg = sanitize_profile(cfg)

        layout = QVBoxLayout(self)
        note = QLabel(
            "Behavior of the simulated DUT behind every virtual serial "
            "console channel (Virtual mode only). Rules match "
            "case-insensitive; the first match wins. Applies to "
            "channels opened afterwards.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()

        self.edit_boot = QPlainTextEdit()
        self.edit_boot.setPlainText(
            "\n".join(self._cfg["boot_lines"]))
        self.edit_boot.setToolTip(
            "One boot log line per row, emitted after the connection "
            "opens (searched by Capture/Wait steps)")
        form.addRow("Boot log lines:", self.edit_boot)

        self.edit_prompt = QLineEdit(self._cfg["prompt"])
        form.addRow("Prompt:", self.edit_prompt)

        timing = QHBoxLayout()
        self.spin_boot = QSpinBox()
        self.spin_boot.setRange(0, 5000)
        self.spin_boot.setSuffix(" ms")
        self.spin_boot.setValue(self._cfg["boot_delay_ms"])
        self.spin_line = QSpinBox()
        self.spin_line.setRange(0, 5000)
        self.spin_line.setSuffix(" ms")
        self.spin_line.setValue(self._cfg["line_delay_ms"])
        self.spin_cmd = QSpinBox()
        self.spin_cmd.setRange(0, 5000)
        self.spin_cmd.setSuffix(" ms")
        self.spin_cmd.setValue(self._cfg["cmd_delay_ms"])
        for w, label in ((self.spin_boot, "boot"), (self.spin_line, "line"),
                         (self.spin_cmd, "cmd")):
            w.setToolTip(f"Delay before each {label} line")
            timing.addWidget(QLabel(label))
            timing.addWidget(w)
        timing.addStretch(1)
        form.addRow("Delays:", timing)

        layout.addLayout(form)

        # ------------------------------------------------------- rules
        layout.addWidget(QLabel(
            "Command rules (Match = text contained in the command):"))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Match (contains)",
                                              "Response lines"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 220)
        for rule in self._cfg["rules"]:
            self._append_rule_row(rule["match"], rule["response"])
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Add Rule")
        btn_add.clicked.connect(self._add_rule)
        btn_remove = QPushButton("Remove Rule")
        btn_remove.clicked.connect(self._remove_rule)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_remove)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        form2 = QFormLayout()
        self.edit_unknown = QLineEdit(self._cfg["unknown_response"])
        self.edit_unknown.setToolTip(
            "Reply for unmatched commands ({cmd} = the command); "
            "empty = stay silent")
        form2.addRow("Unknown command reply:", self.edit_unknown)
        layout.addLayout(form2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------ rules
    def _append_rule_row(self, match, response):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(match))
        edit = QPlainTextEdit()
        edit.setPlainText("\n".join(response))
        self.table.setRowHeight(r, 72)
        self.table.setCellWidget(r, 1, edit)

    def _add_rule(self):
        if self.table.rowCount() < MAX_RULES:
            self._append_rule_row("", ["reply line"])

    def _remove_rule(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    # ------------------------------------------------------------ result
    def get_profile(self):
        rules = []
        for r in range(self.table.rowCount()):
            match = (self.table.item(r, 0).text().strip()
                     if self.table.item(r, 0) else "")
            edit = self.table.cellWidget(r, 1)
            response = ([ln for ln in
                         (edit.toPlainText().splitlines() if edit else [])
                         if ln.strip()] if edit else [])
            if match and response:
                rules.append({"match": match, "response": response})
        return sanitize_profile({
            "boot_lines": self.edit_boot.toPlainText().splitlines(),
            "prompt": self.edit_prompt.text(),
            "boot_delay_ms": self.spin_boot.value(),
            "line_delay_ms": self.spin_line.value(),
            "cmd_delay_ms": self.spin_cmd.value(),
            "rules": rules,
            "unknown_response": self.edit_unknown.text(),
        })

    @staticmethod
    def edit(cfg, parent=None):
        """Modal editor; return the new profile dict or None on cancel."""
        dlg = VirtualDutDialog(cfg, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.get_profile()
        return None
