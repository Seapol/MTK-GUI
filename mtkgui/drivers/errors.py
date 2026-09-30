# -*- coding: utf-8 -*-
"""Shared exception types for the instrument driver module.

Location fixed by docs/interface_spec.md section 1.3: these types are
importable cross-module from ``mtkgui.drivers.errors``.  Every driver
raises (or reports through ``MeasurementResult.status``) these errors
instead of leaking transport-specific exceptions to the engine.
"""

from __future__ import annotations


class InstrumentError(Exception):
    """Base class for all instrument faults."""

    pass


class InstrumentTimeoutError(InstrumentError):
    """The instrument did not answer within the configured timeout."""

    pass


class InstrumentIOError(InstrumentError):
    """Serial / GPIB / USB / process I/O failure while talking to an
    instrument."""

    pass


class InstrumentConfigError(InstrumentError):
    """Bad or missing driver configuration (e.g. YAML parameters)."""

    pass


class ConnectionLostError(InstrumentError):
    """The connection to the instrument was lost or was never
    established."""

    pass
