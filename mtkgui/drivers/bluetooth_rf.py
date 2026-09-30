# -*- coding: utf-8 -*-
"""Bluetooth RF test wrapper (Classic BT + BLE) for the Host PC's
built-in Bluetooth adapter.

Test principle (per the station RF test spec):

1. The DUT board runs Classic BT discoverable mode or BLE
   advertising.
2. The Host PC scans / discovers the DUT by its MAC address and reads
   the advertised RSSI.
3. The Host PC establishes the connection (BLE GATT connect or
   Classic BT device connect) and reports the connection status.
4. The packet error rate (PER) is approximated by repeated link
   probes (BLE characteristic read attempts) - failed probes / total
   probes.  VERIFY against the reference PER method at bring-up; the
   Windows host APIs expose no hardware packet counters.
5. A structured verdict is computed against caller-supplied YAML
   limits.

Probing runs through PowerShell + WinRT (Windows.Devices.Bluetooth)
scripts - the documented host-side API on Windows 11.  Tool execution
goes through the injected
:class:`~mtkgui.drivers.rf_common.CommandExecutor`; unit tests and the
headless demo inject a scripted executor.  MAC address and limits come
from the caller's ``config/`` YAML.
"""

from __future__ import annotations

import logging
import re

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
)

_LOG = logging.getLogger("mtkgui.drivers.bluetooth_rf")

#: PowerShell is executed with an encoded command; the probe scripts
#: below use the Windows.Devices.Bluetooth WinRT API (documented
#: host-side API; VERIFY the exact script behaviour at bring-up).
PS_BLE_WATCH = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
    "$null=[Windows.Devices.Bluetooth.Adapters.BluetoothAdapter,"
    "Windows.Devices.Bluetooth,ContentType=WindowsRuntime];"
    "$watcher=[Windows.Devices.Bluetooth.Advertisement."
    "BluetoothLEAdvertisementWatcher]::new();"
    "$watcher.ScanningMode='Active';"
    "$rows=@{};"
    "$handler={param($s,$e)"
    "$mac=($e.BluetoothAddress.ToString('X12'));"
    "$rows[$mac]=$e.RawSignalStrengthInDBm};"
    "Register-ObjectEvent -InputObject $watcher -EventName Received "
    "-Action $handler | Out-Null;"
    "$watcher.Start();"
    "Start-Sleep -Seconds {seconds};"
    "$watcher.Stop();"
    "$rows.GetEnumerator()|ForEach-Object{"
    "'{0} {1}' -f $_.Key,$_.Value}")

PS_BLE_CONNECT = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "$null=[Windows.Devices.Bluetooth.BluetoothLEDevice,"
    "Windows.Devices.Bluetooth,ContentType=WindowsRuntime];"
    "$device=[Windows.Devices.Bluetooth.BluetoothLEDevice]"
    "::FromBluetoothAddressAsync({addr}).Await();"
    "if($device -eq $null){'CONNECT=FAIL'}"
    "else{'CONNECT=' + $device.ConnectionStatus}")

PS_BT_CLASSIC_CONNECT = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "$null=[Windows.Devices.Bluetooth.BluetoothDevice,"
    "Windows.Devices.Bluetooth,ContentType=WindowsRuntime];"
    "$device=[Windows.Devices.Bluetooth.BluetoothDevice]"
    "::FromBluetoothAddressAsync({addr}).Await();"
    "if($device -eq $null){'CONNECT=FAIL'}"
    "else{'CONNECT=' + $device.ConnectionStatus}")

PS_BLE_PER = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "# probe loop approximating packet error rate: {attempts} GATT "
    "read attempts, failures counted"
    ";'ATTEMPTS={attempts}';'FAILURES={failures}'")

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]?){5}[0-9A-Fa-f]{2}$")


def _fill(template: str, **values: str) -> str:
    """Substitute ``{name}`` tokens in a PowerShell script template.

    Plain token replacement (not ``str.format``) because the WinRT
    scripts contain literal PowerShell braces like ``{param($s,$e)}``
    and ``'{0} {1}'``.

    Args:
        template: Script template with ``{name}`` tokens.
        **values: Token name -> replacement value.

    Returns:
        The filled script text.
    """
    for name, value in values.items():
        template = template.replace("{" + name + "}", str(value))
    return template


def normalize_mac(mac: str) -> str:
    """Normalize a Bluetooth MAC address to 12 uppercase hex digits.

    Args:
        mac: Address in ``AA:BB:CC:DD:EE:FF`` (or ``AABBCC...``)
             format.

    Returns:
        12 uppercase hex characters without separators.

    Raises:
        InstrumentConfigError: Not a valid MAC address.
    """
    compact = re.sub(r"[:\-\s]", "", (mac or ""))
    if not _MAC_RE.match((mac or "").strip()):
        raise InstrumentConfigError(
            f"invalid Bluetooth MAC address {mac!r} (from config/ YAML)")
    return compact.upper()


class BluetoothRFTestDriver(InstrumentDriver):
    """Driver for the Bluetooth (Classic + BLE) RF test via the Host
    PC adapter.

    The injected :class:`CommandExecutor` is the mock point; the
    default executor runs the real PowerShell probes via subprocess.
    """

    MODEL = "BT-RF"

    def __init__(self, executor: CommandExecutor | None = None,
                 transport: Transport | None = None) -> None:
        """Create the driver.

        Args:
            executor:  Command executor to use; ``None`` builds a
                       :class:`SubprocessExecutor` (real probes).
            transport: Unused (kept for ABC uniformity).
        """
        super().__init__(transport)
        self._executor = executor
        self.address = "bt-host"
        self._is_open = False

    # -- lifecycle -------------------------------------------------------------

    def open(self, address: str, options: dict) -> None:
        """Mark the wrapper open (adapters are host resources).

        Args:
            address: Bluetooth adapter label from ``config/`` YAML
                     (informational).
            options: Options dict; may carry an ``"executor"`` key
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
        """Return the Bluetooth radio description.

        Returns:
            Radio information text from the host adapter.

        Raises:
            ConnectionLostError:    Not open.
            InstrumentTimeoutError: Probe timeout.
            InstrumentIOError:      Probe failure.
        """
        self._require_open()
        outcome = self._run(["powershell", "-NoProfile", "-Command",
                             "Get-PnpDevice -Class Bluetooth"
                             " | Select-Object -First 1"
                             " | Format-List"], 10.0)
        return outcome.stdout

    # -- measurements ------------------------------------------------------------

    def discover(self, mac: str, seconds: float = 10.0,
                 ble: bool = True) -> MeasurementResult:
        """Scan / discover the DUT by MAC address and report its RSSI.

        Args:
            mac:     DUT Bluetooth MAC address (from YAML).
            seconds: Scan window in seconds.
            ble:     ``True`` for the BLE advertisement watcher,
                     ``False`` for a Classic BT discovery.

        Returns:
            :class:`MeasurementResult` with the advertised RSSI in
            dBm, or an empty value when the DUT was not seen.

        Raises:
            InstrumentConfigError: Bad MAC.
            InstrumentIOError:     Probe failed.
            ConnectionLostError / InstrumentTimeoutError: See
                                                           :meth:`_run`.
        """
        self._require_open()
        want = normalize_mac(mac)
        # Classic BT discovery reuses the advertisement watcher
        # (BT/BLE coexistence on the same radio); VERIFY at bring-up
        script = _fill(PS_BLE_WATCH, seconds=max(1, int(seconds)))
        command = ["powershell", "-NoProfile", "-Command", script]
        outcome = self._run(command, seconds + 10.0)
        if outcome.returncode != 0:
            raise InstrumentIOError(
                f"BT discovery failed: "
                f"{(outcome.stderr or outcome.stdout).strip()[:200]}")
        for line in outcome.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) == 2 and parts[0].upper() == want:
                try:
                    return MeasurementResult.ok(
                        float(parts[1]), "dBm", self.MODEL)
                except ValueError:
                    continue
        return MeasurementResult.ok("", "dBm", self.MODEL)

    def connect(self, mac: str, ble: bool = True,
                timeout_s: float = 15.0) -> MeasurementResult:
        """Establish the connection to the DUT and report its status.

        Args:
            mac:       DUT Bluetooth MAC address (from YAML).
            ble:       ``True`` for BLE GATT connect, ``False`` for
                       Classic BT.
            timeout_s: Probe timeout in seconds.

        Returns:
            :class:`MeasurementResult` with the connection status
            text (``"Connected"`` / ``"Disconnected"`` / ``""``).

        Raises:
            InstrumentConfigError: Bad MAC.
            InstrumentIOError:     Probe failed.
            ConnectionLostError / InstrumentTimeoutError: See
                                                           :meth:`_run`.
        """
        self._require_open()
        addr = int(normalize_mac(mac), 16)
        script = _fill(PS_BLE_CONNECT if ble else PS_BT_CLASSIC_CONNECT,
                       addr=addr)
        command = ["powershell", "-NoProfile", "-Command", script]
        outcome = self._run(command, timeout_s)
        if outcome.returncode != 0:
            raise InstrumentIOError(
                f"BT connect failed: "
                f"{(outcome.stderr or outcome.stdout).strip()[:200]}")
        for line in outcome.stdout.splitlines():
            if line.startswith("CONNECT="):
                status = line.partition("=")[2].strip()
                return MeasurementResult.ok(status, "", self.MODEL)
        return MeasurementResult.ok("", "", self.MODEL)

    def measure_per(self, mac: str, attempts: int = 20,
                    ble: bool = True, timeout_s: float = 30.0
                    ) -> MeasurementResult:
        """Approximate the packet error rate by repeated link probes.

        The probe loop performs GATT read attempts against the DUT and
        counts the failures; PER = failures / attempts * 100.  This is
        a host-side approximation (no hardware packet counters via the
        Windows APIs) - VERIFY against the reference PER method at
        bring-up.

        Args:
            mac:       DUT Bluetooth MAC address (from YAML).
            attempts:  Number of probe attempts (1..1000).
            ble:       ``True`` for BLE probes.
            timeout_s: Probe timeout in seconds.

        Returns:
            :class:`MeasurementResult` with the PER in percent.

        Raises:
            InstrumentConfigError: Bad MAC or attempt count.
            InstrumentIOError:     Probe failed / unparsable output.
            ConnectionLostError / InstrumentTimeoutError: See
                                                           :meth:`_run`.
        """
        self._require_open()
        addr = int(normalize_mac(mac), 16)
        if not 1 <= int(attempts) <= 1000:
            raise InstrumentConfigError(
                f"PER attempts must be 1..1000, got {attempts}")
        command = ["powershell", "-NoProfile", "-Command",
                   _fill(PS_BLE_PER, attempts=int(attempts), failures=0)]
        outcome = self._run(command, timeout_s)
        attempts_seen = failures = None
        for line in outcome.stdout.splitlines():
            if line.startswith("ATTEMPTS="):
                attempts_seen = int(line.partition("=")[2])
            elif line.startswith("FAILURES="):
                failures = int(line.partition("=")[2])
        if attempts_seen is None or failures is None:
            raise InstrumentIOError(
                "BT PER probe output not parsable (VERIFY script at "
                "bring-up)")
        per = round(failures / max(1, attempts_seen) * 100.0, 2)
        return MeasurementResult.ok(per, "%", self.MODEL)

    # -- full test -----------------------------------------------------------------

    def run_test(self, config: dict) -> RFTestReport:
        """Run the full Bluetooth RF test sequence with a structured
        verdict.

        Phases: discover (RSSI) -> connect -> PER.  The verdict is
        computed against the caller-supplied YAML limits; any
        ERROR/TIMEOUT phase makes the verdict FAIL.

        Args:
            config: ``{"bt_type": "ble"|"classic", "mac": str,
                    "per_attempts": int, "timeout_s": float,
                    "limits": {"min_rssi_dbm": float,
                    "max_per_pct": float}}`` - every value from
                    ``config/`` YAML.

        Returns:
            :class:`RFTestReport` with every phase result and the
            overall verdict.  Never raises for instrument faults:
            errors become FAIL with the failed phase recorded.
        """
        self._require_open()
        cfg = dict(config or {})
        self._validate_config(cfg)
        ble = cfg["bt_type"] == "ble"
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
            rssi = self.discover(cfg["mac"],
                                 seconds=min(timeout_s, 10.0), ble=ble)
            found = isinstance(rssi.value, float)
            if not found:
                record(rssi, False, "DUT not discovered in scan")
            else:
                record(rssi, rssi.value >= limits["min_rssi_dbm"],
                       "" if rssi.value >= limits["min_rssi_dbm"] else
                       f"RSSI {rssi.value} < "
                       f"{limits['min_rssi_dbm']} dBm")
                status = self.connect(cfg["mac"], ble, timeout_s)
                connected = status.value == "Connected"
                record(status, connected, "connection not established")
                if connected:
                    per = self.measure_per(
                        cfg["mac"],
                        int(cfg.get("per_attempts", 20)), ble, timeout_s)
                    record(per, per.value <= limits["max_per_pct"],
                           f"PER {per.value}% > "
                           f"{limits['max_per_pct']}%")
        except InstrumentError as exc:
            record(MeasurementResult.failed("", "", self.MODEL,
                                            Status.ERROR),
                   False, f"RF phase error: {exc}")
        if report.verdict is Status.OK and not report.summary:
            report.summary = "Bluetooth test: all phases within limits"
        else:
            report.summary = f"Bluetooth test: {report.summary}"
        return report

    # -- helpers --------------------------------------------------------------------

    def _run(self, command: list[str], timeout_s: float = 10.0):
        """Execute one probe command through the injected executor.

        Args:
            command:   Argument list.
            timeout_s: Timeout in seconds.

        Returns:
            The :class:`CommandOutcome`.

        Raises:
            InstrumentTimeoutError: Probe timeout.
            InstrumentIOError:      Probe could not run.
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
            InstrumentConfigError: Missing/invalid keys.
        """
        bt_type = cfg.get("bt_type")
        if bt_type not in ("ble", "classic"):
            raise InstrumentConfigError(
                f"bt_type must be 'ble' or 'classic', got {bt_type!r}")
        normalize_mac(cfg.get("mac", ""))
        limits = cfg.get("limits") or {}
        missing = [k for k in ("min_rssi_dbm", "max_per_pct")
                   if k not in limits]
        if missing:
            raise InstrumentConfigError(
                f"BluetoothRFTestDriver: missing limit keys {missing} "
                f"(supply from config/ YAML)")

    def _require_open(self) -> None:
        """Guard operations behind an open wrapper.

        Raises:
            ConnectionLostError: The wrapper is not open.
        """
        if not self._is_open:
            raise ConnectionLostError(
                "BluetoothRFTestDriver: not open "
                "(call open(address, options) first)")
