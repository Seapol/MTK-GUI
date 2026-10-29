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
  Windows deployment host (acceptance report source of truth);
* :func:`signal_quality` / :func:`percent_to_rssi_dbm` /
  :func:`wifi_link_probe_cmds` / :func:`run_link_cmd` /
  :func:`probe_host_ap_link` - the M31 "Test Host PC <-> Hotspot AP
  connection" helper set.

Signal-quality thresholds (dBm): Excellent >= -50, Good >= -60,
Weak >= -70, Bad >= -80, No Signal < -80 or no association.
The Windows ``Signal %`` -> dBm approximation is ``pct // 2 - 100``
(``netsh`` exposes no dBm; the mapping is documented as approximate).

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
    "bt_backend_cmds", "windows_capabilities", "signal_quality",
    "percent_to_rssi_dbm", "wifi_link_probe_cmds", "run_link_cmd",
    "probe_host_ap_link",
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


def signal_quality(rssi_dbm) -> str:
    """Map an associated RSSI (dBm, or ``None`` when not associated) to
    a human Signal Quality tier.

    Thresholds (dBm): Excellent >= -50, Good >= -60, Weak >= -70,
    Bad >= -80, No Signal < -80 or ``None`` (no association)."""
    if rssi_dbm is None:
        return "No Signal"
    try:
        value = float(rssi_dbm)
    except (TypeError, ValueError):
        return "No Signal"
    if value >= -50:
        return "Excellent"
    if value >= -60:
        return "Good"
    if value >= -70:
        return "Weak"
    if value >= -80:
        return "Bad"
    return "No Signal"


def percent_to_rssi_dbm(pct: int) -> int:
    """Approximate a 0-100% Windows ``netsh`` signal strength as dBm.

    Linear approximation of the quality band: ``pct // 2 - 100``.
    Documented as approximate only (``netsh`` exposes no dBm)."""
    return int(pct) // 2 - 100


def wifi_link_probe_cmds() -> dict:
    """The Host PC <-> AP connection-test command table for THIS platform.

    Unlike :func:`wifi_backend_cmds` (Windows reports every visible
    network via ``mode=bssid``), the connection test needs the CURRENT
    association RSSI, so Windows uses ``netsh wlan show interfaces``
    (Signal %) here.  ``ping_cmd`` carries a ``{}`` gateway placeholder."""
    key = platform_key()
    if key == "mac":
        return {
            "rssi_cmd": "system_profiler SPAirPortDataType",
            "rssi_is_percent": False,
            "rssi_dbm_parse": r"Signal / Noise: (-?\d+) dBm",
            "rssi_pct_parse": None,
            "ping_cmd": "ping -c 3 {}",
        }
    if key == "windows":
        return {
            "rssi_cmd": "netsh wlan show interfaces",
            "rssi_is_percent": True,
            "rssi_dbm_parse": None,
            "rssi_pct_parse": r"Signal\s*:\s*(\d+)%",
            "ping_cmd": "ping -n 3 {}",
        }
    raise PlatformBackendMissing(
        "rf.wifi connection test: no built-in Linux host-side command "
        "table; configure a 'linux' backend in the product YAML.")


def run_link_cmd(cmd_line: str, timeout_s: int = 15) -> str:
    """Run a host-side shell command and return its stdout+stderr text.

    A single module-level subprocess wrapper so the connection probe
    (and its unit tests) `monkeypatch` this one entry point instead of
    reaching into subprocess directly."""
    import subprocess
    try:
        proc = subprocess.run(cmd_line, shell=True, capture_output=True,
                              text=True, timeout=timeout_s)
    except Exception as exc:              # noqa: BLE001 - the text is the
        return f"ERROR: {exc}"            # probe's real error message
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def _ping_has_reply(out: str) -> bool:
    """True when the ping output indicates at least one reply."""
    import re
    low = out.lower()
    m = re.search(r"received\s*=\s*(\d+)", low)   # Windows
    if m:
        return int(m.group(1)) > 0
    m = re.search(r"(\d+)\s+packets? received", low)  # mac / Linux
    return bool(m) and int(m.group(1)) > 0


def probe_host_ap_link(gateway: str, progress=None) -> dict:
    """Orchestrate the Host PC <-> AP connection test (M31).

    Runs :func:`run_link_cmd` twice - the current-association RSSI, then
    a 3-packet ping of the AP/gateway (``Connection OK`` requires >=1
    reply).  RSSI / signal-quality are always reported but do NOT gate
    the verdict by themselves; an empty gateway fails immediately.

    Returns ``{"ok": bool, "rssi": float|None, "pct": int|None,
    "lines": [...], "quality": str, "error": str}``.  `progress`, when
    given, is called as ``progress(done, total)`` at each stage."""
    import re
    cmds = wifi_link_probe_cmds()
    if progress:
        progress(1, 3)
    out = run_link_cmd(cmds["rssi_cmd"])
    rssi = None
    pct = None
    lines = []
    if cmds["rssi_is_percent"]:
        m = re.search(cmds["rssi_pct_parse"], out)
        if m:
            pct = int(m.group(1))
            rssi = float(percent_to_rssi_dbm(pct))
            lines.append(f"RSSI: {rssi:.0f} dBm ({pct}%)")
        else:
            lines.append("RSSI: N/A")
    else:
        m = re.search(cmds["rssi_dbm_parse"], out)
        if m:
            rssi = float(m.group(1))
            lines.append(f"RSSI: {rssi:.0f} dBm")
        else:
            lines.append("RSSI: N/A")
    if progress:
        progress(2, 3)
    quality = signal_quality(rssi)
    if not gateway:
        lines.append("Connection FAILED: no AP IP / gateway")
        if progress:
            progress(3, 3)
        return {"ok": False, "rssi": rssi, "pct": pct, "lines": lines,
                "quality": quality, "error": "no AP IP / gateway"}
    ping_out = run_link_cmd(cmds["ping_cmd"].format(gateway))
    ok = _ping_has_reply(ping_out)
    error = "" if ok else f"no reply from {gateway}"
    lines.append("Connection OK" if ok else
                 f"Connection FAILED: {error}")
    lines.append(f"Signal Quality: {quality}")
    if progress:
        progress(3, 3)
    return {"ok": ok, "rssi": rssi, "pct": pct, "lines": lines,
            "quality": quality, "error": error}
