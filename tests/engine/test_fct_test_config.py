# -*- coding: utf-8 -*-
"""P3-B5: fct_test_config + fct_test_runner unit tests (no hardware)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from mtkgui.engine.fct_test_config import (
    FctTestConfig,
    build_fct_steps,
)
from mtkgui.engine.fct_test_runner import (
    FctStepResult,
    FctTestRunner,
    console_send_and_expect,
    match_expectation,
)

FRDM_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/cu.usbmodem53930099631"
    baudrate: 115200
    login_sequence:
      - {wait_for: "login:", send: root}
      - {wait_for: "Password:", send: ""}
      - {wait_for: root@imx93frdm}
    test_commands:
      - {name: Kernel check, send: "uname -a",
         expect_pass: "Linux imx93frdm", expect_fail: "", timeout: 5}
      - {name: Load RF drivers, send: /root/load_rf_drivers.sh,
         expect_pass: "RF drivers loaded OK", expect_fail: FAILED,
         timeout: 15, retries: 2}
  wifi:
    enabled: true
    mode: rssi_only
    interface: mlan0
    driver_load_cmd: /root/load_rf_drivers.sh
    ssid: FRDM-IMX93-DUT
    rssi_min: -70
  bluetooth:
    enabled: true
    mode: rssi_only
    expected_name: FRDM-IMX93-DUT
    rssi_min: -70
    audio_confirm: true
    l2ping_count: 5
"""


def frdm_config() -> FctTestConfig:
    import yaml
    node = yaml.safe_load(FRDM_YAML)
    return FctTestConfig.from_dict(node["fct_test_config"])


# ------------------------------------------------------------------ model
def test_roundtrip_preserves_fields():
    cfg = frdm_config()
    restored = FctTestConfig.from_dict(cfg.to_dict())
    assert restored.to_dict() == cfg.to_dict()


def test_validate_clean_for_frdm():
    assert frdm_config().validate() == []


def test_validate_rejects_bad_mode_and_baud():
    cfg = frdm_config()
    cfg.wifi.mode = "both"
    cfg.console.baudrate = 1234
    cfg.bluetooth.mode = "a2dp"            # not a real mode
    errors = cfg.validate()
    assert len(errors) == 3


def test_build_steps_console_chain():
    steps = build_fct_steps(frdm_config(), channel_key="ser1")
    names = [s.name for s in steps]
    # wait login: -> send root (expects Password:) -> send "" (expects
    # shell prompt) -> 2 test commands -> wifi -> bluetooth
    # tolerance: every login step also accepts the FINAL prompt
    final = "root@imx93frdm"
    assert names[0] == "Console wait 'login:'"
    assert steps[0].expect_pass == ["login:", final]
    assert steps[1].params["send"] == "root"
    assert steps[1].expect_pass == ["Password:", final]
    assert steps[2].params["send"] == ""
    assert steps[2].expect_pass == [final]
    assert "Kernel check" in names and "Load RF drivers" in names
    wifi = next(s for s in steps
                if s.params.get("tool_family") == "wifi")
    bt = next(s for s in steps
              if s.params.get("tool_family") == "bluetooth")
    assert wifi.params["rssi_via"] == "dut_console"   # station mode
    assert bt.step_type == "EXTERNAL_TOOL"
    assert all(s.channel == "ser1"
               for s in steps if s.step_type == "MESSAGE_CHECK")


def test_build_steps_retries_carried():
    steps = build_fct_steps(frdm_config())
    by_name = {s.name: s for s in steps}
    assert by_name["Kernel check"].retries == 0
    assert by_name["Load RF drivers"].retries == 2


def test_build_steps_disabled_sections_absent():
    cfg = frdm_config()
    cfg.console.enabled = False
    cfg.wifi.enabled = False
    steps = build_fct_steps(cfg)
    # BT emits piscan + FCT + the L2CAP data-transfer proof
    assert [s.name for s in steps] == ["BT discoverable (piscan)",
                                       "Bluetooth FCT",
                                       "BT L2CAP ping (5)"]


# ---------------------------------------------------------------- matcher
def test_match_pass_regex():
    v, d = match_expectation("Linux imx93frdm 6.6.36", r"Linux imx93frdm",
                             "")
    assert v == "PASS" and "imx93frdm" in d


def test_match_fail_wins():
    v, _ = match_expectation("OK then FAILED", r"OK", r"FAILED")
    assert v == "FAIL"


def test_match_no_pass_match_empty():
    assert match_expectation("nothing here", r"Linux", "") == ("", "")


def test_match_any_output_when_no_patterns():
    assert match_expectation("some output", "", "")[0] == "PASS"
    assert match_expectation("", "", "") == ("", "")


# ------------------------------------------------------ console executor
class FakeSerial:
    """Scripted pyserial-like: replies after the command is sent."""

    def __init__(self, script):
        self.script = script                   # cmd -> reply lines
        self.sent: list = []
        self.buffer = b""

    def reset_input_buffer(self):
        self.buffer = b""

    def write(self, data: bytes):
        cmd = data.decode().strip()
        self.sent.append(cmd)
        reply = self.script.get(cmd, b"")
        self.buffer += reply if isinstance(reply, bytes) \
            else reply.encode()
        return len(data)

    def read(self, n):
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data


def test_console_send_and_expect_pass():
    s = FakeSerial({"uname -a": "Linux imx93frdm 6.6.36\r\nroot@imx93frdm"})
    verdict, text = console_send_and_expect(s, "uname -a",
                                            r"Linux imx93frdm", "", 2)
    assert verdict == "PASS" and "6.6.36" in text
    assert s.sent[-1] == "uname -a"


def test_console_send_and_expect_fail_wins():
    s = FakeSerial({"/root/load_rf_drivers.sh": "loading... FAILED"})
    verdict, _ = console_send_and_expect(s, "/root/load_rf_drivers.sh",
                                         r"loaded OK", r"FAILED", 2)
    assert verdict == "FAIL"


def test_console_send_and_expect_timeout():
    s = FakeSerial({})                          # no reply at all
    verdict, text = console_send_and_expect(s, "bad cmd", r"ok", "", 0.5)
    assert verdict == "TIMEOUT"


def test_console_stale_output_does_not_judge():
    """reset_input_buffer BEFORE send: pre-existing output must not
    produce an instant PASS for the new command."""
    s = FakeSerial({"b": "Linux imx93frdm"})    # only 'b' triggers it
    s.buffer = b"Linux imx93frdm"               # stale bytes waiting
    verdict, _ = console_send_and_expect(s, "a", r"Linux imx93frdm",
                                         "", 0.4)
    assert verdict == "TIMEOUT"


# ------------------------------------------------------------- orchestrator
def test_fct_runner_full_cycle_pass():
    cfg = frdm_config()
    script = {
        "root": "Password: ",                       # login reply
        "": "root@imx93frdm:~# ",                   # empty password ->
        "uname -a": "Linux imx93frdm 6.6.36 #1 SMP\r\n",
        "iw dev mlan0 link":
            "Connected to 9c:xx (mlan0)\r\n    signal: -49.0 dBm\r\n",
        "hciconfig hci0 piscan": "hci0 UP RUNNING PSCAN ISCAN\r\n",
        "l2ping -c 5 14:7D:DA:D2:BA:B4":
            "5 sent, 5 received, 0.0% loss\r\n",
        "/root/load_rf_drivers.sh":
            "moal inserted\r\nbtnxpuart inserted\r\nRF drivers loaded OK\r\n",
    }
    serial = FakeSerial(script)
    # pre-load the login banner (DUT already at the prompt)
    serial.buffer = (b"imx93frdm login: ")
    logs = []
    runner = FctTestRunner(cfg, log_sink=logs.append,
                           station_id="ST01", user="op")

    class StubRF:
        def __init__(self, table):
            self.table = table

        def run(self, template, params=None, **kw):
            cmd = template
            for k, v in (params or {}).items():
                cmd = cmd.replace("{{" + k + "}}", str(v))
            lines, exit_code = self.table.get(cmd, ([], 0))
            from mtkgui.engine.host_cli import HostCliResult, judge_keywords
            verdict, reason = judge_keywords(lines, exit_code=exit_code)
            return HostCliResult(cmd, list(lines), exit_code, 0.0,
                                 verdict, reason, {})

    wifi_lines = ("SSID: FRDM-IMX93-DUT\r\n  Signal / Noise: -49 dBm")
    bt_lines = "Not Connected:\n  JBL: RSSI: -55"
    host = StubRF({
        "system_profiler SPAirPortDataType": (wifi_lines.split("\n"), 0),
        "system_profiler SPBluetoothDataType": (
            ["Not Connected:", "  FRDM-IMX93-DUT:", "    RSSI: -55",
             "Address: 14:7D:DA:D2:BA:B4"], 0),
        "networksetup -listpreferredwirelessnetworks en0": ([], 0),
        "blueutil --inquiry 10": (
            ["address: B8:F4:4F:59:51:A0, name: FRDM-IMX93-DUT, "
             "RSSI: -55 dBm"], 0),
    })
    # rssi_only: no connect / no ping - the scan suffices
    out = runner.run(serial, host)
    assert out["overall"] == "PASS"
    names = [r.name for r in out["results"]]
    assert any("login wait 'login:'" in n for n in names)
    assert "Kernel check" in names and "Load RF drivers" in names
    assert "Wi-Fi rssi_only" in names and "Bluetooth rssi_only" in names
    assert "Overall Result: PASS" in out["report"]


def test_fct_runner_command_fail_flips_overall():
    cfg = frdm_config()
    script = {
        "root": "Password: ",
        "": "root@imx93frdm:~# ",
        "/root/load_rf_drivers.sh": "oops FAILED",
    }
    serial = FakeSerial(script)
    serial.buffer = b"imx93frdm login: "
    runner = FctTestRunner(cfg)
    out = runner.run(serial, None)
    assert out["overall"] == "FAIL"
    assert any(r.name == "Load RF drivers" and r.verdict == "FAIL"
               for r in out["results"])
