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
    FctSetupCfg,
    FctTestConfig,
    WifiCfg,
    build_fct_steps,
    cases_to_console_commands,
    overlay_console_commands,
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
    interface: mlan0
    driver_load_cmd: ""
    scan_enabled: true
    ap_ssid: FRDM-IMX93-DUT
    scan_via: dut_console
    rssi_min: -70
    scan_timeout: 15
    ping_enabled: false
    iperf_enabled: false
  bluetooth:
    enabled: true
    rssi_enabled: true
    expected_name: FRDM-IMX93-DUT
    rssi_min: -70
    rssi_timeout: 15
    pair_enabled: false
    tone_enabled: false
    l2ping_count: 0
    audio_confirm: true
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
    cfg.console.baudrate = 1234
    # every Wi-Fi / BT sub-test switched off -> one error each
    cfg.wifi.scan_enabled = False
    cfg.bluetooth.rssi_enabled = False
    errors = cfg.validate()
    assert len(errors) == 3
    assert any("baudrate" in e for e in errors)
    assert any("wifi" in e and "scan / ping / iperf" in e for e in errors)
    assert any("bluetooth" in e and "rssi / pair / tone" in e
               for e in errors)


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
    assert wifi.name == "Wi-Fi Scan / RSSI (DUT console)"
    assert wifi.params["rssi_via"] == "dut_console"   # station mode
    assert bt.name == "Bluetooth RSSI"
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
    # Linux BT, RSSI-only: make discoverable, then the host RSSI scan
    assert [s.name for s in steps] == ["BT discoverable (piscan)",
                                       "Bluetooth RSSI"]


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
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="host Bluetooth RSSI uses the macOS toolchain (blueutil/"
           "system_profiler); Windows has no built-in classic-BT backend")
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
    # scan/RSSI only: no connect / ping / iperf - the discovery suffices
    out = runner.run(serial, host)
    assert out["overall"] == "PASS"
    names = [r.name for r in out["results"]]
    assert "Wait login prompt" in names
    assert "Kernel check" in names and "Load RF drivers" in names
    assert "Wi-Fi Scan / RSSI" in names and "Bluetooth RSSI" in names
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


# ------------------------------------------------------------ host CLI rows
def test_host_row_roundtrip_and_steps():
    """'host' rows run a command ON THE HOST PC; post_rf rows are
    ordered AFTER every Wi-Fi/BT RF step."""
    cfg = frdm_config()
    cfg.console.test_commands.append(ConsoleCommand(
        kind="host", name="Start server", host_cmd="iperf3 -s -D",
        host_cmd_windows="start /B iperf3 -s", timeout=15))
    cfg.console.post_rf_commands = [
        ConsoleCommand(kind="send", name="Shutdown DUT",
                       wait_enabled=True, expect_pass="root@imx93frdm",
                       send="shutdown now"),
        ConsoleCommand(kind="host", name="Stop server",
                       host_cmd="pkill -x iperf3 || true"),
    ]
    restored = FctTestConfig.from_dict(cfg.to_dict())
    assert restored.to_dict() == cfg.to_dict()
    assert restored.validate() == []
    steps = build_fct_steps(restored, channel_key="ser1")
    host = [s for s in steps if s.params.get("fct_host_cmd")]
    assert [s.name for s in host] == ["Start server", "Stop server"]
    assert host[0].step_type == "EXTERNAL_TOOL" and host[0].channel == ""
    assert host[0].params["fct_host_cmd"]["cmd"] == "iperf3 -s -D"
    assert host[0].params["fct_host_cmd"]["cmd_windows"] == \
        "start /B iperf3 -s"
    # post-RF rows come AFTER every RF tool step (wifi/bluetooth)
    last_rf = max(i for i, s in enumerate(steps)
                  if s.params.get("tool_family"))
    post = [i for i, s in enumerate(steps)
            if s.name in ("Stop server", "Shutdown DUT",
                          "Shutdown DUT (wait)")]
    assert min(post) > last_rf


def test_host_row_requires_command():
    cfg = frdm_config()
    cfg.console.test_commands.append(
        ConsoleCommand(kind="host", name="empty"))
    assert any("host_cmd" in e for e in cfg.validate())


def test_fct_exec_host_cli_branch(monkeypatch):
    """fct_exec runs a host row on the HOST PC and judges by exit code
    (rc 0 = PASS, rc != 0 = FAIL); the macOS command is the default."""
    from mtkgui.engine import fct_exec
    from mtkgui.gui.yamlbuild.fct_build import FctStep, STEP_EXTERNAL_TOOL

    seen = {}

    class FakeRes:
        def __init__(self, rc, lines):
            self.exit_code, self.lines = rc, lines

    class FakeRunner:
        def __init__(self, rc, lines):
            self.rc, self.lines = rc, lines

        def run(self, cmd, timeout_s=30.0, **kw):
            seen["cmd"], seen["timeout"] = cmd, timeout_s
            return FakeRes(self.rc, self.lines)

    monkeypatch.setattr(fct_exec, "runner_for",
                        lambda ctx: FakeRunner(0, ["server started"]))
    logs = []
    ctx = fct_exec.FctContext(log_sink=logs.append)
    step = FctStep(name="Start iperf3 server",
                   step_type=STEP_EXTERNAL_TOOL, timeout_s=15.0,
                   params={"fct_host_cmd": {
                       "cmd": "iperf3 -s -D",
                       "cmd_windows": "start /B iperf3 -s"}})
    out = fct_exec.execute_fct_step(step, ctx)
    import sys
    expected_cmd = ("start /B iperf3 -s" if sys.platform == "win32"
                    else "iperf3 -s -D")
    assert out.verdict == "PASS"
    assert out.reason.startswith(f"{expected_cmd} -> rc=0")
    assert seen["cmd"] == expected_cmd   # platform-specific host_cmd
    assert seen["timeout"] == 15.0

    monkeypatch.setattr(fct_exec, "runner_for",
                        lambda ctx: FakeRunner(1, []))
    out = fct_exec.execute_fct_step(step, ctx)
    assert out.verdict == "FAIL"


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
        wifi=WifiCfg(enabled=True, scan_enabled=True, ap_ssid="DUT-AP"),
        bluetooth=BluetoothCfg(enabled=True, rssi_enabled=True,
                               expected_name="DUT-BT",
                               pair_enabled=False, tone_enabled=False,
                               l2ping_count=0))


def test_bare_metal_validate_clean():
    assert bare_config().validate() == []


def test_bare_metal_validate_rejects_host_side_gaps():
    cfg = bare_config()
    cfg.console.ssh_host = "192.168.10.129"
    cfg.wifi.ping_enabled = True
    cfg.bluetooth.pair_enabled = True
    errors = cfg.validate()
    assert len(errors) == 3
    assert any("ssh_host" in e for e in errors)
    assert any("Wi-Fi ping" in e for e in errors)
    assert any("pair/connect" in e for e in errors)


def test_bare_metal_serial_three_stage_steps():
    # Bare metal keeps the full Wait->Send->Capture flow over serial;
    # only SSH/SFTP and the DUT-side RF data paths are absent.
    steps = build_fct_steps(bare_config(), channel_key="ser1")
    names = [s.name for s in steps]
    by_name = {s.name: s for s in steps}
    # no auto login chain, no DUT-side piscan/ping/iperf/L2CAP steps
    assert not any("Console wait" in n or "Console send" in n
                   for n in names)
    assert not any("piscan" in n or "L2CAP" in n or "iPerf" in n
                   or "Connect & Ping" in n or "Pair" in n
                   or "Tone" in n for n in names)
    # serial command rows still send to the firmware
    ver = by_name["FW version"]
    assert ver.params["send"] == "version"
    assert ver.params["expect_pass_re"] == r"FW v\d+"
    cap = by_name["Boot log capture"]
    assert "send" not in cap.params
    # interactive Button/LED row: ONE interact step carrying all three
    # stages (WaitFor -> Send -> Capture); the old "(wait)" pre-step is
    # gone (unified model 2026-10-28)
    assert "Button 1 / LED (wait)" not in by_name
    btn = by_name["Button 1 / LED"]
    assert btn.params["wait_enabled"] is True
    assert btn.params["wait_pattern"] == "PRESS BUTTON 1 THEN CONFIRM"
    assert btn.params["wait_is_regex"] is False
    assert btn.params["send"] == "y"
    assert btn.params["expect_pass_re"] == "LED1 OK"
    # every console step is bound to the serial channel, none are ssh/sftp
    for s in steps:
        if s.params.get("fct_console"):
            assert s.channel == "ser1"
            assert s.params.get("kind") not in ("sftp_put", "sftp_get")
    # Wi-Fi RSSI is a HOST-side discovery scan (unbound channel)
    wifi = next(s for s in steps if s.params.get("tool_family") == "wifi")
    assert wifi.name == "Wi-Fi Scan / RSSI"
    assert wifi.channel == ""
    # BT verdict stays host-side; discoverability is firmware-owned
    assert "Bluetooth RSSI" in names


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


def test_wait_stage_matches_session_history():
    # row-8 scenario: the prompt was consumed by an earlier row's
    # capture and no fresh bytes arrive - history must still match
    # (GUI-equivalent accumulated-buffer semantics)
    s = FakeSerial({})
    v, text = wait_stage(s, "root@imx93frdm", False, True, 0.4,
                         history="Linux imx93frdm\r\nroot@imx93frdm:~# ")
    assert v == "PASS" and "root@imx93frdm" in text
    # empty history on a silent line still times out
    s2 = FakeSerial({})
    v2, _ = wait_stage(s2, "root@imx93frdm", False, True, 0.3)
    assert v2 == "TIMEOUT"


def test_pipeline_wait_matches_prompt_consumed_by_earlier_capture():
    # cmd1's capture consumes the trailing prompt; cmd2 waits for the
    # same prompt before sending - it must pass via session history
    s = FakeSerial({
        "uname -a": "Linux imx93frdm 6.6.36\r\nroot@imx93frdm:~# ",
        "cd /root && python3 fat.py": "FRDM-i.MX93 DUT\r\n",
    })
    cmds = [
        _cmd(name="Preflight kernel", send="uname -a",
             capture_enabled=True, expect_fail="Linux imx93frdm",
             capture_is_expected=True),
        _cmd(name="Start fat.py", send="cd /root && python3 fat.py",
             wait_enabled=True, expect_pass="root@imx93frdm",
             capture_enabled=True, expect_fail="FRDM-i.MX93 DUT",
             capture_is_expected=True),
    ]
    res = _runner(cmds).run_console(s)
    assert [r.verdict for r in res] == ["PASS", "PASS"], \
        [(r.name, r.verdict, r.detail) for r in res]


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


def test_pipeline_forbid_hit_carries_evidence_detail():
    # a forbid hit fails fast AND the report detail names the unwanted
    # keyword (e.g. fat.py verdict row: 'Overall result: FAIL')
    s = FakeSerial({"run": "READY\r\nOverall result: FAIL\r\n"})
    cmd = _cmd(name="fat.py verdict", kind="send", send="run",
               wait_enabled=False, send_enabled=True, capture_enabled=True,
               expect_fail="Overall result: PASS",
               capture_is_expected=True,
               capture_forbid="Overall result: FAIL")
    r = _runner([cmd]).run_console(s)
    assert r[0].verdict == "FAIL"
    assert r[0].detail == "matched unwanted 'Overall result: FAIL'"


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


# ------------------------------------------------- Confirm stage (v2.1)
def test_confirm_fields_roundtrip():
    """confirm_enabled / confirm_message survive the yaml round-trip."""
    cmd = _cmd(name="Earphone", kind="send", send="y",
               wait_enabled=True, send_enabled=True, capture_enabled=True,
               expect_pass="tone?", expect_fail="heard",
               confirm_enabled=True, confirm_message="Did you hear it?")
    cfg = frdm_config()
    cfg.console.test_commands = [cmd]
    restored = FctTestConfig.from_dict(cfg.to_dict())
    c = restored.console.test_commands[0]
    assert c.confirm_enabled is True
    assert c.confirm_message == "Did you hear it?"
    assert restored.to_dict() == cfg.to_dict()


def test_confirm_defaults_off_and_survive_default_load():
    cmd = _cmd(name="Kernel check", kind="send", send="uname -a")
    assert cmd.confirm_enabled is False and cmd.confirm_message == ""
    cfg = frdm_config()
    cfg.console.test_commands = [cmd]
    restored = FctTestConfig.from_dict(cfg.to_dict())
    assert restored.to_dict() == cfg.to_dict()


def test_build_steps_confirm_is_an_explicit_dialog_step():
    """Unified model: a row's confirmation is its OWN visible dialog
    step placed right after the interact row - never an implicit popup
    and never a marker hidden in the row's params."""
    cmd = _cmd(name="Earphone", kind="send", send="y",
               wait_enabled=True, send_enabled=True, capture_enabled=True,
               expect_pass="tone?", expect_fail="heard",
               confirm_enabled=True, confirm_message="Did you hear it?")
    cfg = frdm_config()
    cfg.console.test_commands = [cmd]
    steps = build_fct_steps(cfg)
    names = [s.name for s in steps]
    assert "Earphone (wait)" not in names
    main = next(s for s in steps if s.name == "Earphone")
    assert "confirm_enabled" not in main.params
    dlg = next(s for s in steps if s.name == "Confirm: Earphone")
    assert dlg.params["console_dialog"] is True
    assert dlg.params["style"] == "yesno"
    assert dlg.params["message"] == "Did you hear it?"
    assert names.index("Earphone") < names.index("Confirm: Earphone")


def test_pipeline_confirm_no_stops_before_send():
    s = FakeSerial({})
    cmd = _cmd(name="Earphone", kind="send", send="y",
               wait_enabled=False, send_enabled=True,
               capture_enabled=False,
               confirm_enabled=True, confirm_message="Did you hear it?")
    runner = _runner([cmd])
    runner._human_confirm = lambda q: False
    r = runner.run_console(s)
    assert r[0].verdict == "FAIL"
    assert r[0].detail == "operator answered No"
    assert s.sent == []                      # nothing reached the DUT


def test_pipeline_confirm_yes_sends_and_asks_message_text():
    s = FakeSerial({"y": "heard\r\n"})
    cmd = _cmd(name="Earphone", kind="send", send="y",
               wait_enabled=False, send_enabled=True,
               capture_enabled=True, expect_fail="heard",
               capture_is_expected=True,
               confirm_enabled=True, confirm_message="Did you hear it?")
    runner = _runner([cmd])
    questions = []
    runner._human_confirm = lambda q: (questions.append(q), True)[1]
    r = runner.run_console(s)
    assert r[0].verdict == "PASS"
    assert questions == ["Did you hear it?"]  # dialog shows the message
    assert s.sent == ["y"]


def test_pipeline_confirm_missing_hook_is_error():
    s = FakeSerial({"y": "heard\r\n"})
    cmd = _cmd(name="Earphone", kind="send", send="y",
               wait_enabled=False, send_enabled=True,
               capture_enabled=False, confirm_enabled=True)
    r = _runner([cmd]).run_console(s)        # no _human_confirm bound
    assert r[0].verdict == "ERROR"
    assert r[0].detail == "no confirm hook bound"
    assert s.sent == []


def test_pipeline_capture_pass_keeps_last_line_evidence():
    """The capture verdict row keeps its last output line as the step
    detail (evidence, e.g. fat.py 'Overall result: PASS')."""
    s = FakeSerial({})
    s.buffer = b"noise line\r\nOverall result: PASS\r\n"
    cmd = _cmd(name="fat verdict", kind="capture",
               wait_enabled=False, send_enabled=False,
               capture_enabled=True,
               expect_fail="Overall result: PASS",
               capture_is_expected=True)
    r = _runner([cmd]).run_console(s)
    assert r[0].verdict == "PASS"
    assert r[0].detail.endswith("Overall result: PASS")


def test_console_step_result_carries_duration():
    """Every executed console row reports its wall time for the report
    'duration' column (a negative capture spans its whole timeout
    window).  Reverse validation (v1.0.2): a SILENT DUT can never PASS
    a capture — 'survived the window clean' requires actual output."""
    s = FakeSerial({})                      # silent: unwanted line never comes
    cmd = _cmd(name="slow verdict", kind="capture",
               wait_enabled=False, send_enabled=False,
               capture_enabled=True,
               expect_fail="never arrives", capture_is_expected=False)
    r = _runner([cmd]).run_console(s)
    assert r[0].verdict == "FAIL"           # silence is no evidence
    assert "no console output" in r[0].detail
    assert r[0].duration >= 0.25            # ... and it timed the window


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


def test_sftp_step_carries_own_ssh_channel_and_endpoint():
    """M27 P8: an sftp row is emitted with channel='ssh' plus the
    console's ssh_host / ssh_username, so the runner binds an SSH
    channel instead of the serial console."""
    cfg = frdm_config()
    cfg.console.ssh_host = "192.168.10.129"
    cfg.console.ssh_username = "root"
    sftp = ConsoleCommand(name="Get fat_result.json", kind="sftp_get",
                          transport="ssh", local="{{dut_report}}/fat.json",
                          remote="/root/fat_result.json",
                          wait_enabled=False, send_enabled=True,
                          capture_enabled=False)
    cfg.console.test_commands = [sftp]
    st = build_fct_steps(cfg, channel_key="ser1")[0]
    assert st.channel == "ssh"
    assert st.params["kind"] == "sftp_get"
    assert st.params["ssh_host"] == "192.168.10.129"
    assert st.params["ssh_username"] == "root"


def test_apply_does_not_duplicate_deploy_or_confirm(monkeypatch, tmp_path):
    """M27 P9: an apply/reload cycle yields ONE 'Deploy test assets to
    DUT' and ONE earphone confirm, and the earphone interact row does
    NOT send 'y' (the explicit dialog is the single sender)."""
    from mtkgui.gui.yamlbuild.fct_build import FctSequence, to_project_fct_cases

    cfg = frdm_config()
    cfg.dut_type = "linux"
    # a console command whose answer is a legacy confirm_enabled marker
    tone = ConsoleCommand(
        name="fat.py: MQS earphone tone", kind="send", transport="serial",
        wait_enabled=True, expect_pass=r"Did you hear the \d+ Hz tone\?",
        expect_pass_is_regex=True, send_enabled=True, send="y",
        capture_enabled=True, expect_fail="operator confirmed tone heard",
        timeout=20.0, wait_timeout=120.0, confirm_enabled=True,
        confirm_message="Did you hear the tone?")
    login = ConsoleCommand(
        name="Console login", kind="send", transport="serial",
        wait_enabled=True, expect_pass="imx93frdm login:",
        send_enabled=True, send="root", capture_enabled=True,
        expect_fail="root@imx93frdm", timeout=15.0, retries=1)
    cfg.console.test_commands = [login, tone]
    cfg.console.serial_deploy = True
    cfg.console.serial_deploy_files = [
        {"local": "scripts/connect_wifi.sh", "remote": "/root/connect_wifi.sh"}]

    def emit(cfg):
        steps = build_fct_steps(cfg, channel_key="ser1")
        cases = to_project_fct_cases(FctSequence(name="f", steps=steps))
        return steps, cases

    steps1, cases1 = emit(cfg)
    names1 = [s.name for s in steps1]
    assert names1.count("Deploy test assets to DUT") == 1
    assert names1.count("Confirm: fat.py: MQS earphone tone") == 1
    # single sender: the interact row sends nothing, the dialog carries y
    tone1 = next(s for s in steps1 if s.name == "fat.py: MQS earphone tone")
    assert tone1.params.get("send_enabled") is False
    assert "send" not in tone1.params

    # reload: overlay the published cases back and re-emit (round-trip)
    import yaml as _yaml
    yaml_text = _cfg_to_yaml(cfg)
    _, cases = emit(cfg)
    overlaid = overlay_console_commands(yaml_text, cases)
    cfg2 = FctTestConfig.from_dict(
        _yaml.safe_load(overlaid)["fct_test_config"])
    steps2, cases2 = emit(cfg2)
    names2 = [s.name for s in steps2]
    assert names2.count("Deploy test assets to DUT") == 1
    assert names2.count("Confirm: fat.py: MQS earphone tone") == 1
    tone2 = next(s for s in steps2 if s.name == "fat.py: MQS earphone tone")
    assert tone2.params.get("send_enabled") is False


def _cfg_to_yaml(cfg):
    import yaml as _yaml
    node = {"fct_test_config": cfg.to_dict()}
    return _yaml.safe_dump(node, sort_keys=False)



# ---------------------------------------------------------------------------
# FCT setup wrapper (power source + ATE fixture spine), P3-B5
# ---------------------------------------------------------------------------
from mtkgui.gui.yamlbuild.fct_build import FctStep as _FctStep  # noqa: E402
from mtkgui.engine.fct_test_config import (  # noqa: E402
    FctSetupCfg,
    POWER_MANUAL,
    POWER_NONE,
    POWER_PSU,
    wrap_fct_setup,
)


def _body():
    return [_FctStep(name="Body test", step_type="MESSAGE_CHECK")]


def _setup_cfg(power_mode=POWER_MANUAL, use_fixture=False):
    cfg = FctTestConfig()
    cfg.setup = FctSetupCfg(power_mode=power_mode, use_fixture=use_fixture)
    return cfg


def test_setup_manual_wraps_on_and_off_prompts():
    steps = wrap_fct_setup(_setup_cfg(POWER_MANUAL), _body())
    names = [s.name for s in steps]
    assert "Connect the power adapter" in names[0]
    assert names[-1].startswith("FCT finished")
    # M22: the spine no longer auto-appends a closing "FCT done." row
    assert "FCT done." not in names
    # no standard op rows in manual mode
    assert all(not s.params.get("op") for s in steps)


def test_setup_psu_uses_power_on_off_ops():
    steps = wrap_fct_setup(_setup_cfg(POWER_PSU), _body())
    names = [s.name for s in steps]
    assert names[0] == "Power On DUT"
    assert "Power Off DUT" in names
    on = names.index("Power On DUT")
    off = names.index("Power Off DUT")
    assert on < names.index("Body test") < off


def test_setup_none_adds_no_power_action():
    steps = wrap_fct_setup(_setup_cfg(POWER_NONE), _body())
    names = [s.name for s in steps]
    assert names == ["Body test"]


def test_wrap_never_auto_appends_fct_done():
    """M22: the loader/build never adds a closing row by itself."""
    for mode in (POWER_NONE, POWER_MANUAL, POWER_PSU):
        names = [s.name for s in wrap_fct_setup(_setup_cfg(mode), _body())]
        assert "FCT done." not in names


def test_wrap_dedupes_identical_phantom_rows():
    """M22: legacy YAMLs with the old auto row load as ONE row."""
    body = [_FctStep(name="FCT done.", step_type="MESSAGE_CHECK"),
            _FctStep(name="FCT done.", step_type="MESSAGE_CHECK")]
    steps = wrap_fct_setup(_setup_cfg(POWER_NONE), body)
    assert [s.name for s in steps] == ["FCT done."]


def test_sequence_roundtrip_is_deterministic():
    """M22: load(build(cfg)) -> build again yields the same cases
    (names + full step markers) - no phantom rows, no drift."""
    from mtkgui.gui.yamlbuild.fct_build import (
        FctSequence,
        to_project_fct_cases,
    )
    cfg = FctTestConfig()
    cfg.setup = FctSetupCfg(power_mode=POWER_NONE)
    cfg.console.enabled = True
    cfg.console.test_commands = [
        ConsoleCommand(kind="send", name="Cmd", wait_enabled=True,
                       send_enabled=True, capture_enabled=False,
                       expect_pass="ready", send="run", timeout=5.0,
                       wait_timeout=5.0)]

    def _cases(c):
        steps = wrap_fct_setup(c, build_fct_steps(c))
        return to_project_fct_cases(FctSequence(name="x", steps=steps))

    first = _cases(cfg)
    again = _cases(FctTestConfig.from_dict(
        cfg.to_yaml_node()["fct_test_config"]))
    assert [c["name"] for c in first] == [c["name"] for c in again]
    assert ([c["op_params"]["fct_step"] for c in first]
            == [c["op_params"]["fct_step"] for c in again])


def test_setup_fixture_order_with_psu():
    steps = wrap_fct_setup(_setup_cfg(POWER_PSU, use_fixture=True), _body())
    names = [s.name for s in steps]
    assert names[:3] == ["Fixture Clamp Down", "Fixture Lock",
                         "Fixture E-Stop Healthy"]
    assert names[3] == "Power On DUT"
    assert names[-2:] == ["Fixture Unlock", "Fixture Release"]


def test_setup_validation_rules():
    assert FctSetupCfg(power_mode="bogus").validate()
    assert FctSetupCfg(power_mode=POWER_MANUAL,
                       manual_on_message="  ").validate()
    assert FctSetupCfg(power_mode=POWER_PSU).validate() == []
    assert FctSetupCfg(power_mode=POWER_NONE).validate() == []


def test_setup_round_trips_through_yaml():
    cfg = _setup_cfg(POWER_PSU, use_fixture=True)
    restored = FctTestConfig.from_dict(cfg.to_dict())
    assert restored.setup.power_mode == POWER_PSU
    assert restored.setup.use_fixture is True


# ------------------------------------------------- RF per-sub-test model
def _linux_full_rf_config() -> FctTestConfig:
    return FctTestConfig(
        dut_type="linux",
        wifi=WifiCfg(
            enabled=True, interface="mlan0",
            driver_load_cmd="/root/load_rf_drivers.sh",
            scan_enabled=True, ap_ssid="DUT-AP", ap_password="pw",
            scan_via="host",
            ping_enabled=True,
            ping_count=20,
            iperf_enabled=True, iperf_tool="iperf3", iperf_min_mbps=10,
            iperf_server_ip="", iperf_duration=10),
        bluetooth=BluetoothCfg(
            enabled=True, rssi_enabled=True, expected_name="DUT-BT",
            pair_enabled=True, l2ping_count=5, tone_enabled=True,
            audio_confirm=True))


def test_linux_all_rf_subtests_build_distinct_steps():
    cfg = _linux_full_rf_config()
    assert cfg.validate() == []          # empty server IP = auto-detect
    names = [s.name for s in build_fct_steps(cfg)]
    # driver load once, then the three Wi-Fi and three BT sub-tests
    assert names.count("Load RF drivers") == 1
    assert "Wi-Fi Scan / RSSI" in names
    assert any(s.startswith("Wi-Fi Ping") for s in names)
    assert "Wi-Fi iPerf Throughput (iperf3)" in names
    assert "BT discoverable (piscan)" in names
    assert "Bluetooth RSSI" in names
    assert "Bluetooth Pair & Connect" in names
    assert "BT L2CAP ping (5)" in names
    assert "Bluetooth Tone / Music (A2DP)" in names
    # Connect&Ping uses >=1-reply rule, iPerf auto-detects the server
    ping = next(s for s in build_fct_steps(cfg)
                if s.name.startswith("Wi-Fi Ping"))
    assert ping.params["fct_rf"]["any_reply"] is True
    iperf = next(s for s in build_fct_steps(cfg)
                 if s.name.startswith("Wi-Fi iPerf"))
    assert iperf.params["fct_wifi_iperf"]["server_ip"] == ""


def test_bare_metal_rf_is_discovery_only():
    cfg = FctTestConfig(
        dut_type="bare_metal",
        wifi=WifiCfg(enabled=True, scan_enabled=True, ap_ssid="DUT-AP"),
        bluetooth=BluetoothCfg(enabled=True, rssi_enabled=True,
                               expected_name="DUT-BT"))
    assert cfg.validate() == []
    names = [s.name for s in build_fct_steps(cfg)]
    assert names == ["Wi-Fi Scan / RSSI", "Bluetooth RSSI"]
    wifi = next(s for s in build_fct_steps(cfg)
                if s.name == "Wi-Fi Scan / RSSI")
    assert wifi.channel == ""           # host-side, no console channel


def test_legacy_mode_yaml_migrates_to_subtests():
    legacy = {
        "dut_type": "linux",
        "wifi": {"enabled": True, "mode": "full_stack", "ssid": "OLD",
                 "password": "p", "ping_count": 30,
                 "bandwidth": {"enabled": True, "tool": "iperf2",
                               "min_mbps": 25.0, "server_ip": "1.2.3.4"}},
        "bluetooth": {"enabled": True, "mode": "a2dp_sink",
                      "expected_name": "OLD-BT"}}
    cfg = FctTestConfig.from_dict(legacy)
    w, b = cfg.wifi, cfg.bluetooth
    assert (w.scan_enabled, w.ping_enabled, w.iperf_enabled) == \
        (True, True, True)
    assert w.ap_ssid == "OLD"
    assert w.ap_password == "p" and w.ping_count == 30
    assert w.iperf_tool == "iperf2" and w.iperf_min_mbps == 25.0
    assert w.iperf_server_ip == "1.2.3.4"
    assert (b.rssi_enabled, b.pair_enabled, b.tone_enabled) == \
        (True, False, True)
    # legacy rssi_only -> scan only
    rssi = FctTestConfig.from_dict(
        {"wifi": {"enabled": True, "mode": "rssi_only", "ssid": "X"},
         "bluetooth": {"enabled": True, "mode": "rssi_only",
                       "expected_name": "X"}})
    assert rssi.wifi.scan_enabled and not rssi.wifi.ping_enabled
    assert rssi.bluetooth.rssi_enabled and not rssi.bluetooth.tone_enabled


def test_rf_subtest_validation_rules():
    # ping enabled with a valid ping count is clean (SSID/password are
    # now shared as ap_ssid/ap_password, no per-ping fields)
    cfg = FctTestConfig(dut_type="linux", wifi=WifiCfg(
        enabled=True, scan_enabled=False, ping_enabled=True,
        ping_count=20, iperf_enabled=False))
    assert cfg.validate() == []
    # bad iperf tool
    cfg.wifi = WifiCfg(enabled=True, scan_enabled=False, iperf_enabled=True)
    cfg.wifi.iperf_tool = "iperf9"
    assert any("iperf" in e and "tool" in e for e in cfg.validate())
    # zero/negative timeouts rejected
    cfg.wifi = WifiCfg(enabled=True, ap_ssid="X", scan_timeout=0)
    assert any("timeout" in e for e in cfg.validate())
    # every sub-test off
    cfg.wifi = WifiCfg(enabled=True, scan_enabled=False)
    assert any("scan / ping / iperf" in e for e in cfg.validate())
    # rssi on but no BT name
    cfg.bluetooth = BluetoothCfg(enabled=True, rssi_enabled=True,
                                 expected_name=" ")
    assert any("expected_name" in e for e in cfg.validate())


def test_rf_default_timeouts_are_15s_minimum_one():
    w, b = WifiCfg(), BluetoothCfg()
    assert (w.scan_timeout, w.ping_timeout, w.iperf_timeout) == (15.0,)*3
    assert (b.rssi_timeout, b.pair_timeout, b.tone_timeout) == (15.0,)*3


# --------------------------------------------- message rows (P3-B7)
from mtkgui.engine.fct_test_config import (  # noqa: E402
    DIALOG_GOSTOP,
    DIALOG_OK,
    DIALOG_YESNO,
    KIND_MESSAGE,
)


def test_message_command_round_trips_dialog_style():
    cmd = _cmd(name="Swap DUT fixture", kind=KIND_MESSAGE,
               dialog_style=DIALOG_GOSTOP, timeout=30.0)
    cfg = frdm_config()
    cfg.console.test_commands = [cmd]
    restored = FctTestConfig.from_dict(cfg.to_dict())
    c = restored.console.test_commands[0]
    assert c.kind == KIND_MESSAGE
    assert c.dialog_style == DIALOG_GOSTOP
    assert restored.to_dict() == cfg.to_dict()


def test_message_command_defaults_to_yesno():
    assert ConsoleCommand(kind=KIND_MESSAGE).dialog_style == DIALOG_YESNO


def test_build_steps_message_row_is_console_dialog_gui_confirm():
    """A '(message)' console row becomes a GUI_CONFIRM bound to the
    console channel carrying the console_dialog marker (user direction
    2026-10-18): the row WAITS the expected Console message first, then
    prompts the operator."""
    cfg = frdm_config()
    cfg.console.test_commands = [
        _cmd(name="Kernel check", kind="send", send="uname -a"),
        _cmd(name="Swap DUT fixture", kind=KIND_MESSAGE,
             dialog_style=DIALOG_YESNO, timeout=30.0),
    ]
    steps = build_fct_steps(cfg)
    assert steps[0].step_type == "MESSAGE_CHECK"     # console neighbour
    msg = steps[1]
    assert msg.name == "Swap DUT fixture"
    assert msg.step_type == "GUI_CONFIRM"
    assert msg.channel == "ser1"                     # waits the console
    assert msg.params["console_dialog"] is True
    assert msg.params["style"] == DIALOG_YESNO
    assert msg.params["message"] == "Swap DUT fixture"


def test_build_steps_message_row_styles_reach_params():
    for style in (DIALOG_OK, DIALOG_YESNO, DIALOG_GOSTOP):
        cfg = frdm_config()
        cfg.console.test_commands = [
            _cmd(name="op ask", kind=KIND_MESSAGE, dialog_style=style)]
        msg = next(s for s in build_fct_steps(cfg) if s.name == "op ask")
        assert msg.params["style"] == style


def test_validate_accepts_message_row_on_bare_metal():
    """A message row needs no OS: serial default transport, no SFTP."""
    cfg = FctTestConfig(dut_type="bare_metal", console=ConsoleCfg(
        enabled=True, port="/dev/cu.usbmodem1",
        test_commands=[ConsoleCommand(kind=KIND_MESSAGE, name="ask")]))
    assert cfg.validate() == []
