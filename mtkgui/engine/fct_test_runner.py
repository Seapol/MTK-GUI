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
    "audio_switch_cmd": 'switchaudio-osx -s "{{name}}"',
    "tone_cmd": "afplay {{tone}}",
}


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


def _read_until(serial, stop_fn, timeout: float) -> tuple:
    """Drain the console into a buffer until stop_fn(text)->True or
    timeout. Returns (status, text): status is whatever stop_fn returns
    truthy-as (a non-empty string verdict), else 'TIMEOUT'."""
    start = time.time()
    buffer = b""
    while time.time() - start < max(timeout, 0.1):
        chunk = serial.read(4096)
        if chunk:
            buffer += chunk
            text = buffer.decode("utf-8", errors="replace")
            verdict = stop_fn(text)
            if verdict:
                return verdict, text
        time.sleep(0.05)
    return "TIMEOUT", buffer.decode("utf-8", errors="replace")


def wait_stage(serial, pattern: str, is_regex: bool, case_sensitive: bool,
               timeout: float) -> tuple:
    """Wait stage: block until `pattern` appears or timeout.

    Used to find the right moment to send (e.g. a login prompt). The
    prompt is static (printed once), so do NOT reset the buffer here:
    a prompt already present must match immediately. Send resets the
    buffer before writing. Returns ('PASS', text) on hit,
    ('TIMEOUT', text) on timeout.
    """
    def _stop(text):
        return "PASS" if _pattern_hit(pattern, is_regex,
                                      case_sensitive, text) else ""
    return _read_until(serial, _stop, timeout)


def send_stage(serial, cmd: str, timeout: float) -> tuple:
    """Send stage: send each non-empty line (newline auto-appended).

    A normal write returns immediately. The timeout guards against a
    stuck serial / dead DUT blocking the write. Returns ('PASS','') on
    success, ('FAIL', detail) if the write cannot complete.
    """
    lines = [ln for ln in cmd.splitlines() if ln.strip()]
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
                  timeout: float, forbid: str = "") -> tuple:
    """Capture stage: judge the output after commands were sent.

    expected=True  : pattern found = PASS; end_line reached without
                     pattern = FAIL; timeout = FAIL.
    expected=False : pattern found = FAIL; end_line reached without
                     pattern = PASS; timeout without end_line = FAIL
                     (or PASS if no end_line is defined).
    `forbid` is an optional negative keyword that fails immediately
    whenever it appears (legacy expect_fail alongside a positive).
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

    verdict, text = _read_until(serial, _stop, timeout)
    if verdict == "TIMEOUT" and not expected and not end_line:
        # no end line defined: survived the whole window without the
        # unwanted message -> PASS
        if not _pattern_hit(pattern, is_regex, case_sensitive, text) \
                and not (forbid and _pattern_hit(forbid, is_regex,
                                                 case_sensitive, text)):
            return "PASS", text
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
                  loss_max: float) -> tuple:
    """DUT-side ping of the gateway: PASS when packet loss <= loss_max."""
    verdict, text = _console_probe(
        serial, f"ping -c {count} {gateway}",
        r"\d+ received, [\d.]+% packet loss", count + 10.0)
    m = re.search(r"(\d+) received, ([\d.]+)% packet loss", text)
    if not m:
        return "FAIL", ("TIMEOUT waiting for ping summary"
                        if verdict == "TIMEOUT" else "no ping summary")
    received, loss = int(m.group(1)), float(m.group(2))
    ok = received == count and loss <= loss_max
    return ("PASS" if ok else "FAIL",
            f"loss {loss}% ({received}/{count}) vs max {loss_max}%")


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

    def __init__(self, name: str, verdict: str, detail: str = "") -> None:
        self.name = name
        self.verdict = verdict          # PASS / FAIL / TIMEOUT / ERROR
        self.detail = detail

    @property
    def passed(self) -> bool:
        return self.verdict == "PASS"


class FctTestRunner:
    """Executes one FCT cycle from an :class:`FctTestConfig`."""

    def __init__(self, config: FctTestConfig, log_sink=None,
                 station_id: str = "", user: str = "") -> None:
        self.cfg = config
        self._log = log_sink or (lambda _m: None)
        self.station_id = station_id
        self.user = user

    def _identity(self) -> str:
        return f"[{self.station_id}] [{self.user}]"

    def log(self, message: str) -> None:
        self._log(f"{self._identity()} {message}")

    # ---------------------------------------------------------- console
    def run_console(self, serial) -> list:
        """Run console test commands.

        Each ConsoleCommand is a Wait -> Send -> Capture pipeline with
        every stage independently enabled. Any stage failure (incl.
        timeout) retries the whole command up to cmd.retries times, then
        FAILs and stops. SFTP rows (sftp_put/sftp_get) run over the SSH
        channel and bypass Wait/Capture.
        """
        results: list = []
        c = self.cfg.console
        if not c.enabled or serial is None:
            return results
        for cmd in c.test_commands:
            verdict, detail, stage = self._run_one_command(serial, cmd)
            label = cmd.name or cmd.send or cmd.expect_pass or "console"
            results.append(FctStepResult(label, verdict, detail))
            self.log(f"console '{label}' [{stage}] -> {verdict} {detail}")
            if verdict != "PASS":
                return results  # stop the whole sequence on failure
        return results

    def _run_one_command(self, serial, cmd) -> tuple:
        """Run one ConsoleCommand with retry. Returns (verdict, detail,
        stage)."""
        attempts = cmd.retries + 1
        last = ("FAIL", "not run", "?")
        for attempt in range(attempts):
            # SFTP rows: file transfer over the SSH channel only
            if cmd.kind in ("sftp_put", "sftp_get"):
                verdict, detail = self._run_sftp(serial, cmd)
                if verdict == "PASS":
                    return verdict, detail, "sftp"
                last = (verdict, detail, "sftp")
                if attempt + 1 < attempts:
                    self.log(f"  retry sftp ({attempt + 1}/{cmd.retries})")
                continue
            # three-stage pipeline: Wait -> Send -> Capture
            verdict, detail, stage = self._run_pipeline(serial, cmd)
            if verdict == "PASS":
                return verdict, detail, stage
            last = (verdict, detail, stage)
            if attempt + 1 < attempts:
                self.log(f"  retry {stage} ({attempt + 1}/{cmd.retries})")
        return last

    def _run_pipeline(self, serial, cmd) -> tuple:
        """Wait -> Send -> Capture for one command."""
        # 1) WAIT (precondition to send, e.g. login prompt)
        if cmd.wait_enabled and cmd.expect_pass:
            verdict, text = wait_stage(
                serial, cmd.expect_pass, cmd.expect_pass_is_regex,
                cmd.case_sensitive, cmd.wait_timeout)
            if verdict != "PASS":
                return "FAIL", f"wait timeout, no '{cmd.expect_pass}'", "wait"
        # 2) SEND (each line auto-newline; timeout guards a stuck link).
        # kind=send with an empty command still sends one newline
        # (e.g. blank password); a capture-only row sends nothing.
        if (cmd.send_enabled
                and cmd.kind not in ("sftp_put", "sftp_get")
                and (cmd.send or cmd.kind == "send")):
            verdict, detail = send_stage(serial, cmd.send, cmd.send_timeout)
            if verdict != "PASS":
                return "FAIL", detail, "send"
        # 3) CAPTURE (judge the resulting output within capture timeout)
        if cmd.capture_enabled and cmd.expect_fail:
            verdict, text = capture_stage(
                serial, cmd.expect_fail, cmd.capture_end_line,
                cmd.capture_is_expected, cmd.expect_fail_is_regex,
                cmd.case_sensitive, cmd.timeout,
                forbid=cmd.capture_forbid)
            if verdict == "TIMEOUT":
                return "FAIL", "capture timeout", "capture"
            if verdict != "PASS":
                return "FAIL", "capture condition not met", "capture"
        return "PASS", "", "done"

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
        """Wi-Fi test: rssi_only reads the DUT's OWN link RSSI over the
        console (station mode: a host-side scan cannot see the DUT);
        full_stack runs through the B4 WifiAdapter (host join + ping)."""
        results: list = []
        w = self.cfg.wifi
        if not w.enabled:
            return results
        if w.mode == "rssi_only":
            if serial is None:
                self.log("Wi-Fi skipped: no console bound")
                return results
            verdict, text = console_send_and_expect(
                serial, f"iw dev {w.interface} link",
                r"signal:\s*(-?[\d.]+)\s*dBm",
                r"not connected|No station|Invalid", 5.0,
                expect_pass_is_regex=True,
                expect_fail_is_regex=True)
            import re
            m = re.search(r"signal:\s*(-?[\d.]+)\s*dBm", text)
            if m:
                rssi = float(m.group(1))
                verdict = "PASS" if rssi >= w.rssi_min else "FAIL"
                detail = f"RSSI {rssi} dBm vs min {w.rssi_min}"
            else:
                verdict = "FAIL"
                detail = ("DUT Wi-Fi not connected" if verdict == "FAIL"
                          else "TIMEOUT waiting for link info")
            results.append(FctStepResult(f"Wi-Fi {w.mode}", verdict,
                                         detail))
            # Linux DUT connectivity + throughput (console-based)
            if w.gateway and serial is not None:
                v2, d2 = dut_wifi_ping(serial, w.gateway, w.ping_count,
                                       w.loss_max)
                results.append(FctStepResult("Wi-Fi DUT ping gateway",
                                             v2, d2))
            bw = w.bandwidth
            if bw.enabled and serial is not None:
                v3, d3 = dut_wifi_iperf(serial, bw.tool, bw.server_ip,
                                        bw.min_mbps)
                results.append(FctStepResult(
                    f"Wi-Fi DUT iperf ({bw.tool})", v3, d3))
            return results
        if host_runner is None:
            self.log("Wi-Fi full_stack skipped: no host runner bound")
            return results
        from .rf_adapters import WifiAdapter
        rf_cfg = {"wifi": {
            # `ssid` is the scan target in rssi_only (e.g. the DUT's
            # uap0 advertisement) and the join target in full_stack
            "mode": w.mode, "expected_ssid": w.ssid,
            "password": w.password, "gateway": w.gateway,
            "rssi_min": w.rssi_min, "ping_count": w.ping_count,
            "cmds": {"mac": dict(WIFI_MAC_CMDS)},
        }}
        ad = WifiAdapter(rf_cfg, runner)
        out = ad.run_test()
        verdict = out["verdict"]
        items = out["items"]
        # bandwidth gate (informational throughput -> FAIL below min)
        bw = w.bandwidth
        if bw.enabled and items.get("throughput") is not None:
            if float(items["throughput"]) < float(bw.min_mbps):
                verdict = "Fail"
        results.append(FctStepResult(
            f"Wi-Fi {w.mode}", "PASS" if verdict == "Pass" else "FAIL",
            str(items)))
        return results

    def run_bluetooth(self, serial, host_runner, human_confirm=None) -> list:
        """Host-side Bluetooth test through the B4 BluetoothAdapter,
        then the L2CAP data-transfer proof (DUT -> host)."""
        results: list = []
        b = self.cfg.bluetooth
        if not b.enabled:
            return results
        if host_runner is None:
            self.log("Bluetooth skipped: no host runner bound")
            return results
        from .rf_adapters import BluetoothAdapter
        rf_cfg = {"bluetooth": {
            "mode": b.mode, "expected_name": b.expected_name,
            "rssi_min": b.rssi_min,
            "audio_confirm": b.audio_confirm,
            "cmds": {"mac": dict(BT_MAC_CMDS)},
        }}
        ad = BluetoothAdapter(rf_cfg, host_runner,
                              human_confirm=human_confirm)
        out = ad.run_test()
        results.append(FctStepResult(
            f"Bluetooth {b.mode}",
            "PASS" if out["verdict"] == "Pass" else "FAIL",
            str(out["items"])))
        # data-transfer proof: L2CAP ping DUT -> host PC (0% loss)
        if b.l2ping_count > 0 and serial is not None:
            verdict, detail = dut_bt_l2ping(serial, host_runner,
                                            b.l2ping_count)
            results.append(FctStepResult(
                f"BT L2CAP ping ({b.l2ping_count})", verdict, detail))
        return results

    # ------------------------------------------------------------- full
    def run(self, serial, host_runner, human_confirm=None) -> dict:
        """One complete FCT cycle -> results + overall verdict."""
        self.log("FCT cycle start")
        results: list = []
        results += self.run_console(serial)
        # DUT-side driver load goes over the CONSOLE (spec 3.2) - only
        # when not already a console test command (no double execute)
        w = self.cfg.wifi
        console_cmds = {c.send for c in self.cfg.console.test_commands}
        if (w.enabled and w.driver_load_cmd and serial is not None
                and w.driver_load_cmd not in console_cmds):
            verdict, text = console_send_and_expect(
                serial, w.driver_load_cmd, r"RF drivers loaded OK",
                r"FAILED", 15.0)
            results.append(FctStepResult(
                f"Load RF drivers ({w.driver_load_cmd})",
                "PASS" if verdict == "PASS" else "FAIL",
                text.strip().splitlines()[-1][:120] if text.strip()
                else ""))
        results += self.run_wifi(serial, host_runner)
        results += self.run_bluetooth(serial, host_runner, human_confirm)
        overall = ("PASS" if results and all(r.passed for r in results)
                   else "FAIL")
        self.log(f"FCT cycle end -> {overall}")
        return {"results": results, "overall": overall,
                "report": self.report(results, overall)}

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
