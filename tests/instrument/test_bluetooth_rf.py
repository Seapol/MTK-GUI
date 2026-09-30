# -*- coding: utf-8 -*-
"""Unit tests for the Bluetooth (Classic + BLE) RF test wrapper
(scripted executor mocks the Windows PowerShell + WinRT probes)."""

from __future__ import annotations

import pytest

from mtkgui.drivers.base import Status
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentIOError,
    InstrumentTimeoutError,
)
from mtkgui.drivers.bluetooth_rf import (
    BluetoothRFTestDriver,
    normalize_mac,
)
from mtkgui.drivers.rf_common import CommandExecutor, CommandOutcome

ADDR = "bt-host"  # example address as it would come from config/ YAML

DUT_MAC = "AA:BB:CC:DD:EE:FF"

WATCH_HIT = "AABBCCDDEEFF -55\n112233445566 -70\n"
WATCH_WEAK = "AABBCCDDEEFF -85\n"
WATCH_MISS = "112233445566 -70\n"
CONNECT_OK = "CONNECT=Connected"
CONNECT_FAIL = "CONNECT=FAIL"
PER_OK = "ATTEMPTS=20\nFAILURES=1\n"
PER_BAD = "ATTEMPTS=20\nFAILURES=5\n"


class ContentExecutor(CommandExecutor):
    """Executor that selects the outcome by matching the joined
    command text (the PowerShell script content distinguishes the
    watch / connect / PER probes)."""

    def __init__(self, rules: list[tuple[str, CommandOutcome | Exception]],
                 default: CommandOutcome | Exception | None = None) -> None:
        """Create the executor.

        Args:
            rules:   ``(substring, outcome)`` pairs, first match wins.
            default: Outcome when nothing matches.
        """
        self.rules = list(rules)
        self.default = default
        self.history: list[str] = []

    def run(self, command: list[str], timeout_s: float) -> CommandOutcome:
        """Return the first matching rule's outcome.

        Args:
            command:   Argument list (joined for content matching).
            timeout_s: Ignored (scripted).

        Returns:
            The matched :class:`CommandOutcome`.

        Raises:
            InstrumentIOError: Nothing matched and no default.
            (as scripted):     The scripted exception, re-raised.
        """
        joined = " ".join(command)
        self.history.append(joined)
        for needle, outcome in self.rules:
            if needle in joined:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        if isinstance(self.default, Exception):
            raise self.default
        if self.default is None:
            raise InstrumentIOError(
                f"ContentExecutor: no rule for {joined[:80]!r}")
        return self.default


def make_bt(rules: list[tuple[str, CommandOutcome | Exception]]) -> (
        BluetoothRFTestDriver):
    """Return an open BT wrapper over a content-matching executor."""
    driver = BluetoothRFTestDriver(executor=ContentExecutor(rules))
    driver.open(ADDR, {})
    return driver


def bt_config(**overrides) -> dict:
    """Return a valid run_test config (as the engine would build from
    config/ YAML); overrides patch top-level keys."""
    cfg = {
        "bt_type": "ble", "mac": DUT_MAC, "per_attempts": 20,
        "timeout_s": 15.0,
        "limits": {"min_rssi_dbm": -80.0, "max_per_pct": 10.0},
    }
    cfg.update(overrides)
    return cfg


def pass_rules() -> list[tuple[str, CommandOutcome | Exception]]:
    """Rules for a healthy BLE test run."""
    return [
        ("AdvertisementWatcher",
         CommandOutcome(["powershell"], 0, WATCH_HIT, "")),
        ("BluetoothLEDevice",
         CommandOutcome(["powershell"], 0, CONNECT_OK, "")),
        ("FAILURES=", CommandOutcome(["powershell"], 0, PER_OK, "")),
    ]


# ---------------------------------------------------------------------------
# helpers / config validation
# ---------------------------------------------------------------------------


def test_normalize_mac():
    """MAC addresses are normalized to 12 uppercase hex digits."""
    assert normalize_mac("AA:BB:CC:DD:EE:FF") == "AABBCCDDEEFF"
    assert normalize_mac("aa-bb-cc-dd-ee-ff") == "AABBCCDDEEFF"
    assert normalize_mac("aabbccddeeff") == "AABBCCDDEEFF"


@pytest.mark.parametrize("bad", ["", "AA:BB:CC", "ZZ:BB:CC:DD:EE:FF",
                                 "AA:BB:CC:DD:EE:FF:00"])
def test_normalize_mac_rejects_invalid(bad):
    """Malformed MAC addresses are config errors."""
    with pytest.raises(InstrumentConfigError):
        normalize_mac(bad)


def test_run_test_rejects_bad_bt_type():
    """An unknown bt_type is a config error."""
    driver = make_bt([])
    with pytest.raises(InstrumentConfigError):
        driver.run_test(bt_config(bt_type="wifi"))


def test_run_test_rejects_missing_limits():
    """Missing YAML limit keys raise InstrumentConfigError."""
    driver = make_bt([])
    with pytest.raises(InstrumentConfigError):
        driver.run_test(bt_config(limits={"min_rssi_dbm": -80}))


def test_measure_per_rejects_bad_attempts():
    """PER attempt counts outside 1..1000 are config errors."""
    driver = make_bt(pass_rules())
    with pytest.raises(InstrumentConfigError):
        driver.measure_per(DUT_MAC, attempts=0)


# ---------------------------------------------------------------------------
# PASS / FAIL cases
# ---------------------------------------------------------------------------


def test_run_test_pass_case_ble():
    """Healthy BLE DUT: discover + connect + PER within limits."""
    driver = make_bt(pass_rules())
    report = driver.run_test(bt_config())
    assert report.verdict is Status.OK
    units = [r.unit for r in report.results]
    assert units == ["dBm", "", "%"]
    assert report.results[0].value == pytest.approx(-55.0)
    assert report.results[1].value == "Connected"
    assert report.results[2].value == pytest.approx(5.0)
    assert "within limits" in report.summary


def test_run_test_classic_uses_classic_connect():
    """bt_type=classic issues the Classic BT connect probe."""
    driver = make_bt(
        [("AdvertisementWatcher",
          CommandOutcome(["powershell"], 0, WATCH_HIT, "")),
         ("BluetoothDevice]::FromBluetoothAddressAsync",
          CommandOutcome(["powershell"], 0, CONNECT_OK, "")),
         ("FAILURES=", CommandOutcome(["powershell"], 0, PER_OK, ""))])
    report = driver.run_test(bt_config(bt_type="classic"))
    assert report.verdict is Status.OK
    connect_calls = [c for c in driver._executor.history
                     if "BluetoothDevice]::FromBluetoothAddressAsync" in c]
    assert connect_calls, "classic connect probe was not issued"


def test_run_test_fail_low_rssi():
    """A weak DUT advertisement -> verdict FAIL."""
    driver = make_bt(
        [("AdvertisementWatcher",
          CommandOutcome(["powershell"], 0, WATCH_WEAK, ""))])
    report = driver.run_test(bt_config())
    assert report.verdict is Status.FAIL
    assert "RSSI" in report.summary


def test_run_test_fail_not_discovered():
    """A missing DUT advertisement -> verdict FAIL."""
    driver = make_bt(
        [("AdvertisementWatcher",
          CommandOutcome(["powershell"], 0, WATCH_MISS, ""))])
    report = driver.run_test(bt_config())
    assert report.verdict is Status.FAIL
    assert "not discovered" in report.summary


def test_run_test_fail_per_too_high():
    """PER above the YAML limit -> verdict FAIL."""
    driver = make_bt(
        pass_rules()[:2] +
        [("FAILURES=", CommandOutcome(["powershell"], 0, PER_BAD, ""))])
    report = driver.run_test(bt_config())
    assert report.verdict is Status.FAIL
    assert "PER" in report.summary


def test_run_test_fail_connect_refused():
    """A refused connection -> verdict FAIL, PER phase skipped."""
    driver = make_bt(
        [("AdvertisementWatcher",
          CommandOutcome(["powershell"], 0, WATCH_HIT, "")),
         ("BluetoothLEDevice",
          CommandOutcome(["powershell"], 0, CONNECT_FAIL, ""))])
    report = driver.run_test(bt_config())
    assert report.verdict is Status.FAIL
    assert "connection not established" in report.summary
    assert len(report.results) == 2  # no PER phase after failed connect


# ---------------------------------------------------------------------------
# timeout / exception cases
# ---------------------------------------------------------------------------


def test_run_test_discover_timeout():
    """A discovery timeout becomes a recorded error phase -> FAIL."""
    driver = make_bt(
        [("AdvertisementWatcher", InstrumentTimeoutError("timed out"))])
    report = driver.run_test(bt_config())
    assert report.verdict is Status.FAIL
    assert report.results[-1].status is Status.ERROR
    assert "error" in report.summary.lower()


def test_discover_propagates_timeout():
    """Direct measure calls raise InstrumentTimeoutError for the
    engine to classify."""
    driver = make_bt(
        [("AdvertisementWatcher", InstrumentTimeoutError("timed out"))])
    with pytest.raises(InstrumentTimeoutError):
        driver.discover(DUT_MAC)


def test_run_test_connect_io_error():
    """A failing connect probe records an ERROR phase -> FAIL."""
    driver = make_bt(
        [("AdvertisementWatcher",
          CommandOutcome(["powershell"], 0, WATCH_HIT, "")),
         ("BluetoothLEDevice", InstrumentIOError("probe crashed"))])
    report = driver.run_test(bt_config())
    assert report.verdict is Status.FAIL
    assert "RF phase error" in report.summary


def test_discover_unparsable_output():
    """A probe stdout without parsable MAC lines yields an empty
    value (not an exception)."""
    driver = make_bt(
        [("AdvertisementWatcher",
          CommandOutcome(["powershell"], 0, "garbage output", ""))])
    result = driver.discover(DUT_MAC)
    assert result.value == ""


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


def test_not_open_guard():
    """Operations before open() raise ConnectionLostError."""
    driver = BluetoothRFTestDriver(executor=ContentExecutor([], default=None))
    with pytest.raises(ConnectionLostError):
        driver.discover(DUT_MAC)
    with pytest.raises(ConnectionLostError):
        driver.run_test(bt_config())


def test_close_is_idempotent():
    """close() can be called twice safely."""
    driver = make_bt(pass_rules())
    driver.close()
    assert not driver._is_open
    driver.close()
