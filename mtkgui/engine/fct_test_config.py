# -*- coding: utf-8 -*-
"""fct_test_config — P3-B5 data model for the FCT test configuration
(Console / Wi-Fi / Bluetooth tabs of Yaml Build block 07).

Pure data + (de)serialization + validation + the mapping to B4
``FctStep`` markers (op_params.fct_step) so the published project YAML
runs through the EXISTING fct_exec executor unchanged.

RED LINES honoured:
  * no Qt, no channel I/O here (execution lives in fct_test_runner /
    fct_exec);
  * no passwords in code — whatever the operator types travels with
    the project YAML they own (console creds stay OUT; the Wi-Fi
    password is the DUT AP password the station needs to join).

YAML shape (product YAML `fct_test_config:` node):

    fct_test_config:
      dut_type: "linux"
      console:                     # present = configured (no master switch)
        port: "/dev/cu.usbmodem53930099631"
        baudrate: 115200
        login_sequence:            # wait_for / send pairs
          - {wait_for: "login:", send: "root"}
        test_commands:             # name/send/expect/timeout rows
          - {name: Kernel check, send: "uname -a",
             expect_pass: "Linux imx93frdm", timeout: 5}
      wifi:                        # sub-test flags = single source of truth
        interface: "mlan0"          # DUT wireless interface
        driver_load_cmd: ""        # optional DUT-side driver script
        # 1. Scan / RSSI  (both Linux and bare-metal/RTOS DUTs)
        scan_enabled: true
        ap_ssid: "MyHotspot"       # hotspot AP the DUT joins ({{ssid}})
        ap_password: ""            # hotspot password ({{password}})
        ap_ip: ""                  # AP/gateway IP; empty = auto-detect
        host_ip: ""                # Host PC IP; empty = auto-detect
        scan_via: "host"           # host | dut_console
        rssi_min: -70
        scan_timeout: 15
        # 2. Ping  (Linux DUT only): Host->AP, DUT->AP, DUT->Host
        ping_enabled: false
        ping_count: 20
        ping_timeout: 15
        # 3. iPerf throughput: Host server -> DUT client (Linux only)
        iperf_enabled: false
        iperf_tool: "iperf3"       # iperf2 | iperf3
        iperf_min_mbps: 10
        iperf_server_ip: ""        # empty = auto-detect Host LAN IP
        iperf_duration: 10
        iperf_timeout: 15
      bluetooth:                   # sub-test flags = single source of truth
        # 1. RSSI discovery (both Linux and bare-metal/RTOS DUTs)
        rssi_enabled: true
        expected_name: "FRDM-IMX93-DUT"
        rssi_min: -70
        rssi_timeout: 15
        # 2. Pair & connect, optional L2CAP ping (Linux DUT only)
        pair_enabled: false
        pair_timeout: 15
        l2ping_count: 0
        # 3. Tone / music over A2DP, Host source -> DUT sink (Linux only)
        tone_enabled: false
        audio_confirm: true
        tone_timeout: 15
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..gui.yamlbuild.fct_build import (
    STEP_EXTERNAL_TOOL,
    STEP_GUI_CONFIRM,
    STEP_MESSAGE_CHECK,
    FctStep,
    dedupe_steps,
)

BAUDRATES = (9600, 19200, 38400, 57600, 115200)
#: adapter modes (rf_adapters) reused by the per-sub-test orchestration
WIFI_MODES = ("rssi_only", "full_stack")
BT_MODES = ("rssi_only", "pair_connect", "a2dp_sink")
BW_TOOLS = ("iperf2", "iperf3")
#: how the Wi-Fi scan/RSSI is read
WIFI_SCAN_VIA = ("host", "dut_console")
#: default per-sub-test timeout (seconds); minimum 1 s
DEFAULT_RF_TIMEOUT = 15.0

#: FCT DUT power source (block 07 setup):
#:   psu    - the rack PSU (N5747A) powers the DUT, same Power On/Off
#:            operations as ICT;
#:   manual - no PSU: a MessageGoStop prompts the operator to connect the
#:            wall adapter / USB cable before the tests and remove it
#:            afterwards;
#:   none   - the DUT is already powered (no power action at all).
POWER_PSU = "psu"
POWER_MANUAL = "manual"
POWER_NONE = "none"
FCT_POWER_MODES = (POWER_PSU, POWER_MANUAL, POWER_NONE)

DEFAULT_MANUAL_ON_MSG = (
    "Connect the power adapter / USB cable to the DUT, then press GO "
    "to start FCT.")
DEFAULT_MANUAL_OFF_MSG = (
    "FCT finished. Disconnect the power adapter / USB cable, then press "
    "GO.")

#: default operator prompt for a Flash_GUI step (M33): the third-party
#: flash GUI is launched (or reused) and the operator judges the outcome
#: with the Go / Stop dialog.
DEFAULT_FLASH_GUI_MESSAGE = (
    "Flash GUI has been launched. Handle it. When you finished, press "
    "Go if flash success, press Stop if flash failure or error.")

#: default per-command timeout (spec §4.1: commands 5 s, driver load
#: 15 s, Wi-Fi join 30 s — configured per row)
DEFAULT_CMD_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------
@dataclass
class LoginStep:
    """One console login pair: wait for `wait_for`, then `send`."""

    wait_for: str = ""
    send: str = ""

    def to_dict(self) -> dict:
        return {"wait_for": self.wait_for, "send": self.send}


#: console command kinds (P3-B5 v2: the three primitives)
KIND_WAIT = "wait"              # capture until expect_pass matches
KIND_SEND = "send"              # write line(s); verdict Pass ("sent")
KIND_CAPTURE = "capture"        # judge output (send optional); fail-wins
KIND_SFTP_PUT = "sftp_put"      # ssh file transfer DUT <- Host
KIND_SFTP_GET = "sftp_get"      # ssh file transfer DUT -> Host
KIND_MESSAGE = "message"        # Console-domain operator dialog
                                # (MessageOKtoConsole / MessageYesNotoConsole
                                # / MessageGoStoptoConsole): the row WAITS the
                                # expected console message, then notifies the
                                # operator; the row joins the ordered sequence
                                # where it is placed
KIND_HOST = "host"              # run a command ON THE HOST PC (test
                                # station CLI, e.g. start/stop a local
                                # iperf3 server); PASS = exit code 0
KIND_OP = "op"                  # standard operation (Init/Reset Instr.,
                                # Fixture, Power, Delay): the merged
                                # Sequence table carries it with
                                # op_params; it round-trips through
                                # fct_sequence_cases_yaml (never
                                # console.test_commands)
KIND_WIFI_TEST = "wifi_test"    # Wi-Fi reference row (m30b): a Sequence
                                # step that expands to one Wi-Fi sub-test
                                # AT its position (no inline dialog)
KIND_BT_TEST = "bt_test"        # Bluetooth reference row (m30b): expands
                                # to one Bluetooth sub-test at its position
KIND_FLASH_GUI = "flash_gui"    # M33: launch (or reuse) the third-party
                                # firmware flash GUI, then take the operator
                                # Go / Stop answer as the verdict
KIND_DELAY = "delay"            # M35: plain wait row - fixed sleep of
                                # wait_ms, no console / instrument I/O;
                                # the step timeout bounds the wait
CONSOLE_KINDS = (KIND_WAIT, KIND_SEND, KIND_CAPTURE,
                 KIND_SFTP_PUT, KIND_SFTP_GET, KIND_MESSAGE, KIND_HOST,
                 KIND_DELAY)

#: row kinds that never open the serial console (M36 validation): a
#: console section made only of these needs no port
_NO_SERIAL_KINDS = (KIND_HOST, KIND_OP, KIND_WIFI_TEST, KIND_BT_TEST,
                    KIND_FLASH_GUI, KIND_DELAY)

#: the labels of the merged "FCT test step" Type column (m30 / m30b /
#: m33).  Each label maps to a ConsoleCommand (or a standard operation)
#: backing.
STEP_TYPE_OPERATION = "Operation"
STEP_TYPE_CONSOLE_SERIAL = "Console_serial"
STEP_TYPE_CONSOLE_SSH = "Console_ssh"
STEP_TYPE_SFTP_PUT = "SFTP_put"
STEP_TYPE_SFTP_GET = "SFTP_get"
STEP_TYPE_CONSOLE_CLI = "Console_cli"
STEP_TYPE_MESSAGE_OK = "MessageOK"
STEP_TYPE_MESSAGE_YESNO = "MessageYesNo"
STEP_TYPE_MESSAGE_GOSTOP = "MessageGoStop"
STEP_TYPE_MESSAGE_OK_WAIT = "MessageOK_to_Console"
STEP_TYPE_MESSAGE_YESNO_WAIT = "MessageYesNo_to_Console"
STEP_TYPE_MESSAGE_GOSTOP_WAIT = "MessageGoStop_to_Console"
#: M33: the third-party firmware flash GUI step (launch / reuse + Go /
#: Stop operator verdict)
STEP_TYPE_FLASH_GUI = "Flash_GUI"
#: M35: plain wait step (fixed sleep, no console interaction)
STEP_TYPE_DELAY = "Delay"
#: the six Wi-Fi/BT reference-row labels (m30b): a Sequence step that
#: expands to the matching sub-test and jumps to its tab for editing.
STEP_TYPE_WIFI_SCAN = "Wifi_Scan"
STEP_TYPE_WIFI_PING = "Wifi_Ping"
STEP_TYPE_WIFI_IPERF = "Wifi_Iperf"
STEP_TYPE_BT_RSSI = "BT_RSSI"
STEP_TYPE_BT_PAIR = "BT_Pair"
STEP_TYPE_BT_TONE = "BT_Tone"
STEP_TYPE_LABELS = (STEP_TYPE_OPERATION, STEP_TYPE_CONSOLE_SERIAL,
                    STEP_TYPE_CONSOLE_SSH, STEP_TYPE_SFTP_PUT,
                    STEP_TYPE_SFTP_GET, STEP_TYPE_CONSOLE_CLI,
                    STEP_TYPE_MESSAGE_OK, STEP_TYPE_MESSAGE_YESNO,
                    STEP_TYPE_MESSAGE_GOSTOP, STEP_TYPE_MESSAGE_OK_WAIT,
                    STEP_TYPE_MESSAGE_YESNO_WAIT,
                    STEP_TYPE_MESSAGE_GOSTOP_WAIT, STEP_TYPE_FLASH_GUI,
                    STEP_TYPE_DELAY,
                    STEP_TYPE_WIFI_SCAN, STEP_TYPE_WIFI_PING,
                    STEP_TYPE_WIFI_IPERF, STEP_TYPE_BT_RSSI,
                    STEP_TYPE_BT_PAIR, STEP_TYPE_BT_TONE)

#: rf_subtest -> Type label per RF reference-row family (m30b)
_RF_SUBTEST_LABELS = {
    KIND_WIFI_TEST: {"scan": STEP_TYPE_WIFI_SCAN,
                     "ping": STEP_TYPE_WIFI_PING,
                     "iperf": STEP_TYPE_WIFI_IPERF},
    KIND_BT_TEST: {"rssi": STEP_TYPE_BT_RSSI,
                   "pair": STEP_TYPE_BT_PAIR,
                   "tone": STEP_TYPE_BT_TONE},
}

#: default module title for the six RF reference rows (Step column)
_RF_SUBTEST_TITLES = {
    STEP_TYPE_WIFI_SCAN: "Wi-Fi: Scan / RSSI",
    STEP_TYPE_WIFI_PING: "Wi-Fi: Ping",
    STEP_TYPE_WIFI_IPERF: "Wi-Fi: iPerf",
    STEP_TYPE_BT_RSSI: "Bluetooth: RSSI / discovery",
    STEP_TYPE_BT_PAIR: "Bluetooth: Pair & Connect",
    STEP_TYPE_BT_TONE: "Bluetooth: Tone / A2DP",
}


def rf_subtest_for_label(label: str) -> tuple:
    """Reverse lookup: RF Type label -> ``(kind, rf_subtest)``.

    Returns ``("", "")`` for any non-RF label."""
    for kind, subs in _RF_SUBTEST_LABELS.items():
        for subtest, lbl in subs.items():
            if lbl == label:
                return (kind, subtest)
    return ("", "")

#: dialog styles of a message row (ConsoleCommand.dialog_style)
DIALOG_OK = "ok"
DIALOG_YESNO = "yesno"
DIALOG_GOSTOP = "gostop"
DIALOG_STYLES = (DIALOG_OK, DIALOG_YESNO, DIALOG_GOSTOP)

#: project fct_test_cases kind -> message dialog style
#:
#: The three "*toConsole" kinds are the Console-domain operator dialogs
#: (user direction 2026-10-18): the row WAITS the expected console
#: message first, then notifies the operator.  They are DIFFERENT from
#: the plain standard-operation MessageOK / MessageYesNo / MessageGoStop
#: (which never touch the Console).
_CASE_MESSAGE_STYLES = {"MessageOK": DIALOG_OK,
                        "MessageYesNo": DIALOG_YESNO,
                        "MessageGoStop": DIALOG_GOSTOP,
                        "MessageOKtoConsole": DIALOG_OK,
                        "MessageYesNotoConsole": DIALOG_YESNO,
                        "MessageGoStoptoConsole": DIALOG_GOSTOP}

#: message kinds whose row waits for a console message first
_CONSOLE_MESSAGE_KINDS = ("MessageOKtoConsole", "MessageYesNotoConsole",
                          "MessageGoStoptoConsole")


def _case_marker(case: dict) -> dict:
    """The full FctStep marker travelling with a page case
    (``op_params.fct_step``), or {} - it carries the COMPLETE step
    (params, timeouts, payloads) and is the lossless sync source."""
    return dict((((case or {}).get("op_params") or {})
                 .get("fct_step")) or {})


def _message_command_from_case(case: dict) -> dict:
    """Page Message* case -> ConsoleCommand dict (the message rows ARE
    fully synced: style, answer payloads, timeout)."""
    kind = str((case or {}).get("kind", ""))
    name = str((case or {}).get("name", ""))
    marker = _case_marker(case)
    params = dict(marker.get("params") or {})
    style = str(params.get("style")
                or _CASE_MESSAGE_STYLES.get(kind, DIALOG_GOSTOP))
    # strip a leading "MessageOK: " style prefix, keep plain names
    # intact ("fat.py: setup confirm" must not lose its prefix).
    # Longest prefix first so "MessageOKtoConsole:" is not stripped by
    # the shorter "MessageOK".
    display = name
    for prefix in ("MessageOKtoConsole", "MessageYesNotoConsole",
                   "MessageGoStoptoConsole",
                   "MessageOK", "MessageYesNo", "MessageGoStop"):
        if display.startswith(prefix + ":"):
            display = display.split(":", 1)[-1].strip()
            break
    is_console = kind in _CONSOLE_MESSAGE_KINDS
    wait_pattern = str(params.get("wait_pattern") or "")
    cmd = {
        "kind": KIND_MESSAGE,
        "name": display or name,
        "transport": "serial",
        "dialog_style": style,
        "send_yes": str(params.get("send_yes") or "y"),
        "send_no": str(params.get("send_no") or "n"),
        # forward map stores `confirm_message or name` in params.message
        # - a message equal to the row name means the dialog text was
        # empty (round-trips back to "")
        "confirm_message": ("" if str(params.get("message") or "")
                            in (display, name)
                            else str(params.get("message") or "")),
        # Console-domain operator dialog: WAIT the expected console
        # message before the operator is notified
        "wait_enabled": bool(is_console or wait_pattern),
        "expect_pass": wait_pattern,
        "expect_pass_is_regex": bool(
            params.get("wait_is_regex", False)),
        "wait_timeout": float(params.get("wait_timeout") or 10.0),
        "send_enabled": style != DIALOG_OK,
        "capture_enabled": False,
        "retries": int(marker.get("retries", 0) or 0),
    }
    if style == DIALOG_OK:
        cmd["timeout"] = 0.0 if not is_console else \
            float(params.get("message_timeout_s") or 4.0)
    else:
        cmd["timeout"] = float(params.get("message_timeout_s") or 4.0)
        cmd["send"] = f"{cmd['send_yes']} / {cmd['send_no']}"
    return cmd


def _console_command_from_marker(marker: dict) -> dict:
    """One console MESSAGE_CHECK FctStep marker -> ConsoleCommand dict.

    The exact inverse of the ConsoleCommand -> FctStep mapping in
    :func:`build_fct_steps` - used ONLY when no matching existing
    console command exists (the existing rows are always preferred so
    the reverse sync can never overwrite the console parameters)."""
    params = dict(marker.get("params") or {})
    name = str(marker.get("name", ""))
    base = name[:-len(" (wait)")] if name.endswith(" (wait)") else name
    kind = str(params.get("kind", "send"))
    cmd = {
        "kind": kind if kind in (KIND_WAIT, KIND_SEND, KIND_CAPTURE)
        else KIND_SEND,
        "name": base,
        "transport": "serial",
        "wait_enabled": bool(params.get("wait_enabled", False)),
        "send_enabled": bool(params.get("send_enabled", False)),
        "capture_enabled": bool(params.get("capture_enabled", False)),
        "send": str(params.get("send", "")),
        "capture_is_expected": bool(params.get("capture_is_expected",
                                               False)),
        "capture_end_line": str(params.get("capture_end_line", "")),
        "case_sensitive": bool(params.get("case_sensitive", True)),
        "confirm_enabled": bool(params.get("confirm_enabled", False)),
        "confirm_message": str(params.get("confirm_message", "")),
        "parse_summary": bool(params.get("parse_summary", False)),
        "wait_timeout": float(params.get("wait_timeout", 10.0) or 10.0),
        "send_timeout": float(params.get("send_timeout", 4.0) or 4.0),
        "timeout": float(params.get("capture_timeout", 6.0) or 6.0),
        "retries": int(marker.get("retries", 0) or 0),
    }
    if cmd["capture_is_expected"]:
        # forward: positive=expect_fail(field), negative=capture_forbid
        cmd["expect_fail"] = str(params.get("expect_pass_re", ""))
        cmd["expect_fail_is_regex"] = bool(
            params.get("expect_pass_is_regex", False))
        cmd["capture_forbid"] = str(params.get("expect_fail_re", ""))
    else:
        cmd["expect_fail"] = str(params.get("expect_fail_re", ""))
        cmd["expect_fail_is_regex"] = bool(
            params.get("expect_fail_is_regex", False))
    if cmd["wait_enabled"]:
        # the pre-send wait pattern (wait-only rows carry it twice)
        cmd["expect_pass"] = str(params.get("wait_pattern")
                                 or params.get("expect_pass_re") or "")
        cmd["expect_pass_is_regex"] = bool(
            params.get("expect_pass_is_regex", False))
    return cmd


def cases_to_console_commands(cases: list) -> list:
    """Reverse sync (user direction 2026-10-14, refined 2026-10-14):
    the CURRENT FCT Test Cases rows -> ConsoleCommand dicts.

    ONLY two things sync from the page:

    * the step ORDER (each console row is identified by its marker
      name; a Wait->Send pair arrives as ``X (wait)`` + ``X`` and is
      merged back into one command);
    * the message rows (MessageOK / MessageYesNo / MessageGoStop -
      the syncable standard operator steps).

    The console Wait / Send / Capture / SFTP / Host PARAMETERS are
    NEVER rebuilt from the coarse page row - they come from the
    existing commands (see :func:`overlay_console_commands`), or,
    for a brand-new row with no existing counterpart, losslessly
    from the full FctStep marker travelling in ``op_params``.

    Args:
        cases: the page's ``fct_test_cases`` list (op_params carried).

    Returns:
        A list of plain command dicts (``ConsoleCommand``-shaped).
    """
    commands: list = []
    pending_wait: tuple | None = None   # (base name, wait fields)

    def flush_wait() -> None:
        nonlocal pending_wait
        if pending_wait is not None:
            base, fields = pending_wait
            cmd = {"kind": KIND_WAIT, "name": base, "transport": "serial",
                   "wait_enabled": True, "send_enabled": False,
                   "capture_enabled": False, "send": "",
                   "capture_is_expected": True, "capture_end_line": "",
                   "case_sensitive": fields.get("case_sensitive", True),
                   "confirm_enabled": False, "confirm_message": "",
                   "parse_summary": False,
                   "wait_timeout": fields.get("timeout", 10.0),
                   "send_timeout": 4.0, "timeout": 6.0, "retries": 0,
                   "expect_pass": fields.get("expect_pass", ""),
                   "expect_pass_is_regex":
                       fields.get("expect_pass_is_regex", False)}
            commands.append(cmd)
            pending_wait = None

    for case in (cases or []):
        kind = str((case or {}).get("kind", ""))
        marker = _case_marker(case)
        params = dict(marker.get("params") or {})
        if params.get("teardown"):
            continue            # post_rf teardown rows (Shutdown DUT,
                                # Stop iperf3, FCT done): the section
                                # keeps owning them - never re-sync into
                                # test_commands
        if params.get("fct_serial_push") is not None:
            continue            # M27 P9: serial asset deploy is owned by
                                # console.serial_deploy - never re-sync
                                # into test_commands (single owner)
        if kind in _CASE_MESSAGE_STYLES:
            flush_wait()
            commands.append(_message_command_from_case(case))
            continue
        if kind in ("WIFI", "Bluetooth"):
            continue                    # dialog-side sections
        if not marker:
            continue                    # rows without markers
        if params.get("fct_host_cmd") is not None:
            # host CLI row (EXTERNAL_TOOL): the command runs on the
            # TEST PC, not on the DUT
            flush_wait()
            host = dict(params["fct_host_cmd"])
            commands.append({
                "kind": KIND_HOST, "name": str(marker.get("name", "")),
                "transport": "serial", "wait_enabled": False,
                "send_enabled": True, "capture_enabled": False,
                "send": "", "retries": int(marker.get("retries", 0) or 0),
                "timeout": float(marker.get("timeout_s", 30.0) or 30.0),
                "host_cmd": str(host.get("cmd", "")),
                "host_cmd_windows": str(host.get("cmd_windows", ""))})
            continue
        if str(marker.get("step_type", "")) != "MESSAGE_CHECK":
            continue                    # ops / other non-console rows
        if params.get("action") in (KIND_SFTP_PUT, KIND_SFTP_GET):
            flush_wait()
            commands.append({
                "kind": params["action"],
                "name": str(marker.get("name", "")),
                "transport": "ssh", "wait_enabled": False,
                "send_enabled": False, "capture_enabled": False,
                "send": "", "retries": int(marker.get("retries", 0) or 0),
                "timeout": 6.0,
                "send_timeout": float(marker.get("timeout_s", 20.0) or 20.0),
                "local": str(params.get("local", "")),
                "remote": str(params.get("remote", ""))})
            continue
        # console Wait / Send / Capture row
        name = str(marker.get("name", ""))
        base = name[:-len(" (wait)")] if name.endswith(" (wait)") else name
        if (name.endswith(" (wait)")
                and not bool(params.get("send_enabled", False))):
            # pre-send WaitFor of a Wait->Send pair: stash it; merged
            # into the main row when the very next console row is its
            # base (the forward map always emits the pair adjacently)
            flush_wait()
            pending_wait = (base, {
                "expect_pass": str(params.get("expect_pass_re", "")),
                "expect_pass_is_regex": bool(
                    params.get("expect_pass_is_regex", False)),
                "case_sensitive": bool(params.get("case_sensitive", True)),
                "timeout": float(params.get("wait_timeout",
                                            marker.get("timeout_s", 10.0))
                                 or 10.0)})
            continue
        if (pending_wait is not None and pending_wait[0] == base):
            # main row of the pending Wait->Send pair: merge - the wait
            # PATTERN comes from the pre-wait marker (the main marker's
            # expect_pass_is_regex is the capture's regex flag)
            fields = pending_wait[1]
            pending_wait = None
            cmd = _console_command_from_marker(marker)
            if cmd.get("wait_enabled"):
                cmd["expect_pass"] = fields["expect_pass"]
                cmd["expect_pass_is_regex"] = fields[
                    "expect_pass_is_regex"]
            commands.append(cmd)
            continue
        flush_wait()
        commands.append(_console_command_from_marker(marker))
    flush_wait()
    return commands


def overlay_console_commands(yaml_text: str, cases: list) -> str:
    """Reverse sync, part 2: rebuild ``console.test_commands`` from the
    live FCT Test Cases rows WITHOUT touching the console parameters
    (user direction 2026-10-14: the sync carries the step ORDER and the
    message rows only).

    * every page console row keeps the EXISTING command of the same
      name verbatim (wait patterns, send payloads, capture windows,
      SFTP paths - nothing is regenerated); a page console row with
      no existing counterpart is section-generated (BT piscan from
      `bluetooth`, teardown rows from `post_rf_commands`) and is
      skipped - the section keeps owning it;
    * message rows are fully synced (added / updated / removed);
    * existing console commands the page does not show are kept at
      the end (never silently dropped);
    * every other section (Wi-Fi / Bluetooth / setup) stays as-is.

    Returns:
        The updated ``fct_test_config_yaml`` text.
    """
    import yaml as _yaml
    node: dict = {}
    if str(yaml_text or "").strip():
        try:
            node = _yaml.safe_load(yaml_text) or {}
        except _yaml.YAMLError:
            node = {}
    cfg = dict(node.get("fct_test_config") or {})
    console = dict(cfg.get("console") or {})
    existing = list(console.get("test_commands") or [])
    mapped = cases_to_console_commands(cases)

    # M27 P9: the page now carries an EXPLICIT "Confirm: <name>" dialog
    # for a console command whose legacy ``confirm_enabled`` was
    # normalized.  That explicit dialog is the single owner, so the
    # console command's confirm_enabled flag (and its now-redundant send
    # payload - the dialog sends the answer) is dropped on the keep.
    confirm_names = {
        str(cmd.get("name", ""))[len("Confirm: "):]
        for cmd in mapped
        if str(cmd.get("kind", "")) == KIND_MESSAGE
        and str(cmd.get("name", "")).startswith("Confirm: ")
    }

    def _normalize_kept(cmd: dict) -> dict:
        kept = dict(cmd)
        name = str(kept.get("name", ""))
        if name in confirm_names and kept.get("confirm_enabled"):
            kept["confirm_enabled"] = False
            # the operator answer now travels in the explicit dialog
            # step (send_yes/send_no) - never also on this console row
            kept["send_enabled"] = False
            kept.pop("send", None)
        return kept

    # console/sftp/host commands keyed by name (first unused wins)
    pool: dict = {}
    for cmd in existing:
        pool.setdefault(str(cmd.get("name", "")), []).append(cmd)
    used: set = set()

    def take(key: str) -> dict | None:
        for cmd in pool.get(key, ()):    # noqa: B905 - identity order
            cmd_id = id(cmd)
            if cmd_id not in used:
                used.add(cmd_id)
                return cmd
        return None

    out: list = []
    for cmd in mapped:
        if str(cmd.get("kind", "")) == KIND_MESSAGE:
            out.append(cmd)              # messages fully sync
            continue
        kept = take(str(cmd.get("name", "")))
        if kept is not None:
            out.append(_normalize_kept(kept))
        # a console row with NO existing counterpart is generated by a
        # config section (BT piscan from `bluetooth`, the teardown rows
        # from `post_rf_commands`) or is unknown - NEVER invent a row:
        # the section keeps owning it (the old guessing-by-name rebuild
        # is what flattened them into duplicated test_commands)
    # console rows the page does not show survive at the end
    for cmd in existing:
        if str(cmd.get("kind", "")) != KIND_MESSAGE and id(cmd) not in used:
            out.append(_normalize_kept(cmd))
    console["test_commands"] = out
    cfg["console"] = console
    node["fct_test_config"] = cfg
    return _yaml.safe_dump(node, sort_keys=False, allow_unicode=True)


def _capture_expected_unexpected(c: dict) -> tuple:
    """Legacy capture fields -> the m30 unified pair.

    A dict that already carries the m30 fields (even empty) is returned
    as-is so the round-trip is idempotent.  A legacy dict (no
    ``capture_expected`` / ``capture_unexpected`` keys) migrates the old
    ``capture_is_expected`` / ``expect_fail`` / ``capture_forbid`` trio:
    ``capture_is_expected=True`` + ``expect_fail=X`` -> ``capture_expected``
    = X; ``capture_is_expected=False`` + ``expect_fail=X`` ->
    ``capture_unexpected`` = X."""
    if "capture_expected" in c or "capture_unexpected" in c:
        return (str(c.get("capture_expected", "") or ""),
                str(c.get("capture_unexpected", "") or ""))
    exp = ""
    unexp = ""
    is_expected = bool(c.get("capture_is_expected", False))
    fail = str(c.get("expect_fail", "") or "")
    forbid = str(c.get("capture_forbid", "") or "")
    if fail:
        if is_expected:
            exp = fail
        else:
            unexp = fail
    if forbid:
        unexp = (unexp + "\n" + forbid) if unexp else forbid
    return exp, unexp


@dataclass
class ConsoleCommand:
    """One console test step (model v2): a Wait / Send / Capture
    primitive, or an SSH file-transfer row (sftp_put/sftp_get)."""

    kind: str = "send"              # wait | send | capture | sftp_put |
                                    # sftp_get | message
    name: str = ""
    transport: str = "serial"       # serial | ssh
    wait_enabled: bool = False      # Wait stage on/off
    send_enabled: bool = True       # Send stage on/off
    capture_enabled: bool = False   # Capture stage on/off
    send: str = ""                  # command line(s), \n separated; {{var}} rendered
    expect_pass: str = ""           # WaitFor pattern (exact default or regex)
    expect_fail: str = ""           # Capture pattern (exact default or regex)
    expect_pass_is_regex: bool = False   # False = exact substring match
    expect_fail_is_regex: bool = False
    case_sensitive: bool = True         # False = ignore case (PASS = pass)
    capture_is_expected: bool = False   # Capture: True = found=PASS, False = found=FAIL
    capture_end_line: str = ""          # end-of-range marker
    capture_forbid: str = ""            # optional negative keyword even when
                                        # expecting a positive (legacy migrate)
    confirm_enabled: bool = False       # operator MessageYesNo stage between
                                        # Wait and Send (interactive DUT
                                        # prompts, e.g. fat.py questions)
    confirm_message: str = ""           # dialog text ("" -> use step name)
    dialog_style: str = DIALOG_YESNO    # kind == "message": ok | yesno |
                                        # gostop - which operator dialog
                                        # the row pops (MessageOK/YesNo/GoStop)
    send_yes: str = "y"             # kind == "message" (yesno / gostop):
                                    # payload sent to the DUT console when
                                    # the operator answers Yes / GO
                                    # (user direction 2026-10-14)
    send_no: str = "n"              # payload sent on No / STOP
    timeout: float = 6.0            # capture timeout (overall judgement window)
    wait_timeout: float = 10.0      # wait-for-message timeout
    send_timeout: float = 4.0       # send command timeout
    retries: int = 0                # extra attempts on ANY fail (incl. timeout)
    extract: str = ""               # "name=regex" lines; group 1 -> variables
    action: str = ""                # sftp_put | sftp_get (transport=ssh rows)
    local: str = ""                 # sftp local path (Host PC)
    remote: str = ""                # sftp remote path (DUT)
    parse_summary: bool = False     # capture row parses a fat.py-style
                                    # Summary table into per-item report
                                    # rows (one report row per test line)
    host_cmd: str = ""              # kind == "host": command run ON THE
                                    # HOST PC (test station shell)
    host_cmd_windows: str = ""      # Windows (cmd.exe) command line —
                                    # m30: Console_cli is WINDOWS ONLY,
                                    # this field is the primary source
                                    # (host_cmd kept for legacy reads)
    enabled: bool = True            # False = skip this row (deployment
                                    # toggle: e.g. SSH/iPerf off while the
                                    # bench network is being re-worked)
                                    # kind == "op": the case enable flag
    # m30 unified Capture: output MUST contain `capture_expected` and
    # MUST NOT contain `capture_unexpected`.  Both empty = no assertion.
    # `expect_fail` / `capture_is_expected` stay readable for legacy load.
    capture_expected: str = ""      # output must contain this (exact)
    capture_unexpected: str = ""    # output must NOT contain this (exact)
    # kind == "op" (standard operation) — one merged-table row:
    op_kind: str = ""               # original case kind ("op" / legacy
                                    # "Delay", "MessageOK", ...) so the
                                    # fct_sequence_cases_yaml round-trip
                                    # stays lossless
    op_params: dict = None          # op parameters (type / instruments /
                                    # fixture / power / flash / dio_*)
    op_wait_ms: int = 100           # case wait_ms (op rows)
    op_timeout_ms: int = 5000       # case timeout_ms (op rows)
    rf_subtest: str = ""            # kind == wifi_test|bt_test (m30b):
                                    # scan|ping|iperf|rssi|pair|tone —
                                    # the Wi-Fi/BT sub-test this reference
                                    # row expands to at its sequence
                                    # position (empty for non-RF rows)
    flash_gui_path: str = ""        # kind == flash_gui (m33): third-party
                                    # flash GUI executable (empty = FAIL)
    flash_gui_message: str = DEFAULT_FLASH_GUI_MESSAGE
                                    # kind == flash_gui: operator prompt
                                    # shown with the Go / Stop dialog
    wait_ms: int = 1000             # kind == delay (M35): fixed wait in
                                    # milliseconds; the step timeout bounds
                                    # the maximum execution time

    def to_dict(self) -> dict:
        d = {"kind": self.kind, "name": self.name,
             "transport": self.transport,
             "enabled": bool(self.enabled),
             "wait_enabled": self.wait_enabled,
             "send_enabled": self.send_enabled,
             "capture_enabled": self.capture_enabled,
             "send": self.send,
             "expect_pass": self.expect_pass,
             "expect_fail": self.expect_fail,
             "expect_pass_is_regex": self.expect_pass_is_regex,
             "expect_fail_is_regex": self.expect_fail_is_regex,
             "case_sensitive": self.case_sensitive,
             "capture_is_expected": self.capture_is_expected,
             "capture_end_line": self.capture_end_line,
             "capture_forbid": self.capture_forbid,
             "confirm_enabled": self.confirm_enabled,
             "confirm_message": self.confirm_message,
             "dialog_style": self.dialog_style,
             "send_yes": self.send_yes,
             "send_no": self.send_no,
             "timeout": float(self.timeout),
             "wait_timeout": float(self.wait_timeout),
             "send_timeout": float(self.send_timeout),
             "retries": int(self.retries),
             "extract": self.extract, "action": self.action,
             "local": self.local, "remote": self.remote,
             "parse_summary": bool(self.parse_summary),
             "host_cmd": self.host_cmd,
             "host_cmd_windows": self.host_cmd_windows,
             "capture_expected": self.capture_expected,
             "capture_unexpected": self.capture_unexpected,
             "rf_subtest": self.rf_subtest,
             "flash_gui_path": self.flash_gui_path,
             "flash_gui_message": self.flash_gui_message,
             "wait_ms": int(self.wait_ms)}
        if self.kind == KIND_OP:
            d["op_kind"] = self.op_kind or "op"
            d["op_params"] = (dict(self.op_params)
                              if self.op_params else None)
            d["op_wait_ms"] = int(self.op_wait_ms)
            d["op_timeout_ms"] = int(self.op_timeout_ms)
        return d

    @staticmethod
    def _from_dict_v2(c: dict) -> "ConsoleCommand":
        """Build a ConsoleCommand, migrating the legacy single-window
        model (send + expect_pass/expect_fail judged together) to the
        Wait -> Send -> Capture pipeline.

        Legacy semantics: expect_pass = positive keyword expected AFTER
        send; expect_fail = negative keyword (fail wins). New rows carry
        explicit wait_enabled/send_enabled/capture_enabled flags.
        """
        legacy = not any(k in c for k in
                         ("wait_enabled", "send_enabled", "capture_enabled"))
        kind = str(c.get("kind", "send"))
        send = str(c.get("send", ""))
        old_pass = str(c.get("expect_pass", ""))
        old_fail = str(c.get("expect_fail", ""))

        if kind == KIND_OP:
            # merged-table standard-operation row (m30): it round-trips
            # through fct_sequence_cases_yaml, never test_commands, but
            # the row still travels as a ConsoleCommand inside the panel.
            return ConsoleCommand(
                kind=KIND_OP, name=str(c.get("name", "")),
                transport=str(c.get("transport", "serial")),
                enabled=bool(c.get("enabled", True)),
                op_kind=str(c.get("op_kind", "") or "op"),
                op_params=(dict(c.get("op_params"))
                           if c.get("op_params") else None),
                op_wait_ms=int(c.get("op_wait_ms", 100) or 100),
                op_timeout_ms=int(c.get("op_timeout_ms", 5000) or 5000))

        exp, unexp = _capture_expected_unexpected(c)

        if not legacy:
            return ConsoleCommand(
                kind=kind, name=str(c.get("name", "")),
                transport=str(c.get("transport", "serial")),
                enabled=bool(c.get("enabled", True)),
                wait_enabled=bool(c.get("wait_enabled", False)),
                send_enabled=bool(c.get("send_enabled", True)),
                capture_enabled=bool(c.get("capture_enabled", False)),
                send=send, expect_pass=old_pass, expect_fail=old_fail,
                expect_pass_is_regex=bool(c.get("expect_pass_is_regex", False)),
                expect_fail_is_regex=bool(c.get("expect_fail_is_regex", False)),
                case_sensitive=bool(c.get("case_sensitive", True)),
                capture_is_expected=bool(c.get("capture_is_expected", False)),
                capture_end_line=str(c.get("capture_end_line", "")),
                capture_forbid=str(c.get("capture_forbid", "")),
                confirm_enabled=bool(c.get("confirm_enabled", False)),
                confirm_message=str(c.get("confirm_message", "")),
                dialog_style=str(c.get("dialog_style",
                                       DIALOG_YESNO) or DIALOG_YESNO),
                send_yes=str(c.get("send_yes", "y")),
                send_no=str(c.get("send_no", "n")),
                timeout=float(c.get("timeout", 6.0)),
                wait_timeout=float(c.get("wait_timeout", 10.0)),
                send_timeout=float(c.get("send_timeout", 4.0)),
                retries=int(c.get("retries", 0) or 0),
                extract=str(c.get("extract", "")),
                action=str(c.get("action", "")),
                local=str(c.get("local", "")),
                remote=str(c.get("remote", "")),
                parse_summary=bool(c.get("parse_summary", False)),
                host_cmd=str(c.get("host_cmd", "")),
                host_cmd_windows=str(c.get("host_cmd_windows", "")),
                capture_expected=exp, capture_unexpected=unexp,
                rf_subtest=str(c.get("rf_subtest", "")),
                flash_gui_path=str(c.get("flash_gui_path", "")),
                flash_gui_message=str(
                    c.get("flash_gui_message", DEFAULT_FLASH_GUI_MESSAGE)
                    or DEFAULT_FLASH_GUI_MESSAGE),
                wait_ms=int(c.get("wait_ms", 1000) or 0))

        # ---- legacy migration ----
        if kind == KIND_MESSAGE:
            # message rows are new-model only (no legacy shape existed):
            # a flagless dict still restores the dialog style
            return ConsoleCommand(
                kind=KIND_MESSAGE, name=str(c.get("name", "")),
                transport=str(c.get("transport", "serial")),
                wait_enabled=False, send_enabled=False,
                capture_enabled=False,
                confirm_message=str(c.get("confirm_message", "")),
                dialog_style=str(c.get("dialog_style",
                                       DIALOG_YESNO) or DIALOG_YESNO),
                send_yes=str(c.get("send_yes", "y")),
                send_no=str(c.get("send_no", "n")),
                timeout=float(c.get("timeout", 6.0)),
                retries=int(c.get("retries", 0) or 0),
                capture_expected=exp, capture_unexpected=unexp)
        if kind == "wait":
            return ConsoleCommand(
                kind="wait", name=str(c.get("name", "")),
                transport=str(c.get("transport", "serial")),
                wait_enabled=True, send_enabled=False, capture_enabled=False,
                send="", expect_pass=old_pass, expect_fail="",
                expect_pass_is_regex=bool(c.get("expect_pass_is_regex", False)),
                expect_fail_is_regex=bool(c.get("expect_fail_is_regex", False)),
                case_sensitive=bool(c.get("case_sensitive", True)),
                timeout=float(c.get("timeout", 6.0)),
                wait_timeout=float(c.get("timeout", 10.0)),
                send_timeout=float(c.get("send_timeout", 4.0)),
                retries=int(c.get("retries", 0) or 0),
                capture_expected=exp, capture_unexpected=unexp)
        # send/capture: the old expect_pass becomes the Capture positive
        # keyword; old expect_fail becomes capture_forbid (or the main
        # negative pattern when no positive exists).
        capture_enabled = bool(old_pass or old_fail)
        if old_pass:
            main_pattern, is_expected, forbid = old_pass, True, old_fail
            cexp, cunexp = old_pass, old_fail
        else:
            main_pattern, is_expected, forbid = old_fail, False, ""
            cexp, cunexp = "", old_fail
        return ConsoleCommand(
            kind=kind, name=str(c.get("name", "")),
            transport=str(c.get("transport", "serial")),
            wait_enabled=False,
            send_enabled=bool(send) or kind == "send",
            capture_enabled=capture_enabled,
            send=send, expect_pass="", expect_fail=main_pattern,
            expect_pass_is_regex=bool(c.get("expect_pass_is_regex", False)),
            expect_fail_is_regex=bool(c.get("expect_fail_is_regex", False)),
            case_sensitive=bool(c.get("case_sensitive", True)),
            capture_is_expected=is_expected,
            capture_end_line="", capture_forbid=forbid,
            timeout=float(c.get("timeout", 6.0)),
            wait_timeout=float(c.get("wait_timeout", 10.0)),
            send_timeout=float(c.get("send_timeout", 4.0)),
            retries=int(c.get("retries", 0) or 0),
            extract=str(c.get("extract", "")),
            action=str(c.get("action", "")),
            local=str(c.get("local", "")),
            remote=str(c.get("remote", "")),
            capture_expected=cexp, capture_unexpected=cunexp)


# ---------------------------------------------------------------------------
# m30 merged-table Type label <-> backing mapping
# ---------------------------------------------------------------------------
def step_type_label(cmd: "ConsoleCommand") -> str:
    """One of the 20 Type labels for a merged FCT test step row."""
    kind = str(getattr(cmd, "kind", ""))
    if kind == KIND_OP:
        return STEP_TYPE_OPERATION
    if kind == KIND_DELAY:
        return STEP_TYPE_DELAY
    if kind in (KIND_WIFI_TEST, KIND_BT_TEST):
        return _RF_SUBTEST_LABELS.get(kind, {}).get(
            str(getattr(cmd, "rf_subtest", "") or ""), "")
    if kind == KIND_SFTP_PUT:
        return STEP_TYPE_SFTP_PUT
    if kind == KIND_SFTP_GET:
        return STEP_TYPE_SFTP_GET
    if kind == KIND_FLASH_GUI:
        return STEP_TYPE_FLASH_GUI
    if kind == KIND_HOST:
        return STEP_TYPE_CONSOLE_CLI
    if kind == KIND_MESSAGE:
        style = str(getattr(cmd, "dialog_style", "") or "")
        waits = bool(getattr(cmd, "wait_enabled", False))
        if waits:
            return ({DIALOG_OK: STEP_TYPE_MESSAGE_OK_WAIT,
                     DIALOG_YESNO: STEP_TYPE_MESSAGE_YESNO_WAIT,
                     DIALOG_GOSTOP: STEP_TYPE_MESSAGE_GOSTOP_WAIT}
                    .get(style, STEP_TYPE_MESSAGE_OK_WAIT))
        return ({DIALOG_OK: STEP_TYPE_MESSAGE_OK,
                 DIALOG_YESNO: STEP_TYPE_MESSAGE_YESNO,
                 DIALOG_GOSTOP: STEP_TYPE_MESSAGE_GOSTOP}
                .get(style, STEP_TYPE_MESSAGE_YESNO))
    # wait | send | capture interact rows
    return (STEP_TYPE_CONSOLE_SSH
            if str(getattr(cmd, "transport", "") or "") == "ssh"
            else STEP_TYPE_CONSOLE_SERIAL)


def console_command_for_label(label: str,
                              name: str = "") -> "ConsoleCommand":
    """The default ConsoleCommand backing one of the 20 Type labels."""
    if label == STEP_TYPE_OPERATION:
        return ConsoleCommand(kind=KIND_OP, name=name or "New Operation",
                              wait_enabled=False, send_enabled=False,
                              capture_enabled=False, op_kind="op",
                              op_params=None, op_wait_ms=100,
                              op_timeout_ms=5000)
    if label == STEP_TYPE_DELAY:
        return ConsoleCommand(kind=KIND_DELAY, name=name or "Delay",
                              wait_enabled=False, send_enabled=False,
                              capture_enabled=False, wait_ms=1000,
                              timeout=0.0)
    if label in _RF_SUBTEST_TITLES:
        kind, subtest = rf_subtest_for_label(label)
        return ConsoleCommand(kind=kind, name=name or _RF_SUBTEST_TITLES[label],
                              rf_subtest=subtest, wait_enabled=False,
                              send_enabled=False, capture_enabled=False)
    if label == STEP_TYPE_CONSOLE_SSH:
        return ConsoleCommand(kind="send", name=name or "",
                              transport="ssh", wait_enabled=False,
                              send_enabled=True, capture_enabled=False)
    if label == STEP_TYPE_SFTP_PUT:
        return ConsoleCommand(kind=KIND_SFTP_PUT, name=name or "",
                              transport="ssh", wait_enabled=False,
                              send_enabled=True, capture_enabled=False,
                              send_timeout=30.0)
    if label == STEP_TYPE_SFTP_GET:
        return ConsoleCommand(kind=KIND_SFTP_GET, name=name or "",
                              transport="ssh", wait_enabled=False,
                              send_enabled=True, capture_enabled=False,
                              send_timeout=30.0)
    if label == STEP_TYPE_FLASH_GUI:
        return ConsoleCommand(kind=KIND_FLASH_GUI,
                              name=name or STEP_TYPE_FLASH_GUI,
                              wait_enabled=False, send_enabled=False,
                              capture_enabled=False,
                              flash_gui_path="",
                              flash_gui_message=DEFAULT_FLASH_GUI_MESSAGE)
    if label == STEP_TYPE_CONSOLE_CLI:
        return ConsoleCommand(kind=KIND_HOST, name=name or "",
                              transport="serial", wait_enabled=False,
                              send_enabled=True, capture_enabled=False,
                              host_cmd_windows="", host_cmd="")
    if label == STEP_TYPE_CONSOLE_SERIAL:
        return ConsoleCommand(kind="send", name=name or "",
                              transport="serial", wait_enabled=False,
                              send_enabled=True, capture_enabled=False)
    if label in (STEP_TYPE_MESSAGE_OK, STEP_TYPE_MESSAGE_OK_WAIT):
        style = DIALOG_OK
    elif label in (STEP_TYPE_MESSAGE_YESNO, STEP_TYPE_MESSAGE_YESNO_WAIT):
        style = DIALOG_YESNO
    else:
        style = DIALOG_GOSTOP
    waits = label in (STEP_TYPE_MESSAGE_OK_WAIT,
                      STEP_TYPE_MESSAGE_YESNO_WAIT,
                      STEP_TYPE_MESSAGE_GOSTOP_WAIT)
    cmd = ConsoleCommand(
        kind=KIND_MESSAGE, name=name or "", transport="serial",
        dialog_style=style, wait_enabled=waits,
        wait_timeout=10.0 if waits else 0.0,
        send_enabled=(style != DIALOG_OK), capture_enabled=False,
        confirm_enabled=False, retries=0,
        timeout=(4.0 if style in (DIALOG_YESNO, DIALOG_GOSTOP) else 0.0))
    if cmd.send_enabled:
        cmd.send = f"{cmd.send_yes} / {cmd.send_no}"
    return cmd


@dataclass
class ConsoleCfg:
    """Host PC console settings + command rows (M36: no master switch -
    the configured port / rows are the single source of truth)."""
    port: str = ""
    baudrate: int = 115200
    newline: str = "lf"             # lf | crlf (send line ending)
    inter_cmd_delay_ms: int = 100   # settle time between command rows
    ssh_host: str = ""              # DUT SSH endpoint for ssh/sftp rows
    ssh_username: str = "root"
    test_commands: list = field(default_factory=list)    # [ConsoleCommand]
    # teardown rows run AFTER the Wi-Fi/BT RF sections (e.g. DUT
    # 'shutdown now', stopping a host-side iperf3 server) - the DUT
    # must stay up while any RF sub-test can still run
    post_rf_commands: list = field(default_factory=list)  # [ConsoleCommand]
    # Linux DUT script-asset provisioning: as soon as SSH/SFTP is up the
    # whole local asset folder is copied to the DUT (once per unit, so a
    # board whose /root was wiped by a reboot is re-provisioned). Scripts
    # stay GENERIC (no per-board MAC/BD/IP); they probe at runtime.
    deploy_scripts: bool = False
    scripts_local_dir: str = ""     # Host asset folder (rel to yaml/pkg)
    scripts_remote_dir: str = "/root"   # DUT target directory
    # M29 pull path (DUT -> Host): the DUT result folder is fetched back
    # into the local destination folder (SshFctChannel.get_dir).  Plain
    # paths only - the SSH password NEVER lands here (credential layer).
    pull_remote_dir: str = ""       # DUT source directory (e.g. /tmp/results)
    pull_local_dir: str = ""        # Host destination directory
    # Serial asset provisioning (no SSH needed): right after the console
    # login, push the listed files to a freshly flashed DUT that has none
    # of them; an archive entry may add "unzip": target dir.  Local paths
    # resolve relative to the project folder.
    serial_deploy: bool = False
    serial_deploy_files: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "port": self.port,
            "baudrate": int(self.baudrate),
            "newline": self.newline,
            "inter_cmd_delay_ms": int(self.inter_cmd_delay_ms),
            "ssh_host": self.ssh_host, "ssh_username": self.ssh_username,
            "deploy_scripts": bool(self.deploy_scripts),
            "scripts_local_dir": self.scripts_local_dir,
            "scripts_remote_dir": self.scripts_remote_dir,
            "pull_remote_dir": self.pull_remote_dir,
            "pull_local_dir": self.pull_local_dir,
            "serial_deploy": bool(self.serial_deploy),
            "serial_deploy_files": [dict(f) for f in self.serial_deploy_files],
            "test_commands": [c.to_dict() for c in self.test_commands],
            "post_rf_commands": [c.to_dict()
                                 for c in self.post_rf_commands],
        }


@dataclass
class WifiCfg:
    """Wi-Fi FCT split into independently enabled sub-tests.

    Topology: the DUT advertises the RF endpoint (Wi-Fi AP / hotspot);
    the Host PC is the initiator.

    * Scan/RSSI test  - host scans the DUT SSID and reads RSSI; works on
      BOTH Linux and bare-metal/RTOS DUTs (firmware auto-broadcasts after
      power-up on bare metal).
    * Connect & Ping  - host associates to the DUT AP (SSID + password)
      and pings; PASS as soon as >=1 reply is received. Linux DUT only.
    * iPerf throughput- host is the iperf SERVER, DUT the client; PASS at
      or above ``iperf_min_mbps``; iperf2/iperf3 selectable. Linux only.

    ``interface`` / ``driver_load_cmd`` are base parameters (the driver
    load is a BSP deliverable; MTK only sends the editable command over
    the console). Each sub-test carries its own timeout (default 15 s).

    M36: no master ``enabled`` switch - the sub-test flags (scan / ping /
    iperf) are the single source of truth; a legacy YAML ``enabled`` key
    is ignored on load."""
    # base parameters
    interface: str = "mlan0"
    driver_load_cmd: str = ""
    # 1) scan / RSSI (both DUT kinds); M36: opt-in like every other
    # sub-test (the retired master switch used to keep it inert)
    scan_enabled: bool = False
    # Hotspot AP the station-mode DUT joins (factory router OR phone
    # hotspot): {{ssid}} / {{password}} in console rows. Deployment
    # variables - never hard-coded in code / DUT scripts.
    ap_ssid: str = ""
    ap_password: str = ""
    ap_ip: str = ""                 # hotspot/AP gateway IP for the ping
                                    # stages; empty = auto-detect
    host_ip: str = ""               # Host PC IPv4 for ping/SFTP/iperf;
                                    # empty = auto-detect at run time
    rssi_min: int = -70
    scan_timeout: float = 15.0
    scan_via: str = "host"          # host | dut_console (station-mode DUT)
    # 2) connect & ping (Linux only): 3 stages - Host->AP, DUT->AP, DUT->Host
    ping_enabled: bool = False
    ping_count: int = 20
    ping_timeout: float = 15.0
    # 3) iperf throughput (Linux only; host server / DUT client)
    iperf_enabled: bool = False
    iperf_tool: str = "iperf3"      # iperf2 | iperf3
    iperf_min_mbps: float = 10.0
    iperf_server_ip: str = ""       # host PC IP; empty = auto-detect
    iperf_duration: int = 10
    iperf_timeout: float = 15.0

    def to_dict(self) -> dict:
        return {
            "interface": self.interface,
            "driver_load_cmd": self.driver_load_cmd,
            "scan_enabled": self.scan_enabled,
            "ap_ssid": self.ap_ssid,
            "ap_password": self.ap_password,
            "ap_ip": self.ap_ip,
            "host_ip": self.host_ip,
            "rssi_min": int(self.rssi_min),
            "scan_timeout": float(self.scan_timeout),
            "scan_via": self.scan_via,
            "ping_enabled": self.ping_enabled,
            "ping_count": int(self.ping_count),
            "ping_timeout": float(self.ping_timeout),
            "iperf_enabled": self.iperf_enabled,
            "iperf_tool": self.iperf_tool,
            "iperf_min_mbps": float(self.iperf_min_mbps),
            "iperf_server_ip": self.iperf_server_ip,
            "iperf_duration": int(self.iperf_duration),
            "iperf_timeout": float(self.iperf_timeout),
        }

    @property
    def any_enabled(self) -> bool:
        """True when at least one sub-test is switched on (M36: replaces
        the retired master switch)."""
        return bool(self.scan_enabled or self.ping_enabled
                    or self.iperf_enabled)


@dataclass
class BluetoothCfg:
    """Bluetooth FCT split into independently enabled sub-tests.

    Topology: the Host PC is the A2DP SOURCE / initiator, the DUT is the
    sink / advertiser.

    * RSSI test         - host inquiry discovers the DUT by name and
      reads RSSI; works on BOTH Linux and bare-metal/RTOS DUTs.
    * Pair-Connect test - host pairs and connects to the DUT. Linux
      only; optional ``l2ping_count`` (0 = off) proves the data path both
      ways.
    * Tone/Music test   - host routes audio to the DUT A2DP sink and
      plays a test tone; operator GUI confirm. Linux only.

    Each sub-test carries its own timeout (default 15 s).

    M36: no master ``enabled`` switch - rssi / pair / tone flags are the
    single source of truth; a legacy YAML ``enabled`` key is ignored."""
    # 1) RSSI / discovery (both DUT kinds); M36: opt-in, like the other
    # sub-tests (the retired master switch used to keep it inert)
    rssi_enabled: bool = False
    expected_name: str = ""
    # Optional fixed BD address (aa:bb:.. or aa-bb-..). When set, pair/tone
    # skip the probabilistic inquiry and connect straight to it; RSSI still
    # verifies discovery. Empty = always discover by expected_name.
    expected_addr: str = ""
    scan_retries: int = 3          # extra inquiry rounds if the DUT is missed
    rssi_min: int = -70
    rssi_timeout: float = 15.0
    # 2) pair & connect (Linux only); optional DUT-side pair script (host
    # name / addr passed as ARGUMENTS - deploy it with an SFTP put row)
    pair_enabled: bool = False
    pair_timeout: float = 15.0
    l2ping_count: int = 4           # optional L2CAP data-path proof, 0=off
    bt_pair_script: str = ""        # DUT script path, e.g. /root/bt_conn.sh
    # 3) tone / music over A2DP (Linux only; host source -> DUT sink)
    tone_enabled: bool = False
    audio_confirm: bool = True
    tone_timeout: float = 15.0
    test_tone: str = "resources/tones/tone_1khz_6s.wav"
    tone_duration_s: int = 6

    def to_dict(self) -> dict:
        return {
            "rssi_enabled": self.rssi_enabled,
            "expected_name": self.expected_name,
            "expected_addr": self.expected_addr,
            "scan_retries": int(self.scan_retries),
            "rssi_min": int(self.rssi_min),
            "rssi_timeout": float(self.rssi_timeout),
            "pair_enabled": self.pair_enabled,
            "pair_timeout": float(self.pair_timeout),
            "l2ping_count": int(self.l2ping_count),
            "bt_pair_script": self.bt_pair_script,
            "tone_enabled": self.tone_enabled,
            "audio_confirm": self.audio_confirm,
            "tone_timeout": float(self.tone_timeout),
            "test_tone": self.test_tone,
            "tone_duration_s": int(self.tone_duration_s),
        }

    @property
    def any_enabled(self) -> bool:
        """True when at least one sub-test is switched on (M36: replaces
        the retired master switch)."""
        return bool(self.rssi_enabled or self.pair_enabled
                    or self.tone_enabled)


@dataclass
class FctSetupCfg:
    """FCT fixture/power wrapper around the generated test body.

    Unlike ICT, FCT needs NO DAQ. The DUT is powered either by the rack
    PSU (Power On/Off operations) or by a wall adapter / USB cable the
    operator connects when prompted (MessageGoStop). The ATE fixture,
    when used, is driven through the U2355A DIO resource.
    """

    power_mode: str = POWER_MANUAL     # psu | manual | none
    use_fixture: bool = False
    manual_on_message: str = DEFAULT_MANUAL_ON_MSG
    manual_off_message: str = DEFAULT_MANUAL_OFF_MSG

    def to_dict(self) -> dict:
        return {
            "power_mode": self.power_mode,
            "use_fixture": bool(self.use_fixture),
            "manual_on_message": self.manual_on_message,
            "manual_off_message": self.manual_off_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FctSetupCfg":
        data = data or {}
        return cls(
            power_mode=str(data.get("power_mode", POWER_MANUAL)),
            use_fixture=bool(data.get("use_fixture", False)),
            manual_on_message=str(
                data.get("manual_on_message", DEFAULT_MANUAL_ON_MSG)),
            manual_off_message=str(
                data.get("manual_off_message", DEFAULT_MANUAL_OFF_MSG)),
        )

    def validate(self) -> list:
        errors: list = []
        if self.power_mode not in FCT_POWER_MODES:
            errors.append(f"setup.power_mode must be one of "
                          f"{FCT_POWER_MODES}")
        if self.power_mode == POWER_MANUAL and not \
                self.manual_on_message.strip():
            errors.append("setup.manual_on_message must not be empty "
                          "for manual power mode")
        return errors


@dataclass
class FctTestConfig:
    """The whole `fct_test_config:` node (block 07 three tabs)."""

    dut_type: str = "linux"              # bare_metal | linux
    console: ConsoleCfg = field(default_factory=ConsoleCfg)
    wifi: WifiCfg = field(default_factory=WifiCfg)
    bluetooth: BluetoothCfg = field(default_factory=BluetoothCfg)
    setup: FctSetupCfg = field(default_factory=FctSetupCfg)

    # ------------------------------------------------------------ YAML IO
    def to_dict(self) -> dict:
        return {
            "dut_type": self.dut_type,
            "console": self.console.to_dict(),
            "wifi": self.wifi.to_dict(),
            "bluetooth": self.bluetooth.to_dict(),
            "setup": self.setup.to_dict(),
        }

    def to_yaml_node(self) -> dict:
        return {"fct_test_config": self.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> "FctTestConfig":
        """Tolerant restore (missing keys keep defaults)."""
        data = data or {}
        console = data.get("console") or {}
        wifi = data.get("wifi") or {}
        bt = data.get("bluetooth") or {}
        bw = wifi.get("bandwidth") or {}
        # ---- legacy single-mode migration ------------------------------
        wmode = wifi.get("mode")          # rssi_only | full_stack | None
        legacy_ssid = str(wifi.get("ssid", ""))
        bmode = bt.get("mode")            # rssi_only | pair_connect | a2dp_sink
        # M36: legacy ``enabled`` master keys under console/wifi/bluetooth
        # are IGNORED - the configured fields / sub-test flags win.
        wifi_cfg = WifiCfg(
            interface=str(wifi.get("interface", "mlan0")),
            driver_load_cmd=str(wifi.get("driver_load_cmd", "")),
            scan_enabled=bool(wifi.get(
                "scan_enabled",
                wmode in ("rssi_only", "full_stack"))),
            ap_ssid=str(wifi.get("ap_ssid",
                                 wifi.get("scan_ssid", legacy_ssid))),
            ap_password=str(wifi.get("ap_password",
                                     wifi.get("password", ""))),
            ap_ip=str(wifi.get("ap_ip", "")),
            host_ip=str(wifi.get("host_ip", "") or wifi.get(
                "iperf_server_ip", "")),
            rssi_min=int(wifi.get("rssi_min", -70)),
            scan_timeout=float(wifi.get("scan_timeout",
                                       DEFAULT_RF_TIMEOUT)),
            scan_via=str(wifi.get("scan_via", "host")),
            ping_enabled=bool(wifi.get(
                "ping_enabled", wmode == "full_stack")),
            ping_count=int(wifi.get("ping_count", 20)),
            ping_timeout=float(wifi.get("ping_timeout",
                                       DEFAULT_RF_TIMEOUT)),
            iperf_enabled=bool(wifi.get(
                "iperf_enabled", bool(bw.get("enabled", False)))),
            iperf_tool=str(wifi.get("iperf_tool",
                                   bw.get("tool", "iperf3"))),
            iperf_min_mbps=float(wifi.get(
                "iperf_min_mbps", bw.get("min_mbps", 10.0))),
            iperf_server_ip=str(wifi.get(
                "iperf_server_ip", bw.get("server_ip", ""))),
            iperf_duration=int(wifi.get(
                "iperf_duration", bw.get("duration", 10))),
            iperf_timeout=float(wifi.get("iperf_timeout",
                                        DEFAULT_RF_TIMEOUT)),
        )
        bt_cfg = BluetoothCfg(
            rssi_enabled=bool(bt.get(
                "rssi_enabled",
                bmode in ("rssi_only", "pair_connect",
                          "a2dp_sink"))),
            expected_name=str(bt.get("expected_name", "")),
            expected_addr=(str(bt.get("expected_addr", "")).strip()
                           .lower().replace("-", ":")),
            scan_retries=int(bt.get("scan_retries", 3) or 0),
            rssi_min=int(bt.get("rssi_min", -70)),
            rssi_timeout=float(bt.get("rssi_timeout",
                                     DEFAULT_RF_TIMEOUT)),
            pair_enabled=bool(bt.get(
                "pair_enabled", bmode == "pair_connect")),
            pair_timeout=float(bt.get("pair_timeout",
                                     DEFAULT_RF_TIMEOUT)),
            l2ping_count=int(bt.get("l2ping_count", 4) or 0),
            bt_pair_script=str(bt.get("bt_pair_script", "")),
            tone_enabled=bool(bt.get(
                "tone_enabled", bmode == "a2dp_sink")),
            audio_confirm=bool(bt.get("audio_confirm", True)),
            tone_timeout=float(bt.get("tone_timeout",
                                     DEFAULT_RF_TIMEOUT)),
            test_tone=str(bt.get(
                "test_tone", "resources/tones/tone_1khz_6s.wav")),
            tone_duration_s=int(bt.get("tone_duration_s", 6)),
        )
        return cls(
            dut_type=str(data.get("dut_type", "linux")),
            console=ConsoleCfg(
                port=str(console.get("port", "")),
                baudrate=int(console.get("baudrate", 115200)),
                newline=str(console.get("newline", "lf")),
                inter_cmd_delay_ms=int(console.get("inter_cmd_delay_ms", 100)),
                ssh_host=str(console.get("ssh_host", "")),
                ssh_username=str(console.get("ssh_username", "root")),
                deploy_scripts=bool(console.get("deploy_scripts", False)),
                scripts_local_dir=str(
                    console.get("scripts_local_dir", "")),
                scripts_remote_dir=str(
                    console.get("scripts_remote_dir", "/root")),
                pull_remote_dir=str(console.get("pull_remote_dir", "")),
                pull_local_dir=str(console.get("pull_local_dir", "")),
                serial_deploy=bool(console.get("serial_deploy", False)),
                serial_deploy_files=[
                    dict(f) for f in
                    (console.get("serial_deploy_files") or [])],
                test_commands=[
                    ConsoleCommand._from_dict_v2(c)
                    for c in (console.get("test_commands") or [])],
                post_rf_commands=[
                    ConsoleCommand._from_dict_v2(c)
                    for c in (console.get("post_rf_commands") or [])],
            ),
            wifi=wifi_cfg,
            bluetooth=bt_cfg,
            setup=FctSetupCfg.from_dict(data.get("setup")),
        )

    # ---------------------------------------------------------- validation
    def validate(self) -> list:
        """Returns a list of error strings (empty = valid).

        M36: there are no master enable switches.  The console section is
        active when it holds a port / endpoint / rows, and each RF module
        is active when at least one of its sub-tests is switched on."""
        errors: list = []
        c, w, b = self.console, self.wifi, self.bluetooth
        rows = list(c.test_commands) + list(c.post_rf_commands)
        console_active = bool(c.port.strip() or c.ssh_host.strip()
                              or c.deploy_scripts or rows)
        if self.dut_type not in ("bare_metal", "linux"):
            errors.append("dut_type must be bare_metal|linux")
        if console_active:
            # only rows that really talk to the DUT over the serial line
            # need a port (Flash_GUI / Delay / host CLI / RF reference
            # rows run without one)
            if not c.port.strip() and any(
                    getattr(r, "transport", "serial") != "ssh"
                    and getattr(r, "kind", "") not in _NO_SERIAL_KINDS
                    for r in rows):
                errors.append("console.port must not be empty "
                              "(serial console rows need a port)")
            if int(c.baudrate) not in BAUDRATES:
                errors.append(f"console.baudrate must be one of "
                              f"{BAUDRATES}")
            if (self.dut_type == "bare_metal" and c.ssh_host.strip()):
                # no OS -> no shell -> no SSH
                errors.append("bare_metal DUT: ssh_host requires "
                              "a Linux shell - remove it")
            if c.deploy_scripts:
                if self.dut_type == "bare_metal":
                    errors.append("bare_metal DUT: script deployment over "
                                  "SFTP needs a Linux shell - disable it")
                else:
                    if not c.scripts_local_dir.strip():
                        errors.append("console.deploy_scripts: "
                                      "scripts_local_dir must not be empty")
                    if not c.scripts_remote_dir.strip():
                        errors.append("console.deploy_scripts: "
                                      "scripts_remote_dir must not be empty")
                    if not c.ssh_host.strip():
                        errors.append("console.deploy_scripts: ssh_host is "
                                      "required for SFTP deployment")
            if self.dut_type == "bare_metal":
                # Bare metal/RTOS still interacts over SERIAL
                # (Wait->Send->Capture, e.g. a Button/LED prompt answered
                # with yes/no), but SSH and SFTP do not exist without an OS.
                for cmd in c.test_commands:
                    if cmd.transport == "ssh":
                        errors.append(
                            f"bare_metal DUT: command '{cmd.name}' uses SSH "
                            "- serial console is the only transport")
                    if cmd.kind in ("sftp_put", "sftp_get"):
                        errors.append(
                            f"bare_metal DUT: command '{cmd.name}' uses "
                            f"{cmd.kind} - SFTP requires a Linux shell")
            # host CLI rows (both command lists): the command is
            # mandatory; it runs on the test PC, not on the DUT
            for cmd in list(c.test_commands) + list(c.post_rf_commands):
                if cmd.kind == KIND_HOST and not cmd.host_cmd.strip():
                    errors.append(
                        f"host CLI row '{cmd.name}': host_cmd must not "
                        "be empty")
        if w.any_enabled:
            if w.scan_via not in WIFI_SCAN_VIA:
                errors.append(f"wifi.scan_via must be one of "
                              f"{WIFI_SCAN_VIA}")
            if w.scan_enabled and not w.ap_ssid.strip():
                errors.append("wifi scan: ap_ssid (hotspot SSID) must not "
                              "be empty")
            if w.scan_timeout < 1 or w.ping_timeout < 1 \
                    or w.iperf_timeout < 1:
                errors.append("wifi timeouts must be >= 1 s")
            if w.ping_enabled:
                if self.dut_type == "bare_metal":
                    errors.append("bare_metal DUT: Wi-Fi ping needs a "
                                  "Linux stack - disable it")
                elif int(w.ping_count) < 1:
                    errors.append("wifi ping: ping_count must be >= 1")
            if w.iperf_enabled:
                if self.dut_type == "bare_metal":
                    errors.append("bare_metal DUT: iperf needs a Linux "
                                  "stack - disable it")
                elif w.iperf_tool not in BW_TOOLS:
                    errors.append(f"wifi iperf: tool must be one of "
                                  f"{BW_TOOLS}")
                elif float(w.iperf_min_mbps) <= 0:
                    errors.append("wifi iperf: iperf_min_mbps must be > 0")
        if b.any_enabled:
            if b.rssi_timeout < 1 or b.pair_timeout < 1 \
                    or b.tone_timeout < 1:
                errors.append("bluetooth timeouts must be >= 1 s")
            if b.rssi_enabled and not b.expected_name.strip():
                errors.append("bluetooth rssi: expected_name (DUT BT name) "
                              "must not be empty")
            if self.dut_type == "bare_metal":
                if b.pair_enabled:
                    errors.append("bare_metal DUT: BT pair/connect needs a "
                                  "Linux stack - disable it")
                if b.tone_enabled:
                    errors.append("bare_metal DUT: BT A2DP tone needs a "
                                  "Linux stack - disable it")
                if b.pair_enabled and b.l2ping_count > 0:
                    errors.append("bare_metal DUT: L2CAP ping runs on the "
                                  "DUT console - set l2ping_count to 0")
        errors.extend(self.setup.validate())
        return errors


# ---------------------------------------------------------------------------
# mapping to B4 FctStep markers (the runner executes THESE)
# ---------------------------------------------------------------------------
def _console_row_steps(cmd: ConsoleCommand, channel_key: str,
                       ssh_host: str = "", ssh_username: str = "root") -> list:
    """One ConsoleCommand row -> its ordered list[FctStep].

    Shared by ``console.test_commands`` (run BEFORE the RF sections)
    and ``console.post_rf_commands`` (run AFTER them).  Host CLI rows
    become EXTERNAL_TOOL steps executed on the HOST PC (see the
    ``fct_host_cmd`` branch in fct_exec).  SFTP rows carry their own
    ssh endpoint (``ssh_host`` / ``ssh_username``) and a dedicated ssh
    channel reference so the runner can bind an SshFctChannel.
    """
    steps: list = []
    if not getattr(cmd, "enabled", True):
        return steps                   # disabled row -> no steps
    # RF reference rows never produce steps through the console path:
    # they are expanded by build_fct_steps (post_rf reference rows are
    # invalid and simply vanish here defensively).
    if getattr(cmd, "kind", "") in (KIND_WIFI_TEST, KIND_BT_TEST):
        return steps
    # Host CLI rows: the command runs on the TEST PC, not on the DUT
    # (e.g. start/stop a local iperf3 server); PASS = exit code 0
    if cmd.kind == KIND_HOST:
        steps.append(FctStep(
            name=cmd.name or "Host CLI",
            step_type=STEP_EXTERNAL_TOOL, channel="",
            timeout_s=float(cmd.timeout or 30.0),
            retries=int(cmd.retries),
            params={"fct_host_cmd": {
                "cmd": cmd.host_cmd,
                "cmd_windows": cmd.host_cmd_windows}}))
        return steps
    # SFTP file-transfer rows: bound to an SSH channel (M27 P8), with
    # the console's ssh endpoint carried on the step (credential layer
    # supplies the password at run time - never the YAML).
    if cmd.kind in ("sftp_put", "sftp_get"):
        steps.append(FctStep(
            name=cmd.name or cmd.kind,
            step_type=STEP_MESSAGE_CHECK, channel="ssh",
            timeout_s=float(cmd.send_timeout),
            retries=int(cmd.retries),
            params={"fct_console": True, "kind": cmd.kind,
                    "action": cmd.kind,
                    "local": cmd.local, "remote": cmd.remote,
                    "ssh_host": ssh_host,
                    "ssh_username": ssh_username or "root"}))
        return steps
    # Flash_GUI row (M33): launch (or reuse) the third-party flash GUI
    # on the HOST PC, then take the operator Go / Stop answer as the
    # verdict (Go -> continue, Stop -> FAIL and stop the sequence).
    if cmd.kind == KIND_FLASH_GUI:
        steps.append(FctStep(
            name=cmd.name or "Flash_GUI",
            step_type=STEP_GUI_CONFIRM, channel="",
            timeout_s=float(cmd.timeout or 30.0),
            retries=0,
            params={"style": DIALOG_GOSTOP,
                    "message": cmd.flash_gui_message
                    or DEFAULT_FLASH_GUI_MESSAGE,
                    "flash_gui_path": cmd.flash_gui_path}))
        return steps
    # Delay row (M35): a plain fixed wait - no console, no instrument.
    # The step timeout still bounds the maximum execution time.
    if cmd.kind == KIND_DELAY:
        steps.append(FctStep(
            name=cmd.name or "Delay",
            step_type=STEP_EXTERNAL_TOOL, channel="",
            timeout_s=float(cmd.timeout or 0.0),
            retries=int(cmd.retries),
            params={"fct_delay_ms": max(0, int(cmd.wait_ms))}))
        return steps
    # Console-domain operator-dialog rows (MessageOKtoConsole /
    # MessageYesNotoConsole / MessageGoStoptoConsole, user direction
    # 2026-10-18): the row WAITS the expected console message from the
    # bound DUT console, THEN notifies the operator.  OK sends nothing
    # (non-blocking), YesNo / GoStop send send_yes / send_no (default y
    # / n); the row joins the ordered sequence exactly where it is
    # placed.  Legacy rows without an expected message simply skip the
    # wait phase.
    if cmd.kind == KIND_MESSAGE:
        steps.append(FctStep(
            name=cmd.name or "Operator message",
            step_type=STEP_GUI_CONFIRM, channel=channel_key,
            timeout_s=float(cmd.wait_timeout or 10.0),
            retries=int(cmd.retries),
            params={"style": cmd.dialog_style or DIALOG_YESNO,
                    "message": cmd.confirm_message
                    or cmd.name or "Operator message",
                    "send_yes": cmd.send_yes or "y",
                    "send_no": cmd.send_no or "n",
                    "message_timeout_s": float(cmd.timeout or 0.0),
                    "console_dialog": True,
                    "wait_pattern": str(cmd.expect_pass or ""),
                    "wait_timeout": float(cmd.wait_timeout or 10.0),
                    "wait_is_regex": bool(cmd.expect_pass_is_regex),
                    "case_sensitive": bool(cmd.case_sensitive)}))
        return steps
    # Map the three-stage model to the MESSAGE_CHECK executor.
    #   WaitFor (wait-only row) -> positive pattern, found=PASS
    #   Capture expected=yes  -> positive=want, negative=forbid
    #   Capture expected=no   -> negative=bad msg, End Line bounds
    is_wait_only = (cmd.wait_enabled and not cmd.send_enabled)
    if is_wait_only:
        pass_pat, neg_pat = cmd.expect_pass, ""
        pass_regex = cmd.expect_pass_is_regex
        neg_regex = False
        is_expected = True
        end_line = ""
    else:
        if cmd.capture_enabled and cmd.capture_is_expected:
            pass_pat, neg_pat = cmd.expect_fail, cmd.capture_forbid
        elif cmd.capture_enabled:
            pass_pat, neg_pat = "", cmd.expect_fail
        else:
            pass_pat, neg_pat = "", ""
        pass_regex = cmd.expect_fail_is_regex
        neg_regex = cmd.expect_fail_is_regex
        is_expected = (cmd.capture_is_expected
                       if cmd.capture_enabled else False)
        end_line = cmd.capture_end_line
    params: dict = {
        "fct_console": True,
        "kind": "wait" if is_wait_only else "send",
        "wait_enabled": cmd.wait_enabled,
        "send_enabled": cmd.send_enabled,
        "capture_enabled": cmd.capture_enabled,
        "wait_pattern": cmd.expect_pass,
        "wait_timeout": float(cmd.wait_timeout),
        "wait_is_regex": bool(cmd.expect_pass_is_regex),
        "send_timeout": float(cmd.send_timeout),
        "capture_timeout": float(cmd.timeout),
        "capture_end_line": end_line,
        "capture_is_expected": is_expected,
        "case_sensitive": cmd.case_sensitive,
        "confirm_message": str(cmd.confirm_message or ""),
        "expect_pass_re": pass_pat,
        "expect_fail_re": neg_pat,
        "expect_pass_is_regex": pass_regex,
        "expect_fail_is_regex": neg_regex,
        "parse_summary": bool(cmd.parse_summary),
    }
    base_name = cmd.name or cmd.send or "Console step"
    confirm = bool(getattr(cmd, "confirm_enabled", False))
    if confirm:
        # M27 P9: the answer ("y"/"n") travels in the explicit dialog
        # step, NOT also on this console row - exactly one sender.  The
        # serial send is cleared and the dialog's send_yes carries it.
        params["send_enabled"] = False
        params.pop("send", None)
    elif cmd.send_enabled and (cmd.send or cmd.kind == "send"):
        params["send"] = cmd.send
    # ONE step per console row (unified model 2026-10-28): the old
    # "(wait)" pre-step + main step split is gone; wait / send /
    # capture are stages of the SAME interact step, so the yaml, the
    # step editor and the Test Work Flow table all show one row.
    steps.append(FctStep(
        name=base_name,
        step_type=STEP_MESSAGE_CHECK, channel=channel_key,
        timeout_s=float(cmd.timeout), retries=int(cmd.retries),
        params=params))
    # An operator confirmation is an EXPLICIT dialog step placed right
    # after the row (model item 3: nothing pops implicitly any more).
    if confirm:
        steps.append(FctStep(
            name=f"Confirm: {base_name}",
            step_type=STEP_GUI_CONFIRM, channel="",
            timeout_s=0.0,
            params={"style": DIALOG_YESNO, "console_dialog": True,
                    "message": str(cmd.confirm_message or base_name),
                    "wait_pattern": "", "wait_timeout": 0.0,
                    "send_yes": cmd.send_yes or cmd.send or "y",
                    "send_no": cmd.send_no or "n",
                    "message_timeout_s": float(cmd.timeout or 4.0)}))
    return steps


def _serial_deploy_step(c: "ConsoleCfg", channel_key: str) -> "FctStep":
    """Build the serial asset-deploy step (params.fct_serial_push) that
    runs right after the console login.  Files are the configured
    {local, remote, optional unzip} entries."""
    files: list = []
    for spec in c.serial_deploy_files:
        entry = {"local": str(spec.get("local", "")),
                 "remote": str(spec.get("remote", ""))}
        if spec.get("unzip"):
            entry["unzip"] = str(spec["unzip"])
        files.append(entry)
    return FctStep(
        name="Deploy test assets to DUT",
        step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
        timeout_s=300.0,
        params={"fct_serial_push": {"files": files}})


def _rf_driver_step(cfg: FctTestConfig, channel_key: str) -> "FctStep":
    """The one-time Wi-Fi/BT driver load (Linux only, editable command)."""
    return FctStep(
        name="Load RF drivers",
        step_type=STEP_MESSAGE_CHECK, channel=channel_key,
        timeout_s=15.0,
        params={"fct_console": True,
                "send": cfg.wifi.driver_load_cmd.strip()})


def _bt_piscan_step(channel_key: str) -> "FctStep":
    """Make the DUT discoverable first (hciconfig piscan, Linux only)."""
    return FctStep(
        name="BT discoverable (piscan)",
        step_type=STEP_MESSAGE_CHECK, channel=channel_key,
        timeout_s=3.0,
        params={"fct_console": True,
                "send": "hciconfig hci0 piscan"})


def _wifi_subtest_steps(cfg: FctTestConfig, subtest: str,
                        channel_key: str) -> list:
    """One Wi-Fi sub-test (scan|ping|iperf) -> its list[FctStep].

    Returns [] when the module / sub-test is disabled or the sub-test is
    Linux-only on a bare-metal DUT."""
    w = cfg.wifi
    if subtest == "scan":
        if not w.scan_enabled:
            return []
        rf = {"mode": "rssi_only", "ssid": w.ap_ssid,
              "expected_ssid": w.ap_ssid,
              "rssi_min": int(w.rssi_min),
              "interface": w.interface}
        if cfg.dut_type == "linux" and w.scan_via == "dut_console":
            return [FctStep(
                name="Wi-Fi Scan / RSSI (DUT console)",
                step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
                timeout_s=float(w.scan_timeout),
                params={"tool_family": "wifi",
                        "rssi_via": "dut_console", "fct_rf": rf})]
        return [FctStep(
            name="Wi-Fi Scan / RSSI",
            step_type=STEP_EXTERNAL_TOOL, channel="",
            timeout_s=float(w.scan_timeout),
            params={"tool_family": "wifi", "fct_rf": rf})]
    if subtest == "ping":
        if not (w.ping_enabled and cfg.dut_type == "linux"):
            return []
        # 3 stages over the shared AP - the runner executes Host->AP,
        # DUT->AP, DUT->Host as independent verdicts
        return [FctStep(
            name="Wi-Fi Ping (Host->AP / DUT->AP / DUT->Host)",
            step_type=STEP_EXTERNAL_TOOL, channel="",
            timeout_s=float(w.ping_timeout),
            params={"tool_family": "wifi", "fct_rf": {
                "mode": "full_stack", "ssid": w.ap_ssid,
                "expected_ssid": w.ap_ssid,
                "password": w.ap_password,
                "ssid_password": w.ap_password,
                "ap_ip": w.ap_ip,
                "rssi_min": int(w.rssi_min),
                "ping_count": int(w.ping_count),
                "iperf3": False, "any_reply": True,
                "rf_timeout_s": float(w.ping_timeout)}})]
    if subtest == "iperf":
        if not (w.iperf_enabled and cfg.dut_type == "linux"):
            return []
        return [FctStep(
            name=f"Wi-Fi iPerf Throughput ({w.iperf_tool})",
            step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
            timeout_s=float(w.iperf_timeout),
            params={"tool_family": "wifi",
                    "fct_wifi_iperf": {
                        "tool": w.iperf_tool,
                        "server_ip": w.iperf_server_ip,
                        "min_mbps": float(w.iperf_min_mbps),
                        "duration": int(w.iperf_duration)}})]
    return []


def pair_script_command(script: str, host_name: str, host_addr: str) -> str:
    """Render the DUT-side pair invocation: ``<script> <name> <addr>``.

    Pure text mapping (no I/O); the host name / addr come from
    :func:`mtkgui.engine.host_platform.host_bt_identity` at build time so
    the operator never hard-codes them in the sequence."""
    parts = [str(script), str(host_name).strip(), str(host_addr).strip()]
    return " ".join(p for p in parts if p)


def _bt_subtest_steps(cfg: FctTestConfig, subtest: str,
                      channel_key: str) -> list:
    """One Bluetooth sub-test (rssi|pair|tone) -> its list[FctStep].

    ``pair`` carries the optional L2CAP data-path proof.  The one-time
    piscan step is emitted separately by build_fct_steps before the first
    BT step, preserving the old order."""
    b = cfg.bluetooth
    if subtest == "rssi":
        if not b.rssi_enabled:
            return []
        return [FctStep(
            name="Bluetooth RSSI",
            step_type=STEP_EXTERNAL_TOOL, channel="",
            timeout_s=float(b.rssi_timeout),
            params={"tool_family": "bluetooth", "fct_rf": {
                "mode": "rssi_only",
                "expected_name": b.expected_name,
                "rssi_min": int(b.rssi_min),
                "rf_timeout_s": float(b.rssi_timeout)}})]
    if subtest == "pair":
        if not (b.pair_enabled and cfg.dut_type == "linux"):
            return []
        if b.bt_pair_script:
            # DUT Linux script drives the pair/connect (DUT -> Host); the
            # Host PC BT name + BD addr are passed as ARGUMENTS. Deploy it
            # beforehand with an SFTP put row in the sequence.
            from mtkgui.engine import host_platform
            host_name, host_addr = host_platform.host_bt_identity()
            steps = [FctStep(
                name="Bluetooth Pair & Connect (DUT script)",
                step_type=STEP_MESSAGE_CHECK, channel=channel_key,
                timeout_s=float(b.pair_timeout),
                params={"fct_console": True,
                        "send": pair_script_command(
                            b.bt_pair_script, host_name, host_addr)})]
        else:
            steps = [FctStep(
                name="Bluetooth Pair & Connect",
                step_type=STEP_EXTERNAL_TOOL, channel="",
                timeout_s=float(b.pair_timeout),
                params={"tool_family": "bluetooth", "fct_rf": {
                    "mode": "pair_connect",
                    "expected_name": b.expected_name,
                    "rssi_min": int(b.rssi_min),
                    "rf_timeout_s": float(b.pair_timeout)}})]
        if b.l2ping_count > 0:
            steps.append(FctStep(
                name=f"BT L2CAP ping ({b.l2ping_count})",
                step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
                timeout_s=float(b.pair_timeout),
                params={"tool_family": "bluetooth",
                        "fct_bt_l2ping": {
                            "count": int(b.l2ping_count)}}))
        return steps
    if subtest == "tone":
        if not (b.tone_enabled and cfg.dut_type == "linux"):
            return []
        return [FctStep(
            name="Bluetooth Tone / Music (A2DP)",
            step_type=STEP_EXTERNAL_TOOL, channel="",
            timeout_s=float(b.tone_timeout),
            params={"tool_family": "bluetooth", "fct_rf": {
                "mode": "a2dp_sink",
                "expected_name": b.expected_name,
                "audio_confirm": bool(b.audio_confirm),
                "rf_timeout_s": float(b.tone_timeout)}})]
    return []


def build_fct_steps(cfg: FctTestConfig,
                    channel_key: str = "ser1") -> list:
    """FctTestConfig -> ordered list[FctStep] for the work flow.

    * console login pairs + test commands: MESSAGE_CHECK steps bound
      to `channel_key`; per-step data travels in params
      (``fct_console_cmd`` with regex expects, ``send`` payload);
    * Wi-Fi / Bluetooth: EXTERNAL_TOOL steps carrying the sub-config
      in params (``tool_family`` + ``fct_rf``) — executed by the B5
      runner branch through the B4 rf_adapters.

    m30b: the merged Sequence table is the single ordered source.  An
    enabled Wi-Fi/BT sub-test with a ``wifi_test`` / ``bt_test``
    reference row expands AT that row's position; sub-tests with NO
    reference row still append after the console body exactly as before
    (old project files keep identical semantics)."""
    steps: list = []
    c = cfg.console
    is_linux = cfg.dut_type == "linux"
    driver_needed = bool(
        is_linux and (cfg.wifi.any_enabled or cfg.bluetooth.any_enabled)
        and cfg.wifi.driver_load_cmd.strip())
    expanded: set = set()         # (kind, rf_subtest) reference rows seen
    rf_prologue_done = False      # RF driver load emitted once
    bt_prologue_done = False      # piscan emitted once

    def _emit_rf(family: str, sub_steps: list) -> None:
        """Append RF sub-steps, emitting the one-time driver load (and the
        BT piscan) before the first RF/BT step."""
        nonlocal rf_prologue_done, bt_prologue_done
        if not rf_prologue_done:
            rf_prologue_done = True
            if driver_needed:
                steps.append(_rf_driver_step(cfg, channel_key))
        if family == "bluetooth" and not bt_prologue_done:
            bt_prologue_done = True
            if is_linux:
                steps.append(_bt_piscan_step(channel_key))
        steps.extend(sub_steps)

    # console steps: Wait->Send->Capture primitives (v2 model).  Both DUT
    # kinds use the SAME three-stage flow over serial; a bare-metal/RTOS
    # firmware can prompt and accept replies too (e.g. Button/LED: wait
    # for the prompt -> send yes/no -> capture the result).  The only
    # console difference is that a bare-metal DUT has no SSH/SFTP
    # transport; RF stays RSSI-only.  (M36: no master switch - the rows
    # themselves are the source of truth.)
    for cmd in c.test_commands:
        kind = str(getattr(cmd, "kind", "") or "")
        if kind in (KIND_WIFI_TEST, KIND_BT_TEST):
            subtest = str(getattr(cmd, "rf_subtest", "") or "")
            family = "wifi" if kind == KIND_WIFI_TEST else "bluetooth"
            key = (kind, subtest)
            if subtest and key not in expanded:
                sub_steps = (_wifi_subtest_steps(cfg, subtest, channel_key)
                             if family == "wifi" else
                             _bt_subtest_steps(cfg, subtest, channel_key))
                if sub_steps:
                    expanded.add(key)
                    _emit_rf(family, sub_steps)
            continue
        steps.extend(_console_row_steps(cmd, channel_key,
                                        c.ssh_host, c.ssh_username))
        # Serial asset provisioning right after the login (a fresh DUT
        # has no scripts / board-test package; no SSH yet).
        if c.serial_deploy and "login" in str(
                getattr(cmd, "name", "")).lower():
            steps.append(_serial_deploy_step(c, channel_key))
    # Backward-compatible fallback: enabled RF sub-tests with NO reference
    # row still expand after the console body in the old fixed order.
    for kind, subtests in ((KIND_WIFI_TEST, ("scan", "ping", "iperf")),
                           (KIND_BT_TEST, ("rssi", "pair", "tone"))):
        family = "wifi" if kind == KIND_WIFI_TEST else "bluetooth"
        for subtest in subtests:
            if (kind, subtest) in expanded:
                continue
            sub_steps = (_wifi_subtest_steps(cfg, subtest, channel_key)
                         if family == "wifi" else
                         _bt_subtest_steps(cfg, subtest, channel_key))
            if sub_steps:
                expanded.add((kind, subtest))
                _emit_rf(family, sub_steps)
    # Post-RF teardown rows ('shutdown now', stopping the host-side
    # iperf3 server, ...) - appended AFTER the Wi-Fi/BT sections so the
    # DUT stays up while any RF sub-test can still run.  Each row is
    # tagged params.teardown=True so the runner executes it EVEN on an
    # abort (stop_if_failure) — teardown must never be skipped.
    for cmd in c.post_rf_commands:
        for step in _console_row_steps(cmd, channel_key,
                                       c.ssh_host, c.ssh_username):
            step.params = dict(step.params or {})
            step.params["teardown"] = True
            steps.append(step)
    return steps


def _fct_op_step(name: str) -> "FctStep":
    """A standard-operation row (fixture / rack PSU) reused from the
    engine OP_STEPS catalog; ``params.op`` makes to_project_fct_cases
    emit an ``op`` row executed by the standard op runner."""
    return FctStep(name=name, step_type=STEP_GUI_CONFIRM, timeout_s=0.0,
                   params={"op": name})


def _dedupe_steps(steps: list) -> list:
    """Drop EXACT duplicate steps (one shared implementation with
    ``fct_build.dedupe_steps`` so a phantom row can never survive a
    load/save, M22/M26)."""
    return dedupe_steps(steps)


def wrap_fct_setup(cfg: FctTestConfig, body: list,
                   channel_key: str = "ser1") -> list:
    """Wrap the generated FCT test body with the production spine.

    Order: optional fixture clamp/lock/E-Stop -> power on (rack PSU op OR
    a manual adapter/USB MessageGoStop OR nothing) -> body -> power off /
    manual remove prompt -> fixture unlock/release.

    M22: the spine NEVER auto-appends a closing "FCT done." row any
    more - that duplicate was re-created on every overwrite and the
    operator could not delete it.  A closing dialog belongs to the
    project ``post_rf_commands`` (visible/editable) only.  Exact
    duplicate steps are removed so a legacy YAML that still carries the
    old auto row loads as ONE row.

    FCT uses NO DAQ; the ATE fixture (when present) is driven through the
    U2355A DIO resource on the real rack (the op names are shared with
    ICT; the instrument routing is resolved at run time).
    """
    s = cfg.setup
    pre: list = []
    post: list = []
    if s.use_fixture:
        pre += [_fct_op_step("Fixture Clamp Down"),
                _fct_op_step("Fixture Lock"),
                _fct_op_step("Fixture E-Stop Healthy")]
        post += [_fct_op_step("Fixture Unlock"),
                 _fct_op_step("Fixture Release")]
    if s.power_mode == POWER_PSU:
        pre.append(_fct_op_step("Power On DUT"))
        post.insert(0, _fct_op_step("Power Off DUT"))
    elif s.power_mode == POWER_MANUAL:
        pre.append(FctStep(name=s.manual_on_message,
                           step_type=STEP_GUI_CONFIRM, timeout_s=0.0))
        post.insert(0, FctStep(name=s.manual_off_message,
                               step_type=STEP_GUI_CONFIRM, timeout_s=0.0))
    # power_mode == POWER_NONE: no power action
    return _dedupe_steps(pre + list(body) + post)

