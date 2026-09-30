# -*- coding: utf-8 -*-
"""WiFi RF test wrapper for the Host PC's built-in WLAN adapter.

Test principle (per the station RF test spec):

1. The DUT board is configured into WiFi AP / broadcast mode.
2. The Host PC scans for the target SSID (``netsh wlan show networks
   mode=bssid``) and reads the best BSSID signal quality, converted to
   an RSSI estimate in dBm.
3. The Host PC associates with the DUT (profile + ``netsh wlan
   connect``) and verifies the interface state.
4. ``ping`` measures latency and packet loss; the optional
   ``iperf3 -J`` run measures throughput.
5. A structured verdict is computed against caller-supplied YAML
   limits.

Tool execution goes through the injected
:class:`~mtkgui.drivers.rf_common.CommandExecutor`, so the unit tests
and the headless demo run without Windows / hardware.  All config
values (SSID, password, target IP, limits, timeouts) come from the
caller's ``config/`` YAML - nothing is hardcoded here.

Locale note: the ``netsh``/``ping`` parsers expect the English
output format - VERIFY against the production image locale at bring-up.
"""

from __future__ import annotations

import logging
import os
import tempfile

from mtkgui.drivers.base import (
    InstrumentDriver,
    MeasurementResult,
    Status,
    Transport,
)
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentError,
    InstrumentIOError,
    InstrumentTimeoutError,
)
from mtkgui.drivers.rf_common import (
    CommandExecutor,
    RFTestReport,
    SubprocessExecutor,
    netsh_signal_to_dbm,
    parse_iperf_json,
    parse_ping_windows,
)

_LOG = logging.getLogger("mtkgui.drivers.wifi_rf")

#: netsh/ping/iperf3 command templates (documented Windows CLI).
CMD_NETSH_SHOW_NETWORKS = ["netsh", "wlan", "show", "networks",
                           "mode=bssid"]
CMD_NETSH_SHOW_INTERFACES = ["netsh", "wlan", "show", "interfaces"]
CMD_NETSH_SHOW_DRIVERS = ["netsh", "wlan", "show", "drivers"]
CMD_PING = ["ping", "-n", "{count}", "{host}"]
CMD_IPERF = ["iperf3", "-c", "{host}", "-t", "{seconds}", "-J"]

#: netsh profile XML template for a WPA2-Personal network (documented
#: netsh WLAN profile schema).
_PROFILE_XML = (
    '<?xml version="1.0"?>\n'
    '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/'
    'profile/v1">\n'
    '  <name>{ssid}</name>\n'
    '  <SSIDConfig>\n    <SSID>\n      <name>{ssid}</name>\n'
    '    </SSID>\n  </SSIDConfig>\n'
    '  <connectionType>ESS</connectionType>\n'
    '  <connectionMode>manual</connectionMode>\n'
    '  <MSM>\n    <security>\n'
    '      <authEncryption>\n'
    '        <authentication>WPA2PSK</authentication>\n'
    '        <encryption>AES</encryption>\n'
    '        <useOneX>false</useOneX>\n'
    '      </authEncryption>\n'
    '      <sharedKey>\n        <keyType>passPhrase</keyType>\n'
    '        <protected>false</protected>\n'
    '        <keyMaterial>{password}</keyMaterial>\n'
    '      </sharedKey>\n'
    '    </security>\n  </MSM>\n'
    '</WLANProfile>\n')

#: run_test() config keys (all supplied from config/ YAML by the
#: caller; values shown are the *required* key names, not defaults).
#: {"ssid": str, "password": str, "target_ip": str, "iperf_enabled":
#:  bool, "iperf_seconds": int, "timeout_s": float,
#:  "limits": {"min_rssi_dbm": float, "max_ping_ms": float,
#'             "max_packet_loss_pct": float, "min_throughput_mbps": float}}
_REQUIRED_KEYS = ("ssid", "password", "target_ip", "limits")
_REQUIRED_LIMITS = ("min_rssi_dbm", "max_ping_ms", "max_packet_loss_pct",
                    "min_throughput_mbps")


def parse_netsh_networks(output: str, ssid: str) -> float:
    """Find the best signal percentage for one SSID in ``netsh wlan
    show networks mode=bssid`` output.

    Args:
        output: Raw netsh stdout.
        ssid:   Target SSID (exact match, case-insensitive).

    Returns:
        Best matching signal quality percentage (0..100), or ``-1``
        when the SSID was not found.

    Raises:
        InstrumentIOError: The output has no parsable blocks at all
                           (wrong tool or locale).
    """
    best = -1
    current_ssid = None
    seen_any_block = False
    for line in (output or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("SSID") and ":" in stripped:
            # "SSID 3 : MYDUT" - a BSSID block header
            name = stripped.partition(":")[2].strip()
            current_ssid = name if name else None
            seen_any_block = True
        elif stripped.startswith("Signal") and ":" in stripped:
            raw = stripped.partition(":")[2].strip().rstrip("%")
            try:
                pct = int(raw)
            except ValueError:
                continue
            if current_ssid is not None and \
                    current_ssid.casefold() == (ssid or "").casefold():
                best = max(best, pct)
    if not seen_any_block and not any(
            marker in (output or "")
            for marker in ("Signal", "Interface")):
        # neither SSID blocks nor netsh headers -> not netsh output
        # (an empty scan with 0 networks is a valid not-found outcome)
        raise InstrumentIOError(
            "netsh output has no parsable network blocks "
            "(check tool / locale)")
    return best


def parse_netsh_interfaces(output: str, ssid: str) -> bool:
    """Check ``netsh wlan show interfaces`` output for an established
    connection to the target SSID.

    Args:
        output: Raw netsh stdout.
        ssid:   Target SSID (case-insensitive).

    Returns:
        ``True`` when the interface state is ``connected`` and the
        SSID line matches the target.
    """
    state_ok = False
    ssid_ok = False
    for line in (output or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("State") and ":" in stripped:
            state_ok = "connected" in stripped.partition(":")[2].lower()
        elif stripped.startswith("SSID") and ":" in stripped:
            value = stripped.partition(":")[2].strip()
            if value.casefold() == (ssid or "").casefold():
                ssid_ok = True
    return state_ok and ssid_ok


class WiFiRFTestDriver(InstrumentDriver):
    """Driver for the WiFi RF test via the Host PC WLAN adapter.

    The injected :class:`CommandExecutor` is the mock point; the
    default executor runs the real tools via subprocess.
    """

    MODEL = "WIFI-RF"

    def __init__(self, executor: CommandExecutor | None = None,
                 transport: Transport | None = None) -> None:
        """Create the driver.

        Args:
            executor:  Command executor to use; ``None`` builds a
                       :class:`SubprocessExecutor` (real tools).
            transport: Unused (kept for ABC uniformity).
        """
        super().__init__(transport)
        self._executor = executor
        self.address = "wlan-host"
        self._is_open = False

    # -- lifecycle -----------------------------------------------------------

    def open(self, address: str, options: dict) -> None:
        """Mark the wrapper open (adapters are host resources; no
        connection setup needed).

        Args:
            address: WLAN interface label from ``config/`` YAML
                     (informational; e.g. ``"wlan0"``).
            options: Options dict; may carry a ``"executor"`` key
                     overriding the constructor executor.

        Raises:
            InstrumentConfigError: Empty address.
        """
        self.address = self._validate_address(address)
        self.options = dict(options or {})
        if self._executor is None:
            self._executor = self.options.get("executor")
        if self._executor is None:
            self._executor = SubprocessExecutor()
        self._is_open = True

    def close(self) -> None:
        """Mark the wrapper closed.  Safe to call twice."""
        self._is_open = False

    def identify(self) -> str:
        """Return the WLAN adapter description (``netsh wlan show
        drivers``).

        Returns:
            Raw adapter description text.

        Raises:
            ConnectionLostError:    Not open.
            InstrumentTimeoutError: Tool timeout.
            InstrumentIOError:      Tool failure.
        """
        self._require_open()
        outcome = self._run(CMD_NETSH_SHOW_DRIVERS)
        return outcome.stdout

    # -- measurements ----------------------------------------------------------

    def scan(self, ssid: str, timeout_s: float = 10.0) -> MeasurementResult:
        """Scan for the target SSID and report the best RSSI.

        Args:
            ssid:     Target SSID (from YAML).
            timeout_s: Tool timeout in seconds.

        Returns:
            :class:`MeasurementResult` with the RSSI estimate in dBm;
            when the SSID was not found, ``value`` is the empty string
            (the engine / run_test verdict treats that as a failure).

        Raises:
            InstrumentConfigError: Empty SSID.
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See :meth:`_run`.
        """
        self._require_open()
        if not isinstance(ssid, str) or not ssid.strip():
            raise InstrumentConfigError("WiFiRFTestDriver: ssid required")
        outcome = self._run(CMD_NETSH_SHOW_NETWORKS, timeout_s)
        if outcome.returncode != 0:
            raise InstrumentIOError(
                f"netsh scan failed: {outcome.stderr.strip()}")
        pct = parse_netsh_networks(outcome.stdout, ssid.strip())
        if pct < 0:
            # valid scan outcome: SSID absent -> empty value; the
            # run_test verdict (engine logic) treats it as failure
            return MeasurementResult.ok("", "dBm", self.MODEL)
        return MeasurementResult.ok(
            netsh_signal_to_dbm(pct), "dBm", self.MODEL)

    def connect(self, ssid: str, password: str,
                timeout_s: float = 15.0) -> MeasurementResult:
        """Associate with the target SSID and verify the state.

        Creates a WPA2-Personal profile (the password is written to a
        temporary profile file which is deleted immediately after) and
        runs ``netsh wlan connect``.

        Args:
            ssid:      Target SSID (from YAML).
            password:  Network key (from YAML).
            timeout_s: Tool timeout in seconds.

        Returns:
            :class:`MeasurementResult` with ``value="connected"`` on
            success, empty string otherwise.

        Raises:
            InstrumentConfigError: Empty SSID.
            InstrumentIOError:     netsh reported a failure.
            ConnectionLostError / InstrumentTimeoutError: See
                                                                   :meth:`_run`.
        """
        self._require_open()
        if not isinstance(ssid, str) or not ssid.strip():
            raise InstrumentConfigError("WiFiRFTestDriver: ssid required")
        profile_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                    "w", suffix=".xml", delete=False,
                    encoding="utf-8") as handle:
                handle.write(_PROFILE_XML.format(
                    ssid=_xml_escape(ssid.strip()),
                    password=_xml_escape(password or "")))
                profile_path = handle.name
            outcome = self._run(
                ["netsh", "wlan", "add", "profile",
                 f"filename={profile_path}", "user=all"], timeout_s)
            if outcome.returncode != 0:
                raise InstrumentIOError(
                    f"netsh add profile failed: "
                    f"{outcome.stderr.strip() or outcome.stdout.strip()}")
            outcome = self._run(
                ["netsh", "wlan", "connect", f"name={ssid.strip()}"],
                timeout_s)
            if outcome.returncode != 0:
                raise InstrumentIOError(
                    f"netsh connect failed: "
                    f"{outcome.stderr.strip() or outcome.stdout.strip()}")
            verify = self._run(CMD_NETSH_SHOW_INTERFACES, timeout_s)
            connected = parse_netsh_interfaces(verify.stdout, ssid.strip())
            self._run(["netsh", "wlan", "delete",
                       f"profile={ssid.strip()}"], timeout_s)
            if connected:
                return MeasurementResult.ok("connected", "", self.MODEL)
            # association not established (valid outcome; verdict
            # logic judges it against the YAML limits)
            return MeasurementResult.ok("", "", self.MODEL)
        finally:
            if profile_path:
                try:
                    os.unlink(profile_path)
                except OSError:
                    pass

    def ping_stats(self, host: str, count: int = 4,
                   timeout_s: float = 15.0) -> tuple[float, float]:
        """Ping the DUT and parse latency + packet loss.

        Args:
            host:      Target IP address (from YAML).
            count:     Number of echo requests.
            timeout_s: Tool timeout in seconds.

        Returns:
            ``(avg_latency_ms, packet_loss_pct)`` tuple.

        Raises:
            InstrumentConfigError: Empty host or bad count.
            InstrumentIOError:     ping failed / unparsable output.
            ConnectionLostError / InstrumentTimeoutError: See
                                                           :meth:`_run`.
        """
        self._require_open()
        if not isinstance(host, str) or not host.strip():
            raise InstrumentConfigError("WiFiRFTestDriver: host required")
        if not 1 <= int(count) <= 100:
            raise InstrumentConfigError(
                f"WiFiRFTestDriver: ping count 1..100, got {count}")
        command = [part.format(count=int(count), host=host.strip())
                   for part in CMD_PING]
        outcome = self._run(command, timeout_s)
        return parse_ping_windows(outcome.stdout, int(count))

    def measure_ping(self, host: str, count: int = 4,
                     timeout_s: float = 15.0) -> MeasurementResult:
        """Measure the average ping latency to the DUT.

        Args:
            host:      Target IP address (from YAML).
            count:     Number of echo requests.
            timeout_s: Tool timeout in seconds.

        Returns:
            :class:`MeasurementResult` with the average latency in ms.

        Raises:
            InstrumentConfigError / InstrumentIOError: See
                                                       :meth:`ping_stats`.
        """
        avg, _ = self.ping_stats(host, count, timeout_s)
        return MeasurementResult.ok(avg, "ms", self.MODEL)

    def measure_packet_loss(self, host: str, count: int = 4,
                            timeout_s: float = 15.0) -> MeasurementResult:
        """Measure the packet loss towards the DUT.

        Args:
            host:      Target IP address (from YAML).
            count:     Number of echo requests.
            timeout_s: Tool timeout in seconds.

        Returns:
            :class:`MeasurementResult` with the loss percentage.

        Raises:
            InstrumentConfigError / InstrumentIOError: See
                                                       :meth:`ping_stats`.
        """
        _, loss = self.ping_stats(host, count, timeout_s)
        return MeasurementResult.ok(loss, "%", self.MODEL)

    def measure_throughput(self, host: str, seconds: int = 10,
                           timeout_s: float = 60.0) -> MeasurementResult:
        """Run the optional iperf3 throughput test.

        Args:
            host:      iperf server (DUT) address (from YAML).
            seconds:   Test duration in seconds.
            timeout_s: Tool timeout in seconds (must exceed the
                       duration).

        Returns:
            :class:`MeasurementResult` with the received throughput in
            Mbit/s.

        Raises:
            InstrumentIOError:     iperf3 missing / failed / invalid
                                   output.
            InstrumentConfigError: Bad duration.
            ConnectionLostError / InstrumentTimeoutError: See
                                                          :meth:`_run`.
        """
        self._require_open()
        if not 1 <= int(seconds) <= 300:
            raise InstrumentConfigError(
                f"WiFiRFTestDriver: iperf seconds 1..300, got {seconds}")
        command = [part.format(host=host.strip(), seconds=int(seconds))
                   for part in CMD_IPERF]
        outcome = self._run(command, timeout_s)
        if outcome.returncode != 0:
            raise InstrumentIOError(
                f"iperf3 failed: "
                f"{(outcome.stderr or outcome.stdout).strip()[:200]}")
        mbps = parse_iperf_json(outcome.stdout)
        return MeasurementResult.ok(mbps, "Mbit/s", self.MODEL)

    # -- full test --------------------------------------------------------------

    def run_test(self, config: dict) -> RFTestReport:
        """Run the full WiFi RF test sequence with a structured
        verdict.

        Phases: scan -> connect -> ping latency/loss -> optional
        iperf3.  The verdict is computed against the caller-supplied
        YAML limits; any ERROR/TIMEOUT phase makes the verdict FAIL.

        Args:
            config: ``{"ssid", "password", "target_ip",
                    "iperf_enabled", "iperf_seconds", "timeout_s",
                    "limits": {"min_rssi_dbm", "max_ping_ms",
                    "max_packet_loss_pct", "min_throughput_mbps"}}``
                    - every value from ``config/`` YAML.

        Returns:
            :class:`RFTestReport` with every phase result and the
            overall verdict.  Never raises for instrument faults:
            errors become FAIL with the failed phase recorded.
        """
        self._require_open()
        cfg = dict(config or {})
        self._validate_config(cfg)
        limits = cfg["limits"]
        timeout_s = float(cfg.get("timeout_s", 15.0))
        report = RFTestReport(verdict=Status.OK)

        def record(result: MeasurementResult,
                   passed: bool, note: str) -> None:
            report.add(result)
            if not passed and report.verdict is Status.OK:
                report.verdict = Status.FAIL
            if not passed:
                report.summary = (
                    f"{report.summary}; {note}" if report.summary
                    else note)

        try:
            scan = self.scan(cfg["ssid"], timeout_s)
            found = isinstance(scan.value, float) and \
                scan.value > -100.0
            if not found:
                record(scan, False, "SSID not found in scan")
            else:
                within_rssi = scan.value >= limits["min_rssi_dbm"]
                record(scan, within_rssi,
                       "" if within_rssi else
                       f"RSSI {scan.value} < "
                       f"{limits['min_rssi_dbm']} dBm")
                conn = self.connect(cfg["ssid"], cfg.get("password", ""),
                                    timeout_s)
                record(conn, conn.value == "connected",
                       "association failed")
        except InstrumentError as exc:
            record(MeasurementResult.failed("", "", self.MODEL,
                                            Status.ERROR),
                   False, f"RF phase error: {exc}")
            report.summary = f"WiFi test: {report.summary or 'failed'}"
            return report

        if report.verdict is Status.FAIL:
            # scan / association already failed -> skip traffic phases
            report.summary = f"WiFi test: {report.summary or 'failed'}"
            return report

        try:
            avg, loss = self.ping_stats(cfg["target_ip"], 4, timeout_s)
            record(MeasurementResult.ok(avg, "ms", self.MODEL),
                   avg <= limits["max_ping_ms"],
                   f"ping {avg} ms > {limits['max_ping_ms']}")
            record(MeasurementResult.ok(loss, "%", self.MODEL),
                   loss <= limits["max_packet_loss_pct"],
                   f"loss {loss}% > {limits['max_packet_loss_pct']}")
            if cfg.get("iperf_enabled"):
                tput = self.measure_throughput(
                    cfg["target_ip"],
                    int(cfg.get("iperf_seconds", 10)), timeout_s)
                record(tput,
                       tput.value >= limits["min_throughput_mbps"],
                       f"throughput {tput.value} < "
                       f"{limits['min_throughput_mbps']} Mbit/s")
        except InstrumentError as exc:
            record(MeasurementResult.failed("", "", self.MODEL,
                                            Status.ERROR),
                   False, f"traffic phase error: {exc}")
        if report.verdict is Status.OK and not report.summary:
            report.summary = "WiFi test: all phases within limits"
        else:
            report.summary = f"WiFi test: {report.summary}"
        return report

    # -- helpers ---------------------------------------------------------------

    def _run(self, command: list[str], timeout_s: float = 10.0):
        """Execute one tool command through the injected executor.

        Args:
            command:   Argument list.
            timeout_s: Timeout in seconds.

        Returns:
            The :class:`CommandOutcome`.

        Raises:
            InstrumentTimeoutError: Tool timeout.
            InstrumentIOError:      Tool could not run.
            ConnectionLostError:    Wrapper not open.
        """
        self._require_open()
        return self._executor.run(command, timeout_s)

    @staticmethod
    def _validate_config(cfg: dict) -> None:
        """Validate the run_test configuration keys.

        Args:
            cfg: Config dict from the caller.

        Raises:
            InstrumentConfigError: Missing keys or limits.
        """
        missing = [k for k in _REQUIRED_KEYS if k not in cfg]
        if missing:
            raise InstrumentConfigError(
                f"WiFiRFTestDriver: missing config keys {missing} "
                f"(supply from config/ YAML)")
        limits = cfg.get("limits") or {}
        missing = [k for k in _REQUIRED_LIMITS if k not in limits]
        if missing:
            raise InstrumentConfigError(
                f"WiFiRFTestDriver: missing limit keys {missing} "
                f"(supply from config/ YAML)")

    def _require_open(self) -> None:
        """Guard operations behind an open wrapper.

        Raises:
            ConnectionLostError: The wrapper is not open.
        """
        if not self._is_open:
            raise ConnectionLostError(
                "WiFiRFTestDriver: not open "
                "(call open(address, options) first)")


def _xml_escape(text: str) -> str:
    """Escape a string for embedding into the WLAN profile XML.

    Args:
        text: Raw SSID or passphrase.

    Returns:
        XML-escaped text.
    """
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
