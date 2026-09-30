# -*- coding: utf-8 -*-
"""Unit tests for the SEGGER J-Link driver (mocked transport)."""

from __future__ import annotations

import pytest

from mtkgui.drivers.base import Status
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentIOError,
    InstrumentTimeoutError,
)
from mtkgui.drivers.jlink import JLinkDriver, JLinkTransport

BANNER = (
    "SEGGER J-Link Commander V7.88 (Compile time: Jan  1 2026)",
    "DLL version V7.88, compiled Jan  1 2026",
)


class MockJLink(JLinkTransport):
    """In-memory stand-in for the interactive J-Link Commander process.

    Overrides the process-level methods (open/_read_until_prompt) while
    keeping the real Transport bookkeeping of JLinkTransport.
    """

    def __init__(self, replies: dict[str, str] | None = None) -> None:
        self.replies = dict(replies or {})
        self.written: list[str] = []
        self.closed = False
        self._banner = "\n".join(BANNER)
        self._is_open = False

    def open(self, address: str, options: dict) -> None:
        self.address = address
        self.options = dict(options or {})
        self._is_open = True

    def close(self) -> None:
        self.closed = True
        self._is_open = False

    def write(self, command: str) -> None:
        if not self._is_open:
            raise ConnectionLostError("MockJLink: not open")
        self.written.append(command)

    def query(self, command: str) -> str:
        self.write(command)
        if command in self.replies:
            return self.replies[command]
        return f"{command} returns O.K."

    def identify(self) -> str:
        if not self._is_open:
            raise ConnectionLostError("MockJLink: not open")
        return self._banner


@pytest.fixture
def jlink() -> JLinkDriver:
    """Return a JLinkDriver over an in-memory J-Link stand-in."""
    transport = MockJLink()
    driver = JLinkDriver(transport=transport)
    driver.open("JLinkExe", {"device": "MIMXRT700xxxxx"})
    return driver


def test_open_options_are_forwarded():
    """open() stores address/options from the caller (YAML values)."""
    transport = MockJLink()
    driver = JLinkDriver(transport=transport)
    driver.open("C:/SEGGER/JLink.exe", {
        "device": "MIMXRT700xxxxx", "interface": "SWD", "speed_khz": 1000,
    })
    assert driver.address == "C:/SEGGER/JLink.exe"
    assert driver.options["device"] == "MIMXRT700xxxxx"
    assert driver.options["interface"] == "SWD"


def test_open_requires_device():
    """open() without a device option is a config error."""
    driver = JLinkDriver(transport=MockJLink())
    with pytest.raises(InstrumentConfigError):
        driver.open("JLinkExe", {})


def test_open_rejects_bad_interface():
    """open() rejects interfaces other than SWD/JTAG (UM0801 set)."""
    driver = JLinkDriver(transport=MockJLink())
    with pytest.raises(InstrumentConfigError):
        driver.open("JLinkExe", {"device": "X", "interface": "USB"})


def test_flash_happy_path(jlink):
    """flash_firmware sends loadfile / verifyfile / r / g in order."""
    result = jlink.flash_firmware("/tmp/fat.bin")
    assert jlink._transport.written == [
        "loadfile /tmp/fat.bin",
        "verifyfile /tmp/fat.bin",
        "r",
        "g",
    ]
    assert result.status is Status.OK
    assert result.source == "JLINK"


def test_flash_without_verify_or_run(jlink):
    """With verify/reset disabled only loadfile is sent."""
    jlink.flash_firmware("/tmp/fat.bin", verify=False, reset_and_run=False)
    assert jlink._transport.written == ["loadfile /tmp/fat.bin"]


def test_flash_with_erase(jlink):
    """With erase enabled the erase command precedes loadfile."""
    jlink.flash_firmware("/tmp/fat.bin", verify=False, reset_and_run=False,
                         erase=True)
    assert jlink._transport.written == ["erase", "loadfile /tmp/fat.bin"]


def test_flash_reports_error_output(jlink):
    """An 'Error' marker in the tool output raises InstrumentIOError."""
    jlink._transport.replies["loadfile /tmp/fat.bin"] = \
        "Cannot load file: Error while parsing"
    with pytest.raises(InstrumentIOError):
        jlink.flash_firmware("/tmp/fat.bin")


def test_flash_reports_connect_failure(jlink):
    """A 'Cannot connect' marker during load raises InstrumentIOError."""
    jlink._transport.replies["loadfile /tmp/fat.bin"] = \
        "Cannot connect to target"
    with pytest.raises(InstrumentIOError):
        jlink.flash_firmware("/tmp/fat.bin")


def test_flash_requires_firmware_path(jlink):
    """An empty firmware path is a config error."""
    with pytest.raises(InstrumentConfigError):
        jlink.flash_firmware("  ")


def test_flash_before_open_raises():
    """flash_firmware before open() raises ConnectionLostError."""
    driver = JLinkDriver(transport=MockJLink())
    with pytest.raises(ConnectionLostError):
        driver.flash_firmware("/tmp/fat.bin")


def test_identify_returns_banner(jlink):
    """identify() returns the J-Link DLL banner from the session."""
    banner = jlink.identify()
    assert "J-Link" in banner
    assert "DLL version" in banner


def test_timeout_propagates(jlink):
    """A transport timeout surfaces as InstrumentTimeoutError."""
    def raise_timeout(command: str) -> str:
        raise InstrumentTimeoutError("no prompt")

    jlink._transport.query = raise_timeout  # type: ignore[method-assign]
    with pytest.raises(InstrumentTimeoutError):
        jlink.flash_firmware("/tmp/fat.bin")


def test_close_sends_qc(jlink):
    """close() terminates the session exactly once."""
    jlink.close()
    assert jlink._transport.closed is True
    assert not jlink.is_open
    jlink.close()  # idempotent


def test_real_transport_rejects_empty_address():
    """JLinkTransport.open validates the executable path and device."""
    transport = JLinkTransport()
    with pytest.raises(InstrumentConfigError):
        transport.open("", {"device": "X"})
    with pytest.raises(InstrumentConfigError):
        transport.open("JLinkExe", {})
    with pytest.raises(ConnectionLostError):
        transport.open("definitely-not-a-tool-xyz", {"device": "X"})
