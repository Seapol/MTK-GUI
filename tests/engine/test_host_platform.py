# -*- coding: utf-8 -*-
"""m23 host_platform tests: the platform abstraction entry point -
platform key mapping, per-platform host_lan_ip command shapes, the
Windows netsh Wi-Fi table, the explicit Windows Bluetooth gap and the
rf_adapters backend lookup with a forced 'windows' key.

No real OS command runs here: platform.system() and subprocess.run
are monkeypatched (same style as the existing fct_exec tests).
"""
from __future__ import annotations

import pytest

import mtkgui.engine.host_platform as hp
import mtkgui.engine.fct_exec as fe
import mtkgui.engine.rf_adapters as ra
from mtkgui.engine.rf_adapters import PlatformBackendMissing
from mtkgui.engine.fct_test_runner import (
    BT_MAC_CMDS,
    WIFI_MAC_CMDS,
    WIFI_MAC_CMDS_WINDOWS,
)

REQUIRED_WIFI_KEYS = (
    "list_networks_cmd", "remove_network_cmd", "connect_cmd",
    "add_network_cmd", "rssi_cmd", "rssi_parse", "gateway_cmd",
    "gateway_parse", "ping_cmd")


class _R:
    def __init__(self, out):
        self.stdout = out


def _set_system(monkeypatch, name):
    import platform
    monkeypatch.setattr(platform, "system", lambda: name)


# ------------------------------------------------------------- platform key
@pytest.mark.parametrize("system,expected", [
    ("Darwin", "mac"), ("Windows", "windows"), ("Linux", "linux"),
    ("SunOS", "unknown"),
])
def test_platform_key_mapping(monkeypatch, system, expected):
    _set_system(monkeypatch, system)
    assert hp.platform_key() == expected


# ------------------------------------------------------------- host_lan_ip
def test_host_lan_ip_windows_powershell_branch(monkeypatch):
    import subprocess
    seen = {}
    real_run = subprocess.run

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        if cmd[0] == "powershell":
            return _R("192.168.10.5\r\n")
        return _R("")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _set_system(monkeypatch, "Windows")
    ctx = fe.FctContext()
    assert hp.host_lan_ip(ctx) == "192.168.10.5"
    assert "Get-NetIPAddress" in " ".join(seen["cmd"])
    assert seen["cmd"][0] == "powershell"


def test_host_lan_ip_windows_ipconfig_fallback(monkeypatch):
    import subprocess

    def fake_run(cmd, **kw):
        if cmd[0] == "powershell":
            raise OSError("powershell missing")
        assert cmd[0] == "ipconfig"
        return _R("   IPv4 Address. . . : 192.168.1.20   \n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _set_system(monkeypatch, "Windows")
    assert hp.host_lan_ip(fe.FctContext()) == "192.168.1.20"


def test_host_lan_ip_darwin_and_linux_shapes(monkeypatch):
    import subprocess
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd[0])
        if cmd[:2] == ["ipconfig", "getifaddr"]:
            return _R("192.168.10.141\n")
        return _R("")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _set_system(monkeypatch, "Darwin")
    assert hp.host_lan_ip(fe.FctContext()) == "192.168.10.141"

    seen.clear()

    def fake_run_linux(cmd, **kw):
        seen.append(cmd[0])
        return _R("10.0.0.7 " if cmd[0] == "hostname" else "")

    monkeypatch.setattr(subprocess, "run", fake_run_linux)
    _set_system(monkeypatch, "Linux")
    assert hp.host_lan_ip(fe.FctContext()) == "10.0.0.7"
    assert seen[0] == "hostname"


def test_fct_exec_host_lan_ip_delegates(monkeypatch):
    """fct_exec.host_lan_ip is a thin delegate (single source)."""
    monkeypatch.setattr(hp, "host_lan_ip", lambda ctx: "1.2.3.4")
    assert fe.host_lan_ip(fe.FctContext()) == "1.2.3.4"


# ----------------------------------------------------------- backend tables
def test_wifi_windows_table_same_keys_and_netsh_family():
    assert set(WIFI_MAC_CMDS_WINDOWS) >= set(REQUIRED_WIFI_KEYS)
    assert "netsh wlan" in WIFI_MAC_CMDS_WINDOWS["rssi_cmd"]
    assert "netsh wlan connect" in WIFI_MAC_CMDS_WINDOWS["connect_cmd"]
    assert WIFI_MAC_CMDS_WINDOWS["ping_cmd"].startswith("ping -n ")
    # Windows ping reports "(N% loss)", not "% packet loss"
    assert "ping_loss_parse" in WIFI_MAC_CMDS_WINDOWS
    # percentage RSSI approximation is documented, not hidden
    assert "%" in WIFI_MAC_CMDS_WINDOWS["rssi_parse"]


def test_wifi_backend_cmds_follows_platform(monkeypatch):
    _set_system(monkeypatch, "Darwin")
    assert hp.wifi_backend_cmds() == dict(WIFI_MAC_CMDS)
    _set_system(monkeypatch, "Windows")
    assert hp.wifi_backend_cmds() == dict(WIFI_MAC_CMDS_WINDOWS)


def test_bt_windows_raises_explicit_not_silent(monkeypatch):
    _set_system(monkeypatch, "Windows")
    with pytest.raises(PlatformBackendMissing) as ei:
        hp.bt_backend_cmds()
    msg = str(ei.value)
    assert "BluetoothCL" in msg and "macOS" in msg


def test_bt_mac_table_unchanged(monkeypatch):
    _set_system(monkeypatch, "Darwin")
    assert hp.bt_backend_cmds() == dict(BT_MAC_CMDS)


def test_bt_backend_cmds_linux_also_explicit(monkeypatch):
    _set_system(monkeypatch, "Linux")
    with pytest.raises(PlatformBackendMissing):
        hp.bt_backend_cmds()


# ------------------------------------------------- rf_adapters resolution
def test_backend_section_resolves_forced_windows_key():
    backend = ra._backend_section(
        {"wifi": {"cmds": {"windows": dict(WIFI_MAC_CMDS_WINDOWS)}}},
        "wifi", key="windows")
    assert backend["rssi_cmd"] == "netsh wlan show networks mode=bssid"


def test_ping_gateway_uses_windows_loss_parse(monkeypatch):
    """The adapter reads the optional ping_loss_parse key (Windows ping
    format) instead of the mac-only '% packet loss' default."""
    monkeypatch.setattr(ra, "backend_key_for", lambda s=None: "windows")
    calls = {}

    class _Runner:
        def _log(self, msg):
            pass

        def run(self, template, params, regex_extracts=None, **kw):
            calls["regex"] = (regex_extracts or {}).get("loss_pct")
            class _R2:
                items = {"loss_pct": "0"}
                verdict = "OK"
                exit_code = 0
            return _R2()

    adapter = ra.WifiAdapter(
        {"wifi": {"mode": "full_stack", "gateway": "192.168.1.1",
                  "cmds": {"windows": dict(WIFI_MAC_CMDS_WINDOWS)},
                  "ping_count": 4}},
        _Runner())
    adapter._ping_gateway()
    assert calls["regex"] == WIFI_MAC_CMDS_WINDOWS["ping_loss_parse"]


# --------------------------------------------------- _run_rf_tool key pick
def test_run_rf_tool_builds_config_with_platform_key(monkeypatch):
    monkeypatch.setattr(hp, "platform_key", lambda: "windows")
    captured = {}

    class _FakeAdapter:
        def __init__(self, rf_cfg, runner):
            captured["cfg"] = rf_cfg

        def run_test(self):
            return {"verdict": "Pass", "items": {}, "lines": []}

    monkeypatch.setattr(ra, "WifiAdapter", _FakeAdapter)
    monkeypatch.setattr(fe, "runner_for", lambda ctx: object())
    step = fe.FctStep(
        name="w", step_type="EXTERNAL_TOOL", params={
            "tool_family": "wifi",
            "fct_rf": {"mode": "rssi_only", "ssid": "dut-ap"}})
    out = fe._run_rf_tool(step, "wifi", fe.FctContext())
    assert "windows" in captured["cfg"]["wifi"]["cmds"]
    assert out.verdict == fe.VERDICT_PASS


def test_run_rf_tool_bt_windows_returns_error_with_guidance(monkeypatch):
    """Windows Bluetooth step: explicit ERROR verdict + guidance, never
    a silent PASS and never a raised traceback."""
    monkeypatch.setattr(hp, "platform_key", lambda: "windows")
    monkeypatch.setattr(fe, "runner_for", lambda ctx: object())
    step = fe.FctStep(
        name="bt", step_type="EXTERNAL_TOOL", params={
            "tool_family": "bluetooth",
            "fct_rf": {"mode": "rssi_only", "expected_name": "DUT"}})
    out = fe._run_rf_tool(step, "bluetooth", fe.FctContext())
    assert out.verdict == fe.VERDICT_ERROR
    assert "BluetoothCL" in out.reason or "BluetoothCL" in str(out.lines)


# ------------------------------------------------------------ capabilities
def test_windows_capabilities_declares_supported_vs_unsupported():
    caps = hp.windows_capabilities()
    for op in ("wifi_scan", "wifi_connect", "wifi_rssi", "wifi_gateway",
               "wifi_ping", "host_lan_ip", "host_cli"):
        assert caps[op]["ok"] is True, op
    for op in ("bt_scan_rssi", "bt_pair_connect", "bt_a2dp_tone"):
        assert caps[op]["ok"] is False, op
        assert caps[op]["hint"], op
