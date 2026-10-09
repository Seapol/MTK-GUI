# -*- coding: utf-8 -*-
"""P3-B4 Modules D + E: Wi-Fi and Bluetooth RF adapters.

Both adapters are CONFIGURATION-DRIVEN: every host command template
lives in the product YAML under ``rf.wifi`` / ``rf.bluetooth`` and the
backend is selected by ``platform.system()`` (``mac`` on macOS,
``windows`` on Windows).  A backend with no real command set (Windows
placeholder ``_todo``) raises :class:`PlatformBackendMissing` - the
explicit-error red line, never a silent downgrade.

Modes (product YAML ``mode``):

Wi-Fi:
  * ``full_stack`` - Full Stack DUT (i.MX Linux): clean competing
    networks, join the DUT AP, read RSSI via
    ``system_profiler SPAirPortDataType`` (the ONLY reliable source on
    modern macOS; ``airport -I/-s`` and
    ``networksetup -getairportnetwork`` are deprecated/broken),
    ping the gateway (warm-up packets ignored), optional iperf3,
    restore the competing networks.
  * ``rssi_only``  - Bare Metal DUT (i.MX RT): scan + read RSSI by
    SSID, never joins, never pings.

Bluetooth:
  * ``a2dp_sink`` - Full Stack DUT: blueutil inquiry -> connect ->
    is-connected -> RSSI (system_profiler SPBluetoothDataType) ->
    switch audio output -> play test tone -> operator GUI confirm ->
    disconnect.
  * ``rssi_only`` - Bare Metal DUT: inquiry + RSSI by name only.

All commands run through :class:`~mtkgui.engine.host_cli.HostCliRunner`
so EventLog identity, timeouts and keyword judging are uniform.
"""
from __future__ import annotations

import platform as _platform
import time

#: YAML backend key per platform.system() value
_BACKEND_KEYS = {"Darwin": "mac", "Windows": "windows", "Linux": "linux"}


class PlatformBackendMissing(RuntimeError):
    """No usable command backend for this platform (explicit error)."""


def backend_key_for(system: str | None = None) -> str:
    """Map ``platform.system()`` to the YAML backend key."""
    return _BACKEND_KEYS.get(system or _platform.system(), "unknown")


def _backend_section(rf_cfg: dict, section: str,
                     key: str | None = None) -> dict:
    """Pick ``{section}.{backend_key}`` and reject placeholder / todo
    backends explicitly.  `key` overrides the platform mapping (unit
    tests: force the 'windows' backend)."""
    cmds = rf_cfg.get(section, {}).get("cmds", rf_cfg.get(section, {}))
    key = key or backend_key_for()
    backend = cmds.get(key)
    if not backend or backend.get("_todo") or not any(
            isinstance(v, str) for v in backend.values()):
        raise PlatformBackendMissing(
            f"rf.{section}: no usable '{key}' backend configured "
            "(explicit error, no silent downgrade)")
    return backend


class WifiAdapter:
    """Wi-Fi RF test adapter (P3-B4 Module D)."""

    section = "wifi"

    def __init__(self, rf_cfg: dict, runner) -> None:
        """`rf_cfg` = the whole ``rf:`` YAML node; `runner` = a
        HostCliRunner (identity / EventLog shared)."""
        cfg = rf_cfg.get("wifi", {})
        self.mode = cfg.get("mode", "rssi_only")
        self.expected_ssid = cfg.get("expected_ssid", "")
        self.ssid_password = cfg.get("password", "")
        self.gateway = cfg.get("gateway", "")
        self.rssi_min = int(cfg.get("rssi_min", -70))
        self.ping_count = int(cfg.get("ping_count", 20))
        self.warmup_packets = int(cfg.get("warmup_packets", 3))
        self.assoc_wait_s = float(cfg.get("assoc_wait_s", 8))
        self.run_iperf = bool(cfg.get("iperf3", False))
        self.iperf_timeout_s = float(cfg.get("iperf_timeout_s", 60))
        self.timeout_s = float(cfg.get("timeout_s", 60))
        self.cmds = _backend_section(rf_cfg, "wifi")
        self._runner = runner
        self._competing: list = []       # recorded pre-test SSIDs

    # ------------------------------------------------------------ helpers
    def _run(self, template: str, params: dict | None = None, **kw):
        return self._runner.run(template, params or {},
                                timeout_s=kw.pop("timeout_s",
                                                 self.timeout_s),
                                **kw)

    def scan_rssi(self, target: str) -> tuple:
        """Scan for `target` (SSID or BT name); returns
        ``(rssi:int|None, raw_lines)``."""
        res = self._run(self.cmds["rssi_cmd"])
        pattern = self.cmds.get("rssi_parse",
                                r"Signal / Noise: (-?\d+) dBm")
        import re
        text = "\n".join(res.lines)
        blocks = text.split(target)
        rssi = None
        for block in blocks[1:]:         # first occurrence after name
            m = re.search(pattern, block)
            if m:
                rssi = int(m.group(1))
                break
        return rssi, res.lines

    # ------------------------------------------------------------- full_stack
    def _record_competing(self):
        res = self._run(self.cmds["list_networks_cmd"])
        self._competing = [
            ln for ln in res.lines
            if ln.strip() and "network" not in ln.lower()
            and "en0" not in ln.lower()
            and self.expected_ssid not in ln]

    def _restore_competing(self):
        """Re-add the pre-test networks.  NOTE (macOS 15 verified):
        re-adding a WPA network without its password fails (error
        -3905) - a failure is logged as a warning, NOT raised; macOS
        auto-rejoins known networks on its own (verified: the station
        rejoined the home AP right after removal)."""
        for ssid in self._competing:
            res = self._run(self.cmds["add_network_cmd"],
                            {"ssid": ssid.strip()})
            if res.exit_code != 0:
                self._runner._log(
                    f"[{self._runner.station_id}] [{self._runner.user}] "
                    f"wifi restore warning: could not re-add "
                    f"'{ssid.strip()}' (needs its password; macOS "
                    "auto-rejoin covers this)")

    def _ping_gateway(self) -> dict:
        res = self._run(
            self.cmds["ping_cmd"],
            {"gateway": self.gateway, "count": self.ping_count},
            regex_extracts={"loss_pct":
                            r"(\d+(?:\.\d+)?)% packet loss"},
            timeout_s=max(self.ping_count + 10, 30))
        loss = float(res.items.get("loss_pct", "100"))
        return {"loss_pct": loss, "verdict": res.verdict,
                "exit_code": res.exit_code}

    def _iperf3(self, dut_ip: str) -> dict | None:
        """Optional iperf3 throughput step (cmds key ``iperf_cmd``,
        enabled by the ``iperf3: true`` config flag).  Throughput is
        parsed from the RECEIVER summary line (``iperf_parse``;
        iperf3 auto-scales the unit, so M/Gbits/sec are normalised to
        Mbits/sec).  Informational - it does not gate the verdict
        (RSSI + ping loss remain the gate)."""
        if not self.run_iperf or "iperf_cmd" not in self.cmds:
            return None
        import re
        res = self._run(self.cmds["iperf_cmd"], {"ip": dut_ip},
                        timeout_s=self.iperf_timeout_s)
        m = re.search(self.cmds.get(
            "iperf_parse",
            r"([\d.]+)\s+([MG])bits/sec\s+(?:\d+\s+\S+\s+)?receiver"),
            "\n".join(res.lines))
        throughput = None
        if m:
            val = float(m.group(1))
            if m.group(2).upper() == "G":
                val *= 1000.0
            throughput = f"{val:.1f}"
        return {"throughput": throughput, "verdict": res.verdict}

    def _discover_gateway(self, fallback: str) -> str:
        """Optional gateway auto-discovery (cmds key ``gateway_cmd`` +
        ``gateway_parse`` regex, e.g. ``route -n get default``).  Falls
        back to the configured value when the key is absent."""
        if "gateway_cmd" not in self.cmds:
            return fallback
        res = self._run(self.cmds["gateway_cmd"], timeout_s=15,
                        regex_extracts={"gw": self.cmds.get(
                            "gateway_parse", r"gateway:\s+(\S+)")})
        return res.items.get("gw") or fallback

    def _wait_associated(self, ssid: str, password: str) -> tuple:
        """Send connect, then POLL until the SSID shows up in the RSSI
        source (association actually CONFIRMED - the connect command's
        exit code alone is not proof; macOS auto-rejoin can steal the
        association back).  One reconnect is re-issued at the halfway
        point.  Bounded by assoc_wait_s (min 8s)."""
        deadline = time.monotonic() + max(self.assoc_wait_s, 8)
        half = time.monotonic() + max(self.assoc_wait_s, 8) / 2
        reconnected = False
        rssi, lines = None, []
        while True:
            time.sleep(2)
            rssi, lines = self.scan_rssi(ssid)
            if rssi is not None:
                return rssi, lines
            now = time.monotonic()
            if now >= deadline:
                return None, lines
            if now >= half and not reconnected:
                reconnected = True
                self._run(self.cmds["connect_cmd"],
                          {"ssid": ssid, "password": password})

    # --------------------------------------------------------------- public
    def run_test(self, test_vars: dict | None = None) -> dict:
        """Execute the configured mode; returns a report dict with
        ``verdict`` / ``items`` / ``lines``."""
        tv = dict(test_vars or {})
        ssid = tv.get("ssid", self.expected_ssid)
        password = tv.get("password", self.ssid_password)
        # run-time overrides feed back into self so _ping_gateway and
        # the helpers always see the SAME values this run used
        if tv.get("gateway"):
            self.gateway = tv["gateway"]
        items: dict = {}

        if self.mode == "rssi_only":
            rssi, lines = self.scan_rssi(ssid)
            verdict = ("Pass" if rssi is not None
                       and rssi >= self.rssi_min else "Fail")
            if rssi is not None:
                items["rssi"] = rssi
            return {"verdict": verdict, "items": items, "lines": lines}

        # ---- full_stack -------------------------------------------------
        self._record_competing()
        for other in self._competing:
            self._run(self.cmds["remove_network_cmd"], {"ssid":
                       other.strip()})
        try:
            self._run(self.cmds["connect_cmd"],
                      {"ssid": ssid, "password": password})
            rssi, lines = self._wait_associated(ssid, password)
            if rssi is not None:
                items["rssi"] = rssi
            self.gateway = self._discover_gateway(self.gateway)
            ping = self._ping_gateway()
            items["loss_pct"] = ping["loss_pct"]
            iperf = self._iperf3(tv.get("dut_ip", ""))
            if iperf and iperf.get("throughput"):
                items["throughput"] = iperf["throughput"]
            ok = (rssi is not None and rssi >= self.rssi_min
                  and ping["loss_pct"] <= 5.0)
            verdict = "Pass" if ok else "Fail"
        finally:
            self._restore_competing()                 # always restore
        return {"verdict": verdict, "items": items, "lines": lines}


class BluetoothAdapter:
    """Bluetooth RF test adapter (P3-B4 Module E)."""

    section = "bluetooth"

    def __init__(self, rf_cfg: dict, runner, human_confirm=None) -> None:
        cfg = rf_cfg.get("bluetooth", {})
        self.mode = cfg.get("mode", "rssi_only")
        self.expected_name = cfg.get("expected_name", "")
        self.rssi_min = int(cfg.get("rssi_min", -70))
        self.scan_s = int(cfg.get("scan_s", 10))
        self.timeout_s = float(cfg.get("timeout_s", 30))
        self.tone_path = cfg.get("test_tone", "resources/test_tone.wav")
        self.cmds = _backend_section(rf_cfg, "bluetooth")
        self._runner = runner
        self._confirm = human_confirm   # callable(question) -> bool
        self._addr: str = ""

    def _run(self, template: str, params: dict | None = None, **kw):
        return self._runner.run(template, params or {},
                                timeout_s=kw.pop("timeout_s",
                                                 self.timeout_s),
                                **kw)

    # ------------------------------------------------------------ helpers
    def _scan_find(self, name: str) -> tuple:
        """Inquiry and match the DUT by name; returns
        ``(address|None, rssi|None, lines)``."""
        res = self._run(self.cmds["scan_cmd"],
                        {"seconds": self.scan_s},
                        timeout_s=self.scan_s + 10)
        import re
        addr = None
        rssi = None
        addr_pattern = self.cmds.get("addr_parse",
                                     r"([0-9a-fA-F:-]{17})\s")
        rssi_pattern = self.cmds.get("rssi_parse", r"(-?\d+)\s*dBm")
        for line in res.lines:
            if name in line:
                m = re.search(addr_pattern, line)
                if m:
                    addr = m.group(1).lower().replace("-", ":")
                r = re.search(rssi_pattern, line)
                if r:
                    rssi = int(r.group(1))
                break
        return addr, rssi, res.lines

    # --------------------------------------------------------------- public
    def run_test(self, test_vars: dict | None = None) -> dict:
        tv = dict(test_vars or {})
        name = tv.get("name", self.expected_name)
        items: dict = {}
        addr, rssi, lines = self._scan_find(name)
        if rssi is not None:
            items["rssi"] = rssi

        if self.mode == "rssi_only":
            verdict = ("Pass" if rssi is not None
                       and rssi >= self.rssi_min else "Fail")
            return {"verdict": verdict, "items": items, "lines": lines}

        # ---- a2dp_sink --------------------------------------------------
        if not addr:
            return {"verdict": "Fail",
                    "items": items,
                    "lines": lines + ["[bt] DUT not found in inquiry"]}

        self._run(self.cmds["connect_cmd"], {"addr": addr})
        verify = self._run(self.cmds["verify_cmd"], {"addr": addr})
        connected = verify.exit_code == 0
        if connected:
            items["connected"] = 1
            rssi = self._read_rssi(addr)
            if rssi is not None:
                items["rssi"] = rssi
            # switch audio to the DUT and play the test tone
            self._run(self.cmds["audio_switch_cmd"], {"name": name})
            self._run(self.cmds["tone_cmd"], {"tone": self.tone_path})
            heard = self._confirm(
                f"Do you hear audio from DUT headphone jack? "
                f"(DUT: {name}, addr: {addr})") \
                if self._confirm else False
            items["operator_confirmed"] = 1 if heard else 0
            verdict = ("Pass" if heard
                       and rssi is not None and rssi >= self.rssi_min
                       else ("Pass" if heard and rssi is None else "Fail"))
        else:
            verdict = "Fail"
            items["connected"] = 0
        self._run(self.cmds["disconnect_cmd"], {"addr": addr})
        return {"verdict": verdict, "items": items, "lines": lines}

    def _read_rssi(self, addr: str) -> int | None:
        res = self._run(self.cmds["rssi_cmd"])
        import re
        pattern = self.cmds.get("rssi_parse", r"(-?\d+)\s*dBm")
        text = "\n".join(res.lines)
        if addr in text.lower() or self.expected_name in text:
            m = re.search(pattern, text)
            if m:
                return int(m.group(1))
        return None
