# -*- coding: utf-8 -*-
"""Shared instrument status hub (P3-B2 T9).

Single source of truth for the two instrument health indicators that
the Configure Instruments module (block 03) displays:

* **Test Connection** - OK / NOK / Unknown
* **Self-Test**       - OK / NOK / Unknown

plus the aggregated connected flag.  The Equipment page OWNS the
values (all configuration and connection validation is centralized
there); block 03 only displays them and performs the connect /
disconnect control with status reset.  Qt-free core (plain callback
list) so the sync logic stays headless-testable.
"""

from __future__ import annotations

STATUS_UNKNOWN = "Unknown"
STATUS_OK = "OK"
STATUS_NOK = "NOK"
STATUSES = (STATUS_UNKNOWN, STATUS_OK, STATUS_NOK)


class InstrumentStatusHub:
    """Shared instrument status store with change notification."""

    def __init__(self) -> None:
        self.connected: bool = False
        self.test_connection: str = STATUS_UNKNOWN
        self.self_test: str = STATUS_UNKNOWN
        self._subscribers: list = []

    # ------------------------------------------------------ subscription
    def subscribe(self, callback) -> None:
        """Register a change callback (called with no arguments)."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        """Remove a previously registered callback."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify(self) -> None:
        for callback in list(self._subscribers):
            callback()

    # ------------------------------------------------------------- state
    def set_connected(self, connected: bool) -> None:
        """Update the aggregated connection flag (Equipment page sync
        or the block 03 connect / disconnect control)."""
        self.connected = bool(connected)
        self._notify()

    def set_test_connection(self, result: str) -> None:
        """Set the Test Connection result (Equipment page sync)."""
        if result in STATUSES:
            self.test_connection = result
            self._notify()

    def set_self_test(self, result: str) -> None:
        """Set the Self-Test result (Equipment page sync)."""
        if result in STATUSES:
            self.self_test = result
            self._notify()

    def reset_status(self) -> None:
        """Status reset mechanism: after a disconnect both indicators
        return to Unknown (stale results are cleared)."""
        self.test_connection = STATUS_UNKNOWN
        self.self_test = STATUS_UNKNOWN
        self._notify()

    def disconnect(self) -> None:
        """Disconnect control: clear the flag AND reset the statuses."""
        self.set_connected(False)
        self.reset_status()

    def snapshot(self) -> dict:
        """Plain dict copy (tests / persistence)."""
        return {
            "connected": self.connected,
            "test_connection": self.test_connection,
            "self_test": self.self_test,
        }


#: application-wide hub (Equipment page writes, block 03 reads)
HUB = InstrumentStatusHub()
