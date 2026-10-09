# -*- coding: utf-8 -*-
"""P3-B5: fct_test_config + fct_test_runner unit tests (no hardware)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from mtkgui.engine.fct_test_config import (
    BluetoothCfg,
    ConsoleCfg,
    ConsoleCommand,
    FctTestConfig,
    WifiCfg,
    build_fct_steps,
)
from mtkgui.engine.fct_test_runner import (
    FctStepResult,
    FctTestRunner,
    console_send_and_expect,
    match_expectation,
    wait_stage,
    send_stage,
    capture_stage,
)

FRDM_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/cu.usbmodem53930099631"
    baudrate: 115200
    test_commands:
      - {kind: wait, name: "Wait login prompt", expect_pass: "login:", timeout: 10}
      - {kind: send, name: "Send root", send: "root", expect_pass: "Password:", timeout: 5}
      - {kind: send, name: "Send empty password", send: "", expect_pass: "root@imx93frdm", timeout: 5}
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
    # wait login: -> send root (expects Password:) -> send empty (expects shell)
    # -> 2 test commands -> wifi -> bluetooth
    assert names[0] == "Wait login prompt"
    assert steps[0].params["kind"] == "wait"
    assert steps[1].params["send"] == "root"
    assert steps[1].params["kind"] == "send"
    assert steps[1].params["expect_pass_re"] == "Password:"
    assert steps[2].params["send"] == ""
    assert steps[2].params["expect_pass_re"] == "root@imx93frdm"
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
    assert "Wait login prompt" in names
    assert "Kernel check" in names and "Load RF drivers" in names
    assert "Wi-Fi rssi_only" in names and "Bluetooth rssi_only" in names
    assert "Overall Result: PASS" in out["report"]


def test_fct_runner_command_fail_flips_overall():
    cfg = frdm_config()
    script = {
        "root": "Password: ",
        "": "root@imx93frdm:~# ",
        "uname -a": "Linux imx93frdm 6.6.36\r\n",
        "/root/load_rf_drivers.sh": "oops FAILED",
    }
    serial = FakeSerial(script)
    serial.buffer = b"imx93frdm login: "
    runner = FctTestRunner(cfg)
    out = runner.run(serial, None)
    assert out["overall"] == "FAIL"
    assert any(r.name == "Load RF drivers" and r.verdict == "FAIL"
               for r in out["results"])


# ------------------------------------------------------------ bare metal DUT
def bare_config() -> FctTestConfig:
    """Bare Metal/RTOS DUT: full Wait->Send->Capture over SERIAL (the
    firmware prompts and accepts replies, e.g. a Button/LED test), but no
    SSH/SFTP; Wi-Fi and Bluetooth are host -> DUT RSSI-only scans."""
    return FctTestConfig(
        dut_type="bare_metal",
        console=ConsoleCfg(
            enabled=True, port="/dev/cu.usbmodem1",
            test_commands=[
                ConsoleCommand(name="FW version", kind="send",
                               send="version", send_enabled=True,
                               capture_enabled=True,
                               expect_fail=r"FW v\d+",
                               expect_fail_is_regex=True,
                               capture_is_expected=True),
                # interactive firmware test: wait prompt -> send yes/no
                ConsoleCommand(name="Button 1 / LED", kind="send",
                               send="y",
                               wait_enabled=True, send_enabled=True,
                               capture_enabled=True,
                               expect_pass="PRESS BUTTON 1 THEN CONFIRM",
                               expect_fail="LED1 OK",
                               capture_is_expected=True),
                ConsoleCommand(name="Boot log capture", kind="capture",
                               send_enabled=False, capture_enabled=True),
            ]),
        wifi=WifiCfg(enabled=True, mode="rssi_only", ssid="DUT-AP"),
        bluetooth=BluetoothCfg(enabled=True, expected_name="DUT-BT",
                               l2ping_count=0))


def test_bare_metal_validate_clean():
    assert bare_config().validate() == []


def test_bare_metal_validate_rejects_host_side_gaps():
    cfg = bare_config()
    cfg.console.ssh_host = "192.168.10.129"
    cfg.wifi.bandwidth.enabled = True
    cfg.wifi.bandwidth.server_ip = "192.168.10.141"
    cfg.bluetooth.l2ping_count = 5
    errors = cfg.validate()
    assert len(errors) == 3
    assert any("ssh_host" in e for e in errors)
    assert any("bandwidth" in e for e in errors)
    assert any("l2ping_count" in e for e in errors)


def test_bare_metal_serial_three_stage_steps():
    # Bare metal keeps the full Wait->Send->Capture flow over serial;
    # only SSH/SFTP and the DUT-side RF data paths are absent.
    steps = build_fct_steps(bare_config(), channel_key="ser1")
    names = [s.name for s in steps]
    by_name = {s.name: s for s in steps}
    # no auto login chain, no DUT-side piscan/ping/iperf/L2CAP steps
    assert not any("Console wait" in n or "Console send" in n
                   for n in names)
    assert not any("piscan" in n or "L2CAP" in n or "iperf" in n
                   or "ping gateway" in n for n in names)
    # serial command rows still send to the firmware
    ver = by_name["FW version"]
    assert ver.params["send"] == "version"
    assert ver.params["expect_pass_re"] == r"FW v\d+"
    cap = by_name["Boot log capture"]
    assert "send" not in cap.params
    # interactive Button/LED row: a pre-send Wait step then the send/capture
    btn_wait = by_name["Button 1 / LED (wait)"]
    btn = by_name["Button 1 / LED"]
    assert btn_wait.params["kind"] == "wait"
    assert "send" not in btn_wait.params
    assert btn_wait.params["expect_pass_re"] == "PRESS BUTTON 1 THEN CONFIRM"
    assert btn.params["send"] == "y"
    assert btn.params["expect_pass_re"] == "LED1 OK"
    # every console step is bound to the serial channel, none are ssh/sftp
    for s in steps:
        if s.params.get("fct_console"):
            assert s.channel == "ser1"
            assert s.params.get("kind") not in ("sftp_put", "sftp_get")
    # Wi-Fi RSSI is a HOST-side discovery scan (unbound channel)
    wifi = next(s for s in steps if s.params.get("tool_family") == "wifi")
    assert wifi.name == "Wi-Fi FCT (host scan)"
    assert wifi.channel == ""
    # BT verdict stays host-side; discoverability is firmware-owned
    assert "Bluetooth FCT" in names


def test_bare_metal_rejects_ssh_transport_and_sftp():
    cfg = bare_config()
    cfg.console.test_commands[0].transport = "ssh"
    cfg.console.test_commands.append(
        ConsoleCommand(name="Deploy", kind="sftp_put", transport="ssh",
                       send_enabled=True, local="a.sh", remote="/root/a.sh"))
    errors = cfg.validate()
    assert any("SSH" in e and "serial" in e for e in errors)
    assert any("sftp_put" in e for e in errors)


# ------------------------------------------------- three-stage Wait/Send/Capture
def _cmd(**kw):
    """A ConsoleCommand with fast timeouts for stage testing."""
    base = dict(kind="send", wait_timeout=0.4, send_timeout=0.4, timeout=0.4)
    base.update(kw)
    return ConsoleCommand(**base)


def _runner(commands):
    cfg = frdm_config()
    cfg.console.test_commands = commands
    return FctTestRunner(cfg)


def test_wait_stage_hits_and_times_out():
    # prompt already in buffer -> immediate hit (wait never resets it)
    s = FakeSerial({})
    s.buffer = b"imx93frdm login: "
    v, _ = wait_stage(s, "login:", False, True, 0.4)
    assert v == "PASS"
    # missing prompt -> TIMEOUT
    s2 = FakeSerial({})
    v2, _ = wait_stage(s2, "login:", False, True, 0.3)
    assert v2 == "TIMEOUT"


def test_send_stage_multiline_autonewline_and_empty():
    s = FakeSerial({"echo a": "a\r\n", "echo b": "b\r\n"})
    v, _ = send_stage(s, "echo a\necho b", 0.4)
    assert v == "PASS"
    # each line sent once, newline auto-appended (user never writes \n)
    assert s.sent == ["echo a", "echo b"]
    # an empty command still sends one newline (blank password)
    s2 = FakeSerial({"": "root@imx93:~# "})
    v2, _ = send_stage(s2, "", 0.4)
    assert v2 == "PASS"
    assert s2.sent == [""]


def test_capture_expected_yes_found():
    s = FakeSerial({"run": "booting\r\nREADY\r\n"})
    s.write(b"run\n")
    v, _ = capture_stage(s, "READY", "", True, False, True, 0.4)
    assert v == "PASS"


def test_capture_expected_yes_miss_but_endline_seen_is_fail():
    # EndLine bounds the window; pattern never appears inside it
    s = FakeSerial({"run": "some noise\r\nDONE\r\n"})
    s.write(b"run\n")
    v, _ = capture_stage(s, "READY", "DONE", True, False, True, 0.4)
    assert v == "FAIL"


def test_capture_expected_no_bad_message_fails():
    s = FakeSerial({"run": "starting\r\nERROR boom\r\nDONE\r\n"})
    s.write(b"run\n")
    v, _ = capture_stage(s, "ERROR", "DONE", False, False, True, 0.4)
    assert v == "FAIL"


def test_capture_expected_no_clean_window_passes_at_endline():
    s = FakeSerial({"run": "all good\r\nDONE\r\n"})
    s.write(b"run\n")
    v, _ = capture_stage(s, "ERROR", "DONE", False, False, True, 0.4)
    assert v == "PASS"


def test_capture_expected_no_endline_missing_times_out():
    # no bad message but the bounding EndLine never arrives -> timeout FAIL
    s = FakeSerial({"run": "all good\r\n"})
    s.write(b"run\n")
    v, _ = capture_stage(s, "ERROR", "DONE", False, False, True, 0.3)
    assert v == "TIMEOUT"


def test_capture_forbid_negative_keyword_fails_expected_yes():
    # positive pattern present but a forbidden keyword also appears
    s = FakeSerial({"run": "READY\r\nwarning: FAILED\r\n"})
    s.write(b"run\n")
    v, _ = capture_stage(s, "READY", "", True, False, True, 0.4,
                         forbid="FAILED")
    assert v == "FAIL"


def test_pipeline_capture_only_no_send():
    # firmware runs autonomously after power-on: capture only, no send
    s = FakeSerial({})
    s.buffer = b"FW v3.2 ready\r\n"
    cmd = _cmd(name="Boot capture", kind="capture", send="",
               wait_enabled=False, send_enabled=False, capture_enabled=True,
               expect_fail=r"FW v[\d.]+ ready", expect_fail_is_regex=True,
               capture_is_expected=True)
    r = _runner([cmd]).run_console(s)
    assert r[0].verdict == "PASS"
    assert s.sent == []                      # nothing transmitted


def test_pipeline_send_then_capture_no_wait_bare_metal():
    s = FakeSerial({"version": "FW v9\r\n"})
    cmd = _cmd(name="FW version", kind="send", send="version",
               wait_enabled=False, send_enabled=True, capture_enabled=True,
               expect_fail=r"FW v\d+", expect_fail_is_regex=True,
               capture_is_expected=True)
    r = _runner([cmd]).run_console(s)
    assert r[0].verdict == "PASS"
    assert s.sent == ["version"]


def test_pipeline_send_only_ignores_reply():
    s = FakeSerial({"reset": ""})           # no meaningful reply
    cmd = _cmd(name="Reset", kind="send", send="reset",
               wait_enabled=False, send_enabled=True, capture_enabled=False)
    r = _runner([cmd]).run_console(s)
    assert r[0].verdict == "PASS"


def test_wait_failure_aborts_remaining_commands():
    # WaitFor never satisfied -> whole sequence stops, later send not sent
    s = FakeSerial({"root": "Password: "})
    cmds = [
        _cmd(name="Wait prompt", kind="wait", send="",
             wait_enabled=True, send_enabled=False, capture_enabled=False,
             expect_pass="login:"),
        _cmd(name="Login", kind="send", send="root",
             wait_enabled=False, send_enabled=True, capture_enabled=False),
    ]
    r = _runner(cmds).run_console(s)
    assert r[0].verdict == "FAIL"
    assert len(r) == 1                      # second command never ran
    assert "root" not in s.sent


class _FlakySerial(FakeSerial):
    """Fails the first N writes, then behaves normally."""
    def __init__(self, script, fail_writes=1):
        super().__init__(script)
        self._fail = fail_writes
        self.write_attempts = 0

    def write(self, data):
        self.write_attempts += 1
        if self._fail > 0:
            self._fail -= 1
            raise OSError("device disappeared")
        return super().write(data)


def test_retry_recovers_from_transient_send_failure():
    # retries=1 -> one extra whole-command attempt after the first failure
    s = _FlakySerial({"reset": "ok\r\n"}, fail_writes=1)
    cmd = _cmd(name="Reset", kind="send", send="reset", retries=1,
               wait_enabled=False, send_enabled=True, capture_enabled=True,
               expect_fail="ok", capture_is_expected=True)
    r = _runner([cmd]).run_console(s)
    assert r[0].verdict == "PASS"           # retried and succeeded
    assert s.write_attempts == 2            # first failed, retried once
    assert s.sent == ["reset"]              # the retry transmitted cleanly


def test_retry_on_timeout_runs_command_twice():
    # capture never matches; with retries=1 the command is attempted twice
    s = FakeSerial({"probe": "noise\r\n"})  # no READY, no end line
    cmd = _cmd(name="Probe", kind="send", send="probe", retries=1,
               wait_enabled=False, send_enabled=True, capture_enabled=True,
               expect_fail="READY", capture_is_expected=True, timeout=0.2)
    r = _runner([cmd]).run_console(s)
    assert r[0].verdict == "FAIL"
    assert s.sent == ["probe", "probe"]     # attempted twice


def test_legacy_yaml_migrates_to_three_stage():
    # FRDM_YAML is the legacy shape (no enable flags): wait rows become
    # wait-only, send rows carry the post-send expectation as Capture want
    cfg = frdm_config()
    wait, root, empty, kernel, drivers = cfg.console.test_commands
    assert wait.wait_enabled and not wait.send_enabled
    assert root.send_enabled and root.capture_enabled
    assert root.capture_is_expected
    assert root.expect_fail == "Password:"     # post-send success message
    assert drivers.capture_forbid == "FAILED"  # legacy expect_fail


def test_sftp_row_has_no_wait_or_capture():
    steps = build_fct_steps(frdm_config(), channel_key="ssh1")  # baseline
    # directly build an sftp command and check its runner path
    class _Sftp:
        def __init__(self): self.puts = []
        def put_file(self, local, remote=""): self.puts.append((local, remote))
    cmd = ConsoleCommand(name="Deploy script", kind="sftp_put",
                         transport="ssh", local="load_drivers.sh",
                         remote="/root/load_drivers.sh",
                         wait_enabled=False, send_enabled=True,
                         capture_enabled=False)
    runner = _runner([cmd])
    v, detail = runner._run_sftp(_Sftp(), cmd)
    assert v == "PASS" and "put" in detail
    # build_fct_steps emits an sftp action step, not a message wait
    cfg = frdm_config()
    cfg.console.transport = "ssh"
    cfg.console.test_commands = [cmd]
    st = build_fct_steps(cfg, channel_key="ssh1")[0]
    assert st.params["kind"] == "sftp_put"
    assert "expect_pass_re" not in st.params or st.params["expect_pass_re"] == ""
    assert st.params["local"] == "load_drivers.sh"

