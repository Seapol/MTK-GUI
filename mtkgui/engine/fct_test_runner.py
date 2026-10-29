# -*- coding: utf-8 -*-
"""fct_test_runner — P3-B5 FCT test executor.

* ``console_send_and_expect`` — the spec §4.2 output-stream matching
  algorithm: reset the input buffer, send, keep reading within the
  timeout, ``expect_fail`` wins over ``expect_pass`` (regex), timeout
  returns ``TIMEOUT`` (FAIL) — never blocks forever;
* ``FctTestRunner`` — orchestrates one FCT cycle for a Linux DUT:
  console login + test commands (serial), the DUT driver-load command
  (serial), then the host-side RF tests through the B4 adapters
  (``WifiAdapter`` / ``BluetoothAdapter``); produces per-step results
  and the plain-text report (spec §5.3).

Engine layer: no Qt.  The serial side is any pyserial-like object
(``write(bytes)`` / ``read(n)`` / ``reset_input_buffer()``) — the
real bench uses ``serial.Serial``, tests use fakes.
"""
from __future__ import annotations

import re
import time
from datetime import datetime

from .fct_test_config import FctTestConfig


def host_lan_ip() -> str:
    """Best-effort Host PC LAN IPv4 (iperf server address the DUT client
    connects to). macOS: ipconfig getifaddr en0..; Linux: hostname -I."""
    import platform
    import subprocess
    if platform.system() == "Darwin":
        tries = [["ipconfig", "getifaddr", ifc]
                 for ifc in ("en0", "en1", "en2")]
    else:
        tries = [["hostname", "-I"], ["ip", "-4", "addr"]]
    for cmd in tries:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=5).stdout.split()
        except Exception:                   # noqa: BLE001
            continue
        for tok in out:
            parts = tok.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                a, b = int(parts[0]), int(parts[1])
                if a not in (0, 127) and not (a == 169 and b == 254):
                    return tok
    return ""

#: host-side (mac) command set — B4-verified on macOS 15 (spec:
#: deprecated airport / networksetup -getairportnetwork are NOT used)
WIFI_MAC_CMDS = {
    "list_networks_cmd":
        "networksetup -listpreferredwirelessnetworks en0",
    "remove_network_cmd":
        'networksetup -removepreferredwirelessnetwork en0 "{{ssid}}"',
    "connect_cmd":
        'networksetup -setairportnetwork en0 "{{ssid}}" "{{password}}"',
    "add_network_cmd":
        'networksetup -addpreferredwirelessnetwork en0 "{{ssid}}"',
    "rssi_cmd": "system_profiler SPAirPortDataType",
    "rssi_parse": r"Signal / Noise: (-?\d+) dBm",
    "gateway_cmd": "route -n get default",
    "gateway_parse": r"gateway:\s+(\S+)",
    "ping_cmd": "ping -c {{count}} {{gateway}}",
}
BT_MAC_CMDS = {
    "scan_cmd": "blueutil --inquiry {{seconds}}",
    "addr_parse": r"([0-9a-fA-F:-]{17})",
    "connect_cmd": "blueutil --connect {{addr}}",
    "verify_cmd": "blueutil --is-connected {{addr}}",
    "disconnect_cmd": "blueutil --disconnect {{addr}}",
    "rssi_cmd": "system_profiler SPBluetoothDataType",
    "rssi_parse": r"RSSI: (-?\d+)",
    # After blueutil --connect the A2DP sink takes ~1-3 s to enumerate in
    # CoreAudio; switching immediately fails (exit 1). Poll for the output
    # device to appear, then switch (up to ~20 s, inside the tone timeout).
    "audio_switch_cmd": (
        'for i in $(seq 1 20); do '
        'SwitchAudioSource -a 2>/dev/null | grep -qi "{{name}}" && '
        '{ SwitchAudioSource -s "{{name}}" && exit 0; }; '
        'sleep 1; done; exit 1'),
    "tone_cmd": "afplay {{tone}}",
}

#: host-side (Windows) Wi-Fi command set (m23) - built-in ``netsh wlan``
#: family, no external tools.  SAME keys as WIFI_MAC_CMDS.
#: NOTE: the RSSI source is a PERCENTAGE (0-100) of an ideal link, not
#: dBm (netsh exposes no dBm) - the documented approximation: finding
#: the SSID + the signal percentage is still a valid PASS criterion.
#: ``connect_cmd`` requires an existing WLAN profile (first successful
#: connect stores one); the explicit ``add_network_cmd`` needs a profile
#: XML and is intentionally unsupported (the competing-network restore
#: treats its failure as a warning, macOS auto-rejoin has no Windows
#: equivalent).
WIFI_MAC_CMDS_WINDOWS = {
    "list_networks_cmd": "netsh wlan show networks",
    "remove_network_cmd": 'netsh wlan delete profile name="{{ssid}}"',
    "connect_cmd": 'netsh wlan connect name="{{ssid}}"',
    "add_network_cmd":
        'cmd /c echo explicit profile add needs a profile XML on '
        'Windows (first connect stores it) & exit 1',
    "rssi_cmd": "netsh wlan show networks mode=bssid",
    "rssi_parse": r"Signal\s*:\s*(\d+)%",
    "gateway_cmd":
        'powershell -NoProfile -Command "Get-NetIPConfiguration | '
        'Where-Object {$_.IPv4DefaultGateway} | Select-Object -First 1 '
        '-ExpandProperty IPv4DefaultGateway -ExpandProperty NextHop"',
    "gateway_parse": r"(\d+\.\d+\.\d+\.\d+)",
    "ping_cmd": "ping -n {{count}} {{gateway}}",
    # English Windows ping: "Lost = 0 (0% loss)" - NOT "% packet loss"
    "ping_loss_parse": r"\((\d+(?:\.\d+)?)% ?loss\)",
}
#: Bluetooth: Windows has NO built-in classic-BT RSSI / A2DP CLI.  There
#: is deliberately NO BT command table for windows -
#: host_platform.bt_backend_cmds() raises PlatformBackendMissing with
#: user guidance through the existing fct_exec hint path (explicit
#: ERROR, never a silent PASS, never a traceback).  Decision recorded
#: in reports/m23_host_platform_acceptance.txt.


# ---------------------------------------------------------------------------
# fat.py Summary parsing (per-item report rows)
# ---------------------------------------------------------------------------
#: ANSI escape sequences in DUT console output (SGR colors, cursor ops
#: incl. clear-line [K, OSC strings) — stripped before matching/reporting
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*(?:\x07|\x1b\\)")

#: one fat.py Summary table row (ANSI stripped), e.g.
#: ``20      USB1_C / USB2_A U-disk read/write speed       FAIL          99.50s``
FAT_SUMMARY_ROW_RE = re.compile(
    r"^\s*(\d+)\s+(.+?)\s{2,}(PASS|FAIL|WARN|INFO|SKIP)\s+([\d.]+)s\s*$")


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences and normalize \\r line ends to \\n."""
    return ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def parse_fat_summary(text: str) -> list:
    """Parse a fat.py ``Summary:`` table into per-test rows.

    Returns ``[(index, name, status, duration), ...]`` (duration keeps
    its ``s`` suffix, status is PASS/FAIL/WARN/INFO/SKIP verbatim);
    empty when no Summary block is present.  Only lines after the LAST
    ``Summary:`` anchor are considered, so earlier chatter cannot
    produce phantom rows."""
    stripped = strip_ansi(text)
    anchor = stripped.rfind("Summary:")
    if anchor < 0:
        return []
    rows = []
    for line in stripped[anchor:].splitlines():
        m = FAT_SUMMARY_ROW_RE.match(line)
        if m:
            rows.append((int(m.group(1)), m.group(2).strip(),
                         m.group(3), m.group(4) + "s"))
    return rows


# ---------------------------------------------------------------------------
# console matching primitives (spec §4.1 / §4.2)
# ---------------------------------------------------------------------------
def match_expectation(text: str, expect_pass: str,
                      expect_fail: str,
                      expect_pass_is_regex: bool = False,
                      expect_fail_is_regex: bool = False,
                      case_sensitive: bool = True) -> tuple:
    """Judgement over the accumulated output (fail wins).

    Default: exact substring match. Set *_is_regex=True for regex mode.
    Set case_sensitive=False to ignore case (PASS = pass).
    Empty patterns mean "no opinion" (pass needs SOME output).
    Returns ``(verdict, detail)`` with verdict PASS/FAIL.
    """
    flags = 0 if case_sensitive else re.IGNORECASE

    def _matches(pattern: str, is_regex: bool, sample: str):
        if is_regex:
            return re.search(pattern, sample, flags)
        if case_sensitive:
            return pattern in sample
        return pattern.lower() in sample.lower()

    if expect_fail:
        m = _matches(expect_fail, expect_fail_is_regex, text)
        if m:
            hit = m.group(0) if expect_fail_is_regex else expect_fail
            return "FAIL", f"matched expect_fail '{hit}'"
    if expect_pass:
        m = _matches(expect_pass, expect_pass_is_regex, text)
        if m:
            hit = m.group(0) if expect_pass_is_regex else expect_pass
            return "PASS", f"matched '{hit}'"
        return "", ""
    return ("PASS", "output present") if text.strip() else ("", "")


def console_send_and_expect(serial, cmd: str, expect_pass: str,
                            expect_fail: str, timeout: float,
                            expect_pass_is_regex: bool = False,
                            expect_fail_is_regex: bool = False,
                            case_sensitive: bool = True) -> tuple:
    """Send one or more commands (multi-line = sequential sends) over
    the console, then judge the reply stream.

    Behavior:
    1. reset_input_buffer() BEFORE sending (stale output ignored)
    2. Split cmd by newlines, send each line sequentially
    3. After ALL commands sent, read inside `timeout` and judge output
       with expect_pass / expect_fail (fail wins)
    4. On timeout return TIMEOUT (caller treats as FAIL) — station never hangs.

    Args:
        serial: pyserial-like (write / read / reset_input_buffer).

    Returns:
        ``(verdict, text)`` — verdict in PASS / FAIL / TIMEOUT.
    """
    serial.reset_input_buffer()
    # send all lines sequentially
    lines = [l for l in cmd.splitlines() if l.strip()]
    for line in lines:
        serial.write((line + "\n").encode())
        time.sleep(0.05)  # small gap between sends
    # now judge the accumulated output within timeout
    start = time.time()
    buffer = b""
    while time.time() - start < max(timeout, 0.1):
        chunk = serial.read(4096)
        if chunk:
            buffer += chunk
            text = buffer.decode("utf-8", errors="replace")
            verdict, _ = match_expectation(
                text, expect_pass, expect_fail,
                expect_pass_is_regex, expect_fail_is_regex,
                case_sensitive)
            if verdict:
                return verdict, text
        time.sleep(0.05)
    return "TIMEOUT", buffer.decode("utf-8", errors="replace")


def _pattern_hit(pattern: str, is_regex: bool, case_sensitive: bool,
                 text: str) -> bool:
    """True if pattern matches text (regex or exact substring)."""
    if not pattern:
        return False
    if is_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.search(pattern, text, flags) is not None
    if case_sensitive:
        return pattern in text
    return pattern.lower() in text.lower()


def _read_until(serial, stop_fn, timeout: float,
                history: str = "") -> tuple:
    """Drain the console into a buffer until stop_fn(text)->True or
    timeout. Returns (status, text): status is whatever stop_fn returns
    truthy-as (a non-empty string verdict), else 'TIMEOUT'.  `history`
    is prior session output prepended to the judgement text (the stop
    function sees history + fresh bytes)."""
    start = time.time()
    buffer = history.encode("utf-8", errors="replace")
    while time.time() - start < max(timeout, 0.1):
        chunk = serial.read(4096)
        if chunk:
            buffer += chunk
        # judge on every pass: a history-only match (no fresh bytes)
        # must return immediately
        text = buffer.decode("utf-8", errors="replace")
        verdict = stop_fn(text)
        if verdict:
            return verdict, text
        time.sleep(0.05)
    return "TIMEOUT", buffer.decode("utf-8", errors="replace")


def wait_stage(serial, pattern: str, is_regex: bool, case_sensitive: bool,
               timeout: float, history: str = "") -> tuple:
    """Wait stage: block until `pattern` appears or timeout.

    Used to find the right moment to send (e.g. a login prompt). The
    prompt is static (printed once), so do NOT reset the buffer here:
    a prompt already present must match immediately. Send resets the
    buffer before writing. `history` is prior session output (see
    FctTestRunner._con_hist): a prompt consumed by an earlier row's
    capture still matches here, mirroring the GUI accumulated-buffer
    semantics. Returns ('PASS', text) on hit,
    ('TIMEOUT', text) on timeout."""
    def _stop(text):
        return "PASS" if _pattern_hit(pattern, is_regex,
                                      case_sensitive, text) else ""
    return _read_until(serial, _stop, timeout, history=history)


def send_stage(serial, cmd: str, timeout: float) -> tuple:
    """Send stage: send each non-empty line (newline auto-appended).

    A normal write returns immediately. The timeout guards against a
    stuck serial / dead DUT blocking the write. Returns ('PASS','') on
    success, ('FAIL', detail) if the write cannot complete.
    """
    lines = cmd.splitlines()
    if not lines:
        # empty command: send a single newline (e.g. blank password)
        lines = [""]
    old_wto = getattr(serial, "write_timeout", None)
    try:
        if hasattr(serial, "write_timeout"):
            serial.write_timeout = max(timeout, 0.1)
        # clear stale bytes once, BEFORE writing: the command echo and
        # its result that arrive after this are what Capture judges
        if hasattr(serial, "reset_input_buffer"):
            serial.reset_input_buffer()
        for line in lines:
            serial.write((line + "\n").encode())
            time.sleep(0.05)
        if hasattr(serial, "flush"):
            serial.flush()
        return "PASS", ""
    except Exception as e:  # serial write timeout / port gone / DUT dead
        return "FAIL", f"send error: {e}"
    finally:
        if hasattr(serial, "write_timeout"):
            serial.write_timeout = old_wto


def capture_stage(serial, pattern: str, end_line: str, expected: bool,
                  is_regex: bool, case_sensitive: bool,
                  timeout: float, forbid: str = "",
                  history: str = "") -> tuple:
    """Capture stage: judge the output after commands were sent.

    expected=True  : pattern found = PASS; end_line reached without
                     pattern = FAIL; timeout = FAIL.
    expected=False : pattern found = FAIL; end_line reached without
                     pattern = PASS; timeout without end_line = FAIL
                     (or PASS if no end_line is defined AND the DUT
                     actually produced output in this window).
    `forbid` is an optional negative keyword that fails immediately
    whenever it appears (legacy expect_fail alongside a positive).
    `history` is prior session output prepended to the judgement text
    (capture-only rows look back at the whole transcript — "from the
    console start to the End Line"); send rows pass "" so ONLY bytes
    received after the send-time buffer reset are judged.
    Reverse validation: a window with ZERO received bytes (dead DUT /
    dead link) always FAILs — silence can never satisfy a capture.
    """
    def _stop(text):
        if forbid and _pattern_hit(forbid, is_regex, case_sensitive, text):
            return "FAIL"
        found = _pattern_hit(pattern, is_regex, case_sensitive, text)
        ended = _pattern_hit(end_line, is_regex, case_sensitive, text) \
            if end_line else False
        if expected:
            if found:
                return "PASS"
            if ended:
                return "FAIL"
        else:
            if found:
                return "FAIL"
            if ended:
                return "PASS"
        return ""

    verdict, text = _read_until(serial, _stop, timeout, history=history)
    fresh = text[len(history):] if history and text.startswith(history) \
        else text
    if verdict == "TIMEOUT":
        if not text.strip():
            # nothing received at all (dead DUT / dead link): FAIL
            # regardless of expected / end_line — silence is no evidence
            return "FAIL", "no console output (DUT unresponsive?)"
        if not expected and not end_line:
            # no end line defined: survived the whole window without the
            # unwanted message -> PASS, but ONLY when the DUT actually
            # spoke in this window (fresh bytes, not stale history)
            if fresh.strip() \
                    and not _pattern_hit(pattern, is_regex, case_sensitive,
                                         text) \
                    and not (forbid and _pattern_hit(forbid, is_regex,
                                                     case_sensitive, text)):
                return "PASS", text
            return "FAIL", "no console output in capture window"
    return verdict, text



def host_bt_address(host_runner) -> str:
    """The host PC's own Bluetooth address (system_profiler); empty
    when not determinable."""
    if host_runner is None:
        return ""
    res = host_runner.run("system_profiler SPBluetoothDataType",
                          timeout_s=15)
    m = re.search(r"Address:\s*([0-9A-Fa-f:]{17})", "\n".join(res.lines))
    return m.group(1) if m else ""


def _console_probe(serial, cmd: str, expect: str, timeout: float):
    """Console probe whose `expect` is always a REGEX (RSSI/ping/iperf/
    l2ping summaries are parsed by the caller)."""
    return console_send_and_expect(serial, cmd, expect, "", timeout,
                                   expect_pass_is_regex=True)


def dut_wifi_ping(serial, gateway: str, count: int,
                  loss_max: float, interface: str = "") -> tuple:
    """DUT-side ping of the gateway: PASS when packet loss <= loss_max.

    ``interface`` (e.g. "mlan0") forces the source interface so the
    ping provably traverses the Wi-Fi link the FCT steps depend on."""
    iface = f"-I {interface} " if interface else ""
    verdict, text = _console_probe(
        serial, f"ping {iface}-c {count} {gateway}",
        r"\d+ (?:packets )?received, [\d.]+% packet loss", count + 10.0)
    m = re.search(r"(\d+) (?:packets )?received, ([\d.]+)% packet loss",
                  text)
    if not m:
        return "FAIL", ("TIMEOUT waiting for ping summary"
                        if verdict == "TIMEOUT" else "no ping summary")
    received, loss = int(m.group(1)), float(m.group(2))
    ok = received == count and loss <= loss_max
    return ("PASS" if ok else "FAIL",
            f"loss {loss}% ({received}/{count}) vs max {loss_max}%")


def dut_default_gateway(serial) -> str:
    """DUT default gateway (= the hotspot AP) via ``ip route``."""
    try:
        _, text = _console_probe(serial, "ip route | grep default",
                                 r"default via \S+", 8.0)
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", text)
        return m.group(1) if m else ""
    except Exception:
        return ""


def dut_wifi_iperf(serial, tool: str, server_ip: str, min_mbps: float,
                   duration: int = 10) -> tuple:
    """DUT-side iperf (client -> host PC server): PASS when the
    receiver bitrate >= min_mbps.  iperf3 prints a receiver summary;
    iperf2's last bitrate line is used (auto-scaled M/G normalised)."""
    if tool == "iperf3":
        cmd = f"iperf3 -c {server_ip} -t {duration} -O 1"
        expect = r"\d+\.\d+\s+[MG]bits/sec.*receiver"
    else:                                   # iperf2
        cmd = f"iperf -c {server_ip} -t {duration} -i 1"
        expect = r"\d+\.\d+\s+[MG]bits/sec"
    verdict, text = _console_probe(serial, cmd, expect,
                                   duration + 25.0)
    m = re.findall(r"([\d.]+)\s+([MG])bits/sec", text)
    if not m:
        return "FAIL", ("TIMEOUT waiting for iperf summary"
                        if verdict == "TIMEOUT"
                        else f"no iperf summary (server {server_ip} "
                             "reachable?)")
    val, unit = m[-1]
    mbps = float(val) * (1000.0 if unit.upper() == "G" else 1.0)
    ok = mbps >= min_mbps
    return ("PASS" if ok else "FAIL",
            f"{mbps:.1f} Mbps vs min {min_mbps} Mbps")


def dut_bt_l2ping(serial, host_runner, count: int) -> tuple:
    """Bluetooth data-transfer proof: L2CAP echo ping from the DUT to
    the HOST PC's Bluetooth adapter (real payload echoed both ways).
    PASS when 0% loss (all pings answered)."""
    addr = host_bt_address(host_runner)
    if not addr:
        return "FAIL", "host Bluetooth address not found"
    verdict, text = _console_probe(
        serial, f"l2ping -c {count} {addr}",
        r"\d+ sent, \d+ received, [\d.]+% loss", count * 3.0 + 10.0)
    m = re.search(r"(\d+) sent, (\d+) received, ([\d.]+)% loss", text)
    if not m:
        return "FAIL", ("TIMEOUT waiting for l2ping summary"
                        if verdict == "TIMEOUT" else
                        f"no l2ping summary (host {addr})")
    sent, received, loss = (int(m.group(1)), int(m.group(2)),
                            float(m.group(3)))
    ok = received == sent == count and loss == 0.0
    return ("PASS" if ok else "FAIL",
            f"l2ping {addr}: {received}/{sent}, {loss}% loss")


class ConsoleSerialShim:
    """Adapts a ConsoleBufferChannel to the pyserial-like interface
    (write / read / reset_input_buffer) the dut_* helpers expect."""

    def __init__(self, channel) -> None:
        self._ch = channel
        self._buf = b""

    def reset_input_buffer(self) -> None:
        self._buf = b""

    def write(self, data) -> int:
        self._ch.write(data)
        return len(data)

    def read(self, n: int = 4096) -> bytes:
        lines = self._ch.read_lines(max_lines=500)
        if lines:
            self._buf += ("\n".join(lines) + "\n").encode()
        out, self._buf = self._buf[:n], self._buf[n:]
        return out


# ---------------------------------------------------------------------------
# the orchestrator
# ---------------------------------------------------------------------------
class FctStepResult:
    """One executed FCT step (report row)."""

    #: verdicts that do NOT fail the unit: fat.py Summary rows carry
    #: their real status (INFO/WARN/SKIP) but only FAIL/TIMEOUT/ERROR
    #: count as failures
    NON_FAIL = ("PASS", "INFO", "SKIP", "WARN")

    def __init__(self, name: str, verdict: str, detail: str = "",
                 duration: float = 0.0) -> None:
        self.name = name
        self.verdict = verdict          # PASS / FAIL / TIMEOUT / ERROR
                                        # / INFO / WARN / SKIP (summary rows)
        self.detail = detail
        self.duration = float(duration)  # step wall time, seconds

    @property
    def passed(self) -> bool:
        return self.verdict in self.NON_FAIL


class FctTestRunner:
    """Executes one FCT cycle from an :class:`FctTestConfig`."""

    def __init__(self, config: FctTestConfig, log_sink=None,
                 station_id: str = "", user: str = "",
                 scripts_base_dir: str = "") -> None:
        self.cfg = config
        self._log = log_sink or (lambda _m: None)
        self.station_id = station_id
        self.user = user
        # Used to resolve a relative console.scripts_local_dir (the YAML
        # folder in the GUI, the package root in a frozen Windows build).
        self.scripts_base_dir = scripts_base_dir
        # Session transcript of console output (capture-only rows look
        # back through it: "capture from the console start to the
        # End Line", e.g. the fat.py Summary printed inside an earlier
        # row's read window).
        self._con_hist = ""
        # Fresh window: bytes RECEIVED SINCE THE LAST SEND.  A WAIT
        # stage judges only this window, so a prompt that appeared
        # BEFORE the previous command was sent (session history /
        # stale OS buffer) can never satisfy it — a recurring prompt
        # must appear AGAIN after the previous send.  This is what
        # keeps the sequence synchronous with the DUT (no row can run
        # ahead of the previous command's completion) and what makes a
        # dead DUT fail its WAIT instead of sailing through on stale
        # matches.  send_stage resets the OS input buffer at the send
        # moment; the window here restarts at the same point.
        self._cycle = ""
        # {{token}} -> deployment value (set fresh in run(); empty here so
        # _render is safe before a run starts)
        self._cmd_vars: dict = {}

    def _note_fresh(self, text: str, history_len: int = 0) -> None:
        """Record freshly-received console bytes into the session
        transcript and the current fresh window (`text` is
        `history + fresh`; only the tail beyond `history_len` is
        new)."""
        fresh = text[history_len:] if history_len < len(text) else ""
        if not fresh:
            return
        self._con_hist = (self._con_hist + fresh)[-65536:]
        self._cycle = (self._cycle + fresh)[-65536:]

    def _identity(self) -> str:
        return f"[{self.station_id}] [{self.user}]"

    def log(self, message: str) -> None:
        self._log(f"{self._identity()} {message}")

    def _render(self, text: str) -> str:
        """Substitute {{token}} placeholders in a console send / SFTP
        path with the deployment values resolved at run start (Wi-Fi
        SSID / password, Host PC IP, DUT Bluetooth address) - these vary
        per production site and live in the yaml, never in code."""
        if not text or "{{" not in text:
            return text
        for key, val in self._cmd_vars.items():
            text = text.replace("{{" + key + "}}", str(val))
        return text

    # ---------------------------------------------------------- console
    def run_console(self, serial) -> list:
        """Run console test commands.

        Each ConsoleCommand is a Wait -> Send -> Capture pipeline with
        every stage independently enabled. Any stage failure (incl.
        timeout) retries the whole command up to cmd.retries times, then
        FAILs and stops. SFTP rows (sftp_put/sftp_get) run over the SSH
        channel and bypass Wait/Capture. A parse_summary capture row
        expands the captured fat.py Summary table into one FctStepResult
        per test line (appended right after the row itself).
        """
        results: list = []
        c = self.cfg.console
        if not c.enabled or serial is None:
            return results
        for cmd in c.test_commands:
            if not getattr(cmd, "enabled", True):
                self.log(f"console '{cmd.name}' [skip] -> SKIP (disabled)")
                continue
            t0 = time.time()
            verdict, detail, stage, extras = \
                self._run_one_command(serial, cmd)
            label = cmd.name or cmd.send or cmd.expect_pass or "console"
            results.append(FctStepResult(label, verdict, detail,
                                         duration=time.time() - t0))
            results.extend(extras)
            self.log(f"console '{label}' [{stage}] -> {verdict} {detail}")
            for extra in extras:
                self.log(f"  summary row '{extra.name}' -> {extra.verdict}")
            if verdict != "PASS":
                return results  # stop the whole sequence on failure
        return results

    def _run_message_row(self, serial, cmd) -> tuple:
        """Console-domain operator dialog row (kind == "message").

        Phase 1 (user direction 2026-10-18): WAIT the expected console
        message (``expect_pass``).  Phase 2: the dialog answer drives
        the console - MessageOKtoConsole only acks (no command, PASS),
        MessageYesNotoConsole sends send_yes / send_no (PASS either
        way), MessageGoStoptoConsole GO sends send_yes (PASS, run
        continues) and STOP sends send_no (FAIL, the sequence stops).
        A wait or answer timeout FAILs (and stops the run).
        Returns (verdict, detail)."""
        ask = getattr(self, "_human_confirm", None)
        if not callable(ask):
            return "ERROR", "no confirm hook bound"
        if cmd.wait_enabled and cmd.expect_pass:
            verdict, text = wait_stage(
                serial, cmd.expect_pass, cmd.expect_pass_is_regex,
                cmd.case_sensitive, cmd.wait_timeout,
                history=self._cycle)
            self._note_fresh(text or "", len(self._cycle))
            if verdict != "PASS":
                return "FAIL", f"wait timeout, no '{cmd.expect_pass}'"
        answer = ask(cmd.confirm_message or cmd.name or "Confirm?")
        style = cmd.dialog_style or "ok"
        if style == "ok":
            return "PASS", "operator acknowledged (OK)"
        if style == "yesno":
            payload = cmd.send_yes if answer else cmd.send_no
            if payload:
                send_stage(serial, payload, cmd.send_timeout)
            return "PASS", (f"operator answered "
                            f"{'Yes' if answer else 'No'}, "
                            f"sent '{payload}'")
        # gostop
        if not answer:
            if cmd.send_no:
                send_stage(serial, cmd.send_no, cmd.send_timeout)
            return "FAIL", "operator pressed STOP - run stops"
        if cmd.send_yes:
            send_stage(serial, cmd.send_yes, cmd.send_timeout)
        return "PASS", "operator pressed GO, run continues"

    def _run_one_command(self, serial, cmd) -> tuple:
        """Run one ConsoleCommand with retry. Returns (verdict, detail,
        stage, extras) — extras are additional FctStepResult rows (the
        fat.py Summary expansion) appended after the main row."""
        # resolve {{token}} deployment placeholders (per-unit Wi-Fi
        # SSID/password, Host IP, BT address) once at row entry
        cmd.send = self._render(cmd.send)
        cmd.remote = self._render(cmd.remote)
        cmd.local = self._render(cmd.local)
        cmd.send_yes = self._render(cmd.send_yes)
        cmd.send_no = self._render(cmd.send_no)
        attempts = cmd.retries + 1
        last = ("FAIL", "not run", "?", [])
        for attempt in range(attempts):
            # Operator message rows (MessageOK / MessageYesNo /
            # MessageGoStop, user direction 2026-10-14): the operator
            # answer drives the console - OK only acks, YesNo sends
            # send_yes / send_no (PASS either way), GoStop GO sends
            # send_yes (PASS, run continues) and STOP sends send_no
            # (FAIL, the sequence stops).
            if cmd.kind == "message":
                verdict, detail = self._run_message_row(serial, cmd)
                return verdict, detail, "message", []
            # SFTP rows: file transfer over the SSH channel only
            if cmd.kind in ("sftp_put", "sftp_get"):
                verdict, detail = self._run_sftp(serial, cmd)
                if verdict == "PASS":
                    return verdict, detail, "sftp", []
                last = (verdict, detail, "sftp", [])
                if attempt + 1 < attempts:
                    self.log(f"  retry sftp ({attempt + 1}/{cmd.retries})")
                continue
            # three-stage pipeline: Wait -> Send -> Capture
            verdict, detail, stage, extras = self._run_pipeline(serial, cmd)
            if verdict == "PASS":
                return verdict, detail, stage, extras
            last = (verdict, detail, stage, extras)
            if attempt + 1 < attempts:
                self.log(f"  retry {stage} ({attempt + 1}/{cmd.retries})")
        return last

    def _expand_fat_summary(self, text: str) -> tuple:
        """Parse a fat.py Summary table into per-item FctStepResult rows.

        The step row itself PASSes when the Summary was parsed (execution
        success — the per-item FAILs live in the expanded rows, so the
        sequence keeps running); it FAILs when no Summary is present."""
        rows = parse_fat_summary(text)
        if not rows:
            return "FAIL", "no fat.py Summary found in capture", []
        counts: dict = {}
        extras: list = []
        for idx, name, status, dur in rows:
            counts[status] = counts.get(status, 0) + 1
            try:
                seconds = float(dur[:-1])
            except ValueError:
                seconds = 0.0
            extras.append(FctStepResult(
                f"{idx}. {name}", status, f"{status} in {dur}",
                duration=seconds))
        detail = f"{len(rows)} items: " + ", ".join(
            f"{k} {v}" for k, v in sorted(counts.items()))
        return "PASS", detail, extras

    def _run_pipeline(self, serial, cmd) -> tuple:
        """Wait -> Send -> Capture for one command. Returns (verdict,
        detail, stage, extras).

        Timing discipline (v1.0.2): the WAIT stage matches only the
        FRESH WINDOW — bytes received since the last SEND — so a
        recurring command prompt must appear AGAIN after the previous
        command was sent; stale prompts in the session history can
        never let a row run ahead.  The SEND stage resets the OS input
        buffer and restarts the window.  A CAPTURE stage on a send row
        judges only post-send bytes (the echo plus the command's
        output); a capture-only row looks back through the whole
        session transcript (console start -> End Line)."""
        # 1) WAIT (precondition to send, e.g. login prompt or the
        #    shell prompt that proves the PREVIOUS command finished) —
        #    matched against the fresh window only.
        if cmd.wait_enabled and cmd.expect_pass:
            verdict, text = wait_stage(
                serial, cmd.expect_pass, cmd.expect_pass_is_regex,
                cmd.case_sensitive, cmd.wait_timeout,
                history=self._cycle)
            self._note_fresh(text or "", len(self._cycle))
            if verdict != "PASS":
                return "FAIL", f"wait timeout, no '{cmd.expect_pass}'", \
                    "wait", []
        # 1.5) CONFIRM (operator MessageYesNo between Wait and Send,
        # e.g. a fat.py question): No stops the unit with a FAIL and
        # nothing is sent to the DUT.
        if cmd.confirm_enabled:
            ask = getattr(self, "_human_confirm", None)
            if not callable(ask):
                return "ERROR", "no confirm hook bound", "confirm", []
            question = cmd.confirm_message or cmd.name or "Confirm?"
            if not ask(question):
                return "FAIL", "operator answered No", "confirm", []
        # 2) SEND (each line auto-newline; timeout guards a stuck link).
        # kind=send with an empty command still sends one newline
        # (e.g. blank password); a capture-only row sends nothing.
        sent = False
        if (cmd.send_enabled
                and cmd.kind not in ("sftp_put", "sftp_get")
                and (cmd.send or cmd.kind == "send")):
            verdict, detail = send_stage(serial, cmd.send, cmd.send_timeout)
            if verdict != "PASS":
                return "FAIL", detail, "send", []
            # the send-time reset_input_buffer() in send_stage starts a
            # new fresh window: only bytes received AFTER this point
            # (the echo and the command's own output) may satisfy the
            # capture below and any later WAIT stage
            self._cycle = ""
            sent = True
        # 3) CAPTURE (judge the resulting output within capture timeout)
        if cmd.capture_enabled and cmd.expect_fail:
            # send row  -> judge ONLY the post-send bytes (fresh window;
            #              the echo cannot be confused with earlier output)
            # capture-only row -> look back at the whole session
            #              transcript (console start -> End Line)
            history = "" if sent else self._con_hist
            verdict, text = capture_stage(
                serial, cmd.expect_fail, cmd.capture_end_line,
                cmd.capture_is_expected, cmd.expect_fail_is_regex,
                cmd.case_sensitive, cmd.timeout,
                forbid=cmd.capture_forbid, history=history)
            self._note_fresh(text or "", len(history))
            if verdict == "TIMEOUT":
                return "FAIL", "capture timeout", "capture", []
            if verdict != "PASS":
                if (cmd.capture_forbid
                        and _pattern_hit(cmd.capture_forbid,
                                         cmd.expect_fail_is_regex,
                                         cmd.case_sensitive, text or "")):
                    return ("FAIL",
                            f"matched unwanted '{cmd.capture_forbid}'",
                            "capture", [])
                # keep capture_stage's own diagnosis (e.g. 'no console
                # output (DUT unresponsive?)' returned in place of the
                # text) when it carries one
                fail_detail = "capture condition not met"
                if (text or "").startswith("no console output"):
                    fail_detail = text.strip()
                return "FAIL", fail_detail, "capture", []
            if cmd.parse_summary:
                # expand the fat.py Summary table into per-item rows
                v, d, extras = self._expand_fat_summary(text or "")
                return v, d, "done", extras
            # keep the last output line as evidence - it flows into the
            # report/CSV "measured" column (e.g. 'Overall result: PASS')
            last = ""
            for ln in (text or "").splitlines():
                if ln.strip():
                    last = ln.replace("\r", "").strip()[:160]
            if last:
                return "PASS", last, "done", []
        return "PASS", "", "done", []

    def _run_sftp(self, channel, cmd) -> tuple:
        """sftp_put / sftp_get over an SSH channel exposing put_file /
        get_file."""
        try:
            if cmd.kind == "sftp_put":
                if not hasattr(channel, "put_file"):
                    return "FAIL", "channel has no SFTP put_file"
                channel.put_file(cmd.local, cmd.remote)
                return "PASS", f"put {cmd.local} -> {cmd.remote}"
            else:
                if not hasattr(channel, "get_file"):
                    return "FAIL", "channel has no SFTP get_file"
                channel.get_file(cmd.remote, cmd.local)
                return "PASS", f"get {cmd.remote} -> {cmd.local}"
        except Exception as e:
            return "FAIL", f"sftp error: {e}"

    def _wait_for(self, serial, pattern: str, timeout: float) -> tuple:
        """Legacy capture-only wait (kept for RF helpers)."""
        return wait_stage(serial, pattern, True, True, timeout)


    # -------------------------------------------------------------- RF
    def run_wifi(self, serial, host_runner) -> list:
        """Wi-Fi sub-tests (per-sub-test model). The DUT advertises the
        RF endpoint; the Host PC is the initiator.

        Scan/RSSI runs on both DUT kinds (host scan, or a DUT-console
        link read on a station-mode Linux DUT); Connect & Ping and iPerf
        are Linux only. Ping PASSes on >=1 reply; iperf on >= min Mbps."""
        results: list = []
        w = self.cfg.wifi
        if not w.enabled:
            return results
        from .rf_adapters import WifiAdapter

        def _adapter(runner_, cfg: dict):
            # m23: the backend key follows THIS platform (mac behaviour
            # is byte-identical - the mac table under the "mac" key)
            from .host_platform import platform_key, wifi_backend_cmds
            key = platform_key()
            return WifiAdapter(
                {"wifi": dict(cfg, cmds={key: wifi_backend_cmds()})},
                runner_)

        # 1) scan / RSSI
        if w.scan_enabled:
            if self.cfg.dut_type == "linux" and w.scan_via == "dut_console" \
                    and serial is not None:
                t0 = time.time()
                verdict, text = console_send_and_expect(
                    serial, f"iw dev {w.interface} link",
                    r"signal:\s*(-?[\d.]+)\s*dBm",
                    r"not connected|No station|Invalid",
                    float(w.scan_timeout),
                    expect_pass_is_regex=True,
                    expect_fail_is_regex=True)
                import re
                m = re.search(r"signal:\s*(-?[\d.]+)\s*dBm", text)
                if m:
                    rssi = float(m.group(1))
                    results.append(FctStepResult(
                        "Wi-Fi Scan / RSSI",
                        "PASS" if rssi >= w.rssi_min else "FAIL",
                        f"RSSI {rssi} dBm vs min {w.rssi_min}",
                        duration=time.time() - t0))
                else:
                    results.append(FctStepResult(
                        "Wi-Fi Scan / RSSI", "FAIL",
                        "DUT Wi-Fi not connected / link info timeout",
                        duration=time.time() - t0))
            elif host_runner is not None:
                t0 = time.time()
                out = _adapter(host_runner, {
                    "mode": "rssi_only", "ssid": w.ap_ssid,
                    "expected_ssid": w.ap_ssid,
                    "rssi_min": w.rssi_min}).run_test()
                results.append(FctStepResult(
                    "Wi-Fi Scan / RSSI",
                    "PASS" if out["verdict"] == "Pass" else "FAIL",
                    str(out["items"]), duration=time.time() - t0))
            else:
                self.log("Wi-Fi scan skipped: no host runner bound")
        # 2) connect & ping (Linux only): 3 connectivity stages over the
        #    shared hotspot AP - Host->AP (host CLI), DUT->AP (gateway),
        #    DUT->Host (full path). Each stage is an independent verdict
        #    so a dead segment is pin-pointed (not a vague timeout).
        if w.ping_enabled and self.cfg.dut_type == "linux":
            host_ip = w.host_ip or host_lan_ip()
            ap_ip = w.ap_ip or dut_default_gateway(serial) or ""
            # stage 1 - Host PC -> AP (host CLI)
            t0 = time.time()
            if host_runner is None:
                self.log("Wi-Fi ping Host->AP skipped: no host runner")
            elif not ap_ip:
                results.append(FctStepResult(
                    "Wi-Fi Ping: Host -> AP", "FAIL",
                    "cannot determine AP/gateway IP",
                    duration=time.time() - t0))
            else:
                res = host_runner.run(
                    "ping -c {count} {ip}",
                    {"count": w.ping_count, "ip": ap_ip},
                    regex_extracts={"loss_pct":
                                    r"(\d+(?:\.\d+)?)% packet loss"},
                    timeout_s=max(w.ping_count + 15, 30))
                loss = float(res.items.get("loss_pct", "100"))
                results.append(FctStepResult(
                    "Wi-Fi Ping: Host -> AP",
                    "PASS" if loss < 100.0 else "FAIL",
                    f"loss {loss}% (host -> {ap_ip})",
                    duration=time.time() - t0))
            # stage 2 - DUT -> AP (gateway)
            if serial is not None and ap_ip:
                t0 = time.time()
                v, d = dut_wifi_ping(serial, ap_ip, w.ping_count, 0.0,
                                     interface=w.interface)
                results.append(FctStepResult(
                    "Wi-Fi Ping: DUT -> AP", v, d,
                    duration=time.time() - t0))
            # stage 3 - DUT -> AP -> Host PC (full path)
            if serial is not None and host_ip:
                t0 = time.time()
                v, d = dut_wifi_ping(serial, host_ip, w.ping_count, 0.0,
                                     interface=w.interface)
                results.append(FctStepResult(
                    "Wi-Fi Ping: DUT -> AP -> Host", v, d,
                    duration=time.time() - t0))
        # 3) iperf throughput (Linux only; host server / DUT client).
        #    A ping gate first proves the DUT <-> host path is alive
        #    (a dead Wi-Fi link is what silently stuck the throughput
        #    run), then the throughput test itself retries once.
        if w.iperf_enabled and self.cfg.dut_type == "linux" and serial:
            server_ip = w.host_ip or w.iperf_server_ip or host_lan_ip()
            if not server_ip:
                results.append(FctStepResult(
                    f"Wi-Fi iPerf ({w.iperf_tool})", "FAIL",
                    "cannot determine host server IP"))
            else:
                # connectivity gate: ping the host, 4 packets, 0% loss,
                # forced over mlan0; retry the gate once on failure
                gate = None
                for attempt in range(2):
                    gv, gd = dut_wifi_ping(
                        serial, server_ip, 4, 0.0, interface="mlan0")
                    self.log(f"iPerf ping gate "
                             f"(attempt {attempt + 1}/2): {gv} {gd}")
                    gate = (gv, gd)
                    if gv == "PASS":
                        break
                if gate[0] != "PASS":
                    results.append(FctStepResult(
                        f"Wi-Fi iPerf Throughput ({w.iperf_tool})", "FAIL",
                        f"pre-iperf ping gate failed: {gate[1]}"))
                else:
                    v = d = None
                    duration = 0.0
                    for attempt in range(2):
                        t0 = time.time()
                        v, d = dut_wifi_iperf(
                            serial, w.iperf_tool, server_ip,
                            w.iperf_min_mbps, w.iperf_duration)
                        duration = time.time() - t0
                        if v == "PASS":
                            break
                        if attempt == 0:
                            self.log(f"iPerf retry ({attempt + 1}/1): {d}")
                    results.append(FctStepResult(
                        f"Wi-Fi iPerf Throughput ({w.iperf_tool})", v, d,
                        duration=duration))
        return results

    def run_bluetooth(self, serial, host_runner, human_confirm=None) -> list:
        """Bluetooth sub-tests: RSSI (both DUT kinds), Pair & Connect and
        A2DP Tone/Music (Linux only), each through the B4 adapter."""
        results: list = []
        b = self.cfg.bluetooth
        if not b.enabled:
            return results
        if host_runner is None:
            self.log("Bluetooth skipped: no host runner bound")
            return results
        from .rf_adapters import BluetoothAdapter

        def _run(mode: str, label: str, timeout: float):
            t0 = time.time()
            # m23: platform-aware backend; Windows has no built-in
            # classic-BT CLI -> bt_backend_cmds() raises
            # PlatformBackendMissing -> explicit ERROR row (never a
            # silent PASS, never a traceback)
            from .host_platform import platform_key, bt_backend_cmds
            from .rf_adapters import PlatformBackendMissing
            try:
                key = platform_key()
                ad = BluetoothAdapter(
                    {"bluetooth": {
                        "mode": mode, "expected_name": b.expected_name,
                        "expected_addr": b.expected_addr,
                        "scan_retries": b.scan_retries,
                        "rssi_min": b.rssi_min, "audio_confirm":
                            b.audio_confirm, "timeout_s": float(timeout),
                        "cmds": {key: bt_backend_cmds()}}},
                    host_runner, human_confirm=human_confirm)
                out = ad.run_test()
            except PlatformBackendMissing as exc:
                import sys as _sys
                hint = ("install a command-line scanner (e.g. "
                        "BluetoothCL) and add a 'windows' backend, or "
                        "run this Bluetooth step on macOS."
                        if _sys.platform == "win32" else
                        "configure a command backend for this platform.")
                self.log(f"{label} unavailable: {exc}")
                results.append(FctStepResult(
                    label, "ERROR", f"{exc} {hint}",
                    duration=time.time() - t0))
                return
            results.append(FctStepResult(
                label, "PASS" if out["verdict"] == "Pass" else "FAIL",
                str(out["items"]), duration=time.time() - t0))

        if b.rssi_enabled:
            _run("rssi_only", "Bluetooth RSSI", b.rssi_timeout)
        if self.cfg.dut_type == "linux":
            if b.pair_enabled:
                _run("pair_connect", "Bluetooth Pair & Connect",
                     b.pair_timeout)
                if b.l2ping_count > 0 and serial is not None:
                    t0 = time.time()
                    v, d = dut_bt_l2ping(serial, host_runner,
                                         b.l2ping_count)
                    results.append(FctStepResult(
                        f"BT L2CAP ping ({b.l2ping_count})", v, d,
                        duration=time.time() - t0))
            if b.tone_enabled:
                _run("a2dp_sink", "Bluetooth Tone / Music (A2DP)",
                     b.tone_timeout)
        return results

    # ------------------------------------------------------------- full
    def deploy_scripts(self, channel):
        """Provision the Linux DUT with the maintained local script-asset
        folder over SFTP, once per unit (re-provisions a board whose /root
        was wiped by a reboot). Returns FctStepResult or None when off."""
        import os
        c = self.cfg.console
        if (not c.deploy_scripts or self.cfg.dut_type != "linux"
                or channel is None):
            return None
        local = c.scripts_local_dir or ""
        if local and not os.path.isabs(local) and self.scripts_base_dir:
            # normpath: YAML relative paths use forward slashes on every
            # OS; normalize so Windows gets native separators.
            local = os.path.normpath(
                os.path.join(self.scripts_base_dir, local))
        remote = (c.scripts_remote_dir or "").rstrip("/")
        t0 = time.time()
        try:
            if not os.path.isdir(local):
                raise FileNotFoundError(local)
            if callable(getattr(channel, "put_dir", None)):
                uploaded = channel.put_dir(local, remote)
                n = len(uploaded)
            elif callable(getattr(channel, "put_file", None)):
                n = 0
                for root, _dirs, files in os.walk(local):
                    for fname in sorted(files):
                        lp = os.path.join(root, fname)
                        rel = os.path.relpath(lp, local).replace(os.sep, "/")
                        rp = f"{remote}/{rel}" if remote else rel
                        channel.put_file(lp, rp)
                        n += 1
            else:
                return FctStepResult("Deploy DUT scripts", "FAIL",
                                     "channel has no SFTP capability",
                                     duration=time.time() - t0)
            return FctStepResult(
                "Deploy DUT scripts", "PASS",
                f"{n} file(s) -> {remote or '~'}",
                duration=time.time() - t0)
        except Exception as exc:                    # noqa: BLE001
            return FctStepResult("Deploy DUT scripts", "FAIL",
                                 f"deploy error: {exc}",
                                 duration=time.time() - t0)

    def run(self, serial, host_runner, human_confirm=None) -> dict:
        """One complete FCT cycle -> results + overall verdict."""
        self.log("FCT cycle start")
        # operator confirm hook, shared by the console Confirm stage and
        # the Bluetooth A2DP tone step (callable(question) -> bool)
        self._human_confirm = human_confirm
        # deployment values substituted into {{token}} placeholders in
        # console send / SFTP paths (per-site Wi-Fi SSID/password, Host
        # PC IP, DUT Bluetooth address) - resolved ONCE per cycle
        w = self.cfg.wifi
        b = self.cfg.bluetooth
        self._cmd_vars = {
            "ssid": w.ap_ssid,
            "password": w.ap_password,
            "host_ip": w.host_ip or host_lan_ip(),
            "bt_addr": b.expected_addr,
            "bt_name": b.expected_name,
        }
        results: list = []
        teardown_results: list = []
        aborted_early = False
        try:
            # 0) provision generic Linux scripts over SFTP before anything runs
            deploy = self.deploy_scripts(serial)
            if deploy is not None:
                results.append(deploy)
                self.log(f"console '{deploy.name}' [sftp] -> "
                         f"{deploy.verdict} {deploy.detail}")
                if not deploy.passed:
                    aborted_early = True
            if not aborted_early:
                results += self.run_console(serial)
                # DUT-side driver load goes over the CONSOLE (spec 3.2)
                # - only when not already a console test command (no
                # double execute)
                w = self.cfg.wifi
                console_cmds = {c.send
                                for c in self.cfg.console.test_commands}
                if (w.enabled and w.driver_load_cmd
                        and serial is not None
                        and w.driver_load_cmd not in console_cmds):
                    t0 = time.time()
                    verdict, text = console_send_and_expect(
                        serial, w.driver_load_cmd, r"RF drivers loaded OK",
                        r"FAILED", 15.0)
                    results.append(FctStepResult(
                        f"Load RF drivers ({w.driver_load_cmd})",
                        "PASS" if verdict == "PASS" else "FAIL",
                        text.strip().splitlines()[-1][:120]
                        if text.strip() else "",
                        duration=time.time() - t0))
                results += self.run_wifi(serial, host_runner)
                results += self.run_bluetooth(serial, host_runner,
                                              human_confirm)
        finally:
            # --- post-RF teardown: ALWAYS run, even on abort/exception ---
            teardown_results = self._run_post_rf_commands(
                serial, host_runner)
        results += teardown_results
        overall = ("PASS" if results and all(r.passed for r in results)
                   else "FAIL")
        self.log(f"FCT cycle end -> {overall}")
        return {"results": results, "overall": overall,
                "report": self.report(results, overall)}

    # ------------------------------------------------ teardown guarantee
    def _run_post_rf_commands(self, serial, host_runner) -> list:
        """Execute cfg.console.post_rf_commands (serial + host CLI).

        Runs AFTER every FCT cycle — even if the main sequence aborted
        half-way through — so that DUT shutdown and host-side cleanup
        (e.g. stopping a background iperf3 server) cannot be skipped.
        Each row's FAILURE IS LOGGED BUT DOES NOT STOP the subsequent
        teardown rows (best-effort cleanup); the teardown results are
        appended to the main results list so the report reflects them."""
        results: list = []
        cmds = list(getattr(self.cfg.console, "post_rf_commands", []) or [])
        for cmd in cmds:
            if not getattr(cmd, "enabled", True):
                continue
            t0 = time.time()
            label = cmd.name or getattr(cmd, "send", None) \
                or getattr(cmd, "host_cmd", None) or "teardown"
            if cmd.kind == "host":
                rc, detail = self._run_host_cli(cmd, host_runner)
                verdict = "PASS" if rc == 0 else "FAIL"
                results.append(FctStepResult(
                    label, verdict, detail, duration=time.time() - t0))
                self.log(f"host cli: {label} -> {verdict} {detail}")
            else:
                verdict, detail, stage, extras = \
                    self._run_one_command(serial, cmd)
                results.append(FctStepResult(
                    label, verdict, detail, duration=time.time() - t0))
                results.extend(extras)
                self.log(f"console '{label}' [{stage}] -> {verdict} "
                         f"{detail}")
                for extra in extras:
                    self.log(f"  summary row '{extra.name}' -> "
                             f"{extra.verdict}")
        return results

    def _run_host_cli(self, cmd, host_runner) -> tuple[int, str]:
        """Run one host-side CLI command via HostCliRunner.

        Returns (returncode, detail).  Picks host_cmd_windows on Windows,
        host_cmd on macOS/Linux.  Never raises (failures become rc≠0)."""
        import sys as _sys
        if host_runner is None:
            return -1, "no host_runner available"
        line = (getattr(cmd, "host_cmd_windows", "")
                if _sys.platform == "win32"
                else "") or getattr(cmd, "host_cmd", "")
        if not line:
            return -1, "empty host_cmd"
        try:
            outcome = host_runner.run(line)
            rc = getattr(outcome, "exit_code", -1)
            detail = (getattr(outcome, "reason", "")
                      or "\n".join(getattr(outcome, "lines", [])[:3]))
            return rc, str(detail).strip()[:200]
        except Exception as exc:               # noqa: BLE001
            return -1, f"host cli exception: {exc}"

    # ----------------------------------------------------------- report
    def report(self, results: list, overall: str) -> str:
        """Plain-text report (spec §5.3 format)."""
        lines = [f"=== FCT Test Report ===",
                 f"Date: {datetime.now():%Y-%m-%d %H:%M:%S}"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.name}")
            lines.append(f"   - {r.detail} ..." if r.detail else
                         "   - (no detail)")
            lines.append(f"   Result: {r.verdict}")
        lines.append(f"Overall Result: {overall}")
        return "\n".join(lines)
