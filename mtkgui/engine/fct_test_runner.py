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
                      expect_fail: str) -> tuple:
    """Regex judgement over the accumulated output (fail wins).

    Empty patterns mean "no opinion" (pass needs SOME output).
    Returns ``(verdict, detail)`` with verdict PASS/FAIL.
    """
    if expect_fail and re.search(expect_fail, text):
        hit = re.search(expect_fail, text).group(0)
        return "FAIL", f"matched expect_fail '{hit}'"
    if expect_pass:
        m = re.search(expect_pass, text)
        if m:
            return "PASS", f"matched '{m.group(0)}'"
        return "", ""
    return ("PASS", "output present") if text.strip() else ("", "")


def console_send_and_expect(serial, cmd: str, expect_pass: str,
                            expect_fail: str, timeout: float) -> tuple:
    """Send one command over the console and judge the reply stream.

    Spec §4.2: ``reset_input_buffer()`` BEFORE sending (stale output
    must not judge this command), then keep reading inside `timeout`;
    ``expect_fail`` has priority; on timeout return ``TIMEOUT`` (the
    caller treats it as FAIL) with everything that DID arrive — the
    station never hangs.

    Args:
        serial: pyserial-like (write / read / reset_input_buffer).

    Returns:
        ``(verdict, text)`` — verdict in PASS / FAIL / TIMEOUT.
    """
    serial.reset_input_buffer()
    serial.write((cmd + "\n").encode())
    start = time.time()
    buffer = b""
    while time.time() - start < max(timeout, 0.1):
        chunk = serial.read(4096)
        if chunk:
            buffer += chunk
            text = buffer.decode("utf-8", errors="replace")
            verdict, _ = match_expectation(text, expect_pass, expect_fail)
            if verdict:
                return verdict, text
        time.sleep(0.05)
    return "TIMEOUT", buffer.decode("utf-8", errors="replace")


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
        """Login sequence + test commands over the serial console."""
        results: list = []
        c = self.cfg.console
        if not c.enabled or serial is None:
            return results
        # login: wait_for -> send chain (regex per pair)
        for i, pair in enumerate(c.login_sequence, 1):
            verdict, text = "PASS", ""
            if pair.wait_for:
                verdict, text = self._wait_for(serial, pair.wait_for, 5.0)
                results.append(FctStepResult(
                    f"login wait '{pair.wait_for}'", verdict,
                    text[-200:]))
                if verdict != "PASS":
                    return results
            if pair.send is not None:
                # empty string = bare newline (e.g. empty password) -
                # still a real send, never skipped
                serial.reset_input_buffer()
                serial.write((pair.send + "\n").encode())
                self.log(f"login send {pair.send!r}")
        for cmd in c.test_commands:
            verdict, text = console_send_and_expect(
                serial, cmd.send, cmd.expect_pass, cmd.expect_fail,
                cmd.timeout)
            shown = "TIMEOUT" if verdict == "TIMEOUT" else verdict
            detail = text.strip().splitlines()[-1][:120] if text.strip() \
                else ""
            results.append(FctStepResult(
                cmd.name or cmd.send, shown if verdict != "TIMEOUT"
                else "FAIL", detail))
            self.log(f"console '{cmd.send}' -> "
                     f"{'FAIL (timeout)' if verdict == 'TIMEOUT' else verdict}")
        return results

    def _wait_for(self, serial, pattern: str, timeout: float) -> tuple:
        """Capture-only wait (no send): read until `pattern` matches."""
        start = time.time()
        buffer = b""
        while time.time() - start < max(timeout, 0.1):
            chunk = serial.read(4096)
            if chunk:
                buffer += chunk
                text = buffer.decode("utf-8", errors="replace")
                if re.search(pattern, text):
                    return "PASS", text
            time.sleep(0.05)
        return "TIMEOUT", buffer.decode("utf-8", errors="replace")

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
                r"not connected|No station|Invalid", 5.0)
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

    def run_bluetooth(self, runner, human_confirm=None) -> list:
        """Host-side Bluetooth test through the B4 BluetoothAdapter."""
        results: list = []
        b = self.cfg.bluetooth
        if not b.enabled:
            return results
        if runner is None:
            self.log("Bluetooth skipped: no host runner bound")
            return results
        from .rf_adapters import BluetoothAdapter
        rf_cfg = {"bluetooth": {
            "mode": b.mode, "expected_name": b.expected_name,
            "rssi_min": b.rssi_min,
            "audio_confirm": b.audio_confirm,
            "cmds": {"mac": dict(BT_MAC_CMDS)},
        }}
        ad = BluetoothAdapter(rf_cfg, runner,
                              human_confirm=human_confirm)
        out = ad.run_test()
        results.append(FctStepResult(
            f"Bluetooth {b.mode}",
            "PASS" if out["verdict"] == "Pass" else "FAIL",
            str(out["items"])))
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
        results += self.run_bluetooth(host_runner, human_confirm)
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
