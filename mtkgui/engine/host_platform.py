# -*- coding: utf-8 -*-
"""Host PC platform abstraction for the FCT host-side steps (m23).

The production deployment host is a WINDOWS PC; the FCT host-side RF
logic was developed on macOS.  This module is the SINGLE entry point
the executors use instead of hard-coding the mac command tables:

* :func:`platform_key` - ``platform.system()`` -> the rf_adapters YAML
  backend key (``mac`` / ``windows`` / ``linux``);
* :func:`host_lan_ip` - best-effort Host LAN IPv4 with Darwin, Linux
  AND Windows branches (PowerShell ``Get-NetIPAddress``, ``ipconfig``
  fallback) - moved verbatim from ``fct_exec``;
* :func:`wifi_backend_cmds` / :func:`bt_backend_cmds` - the per-platform
  command table (rf_adapters format) selected by :func:`platform_key`;
* :func:`windows_capabilities` - declares what really works on a
  Windows deployment host (acceptance report source of truth).

Windows Wi-Fi uses the built-in ``netsh wlan`` family (no external
tools).  The RSSI source is ``netsh wlan show networks mode=bssid``
whose ``Signal`` line is a PERCENTAGE (0-100) of an ideal link, not
dBm - the documented approximation: the SSID-is-found + percentage
criterion is still a valid PASS gate.  Windows has NO built-in
classic-Bluetooth RSSI / A2DP command-line interface, so
:func:`bt_backend_cmds` raises :class:`PlatformBackendMissing` with
explicit user guidance - never a silent PASS, never a traceback.
"""
from __future__ import annotations

from .rf_adapters import PlatformBackendMissing, backend_key_for

__all__ = [
    "platform_key", "host_lan_ip", "is_lan_ipv4", "wifi_backend_cmds",
    "bt_backend_cmds", "windows_capabilities",
]


def platform_key() -> str:
    """``platform.system()`` -> rf_adapters backend key."""
    import platform
    return backend_key_for(platform.system())


def is_lan_ipv4(tok: str) -> bool:
    """True when `tok` is a usable unicast LAN IPv4 (moved from
    fct_exec._is_lan_ipv4)."""
    parts = str(tok).strip(".").split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit() or not 0 <= int(p) <= 255:
            return False
    a, b = int(parts[0]), int(parts[1])
    if a == 127 or (a == 169 and b == 254) or a == 0:
        return False
    return True


def host_lan_ip(ctx) -> str:
    """Best-effort Host PC LAN IPv4 (the iperf server address the DUT
    client connects to).  Darwin: ``ipconfig getifaddr`` on en0/en1/en2;
    Windows: PowerShell ``Get-NetIPAddress`` with an ``ipconfig`` parse
    fallback; Linux: ``hostname -I`` / ``ip -4 addr``.  Logs the winning
    command through `ctx.log`."""
    import platform
    import subprocess
    system = platform.system()
    if system == "Darwin":
        tries = [["ipconfig", "getifaddr", ifc]
                 for ifc in ("en0", "en1", "en2")]
    elif system == "Windows":
        tries = [
            ["powershell", "-NoProfile", "-Command",
             "Get-NetIPAddress -AddressFamily IPv4 | "
             "Where-Object {$_.IPAddress -notmatch '^127\\.' -and "
             "$_.IPAddress -notmatch '^169\\.254'} | "
             "Select-Object -ExpandProperty IPAddress"],
            ["ipconfig"],
        ]
    else:
        tries = [["hostname", "-I"], ["ip", "-4", "addr"]]
    for cmd in tries:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=5).stdout.split()
        except Exception:                   # noqa: BLE001
            continue
        for tok in out:
            if is_lan_ipv4(tok):
                ctx.log(f"host iperf server IP: {tok} ({' '.join(cmd)})")
                return tok
    return ""


def wifi_backend_cmds() -> dict:
    """The rf_adapters Wi-Fi command table for THIS platform."""
    from .fct_test_runner import WIFI_MAC_CMDS, WIFI_MAC_CMDS_WINDOWS
    key = platform_key()
    if key == "mac":
        return dict(WIFI_MAC_CMDS)
    if key == "windows":
        return dict(WIFI_MAC_CMDS_WINDOWS)
    raise PlatformBackendMissing(
        "rf.wifi: no built-in Linux host-side Wi-Fi command table; "
        "configure a 'linux' backend in the product YAML.")


def bt_backend_cmds() -> dict:
    """The rf_adapters Bluetooth command table for THIS platform.

    Windows has NO built-in classic-BT RSSI / A2DP CLI: raise the
    explicit PlatformBackendMissing (fct_exec turns it into an ERROR
    verdict with user guidance) - no silent PASS, no traceback."""
    from .fct_test_runner import BT_MAC_CMDS
    key = platform_key()
    if key == "mac":
        return dict(BT_MAC_CMDS)
    if key == "windows":
        raise PlatformBackendMissing(
            "rf.bluetooth: Windows has no built-in classic-Bluetooth "
            "RSSI/A2DP command-line interface; install a command-line "
            "scanner (e.g. BluetoothCL) and add a 'windows' backend, "
            "or run this Bluetooth step on macOS.")
    raise PlatformBackendMissing(
        "rf.bluetooth: no built-in Linux host-side Bluetooth command "
        "table; configure a 'linux' backend in the product YAML.")


def windows_capabilities() -> dict:
    """What really works on a Windows deployment host (per operation:
    ``ok`` + the command used, or ``ok: False`` + the user guidance).
    Source of truth for reports/m23_host_platform_acceptance.txt."""
    return {
        "host_lan_ip": {"ok": True,
                        "cmd": "Get-NetIPAddress (ipconfig fallback)"},
        "host_cli": {"ok": True,
                     "note": "_run_host_cli already picks "
                             "host_cmd_windows on win32 (unchanged)"},
        "wifi_scan": {"ok": True, "cmd": "netsh wlan show networks"},
        "wifi_connect": {"ok": True,
                         "cmd": "netsh wlan connect",
                         "note": "profile must already exist (first "
                                 "connect stores it); explicit add "
                                 "needs a profile XML - unsupported"},
        "wifi_rssi": {"ok": True, "cmd": "netsh wlan show networks "
                                         "mode=bssid",
                      "note": "Signal is a PERCENTAGE (0-100), not "
                              "dBm - documented approximation; "
                              "percentage-only criterion is a valid "
                              "PASS gate"},
        "wifi_gateway": {"ok": True, "cmd": "Get-NetIPConfiguration"},
        "wifi_ping": {"ok": True, "cmd": "ping -n {{count}} {{gateway}}"},
        "wifi_iperf": {"ok": True,
                       "note": "iperf3.exe via host_cmd_windows"},
        "bt_scan_rssi": {"ok": False,
                         "hint": "no built-in classic-BT RSSI CLI; "
                                 "install BluetoothCL (or similar) and "
                                 "add a 'windows' backend, or run the "
                                 "Bluetooth RSSI step on macOS"},
        "bt_pair_connect": {"ok": False,
                            "hint": "same as bt_scan_rssi - explicit "
                                    "PlatformBackendMissing ERROR, no "
                                    "silent PASS"},
        "bt_a2dp_tone": {"ok": False,
                         "hint": "Windows exposes no A2DP source "
                                 "switch/play CLI; run the tone step "
                                 "on macOS"},
    }
