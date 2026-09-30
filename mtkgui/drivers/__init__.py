# -*- coding: utf-8 -*-
"""Instrument driver package for the MTK production test station.

This package implements the Instrument Driver Module contract defined in
docs/interface_spec.md (section 2).  It provides:

* shared exception types (``mtkgui.drivers.errors``) - importable by any
  module; the location is fixed by interface_spec.md section 1.3,
* the abstract base driver and result model (``mtkgui.drivers.base``),
* concrete drivers for the station instruments:
  - ``DAQ973ADriver``   - Keysight DAQ973A mainframe with DAQM908A
                          multiplexers (2-wire OHM / DCV) and the
                          DAQM907A multifunction module (totalizer, AO,
                          open-drain DIO),
  - ``N5747ADriver``    - Keysight N5747A 60 V / 12.5 A system PSU,
  - ``U2355ADriver``    - Keysight U2355A USB DAQ (12 AI, 2 counters,
                          24 DIO),
  - ``JLinkDriver``     - SEGGER J-Link flash via J-Link Commander.

Every driver talks to its instrument exclusively through a
``Transport`` object.  The transport is an injection point: tests pass
a mocked transport, the engine passes a real one (serial today, VISA /
LAN later).  Instrument addresses are never hardcoded in this package;
they are supplied by the caller which reads them from the ``config/``
YAML equipment section (.traerules section 4).

Drivers report measurement facts only (OK / ERROR / TIMEOUT status).
PASS/FAIL limit decisions belong to the test flow engine, never to a
driver.
"""

from mtkgui.drivers.base import (
    InstrumentDriver,
    MeasurementResult,
    Status,
    Transport,
    parse_float,
)
from mtkgui.drivers.bluetooth_rf import BluetoothRFTestDriver
from mtkgui.drivers.daq973a import DAQ973ADriver
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentError,
    InstrumentIOError,
    InstrumentTimeoutError,
)
from mtkgui.drivers.jlink import JLinkDriver, JLinkTransport
from mtkgui.drivers.n5747a import N5747ADriver
from mtkgui.drivers.rf_common import (
    CommandExecutor,
    RFTestReport,
    ScriptedExecutor,
    SubprocessExecutor,
)
from mtkgui.drivers.transport_serial import SerialTransport
from mtkgui.drivers.transport_ssh import SSHTransport
from mtkgui.drivers.u2355a import U2355ADriver
from mtkgui.drivers.wifi_rf import WiFiRFTestDriver

__all__ = [
    "BluetoothRFTestDriver",
    "CommandExecutor",
    "ConnectionLostError",
    "DAQ973ADriver",
    "InstrumentConfigError",
    "InstrumentDriver",
    "InstrumentError",
    "InstrumentIOError",
    "InstrumentTimeoutError",
    "JLinkDriver",
    "JLinkTransport",
    "MeasurementResult",
    "N5747ADriver",
    "RFTestReport",
    "ScriptedExecutor",
    "SerialTransport",
    "SSHTransport",
    "Status",
    "SubprocessExecutor",
    "Transport",
    "U2355ADriver",
    "WiFiRFTestDriver",
    "parse_float",
]
