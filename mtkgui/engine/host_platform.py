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
    "wifi_detect_cmds", "detect_current_wifi", "parse_current_wifi",
    "probe_host_ap_link", "host_bt_status_cmd", "host_bt_devices_cmd",
    "host_bt_scan_cmd", "host_bt_identity", "parse_bt_status",
    "parse_bt_devices", "format_bt_scan_result",
    # M41: DUT network setup + SSH diagnosis
    "netmask_to_prefix", "parse_dut_ip", "wifi_driver_ready",
    "network_ip_commands", "wifi_connect_plan", "lan_setup_plan",
    "ping_cmd", "ping_host", "tcp_port_open", "serial_port_devices",
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


# ---------------------------------------------------------------------------
# M40 Wi-Fi auto-detect: the Wi-Fi the Host PC is CURRENTLY associated to
# IS the Hotspot AP under test (Host PC <-> AP <-> DUT on one segment).
# ---------------------------------------------------------------------------
def wifi_detect_cmds() -> dict:
    """The current-association detect command table for THIS platform.

    ``ip_cmd`` carries an ``{iface}`` placeholder on macOS (the interface
    name comes from the ``system_profiler`` text); Windows derives the
    IPv4 AND the default gateway from one ``ipconfig`` run."""
    key = platform_key()
    if key == "mac":
        return {
            "assoc_cmd": "system_profiler SPAirPortDataType",
            "ip_cmd": "ipconfig getifaddr {iface}",
            "gateway_cmd": "route -n get default",
        }
    if key == "windows":
        return {
            "assoc_cmd": "netsh wlan show interfaces",
            "ip_cmd": "ipconfig",
            "gateway_cmd": "",
        }
    raise PlatformBackendMissing(
        "wifi auto-detect: no built-in Linux host-side command table; "
        "configure a 'linux' backend in the product YAML.")


def parse_mac_wifi(assoc_text: str) -> tuple:
    """``(ssid, iface)`` from ``system_profiler SPAirPortDataType`` text.

    The interface block that carries ``Current Network Information:``
    is the associated one; its first indented ``<ssid>:`` child is the
    SSID.  Missing / disconnected -> ``(None, None)``."""
    ifaces_indent = None
    iface_indent = None
    cur_iface = None
    in_current = False
    current_indent = None
    for raw in str(assoc_text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        indent = len(raw) - len(raw.lstrip())
        if stripped == "Interfaces:":
            ifaces_indent = indent
            iface_indent = None
            continue
        if ifaces_indent is None:
            continue
        if iface_indent is None:
            if stripped.endswith(":"):
                iface_indent = indent
                cur_iface = stripped[:-1].strip()
            continue
        if indent == iface_indent:
            cur_iface = (stripped[:-1].strip()
                         if stripped.endswith(":") else None)
            in_current = False
            continue
        if stripped == "Current Network Information:":
            in_current = True
            current_indent = indent
            continue
        if in_current:
            if indent <= current_indent:
                in_current = False
                continue
            if stripped.endswith(":"):
                return stripped[:-1].strip(), cur_iface
    return None, None


def _parse_win_ssid(assoc_text: str):
    """Current SSID from ``netsh wlan show interfaces`` (``SSID : x``;
    the ``BSSID`` line never matches - the regex is anchored)."""
    import re
    m = re.search(r"^\s*SSID\s*:\s*(.+)$", str(assoc_text or ""),
                  re.MULTILINE)
    return m.group(1).strip() if m else None


def _assoc_ssid(assoc_text: str):
    """Current association SSID for the RUNNING platform."""
    if platform_key() == "windows":
        return _parse_win_ssid(assoc_text)
    return parse_mac_wifi(assoc_text)[0]


_IPV4_RE = r"([0-9]{1,3}(?:\.[0-9]{1,3}){3})"


def parse_current_wifi(key: str, assoc_text: str, ip_text: str,
                      gateway_text: str) -> dict:
    """Turn the three raw command outputs into
    ``{"ssid": str|None, "ip": str|None, "gateway": str|None}``.

    Any field that cannot be found stays ``None`` - never an exception."""
    import re
    ssid = None
    ip = None
    gateway = None
    if key == "windows":
        ssid = _parse_win_ssid(assoc_text)
        m = re.search(r"IPv4 Address[^:\n]*:\s*" + _IPV4_RE, ip_text or "")
        if m:
            ip = m.group(1)
        m = re.search(r"Default Gateway[^:\n]*:\s*" + _IPV4_RE,
                      ip_text or "")
        if m:
            gateway = m.group(1)
    else:
        ssid, _iface = parse_mac_wifi(assoc_text)
        m = re.search(_IPV4_RE, ip_text or "")
        if m:
            ip = m.group(1)
        m = re.search(r"^\s*gateway:\s*" + _IPV4_RE, gateway_text or "",
                      re.MULTILINE)
        if m:
            gateway = m.group(1)
    return {"ssid": ssid or None, "ip": ip or None,
            "gateway": gateway or None}


def detect_current_wifi(progress=None) -> dict:
    """Probe the Host PC's CURRENT Wi-Fi association (M40).

    mac: ``system_profiler SPAirPortDataType`` (SSID + associated
    interface), ``ipconfig getifaddr <iface>`` (IPv4), ``route -n get
    default`` (gateway).  Windows: ``netsh wlan show interfaces`` (SSID)
    plus one ``ipconfig`` run (IPv4 + default gateway).  Every command
    goes through :func:`run_link_cmd` (monkeypatchable in tests)."""
    key = platform_key()
    cmds = wifi_detect_cmds()
    if progress:
        progress(1, 3)
    assoc = run_link_cmd(cmds["assoc_cmd"])
    if progress:
        progress(2, 3)
    if key == "windows":
        ip_text = run_link_cmd(cmds["ip_cmd"])
        gateway_text = ""
    else:
        _ssid, iface = parse_mac_wifi(assoc)
        ip_text = (run_link_cmd(cmds["ip_cmd"].format(iface=iface))
                   if iface else "")
        gateway_text = run_link_cmd(cmds["gateway_cmd"])
    if progress:
        progress(3, 3)
    return parse_current_wifi(key, assoc, ip_text, gateway_text)


def probe_host_ap_link(gateway: str, progress=None,
                       expected_ssid: str | None = None) -> dict:
    """Orchestrate the Host PC <-> AP connection test (M31/M40).

    Runs :func:`run_link_cmd` twice - the current-association RSSI, then
    a 3-packet ping of the AP/gateway (``Connection OK`` requires >=1
    reply).  RSSI / signal-quality are always reported but do NOT gate
    the verdict by themselves; an empty gateway fails immediately.

    M40: the RSSI belongs to WHICHEVER Wi-Fi the Host PC is associated
    to - a misleading PASS is impossible when no Wi-Fi is associated
    (``no Wi-Fi associated``) or the association is not the configured
    AP (``expected_ssid`` mismatch).  The RSSI line stays visible so
    the operator sees the value that caused the mismatch.

    Returns ``{"ok": bool, "rssi": float|None, "pct": int|None,
    "lines": [...], "quality": str, "error": str}``.  `progress`, when
    given, is called as ``progress(done, total)`` at each stage."""
    import re
    cmds = wifi_link_probe_cmds()
    if progress:
        progress(1, 3)
    out = run_link_cmd(cmds["rssi_cmd"])
    current_ssid = _assoc_ssid(out)
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
    expected = str(expected_ssid or "").strip()
    if not current_ssid:
        lines.append("Connection FAILED: no Wi-Fi associated")
        if progress:
            progress(3, 3)
        return {"ok": False, "rssi": rssi, "pct": pct, "lines": lines,
                "quality": quality, "error": "no Wi-Fi associated"}
    if expected and current_ssid != expected:
        lines.append(
            f'Connection FAILED: Host PC connected to "{current_ssid}", '
            f'not configured AP "{expected}"')
        if progress:
            progress(3, 3)
        return {"ok": False, "rssi": rssi, "pct": pct, "lines": lines,
                "quality": quality,
                "error": (f'Host PC connected to "{current_ssid}", not '
                          f'configured AP "{expected}"')}
    if not gateway:
        lines.append("Connection FAILED: no AP IP / gateway")
        lines.append('Configure the AP IP (gateway) or use "Auto-detect".')
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


# ---------------------------------------------------------------------------
# M32 Host PC Bluetooth panel: status / connected devices / scan / identity.
# ---------------------------------------------------------------------------
_WINDOWS_BT_DEVICES_CMD = (
    'powershell -NoProfile -Command "Get-PnpDevice -Class Bluetooth | '
    'Where-Object {$_.Status -eq \'OK\'} | '
    'Select-Object -ExpandProperty FriendlyName"')


def host_bt_status_cmd() -> str:
    """Host PC BT adapter power status command for THIS platform.

    mac: ``blueutil --raw power`` (``1``/``0``); Windows: the Bluetooth
    class device count (``> 0`` => the adapter is present/powered)."""
    key = platform_key()
    if key == "mac":
        return "blueutil --raw power"
    if key == "windows":
        return ('powershell -NoProfile -Command '
                '"@(Get-PnpDevice -Class Bluetooth).Count"')
    raise PlatformBackendMissing(
        "rf.bluetooth: no built-in Linux host-side Bluetooth CLI")


def host_bt_devices_cmd() -> str:
    """Host PC currently-connected-devices listing command."""
    key = platform_key()
    if key == "mac":
        return "system_profiler SPBluetoothDataType"
    if key == "windows":
        return _WINDOWS_BT_DEVICES_CMD
    raise PlatformBackendMissing(
        "rf.bluetooth: no built-in Linux host-side Bluetooth CLI")


def host_bt_scan_cmd() -> str:
    """Nearby-device scan command.

    mac runs a true 10 s inquiry (``blueutil --inquiry 10``).  Windows
    has no surrounding-device scan API, so the button lists the KNOWN /
    paired Bluetooth devices (immediate, no 10 s wait) - the popup says
    so explicitly (owner-approved option B, 2026-10-29)."""
    key = platform_key()
    if key == "mac":
        return "blueutil --inquiry 10"
    if key == "windows":
        return _WINDOWS_BT_DEVICES_CMD
    raise PlatformBackendMissing(
        "rf.bluetooth: no built-in Linux host-side Bluetooth CLI")


def host_bt_identity() -> tuple:
    """Best-effort Host PC Bluetooth identity ``(name, address)``.

    Returns ``("", "")`` when the backend is unavailable - the caller
    renders the pair-script command WITHOUT fabricated identity values."""
    import re
    key = platform_key()
    if key == "mac":
        name = (run_link_cmd(
            "scutil --get ComputerName 2>/dev/null",
            timeout_s=5) or "").strip().splitlines()
        name = name[0] if name else ""
        out = run_link_cmd("system_profiler SPBluetoothDataType",
                           timeout_s=20)
        addr = ""
        m = re.search(r"\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b", out)
        if m:
            addr = m.group(0).replace("-", ":")
        return name, addr
    if key == "windows":
        name = (run_link_cmd(
            'powershell -NoProfile -Command "$env:COMPUTERNAME"',
            timeout_s=10) or "").strip().splitlines()
        return (name[0] if name else ""), ""
    return "", ""


def parse_bt_status(text: str) -> str:
    """Pure ``ON`` / ``OFF`` / ``N/A`` from the status command output.

    Both ``blueutil --raw power`` (``1``/``0``) and the PowerShell count
    share the ``int > 0`` => ON rule; anything unparseable (missing
    ``blueutil`` / backend unavailable) is ``N/A``."""
    t = (text or "").strip()
    if not t:
        return "N/A"
    first = t.splitlines()[0].strip()
    try:
        return "ON" if int(first) > 0 else "OFF"
    except ValueError:
        low = t.lower()
        if "powered" not in low and "state" not in low and "on" in low:
            return "ON"
        if low.startswith("off") or "off" in low.splitlines()[0].lower():
            return "OFF"
    return "N/A"


def parse_bt_devices(text: str) -> list:
    """Pure connected device list from the devices/scan command output.

    Returns ``"Name (aa:bb:cc:dd:ee:ff)"`` strings for mac
    (``system_profiler`` name + Address lines, and ``blueutil --inquiry``
    ``address: .., name: ..`` lines).  For Windows ``Get-PnpDevice``
    output (friendly names only, no MAC) it returns the non-empty lines
    verbatim as device names."""
    import re
    mac_re = re.compile(r"\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
    text = text or ""
    if not mac_re.search(text):
        # Windows friendly-name listing: no addresses at all.
        return [line.strip() for line in text.splitlines() if line.strip()]
    out: list = []
    pending_name: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        addr_m = mac_re.search(line)
        if addr_m:
            addr = addr_m.group(0).replace("-", ":").lower()
            if pending_name is None and "name" in line.lower():
                nm = re.search(r"name:\s*(.+)", line, re.I)
                pending_name = (nm.group(1).strip() if nm else "")
            out.append(f"{pending_name} ({addr})".strip()
                       if pending_name else addr)
            pending_name = None
            continue
        low = line.lower()
        if line.endswith(":"):
            name = line.rstrip(":").strip()
            if name and low[:-1] not in (
                    "address", "connected", "not connected", "minor type",
                    "services", "major type", "paired", "configured"):
                pending_name = name
    return out


def _parse_rssi_map(text: str) -> dict:
    """``name -> int RSSI`` from ``system_profiler SPBluetoothDataType``.

    Each connected/paired device block carries a ``Name:`` line then an
    ``RSSI: -57`` line; this maps them for the scan popup."""
    import re
    out: dict = {}
    current: str | None = None
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        m = re.match(r"RSSI:\s*(-?\d+)", s)
        if m and current is not None:
            out[current] = int(m.group(1))
            current = None
            continue
        if s.endswith(":") and re.match(r"^[\w .\-()/]+:$", s):
            current = s.rstrip(":").strip()
    return out


def _rssi_for_label(label: str, rssi_map: dict):
    name = (label or "").split(" (")[0].strip()
    if name and name in rssi_map:
        return rssi_map[name]
    for k, v in rssi_map.items():
        if k and (k in name or name in k):
            return v
    return None


def format_bt_scan_result(scan_text: str, rssi_text: str,
                          dut_name: str, is_windows: bool) -> dict:
    """Render the scan popup: device lines + the DUT-hit conclusion.

    RSSI rules (owner-approved 2026-10-29):
      * Windows always ``-- dBm (Not supported by Windows 11)`` (never a
        fake number);
      * mac shows the real ``system_profiler`` dBm, else ``-- dBm``
        (device not connected => no RSSI data).

    Returns ``{"lines": [...], "verdict": str}``; ``verdict`` is empty
    when no DUT name was given."""
    lines: list = []
    if is_windows:
        lines.append("Windows has no surrounding-device scan API; showing "
                     "paired devices only.")
    devices = parse_bt_devices(scan_text)
    rssi_map = {} if is_windows else _parse_rssi_map(rssi_text)
    if devices:
        lines.append("Nearby Bluetooth devices:" if not is_windows else
                     "Known / paired Bluetooth devices:")
        for dev in devices:
            if is_windows:
                rssi_txt = "-- dBm (Not supported by Windows 11)"
            else:
                rssi = _rssi_for_label(dev, rssi_map)
                rssi_txt = f"{rssi} dBm" if rssi is not None else "-- dBm"
            lines.append(f"  {dev}  RSSI: {rssi_txt}")
    else:
        lines.append("No Bluetooth devices found.")
    verdict = ""
    if dut_name:
        found = [d for d in devices if dut_name.lower() in d.lower()]
        if found:
            if is_windows:
                verdict = (f"DUT BT name: {dut_name} 信号已找到, "
                           f"RSSI: -- dBm (Not supported by Windows 11)")
            else:
                rssi = _rssi_for_label(found[0], rssi_map)
                verdict = (f"DUT BT name: {dut_name} 信号已找到, RSSI: "
                           f"{rssi} dBm" if rssi is not None else
                           f"DUT BT name: {dut_name} 信号已找到, RSSI: "
                           f"-- dBm")
        else:
            verdict = f"DUT BT name: {dut_name} 未找到"
    return {"lines": lines, "verdict": verdict}


# ---------------------------------------------------------------------------
# M41 DUT network setup (serial console) - pure command / parser helpers
# ---------------------------------------------------------------------------
def netmask_to_prefix(netmask: str) -> int:
    """``255.255.255.0`` -> 24 (invalid masks fall back to 24)."""
    parts = str(netmask or "").strip().split(".")
    if len(parts) != 4:
        return 24
    try:
        bits = sum(bin(int(p)).count("1") for p in parts)
    except ValueError:
        return 24
    return bits if bits else 24


def parse_dut_ip(text: str, iface: str = "") -> str:
    """The first usable IPv4 in ``ip -4 addr show`` output (127.x /
    link-local are skipped); "" when none is present."""
    import re
    body = str(text or "")
    for candidate in re.findall(r"([0-9]+(?:\.[0-9]+){3})", body):
        if is_lan_ipv4(candidate):
            return candidate
    return ""


def wifi_driver_ready(info_text: str, iface: str = "wlan0") -> bool:
    """True when ``iw dev <iface> info`` found the wireless device (a
    missing driver / device prints "No such device" / "command not
    found")."""
    low = str(info_text or "").lower()
    if not low.strip():
        return False
    for marker in ("no such device", "not found", "cannot find",
                   "can't find", "unknown device", "no wireless"):
        if marker in low:
            return False
    return iface.lower() in low


def network_ip_commands(iface: str, dhcp: bool, dut_ip: str = "",
                        netmask: str = "255.255.255.0",
                        gateway: str = "") -> list:
    """The DUT-side address commands for one interface.

    DHCP asks ``dhclient`` first and falls back to the busybox
    ``udhcpc``; the static path flushes the old address, applies the
    configured IPv4 / mask and (when given) the default gateway."""
    iface = str(iface or "eth0").strip() or "eth0"
    if dhcp:
        return [f"dhclient {iface}", f"udhcpc -i {iface}"]
    ip = str(dut_ip or "").strip()
    prefix = netmask_to_prefix(netmask)
    commands = [f"ip addr flush dev {iface}"]
    if ip:
        commands.append(f"ip addr add {ip}/{prefix} dev {iface}")
    commands.append(f"ip link set {iface} up")
    gw = str(gateway or "").strip()
    if gw:
        commands.append(f"ip route add default via {gw}")
    return commands


def wifi_connect_plan(params: dict | None) -> dict:
    """Build the stepwise DUT Wi-Fi connect plan from one op's params.

    Keys: ``prepare`` (link-up), ``probe`` (driver check command),
    ``conf_write`` (multi-line wpa_supplicant.conf writer), ``connect``,
    ``net_commands`` (DHCP / static), ``confirm`` and ``timeout_s``.
    ``ssid`` / ``password`` come from the Wi-Fi page config, plugged
    into the template when the row was created."""
    from .steps import NETWORK_STACKS, wpa_conf_text   # no cycle at import
    p = dict(params or {})
    iface = str(p.get("iface") or "wlan0").strip() or "wlan0"
    stack = str(p.get("stack") or "wpa_supplicant")
    spec = NETWORK_STACKS.get(stack) or NETWORK_STACKS["wpa_supplicant"]
    conf = spec["conf_path"]
    conf_text = wpa_conf_text(str(p.get("ssid") or ""),
                              str(p.get("password") or ""))
    return {
        "type": "wifi_connect", "iface": iface, "stack": stack,
        "prepare": [f"ip link set {iface} up"],
        "probe": f"iw dev {iface} info",
        "conf_path": conf,
        "conf_write": (f"cat > {conf} <<'EOF'\n{conf_text}EOF"),
        "connect": spec["connect"].format(iface=iface, conf=conf),
        "net_commands": network_ip_commands(
            iface, bool(p.get("dhcp", True)), str(p.get("dut_ip") or ""),
            str(p.get("netmask") or "255.255.255.0"),
            str(p.get("gateway") or "")),
        "confirm": f"ip -4 addr show {iface}",
        "timeout_s": float(p.get("timeout_s") or 60.0),
    }


def lan_setup_plan(params: dict | None) -> dict:
    """Build the DUT Ethernet setup plan (DHCP or static per step)."""
    p = dict(params or {})
    iface = str(p.get("iface") or "eth0").strip() or "eth0"
    mode = str(p.get("mode") or "dhcp").lower()
    return {
        "type": "lan_setup", "iface": iface, "mode": mode,
        "prepare": [],
        "probe": "",
        "conf_write": "",
        "connect": "",
        "net_commands": network_ip_commands(
            iface, mode != "static", str(p.get("dut_ip") or ""),
            str(p.get("netmask") or "255.255.255.0"),
            str(p.get("gateway") or "")),
        "confirm": f"ip -4 addr show {iface}",
        "timeout_s": float(p.get("timeout_s") or 60.0),
    }


# ---------------------------------------------------------------------------
# M41 SSH three-layer diagnosis: network -> TCP 22 -> auth
# ---------------------------------------------------------------------------
def ping_cmd(host: str) -> str:
    """One-shot ping command for the Host PC's platform."""
    key = platform_key()
    if key == "windows":
        return f"ping -n 1 {host}"
    return f"ping -c 1 {host}"


def ping_host(host: str, timeout_s: float = 4.0) -> bool:
    """True when the Host PC gets at least one ping reply from `host`."""
    if not str(host or "").strip():
        return False
    out = run_link_cmd(ping_cmd(str(host).strip()),
                       timeout_s=max(1, int(timeout_s)))
    return _ping_has_reply(out)


def tcp_port_open(host: str, port: int = 22, timeout_s: float = 4.0) -> bool:
    """True when a TCP connection to host:port succeeds (sshd reachable)."""
    import socket
    try:
        with socket.create_connection((str(host).strip(), int(port)),
                                      timeout=timeout_s):
            return True
    except Exception:                      # noqa: BLE001 - unreachable
        return False


def serial_port_devices(devices, key: str | None = None) -> list:
    """Filter ``list_ports`` device names for THIS platform.

    mac shows only ``/dev/cu.*`` (the call-out devices; ``/dev/tty.*``
    would block waiting for a carrier), Windows only ``COM*``."""
    key = key or platform_key()
    items = [str(d) for d in (devices or [])]
    if key == "mac":
        return [d for d in items if d.startswith("/dev/cu.")]
    if key == "windows":
        return [d for d in items if d.upper().startswith("COM")]
    return items
