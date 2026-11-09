# -*- coding: utf-8 -*-
"""Host-side RF scanning for the FCT Wi-Fi / Bluetooth RSSI steps (M49b).

The Wi-Fi scan and Bluetooth RSSI steps measure the signal on the HOST
PC, never on the DUT, so they work for bare-metal / RTOS and Linux DUTs
alike with minimal DUT dependency:

* :func:`wifi_scan` - ``{ssid: rssi_dbm | None}`` for the requested
  SSID list.  Windows runs ``lswifi --json`` (pip-installable) and
  parses the JSON; macOS reads the existing CoreWLAN command
  (``system_profiler SPAirPortDataType``), which exposes real dBm.
  The old Windows "Signal %" -> dBm approximation is therefore NOT
  used any more.
* :func:`bt_scan` - one RSSI (dBm) or ``None`` for a BLE device matched
  by broadcast name / BD address, through ``bleak`` (WinRT on Windows,
  CoreBluetooth on macOS).

Both entry points use one tiny host-command seam (:func:`run_command`)
and one BLE-discovery seam (:func:`_bleak_discover`) so unit tests
inject canned outputs without touching the real hardware.

The steps map an unavailable backend / failed command to an explicit
ERROR (never a silent PASS), and a not-found device to FAIL with a
cause line - the caller owns the wording.
"""
from __future__ import annotations

import json
import platform
import tempfile
from pathlib import Path

#: deterministic virtual-mode RSSI (Virtual DUT / tests)
VIRTUAL_RSSI_DBM = -45

_LSWIFI_CMD = "lswifi --json"
_COREWLAN_CMD = "system_profiler SPAirPortDataType"

_RF_DUMP_DIR = Path(tempfile.gettempdir()) / "mtkgui_host_rf"


def dump_dir() -> Path:
    """Where host RF tools may leave their own files (lswifi dumps its scan
    JSON into the CWD) - never the station folder."""
    _RF_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    return _RF_DUMP_DIR


#: stderr fragments produced when the CLI itself is missing
_MISSING_CMD_MARKERS = (
    "not found", "not recognized", "no such file or directory",
    "command not found", "is not recognized",
)

_BACKEND_KEYS = {"Darwin": "mac", "Windows": "windows", "Linux": "linux"}


class HostRfError(RuntimeError):
    """The host-side scan cannot run (missing tool / bad output)."""


def host_key() -> str:
    """``platform.system()`` -> ``mac`` / ``windows`` / ``linux`` /
    ``unknown`` (the same keys the rf_adapters use)."""
    return _BACKEND_KEYS.get(platform.system(), "unknown")


# ---------------------------------------------------------------------------
# host command seam
# ---------------------------------------------------------------------------
def run_command(cmd_line: str, timeout_s: float = 30, *,
                keep_stderr: bool = True, cwd=None) -> str:
    """Run one host shell command; returns stdout + stderr text.

    ``keep_stderr=False`` returns stdout only (callers that must parse
    a payload on stdout while tool logs pollute stderr - e.g.
    ``lswifi --json`` prints INFO logs to stderr).  A missing-command
    marker on stderr is still merged in that mode so callers can tell
    "tool absent" from "bad output".  Never raises: a missing command /
    timeout is returned as an ``ERROR: ...`` line so the caller can
    attribute it.  Tests monkeypatch this single entry point instead of
    reaching into subprocess."""
    import subprocess
    try:
        proc = subprocess.run(cmd_line, shell=True, capture_output=True,
                              text=True, timeout=timeout_s, cwd=cwd)
    except Exception as exc:              # noqa: BLE001 - real cause text
        return f"ERROR: {exc}"
    if keep_stderr or _looks_like_missing_cmd(proc.stderr):
        return (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.stdout or ""


def _looks_like_missing_cmd(text: str) -> bool:
    low = str(text or "").lower()
    return any(m in low for m in _MISSING_CMD_MARKERS)


# ---------------------------------------------------------------------------
# Wi-Fi
# ---------------------------------------------------------------------------
def _rssi_value(value, *, percent: bool = False):
    """Normalise a raw RSSI field to int dBm.

    M66: the lswifi JSON schema carries dBm values directly (negative
    ints such as -76).  A 0-100 value is ONLY converted (``//2 - 100``)
    when the source field is explicitly a percentage; a positive value
    on a dBm field is not a dBm reading and is rejected instead of
    silently mis-converted (the old "-24 for a -76 AP" anomaly)."""
    try:
        rssi = int(float(value))
    except (TypeError, ValueError):
        return None
    if -120 <= rssi <= 0:
        return rssi
    if percent and 0 < rssi <= 100:
        return rssi // 2 - 100
    return None


_SSID_KEYS = ("ssid", "SSID", "name", "Name", "network")
#: documented dBm fields (negative ints) - no generic "signal" guesses
_RSSI_KEYS = ("RSSI", "rssi", "rssi_dbm", "signal_dbm")
#: explicitly percentage-shaped fields (0-100) -> approximation only
_PERCENT_KEYS = ("Signal %", "signal_percent", "SignalPercent")


def _row_ssid(row: dict):
    for key in _SSID_KEYS:
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _row_rssi(row: dict):
    for key in _RSSI_KEYS:
        if key in row:
            val = _rssi_value(row.get(key))
            if val is not None:
                return val
    for key in _PERCENT_KEYS:
        if key in row:
            val = _rssi_value(row.get(key), percent=True)
            if val is not None:
                return val
    return None


def parse_lswifi_json(text: str) -> dict:
    """``{ssid: rssi_dbm}`` from ``lswifi --json`` output.

    Tolerant of the common shapes: a top-level list of BSS entries, a
    ``{"networks": [...]}`` wrapper, or a mapping of SSID -> entry.
    The strongest RSSI wins when one SSID appears on several BSSIDs.
    Malformed JSON raises :class:`HostRfError`."""
    try:
        data = json.loads(str(text or ""))
    except (TypeError, ValueError) as exc:
        raise HostRfError("lswifi output is not valid JSON") from exc
    rows: list = []
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        if isinstance(data.get("networks"), list):
            rows = [r for r in data["networks"] if isinstance(r, dict)]
        else:
            for key, val in data.items():
                if isinstance(val, dict):
                    row = dict(val)
                    row.setdefault("ssid", key)
                    rows.append(row)
    out: dict = {}
    for row in rows:
        ssid = _row_ssid(row)
        rssi = _row_rssi(row)
        if not ssid or rssi is None:
            continue
        if ssid not in out or rssi > out[ssid]:
            out[ssid] = rssi
    return out


def parse_corewlan_text(text: str) -> dict:
    """``{ssid: rssi_dbm}`` from ``system_profiler SPAirPortDataType``.

    Each visible network block carries an ``<SSID>:`` label followed by
    a ``Signal / Noise: -45 dBm / -90 dBm`` line; the label directly
    above the signal line is the SSID."""
    out: dict = {}
    current = None
    for raw in str(text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("Signal / Noise:"):
            if current is None:
                continue
            import re
            m = re.search(r"(-?\d+)\s*dBm", stripped)
            if m:
                out[current] = int(m.group(1))
            current = None
            continue
        if stripped.endswith(":") and not stripped.startswith(
                ("Interfaces:", "Current Network Information",
                 "Other Local Wi-Fi Networks", "awdl", "llw")):
            current = stripped[:-1].strip()
    return out


def wifi_scan(ssid_list, *, key: str | None = None,
              virtual: bool = False, virtual_rssi=None,
              timeout_s: float = 30) -> dict:
    """Scan the HOST PC for `ssid_list`; ``{ssid: rssi_dbm | None}``.

    Windows: ``lswifi --json`` (missing tool / bad output -> HostRfError).
    macOS: CoreWLAN (``system_profiler``).
    Virtual mode: a deterministic configured RSSI for every target."""
    targets = [str(s).strip() for s in (ssid_list or []) if str(s).strip()]
    if not targets:
        raise HostRfError("no Wi-Fi scan target configured")
    if virtual:
        rssi = (VIRTUAL_RSSI_DBM if virtual_rssi is None
                else int(virtual_rssi))
        return {ssid: rssi for ssid in targets}
    backend = key or host_key()
    if backend == "windows":
        # M63: lswifi INFO logs go to stderr; parse stdout only.
        out = run_command(_LSWIFI_CMD, timeout_s=timeout_s,
                          keep_stderr=False, cwd=dump_dir())
        try:
            found = parse_lswifi_json(out)
        except HostRfError:
            if _looks_like_missing_cmd(out):
                raise HostRfError(
                    "lswifi not found / scan failed (install it with "
                    "'pip install lswifi')") from None
            raise
    elif backend == "mac":
        # M63: system_profiler can also emit noise on stderr.
        out = run_command(_COREWLAN_CMD, timeout_s=timeout_s,
                          keep_stderr=False)
        found = parse_corewlan_text(out)
    else:
        raise HostRfError(
            "host-side Wi-Fi scan is supported on Windows (lswifi) and "
            "macOS (CoreWLAN) only")
    return {ssid: found.get(ssid) for ssid in targets}


# ---------------------------------------------------------------------------
# Bluetooth (BLE)
# ---------------------------------------------------------------------------
def _bleak_discover(timeout_s: float = 10.0) -> list:
    """Return ``[(address, name, rssi_dbm | None), ...]`` via the scan
    callback.

    The single BLE seam used by :func:`bt_scan` (tests monkeypatch it).
    Modern bleak (>= 0.21) exposes RSSI only through the detection
    callback's AdvertisementData - ``BLEDevice.rssi`` was removed, so
    ``BleakScanner.discover`` results carry no RSSI.  A missing
    ``bleak`` package raises :class:`HostRfError`."""
    try:
        from bleak import BleakScanner
    except ImportError as exc:
        raise HostRfError(
            "bleak is not installed (install it with 'pip install bleak'); "
            "BT scan failed") from exc
    import asyncio
    hits: list = []

    def _on_detect(device, advertisement_data):
        hits.append((str(getattr(device, "address", "") or ""),
                     str(getattr(device, "name", "") or ""),
                     getattr(advertisement_data, "rssi", None)))

    async def _scan():
        scanner = BleakScanner(detection_callback=_on_detect)
        await scanner.start()
        await asyncio.sleep(timeout_s)
        await scanner.stop()

    try:
        asyncio.run(_scan())
    except Exception as exc:              # noqa: BLE001 - backend failure
        raise HostRfError(f"BT scan failed: {exc}") from exc
    return hits


def parse_bleak_devices(devices, target: str):
    """RSSI (dBm) of the BLE device matching `target`, else ``None``.

    `target` is matched against the BD address (``aa:bb:..`` /
    ``aa-bb-..`` normalised) and the broadcast name (case-insensitive;
    an exact name match wins over a containment match).  `devices`
    accepts BOTH the ``(address, name, rssi)`` tuples returned by
    :func:`_bleak_discover` on modern bleak and legacy objects with
    ``.name/.address/.rssi`` attributes."""
    tgt = str(target or "").strip().lower()
    if not tgt:
        return None
    # only the ADDRESS form is hyphen-normalised - a device NAME may
    # legitimately contain '-' (e.g. "DUT-BT")
    tgt_addr = tgt.replace("-", ":")
    exact = None
    partial = None
    for dev in devices or []:
        if isinstance(dev, (tuple, list)):
            parts = list(dev) + [None, None, None]
            addr, name, rssi = parts[0], str(parts[1] or ""), parts[2]
        else:
            addr = getattr(dev, "address", "") or ""
            name = str(getattr(dev, "name", "") or "")
            rssi = getattr(dev, "rssi", None)
        name = name.strip()
        addr = str(addr).replace("-", ":").lower()
        if rssi is None:
            continue
        try:
            value = int(rssi)
        except (TypeError, ValueError):
            continue
        if (addr and tgt_addr == addr) or (name and tgt == name.lower()):
            exact = value if exact is None else max(exact, value)
        elif name and tgt in name.lower():
            partial = value if partial is None else max(partial, value)
    if exact is not None:
        return exact
    return partial


def bt_scan(target: str, *, virtual: bool = False, virtual_rssi=None,
            timeout_s: float = 10.0):
    """Scan the HOST PC for one BLE device; RSSI (dBm) or ``None``.

    Windows (WinRT) and macOS (CoreBluetooth) go through ``bleak``;
    Linux works when BlueZ is available.  Virtual mode returns the
    deterministic configured RSSI."""
    if virtual:
        return (VIRTUAL_RSSI_DBM if virtual_rssi is None
                else int(virtual_rssi))
    devices = _bleak_discover(timeout_s)
    return parse_bleak_devices(devices, target)
