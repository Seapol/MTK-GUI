# -*- coding: utf-8 -*-
"""M77 - R6 engine fixes.

1 Host ping is Windows-portable (ping_cmd count + dual-dialect loss regex).
2 Wi-Fi connect consumes the configured timeout_s by polling the IPv4.
3 Windows Bluetooth rows are judged on the DUT side (never a bare ERROR).
4 SFTP auto-binds the ssh channel to the DUT Wi-Fi IP (no serial fallback).
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import mtkgui.engine.fct_test_runner as ftr
import mtkgui.engine.host_platform as hp
from mtkgui.engine.fct_exec import (
    FctContext,
    bind_sftp_channel,
    execute_fct_step,
)
from mtkgui.engine.fct_test_config import FctStep, FctTestConfig
from mtkgui.engine.fct_test_runner import FctTestRunner
from mtkgui.engine.host_cli import extract_items
from mtkgui.engine.runner import TestRunner


# --------------------------------------------------- M77-1 host ping
@pytest.mark.parametrize("key,cmd", [
    ("windows", "ping -n 20 1.2.3.4"),
    ("mac", "ping -c 20 1.2.3.4"),
    ("linux", "ping -c 20 1.2.3.4"),
])
def test_ping_cmd_is_platform_portable(monkeypatch, key, cmd):
    monkeypatch.setattr(hp, "platform_key", lambda: key)
    assert hp.ping_cmd("1.2.3.4", 20) == cmd
    # the single-packet default is unchanged for every call site
    assert hp.ping_cmd("1.2.3.4") == (
        "ping -n 1 1.2.3.4" if key == "windows" else "ping -c 1 1.2.3.4")


class _FakeHostRunner:
    """Host CLI stand-in: returns a fixed corpus and parses the regexes
    exactly like the real runner."""

    def __init__(self, corpus: str):
        self.corpus = corpus
        self.commands: list = []

    def run(self, cmd, timeout_s=30, regex_extracts=None, cwd=""):
        self.commands.append(cmd)
        lines = self.corpus.splitlines()
        items = extract_items(lines, regex_extracts or {})
        return SimpleNamespace(lines=lines, items=items, exit_code=0)


def _wifi_cfg(count=20) -> FctTestConfig:
    cfg = FctTestConfig(dut_type="linux")
    cfg.wifi.ping_enabled = True
    cfg.wifi.ap_ip = "192.168.71.1"
    cfg.wifi.ping_count = count
    return cfg


@pytest.mark.parametrize("corpus,key,expected_cmd", [
    ("Packets: Sent = 20, Received = 20, Lost = 0 (0% loss)",
     "windows", "ping -n 20 192.168.71.1"),
    ("20 packets transmitted, 20 received, 0% packet loss",
     "mac", "ping -c 20 192.168.71.1"),
])
def test_wifi_ping_stage1_parses_both_dialects(monkeypatch, corpus, key,
                                               expected_cmd):
    monkeypatch.setattr(hp, "platform_key", lambda: key)
    logs: list = []
    runner = FctTestRunner(_wifi_cfg(20), log_sink=logs.append)
    host = _FakeHostRunner(corpus)
    results = runner.run_wifi(None, host)
    stage1 = next(r for r in results
                  if r.name == "Wi-Fi Ping: Host -> AP")
    assert stage1.verdict == "PASS", stage1.detail
    assert "0.0%" in stage1.detail
    assert host.commands == [expected_cmd]


def test_wifi_ping_stage1_access_denied_still_fails(monkeypatch):
    """M77-1 fail-safe: an unparsable corpus stays 100% -> FAIL."""
    monkeypatch.setattr(hp, "platform_key", lambda: "windows")
    runner = FctTestRunner(_wifi_cfg(20))
    host = _FakeHostRunner(
        "Access denied. Option -c requires administrative privileges.")
    results = runner.run_wifi(None, host)
    stage1 = next(r for r in results
                  if r.name == "Wi-Fi Ping: Host -> AP")
    assert stage1.verdict == "FAIL"
    assert "100.0%" in stage1.detail


# ------------------------------------------- M77-2 Wi-Fi connect budget
class _FakeMc:
    def __init__(self, responder):
        self.channels = {"ser1": {"kind": "serial", "connected": True}}
        self.buf = b""
        self.responder = responder

    def channel_connected(self, _key):
        return True

    def get_read_buffer(self, _key):
        return self.buf

    def write_to_channel(self, _key, payload):
        cmd = payload.decode("utf-8", "replace").strip()
        self.buf += self.responder(cmd).encode()


class _FakeEnv:
    def __init__(self, mc):
        self.multi_console = mc
        self.fct_dut_ip = ""
        self.logs: list = []

    def _log(self, line):
        self.logs.append(line)


def _wifi_params(timeout_s: float) -> dict:
    return {"type": "wifi_connect", "iface": "mlan0",
            "ssid": "lab-ap", "password": "lab-pass",
            "timeout_s": timeout_s}


def _fast_probe(cmd: str) -> str:
    """Short replies so each `_net_run` leaves its quiet window fast."""
    if cmd.startswith("iw dev"):
        return "Interface mlan0\n\ttype managed\n"
    if cmd.startswith("dhclient") or cmd.startswith("udhcpc") \
            or cmd.startswith("ip link"):
        return "udhcpc: started, lease pending\n"
    if cmd.startswith("cat >") or cmd.startswith("wpa_supplicant") \
            or cmd.startswith("killall"):
        return "started\n"
    return ""


def test_wifi_connect_polls_until_the_configured_budget():
    """Confirm answers twice with no IP, then an IP on the 3rd poll."""
    polls = {"n": 0}

    def responder(cmd):
        if cmd.startswith("ip -4 addr show"):
            polls["n"] += 1
            if polls["n"] >= 3:
                return "    inet 192.168.71.12/24 scope global mlan0\n"
            return "2: mlan0: <BROADCAST,MULTICAST,UP> mtu 1500 state UP\n"
        return _fast_probe(cmd)

    mc = _FakeMc(responder)
    env = _FakeEnv(mc)
    runner = TestRunner(env)
    t0 = time.time()
    verdict = runner._run_network_op(
        "FCT", "Wi-Fi: Connect DUT to AP", _wifi_params(6.0))
    elapsed = time.time() - t0
    assert verdict == "Done"
    assert env.fct_dut_ip == "192.168.71.12"
    # more than a single pass proves the polling loop
    assert polls["n"] >= 3
    assert elapsed > 2.0
    assert any("IPv4 192.168.71.12 acquired" in line
               for line in env.logs)


def test_wifi_connect_fails_after_the_budget():
    """Never an IP -> Fail at ~timeout_s (no premature 5 s give-up)."""
    def responder(cmd):
        if cmd.startswith("ip -4 addr show"):
            return "2: mlan0: <BROADCAST,MULTICAST,UP> mtu 1500 state UP\n"
        return _fast_probe(cmd)

    mc = _FakeMc(responder)
    env = _FakeEnv(mc)
    runner = TestRunner(env)
    t0 = time.time()
    verdict = runner._run_network_op(
        "FCT", "Wi-Fi: Connect DUT to AP", _wifi_params(2.0))
    elapsed = time.time() - t0
    assert verdict == "Fail"
    assert "no IPv4 address on mlan0" in runner._last_op_error
    assert elapsed >= 1.8
    assert elapsed <= 5.0


def test_wifi_connect_timeout_defaults_to_60():
    """A plan without timeout_s keeps the documented 60 s budget."""
    plan = hp.wifi_connect_plan({"type": "wifi_connect"})
    assert plan["timeout_s"] == 60.0


# --------------------------------------------- M77-3 DUT-side Bluetooth
class _FakeSerial:
    """pyserial stand-in: each written command yields one canned reply."""

    def __init__(self, replies: dict):
        self.replies = replies
        self.pending = b""
        self.written: list = []

    def reset_input_buffer(self):
        self.pending = b""

    def write(self, payload):
        cmd = payload.decode("utf-8", "replace").strip()
        self.written.append(cmd)
        for key, text in self.replies.items():
            if cmd == key or cmd.startswith(key):
                self.pending += text.encode()
                break

    def read(self, _n=4096):
        out, self.pending = self.pending, b""
        return out


_HCI_UP = (
    "hci0:   Type: Primary  Bus: UART\n"
    "        BD Address: B8:F4:4F:59:51:A0  ACL MTU: 1021:8  SCO MTU: 64:1\n"
    "        UP RUNNING PSCAN ISCAN\n")
_HCI_DOWN = (
    "hci0:   Type: Primary  Bus: UART\n"
    "        BD Address: B8:F4:4F:59:51:A0  ACL MTU: 1021:8  SCO MTU: 64:1\n"
    "        DOWN\n")


def _bt_cfg(**kw) -> FctTestConfig:
    cfg = FctTestConfig(dut_type="linux")
    cfg.bluetooth.pair_enabled = True
    for key, value in kw.items():
        setattr(cfg.bluetooth, key, value)
    return cfg


def test_bt_pair_windows_judges_on_the_dut(monkeypatch):
    monkeypatch.setattr(hp, "platform_key", lambda: "windows")
    serial = _FakeSerial({
        "hciconfig hci0": _HCI_UP,
        "bluetoothctl info": ("Device B8:F4:4F:59:51:A0\n"
                              "  Paired: yes\n  Connected: yes\n"),
    })
    cfg = _bt_cfg(expected_addr="B8:F4:4F:59:51:A0")
    runner = FctTestRunner(cfg)
    result = runner._bt_dut_pair(
        serial, cfg.bluetooth, "Bluetooth Pair & Connect", 0.2)
    assert result.verdict == "PASS"
    assert "connected" in result.detail


def test_bt_pair_windows_adapter_down_fails_not_error(monkeypatch):
    monkeypatch.setattr(hp, "platform_key", lambda: "windows")
    serial = _FakeSerial({"hciconfig hci0": _HCI_DOWN})
    cfg = _bt_cfg(expected_addr="B8:F4:4F:59:51:A0")
    runner = FctTestRunner(cfg)
    result = runner._bt_dut_pair(
        serial, cfg.bluetooth, "Bluetooth Pair & Connect", 0.2)
    assert result.verdict == "FAIL"
    assert "UP/RUNNING" in result.detail


def test_bt_pair_windows_no_link_fails_not_error(monkeypatch):
    monkeypatch.setattr(hp, "platform_key", lambda: "windows")
    serial = _FakeSerial({
        "hciconfig hci0": _HCI_UP,
        "bluetoothctl info": "Connected: no\n",
        "hcitool con": "Connections:\n",
    })
    cfg = _bt_cfg(expected_addr="B8:F4:4F:59:51:A0")
    runner = FctTestRunner(cfg)
    result = runner._bt_dut_pair(
        serial, cfg.bluetooth, "Bluetooth Pair & Connect", 0.2)
    assert result.verdict == "FAIL"


def test_bt_a2dp_windows_without_observability_is_an_explicit_fail(monkeypatch):
    monkeypatch.setattr(hp, "platform_key", lambda: "windows")
    serial = _FakeSerial({
        "pactl list short sinks": "pactl: command not found\n",
        "aplay -l": "aplay: command not found\n",
        "bluetoothctl info": "Connected: no\n",
    })
    cfg = _bt_cfg(expected_addr="B8:F4:4F:59:51:A0")
    runner = FctTestRunner(cfg)
    result = runner._bt_dut_a2dp(
        serial, cfg.bluetooth, "Bluetooth Tone / Music (A2DP)", 0.2)
    assert result.verdict == "FAIL"
    assert "not observable on DUT" in result.detail


def test_bt_row_no_longer_raises_platform_backend_missing(monkeypatch):
    """run_bluetooth on Windows routes to the DUT side, never the
    PlatformBackendMissing ERROR path."""
    monkeypatch.setattr(hp, "platform_key", lambda: "windows")
    serial = _FakeSerial({
        "hciconfig hci0": _HCI_UP,
        "bluetoothctl info": "Paired: yes\nConnected: yes\n",
    })
    cfg = _bt_cfg(expected_addr="B8:F4:4F:59:51:A0", l2ping_count=0)
    runner = FctTestRunner(cfg)
    rows = runner.run_bluetooth(serial, object())
    assert rows
    assert all(row.verdict in ("PASS", "FAIL", "SKIP") for row in rows)
    assert not any(row.verdict == "ERROR" for row in rows)


class _HostRunBackend:
    """Host CLI stand-in for the macOS adapter path (no real commands)."""

    def run(self, cmd, timeout_s=30, regex_extracts=None, cwd=""):
        return SimpleNamespace(lines=[], items={}, exit_code=0)


def test_bt_macos_path_stays_on_the_host_adapter(monkeypatch):
    """macOS keeps the host-CLI adapter (byte-identical behaviour)."""
    monkeypatch.setattr(hp, "platform_key", lambda: "mac")
    calls: list = []

    class _FakeAdapter:
        def __init__(self, cfg, host_runner, human_confirm=None):
            calls.append(cfg)

        def run_test(self):
            return {"verdict": "Pass", "items": "host adapter"}

    monkeypatch.setattr(ftr, "BluetoothAdapter", _FakeAdapter, raising=False)
    import mtkgui.engine.rf_adapters as rf
    monkeypatch.setattr(rf, "BluetoothAdapter", _FakeAdapter, raising=False)
    cfg = _bt_cfg(l2ping_count=0)
    runner = FctTestRunner(cfg)
    rows = runner.run_bluetooth(_FakeSerial({}), _HostRunBackend())
    assert rows and rows[0].verdict == "PASS"
    assert calls


# --------------------------------------------- M77-4 SFTP auto-bind
class _FakeSshChannel:
    opened: list = []

    def __init__(self, host, username, credential_ref, port=22,
                 timeout=10.0, connect_timeout=10.0, remote_dir="",
                 password=None):
        _FakeSshChannel.opened.append(
            {"host": host, "username": username, "password": password})
        self.host = host
        self.got: list = []
        self.removed: list = []

    def get_file(self, remote, local):
        self.got.append((remote, local))

    def remove_file(self, remote):
        self.removed.append(remote)


def _sftp_step() -> FctStep:
    return FctStep(
        name="SFTP download", step_type="MESSAGE_CHECK", channel="ssh",
        timeout_s=30.0,
        params={"fct_console": True, "kind": "sftp_get",
                "action": "sftp_get",
                "local": "{{dut_report}}/fat.log",
                "remote": "/root/fat.log",
                "ssh_host": "", "ssh_username": "root", "args": {}})


def test_sftp_endpoint_uses_fct_dut_ip_and_says_so():
    env = SimpleNamespace(fct_dut_ip="192.168.71.12", _log=lambda _m: None)
    endpoint = TestRunner(env)._fct_ssh_endpoint(_sftp_step())
    assert endpoint["host"] == "192.168.71.12"
    assert endpoint["source"] == "fct_dut_ip over Wi-Fi"
    assert endpoint["username"] == "root"
    assert endpoint["password"] == ""


def test_sftp_autobinds_and_pulls_over_the_wifi_path(monkeypatch, tmp_path):
    _FakeSshChannel.opened = []
    import mtkgui.engine.fct_channels as fc
    monkeypatch.setattr(fc, "SshFctChannel", _FakeSshChannel, raising=True)
    env = SimpleNamespace(fct_dut_ip="192.168.71.12", _log=lambda _m: None)
    runner = TestRunner(env)
    ctx = FctContext(dut_report=str(tmp_path))
    step = _sftp_step()
    assert runner._bind_fct_ssh(step, ctx, step.name) is True
    channel = ctx.channels["ssh"]
    outcome = execute_fct_step(step, ctx)
    assert outcome.verdict == "PASS", outcome.reason
    assert channel.got == [("/root/fat.log",
                            f"{tmp_path}/fat.log")]
    assert channel.removed == ["/root/fat.log"]
    assert _FakeSshChannel.opened[0]["host"] == "192.168.71.12"


def test_sftp_autobind_logs_the_source(monkeypatch, tmp_path):
    _FakeSshChannel.opened = []
    import mtkgui.engine.fct_channels as fc
    monkeypatch.setattr(fc, "SshFctChannel", _FakeSshChannel, raising=True)
    logs: list = []
    env = SimpleNamespace(fct_dut_ip="192.168.71.12", _log=logs.append)
    runner = TestRunner(env)
    ctx = FctContext(dut_report=str(tmp_path))
    step = _sftp_step()
    runner._bind_fct_ssh(step, ctx, step.name)
    assert any("SSH channel auto-bound to 192.168.71.12:22"
               in line and "source: fct_dut_ip over Wi-Fi" in line
               for line in logs)


def test_sftp_without_any_ip_is_an_explicit_error():
    env = SimpleNamespace(fct_dut_ip="", _log=lambda _m: None)
    runner = TestRunner(env)
    ctx = FctContext()
    step = _sftp_step()
    assert runner._bind_fct_ssh(step, ctx, step.name) is False
    outcome = execute_fct_step(step, ctx)
    assert outcome.verdict == "ERROR"
    assert outcome.reason == (
        "no DUT Wi-Fi IP; run the Wi-Fi connect step before SFTP")


def test_sftp_uses_an_already_bound_ssh_channel(monkeypatch, tmp_path):
    """A Console-panel SSH endpoint wins verbatim (no second session)."""
    _FakeSshChannel.opened = []
    import mtkgui.engine.fct_channels as fc
    monkeypatch.setattr(fc, "SshFctChannel", _FakeSshChannel, raising=True)
    step = _sftp_step()
    step.params["ssh_host"] = "10.0.0.9"
    env = SimpleNamespace(fct_dut_ip="192.168.71.12", _log=lambda _m: None)
    runner = TestRunner(env)
    endpoint = runner._fct_ssh_endpoint(step)
    assert endpoint["host"] == "10.0.0.9"
    assert endpoint["source"] == "console ssh endpoint"
    ctx = FctContext(dut_report=str(tmp_path))
    assert bind_sftp_channel(step, ctx) is True
    assert _FakeSshChannel.opened[0]["host"] == "10.0.0.9"
    assert isinstance(ctx.channels["ssh"], _FakeSshChannel)
