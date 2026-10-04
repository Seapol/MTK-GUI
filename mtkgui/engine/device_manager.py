# -*- coding: utf-8 -*-
"""Device lifecycle state management (P1 Task10).

Five-state, mutually-exclusive device control with exclusive token
locks, heartbeat probing, forced release and multi-device isolation.
Purely additive: the protocol layer, scheduler, runner and failure
taxonomy are untouched - this module is the authoritative resource
registry that future scheduling integrations consult.

  states (exactly one at a time, never stacked):
    IDLE      free to acquire
    OCCUPIED  held by exactly one owner token
    OFFLINE   lost heartbeat; occupancy is preserved until release
    ERROR     device reported a fault; not acquirable until cleared
    FROZEN    administratively frozen; not acquirable until released

  * exclusive token locks - one owner per device, tokens are random
    and verified on release (no cross-task preemption)
  * heartbeat probing - mark_offline on missed heartbeat, automatic
    IDLE recovery when the device answers again
  * forced release - an operator-level escape hatch from ANY state
    (deadlock / stale-occupation recovery), fully logged
  * multi-device - every device transitions independently
  * [DEV_STATE] structured lines: state, owner, trigger, reason
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class DeviceState(str, Enum):
    IDLE = "IDLE"
    OCCUPIED = "OCCUPIED"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    FROZEN = "FROZEN"


class DeviceStateError(RuntimeError):
    """Illegal state transition / acquisition conflict."""

    def __init__(self, device: str, current: str, action: str,
                 reason: str = ""):
        self.device = device
        self.current = current
        suffix = f": {reason}" if reason else ""
        super().__init__(f"device '{device}' in state {current} "
                         f"cannot {action}{suffix}")


# legal transitions; every change goes through _transition
_LEGAL = {
    DeviceState.IDLE: {DeviceState.OCCUPIED, DeviceState.OFFLINE,
                       DeviceState.ERROR, DeviceState.FROZEN},
    DeviceState.OCCUPIED: {DeviceState.IDLE, DeviceState.OFFLINE,
                           DeviceState.ERROR, DeviceState.FROZEN},
    DeviceState.OFFLINE: {DeviceState.IDLE, DeviceState.OCCUPIED,
                          DeviceState.ERROR, DeviceState.FROZEN},
    DeviceState.ERROR: {DeviceState.IDLE, DeviceState.OFFLINE,
                        DeviceState.FROZEN},
    DeviceState.FROZEN: {DeviceState.IDLE},
}


@dataclass
class Device:
    name: str
    state: DeviceState = DeviceState.IDLE
    owner: str = ""
    token: str = ""
    since: float = field(default_factory=time.monotonic)
    last_heartbeat: float = field(default_factory=time.monotonic)
    reason: str = ""


class DeviceManager:
    """Registry + lock authority for all station devices."""

    def __init__(self, log_fn: Optional[Callable[[str], None]] = None):
        self._devices: dict[str, Device] = {}
        self._log = log_fn or (lambda line: print(line))

    def _dv(self, line: str) -> None:
        self._log(f"[DEV_STATE] {line}")

    # ------------------------------------------------------ registry
    def register(self, name: str) -> Device:
        if name in self._devices:
            raise DeviceStateError(name, "registered",
                                   "register again")
        dev = Device(name=name)
        self._devices[name] = dev
        self._dv(f"device '{name}' registered state=IDLE "
                 f"(trigger=system)")
        return dev

    def get(self, name: str) -> Device:
        if name not in self._devices:
            raise DeviceStateError(name, "unknown", "operate on")
        return self._devices[name]

    @property
    def names(self) -> list[str]:
        return list(self._devices)

    def state(self, name: str) -> DeviceState:
        return self.get(name).state

    # ---------------------------------------------------- transitions
    def _transition(self, dev: Device, new: DeviceState,
                    trigger: str, owner: str = "", reason: str = ""
                    ) -> None:
        if new not in _LEGAL[dev.state]:
            raise DeviceStateError(
                dev.name, dev.state.value, f"transition to {new.value}")
        old = dev.state
        dev.state = new
        dev.since = time.monotonic()
        dev.reason = reason
        self._dv(f"device '{dev.name}' {old.value} -> {new.value} "
                 f"(trigger={trigger}"
                 + (f", owner={owner}" if owner else "")
                 + (f", reason={reason}" if reason else "") + ")")

    # ---------------------------------------------------------- locks
    def acquire(self, name: str, owner: str) -> str:
        """Exclusive occupation; returns the owner's secret token."""
        dev = self.get(name)
        if dev.state is not DeviceState.IDLE:
            raise DeviceStateError(
                name, dev.state.value, "acquire",
                f"held by '{dev.owner}'" if dev.owner else dev.reason)
        token = secrets.token_hex(8)
        self._transition(dev, DeviceState.OCCUPIED, "operator",
                         owner=owner)
        dev.owner = owner
        dev.token = token
        return token

    def release(self, name: str, token: str) -> None:
        """Verified release; a wrong token can never free a device
        held by someone else."""
        dev = self.get(name)
        if dev.state is DeviceState.OCCUPIED and dev.token != token:
            raise DeviceStateError(name, dev.state.value, "release",
                                   "token mismatch (not the holder)")
        self._transition(dev, DeviceState.IDLE, "operator")
        dev.owner = ""
        dev.token = ""

    def force_release(self, name: str, reason: str = "admin") -> None:
        """Escape hatch from ANY state (deadlock / stale occupation)."""
        dev = self.get(name)
        self._transition(dev, DeviceState.IDLE, "system",
                         reason=f"forced: {reason}")
        dev.owner = ""
        dev.token = ""

    # ------------------------------------------------------- health
    def heartbeat(self, name: str, alive: bool) -> DeviceState:
        """Heartbeat probe: a missed beat marks OFFLINE, an answered
        beat recovers an OFFLINE device back to IDLE."""
        dev = self.get(name)
        dev.last_heartbeat = time.monotonic()
        if alive and dev.state is DeviceState.OFFLINE:
            self._transition(dev, DeviceState.IDLE, "auto",
                             reason="heartbeat recovered")
        elif not alive and dev.state is not DeviceState.OFFLINE:
            self._transition(dev, DeviceState.OFFLINE, "auto",
                             reason="heartbeat missed")
        return dev.state

    def probe_all(self, alive_fn: Callable[[str], bool]) -> dict:
        """Refresh every device; returns the resulting state map."""
        return {name: self.heartbeat(name, alive_fn(name))
                for name in self.names}

    def mark_error(self, name: str, reason: str = "fault") -> None:
        self._transition(self.get(name), DeviceState.ERROR, "auto",
                         reason=reason)

    def clear_error(self, name: str) -> None:
        """Error recovery: back to IDLE once the fault is cleared."""
        dev = self.get(name)
        if dev.state is not DeviceState.ERROR:
            raise DeviceStateError(name, dev.state.value,
                                   "clear error")
        self._transition(dev, DeviceState.IDLE, "operator",
                         reason="fault cleared")

    def freeze(self, name: str, reason: str = "maintenance") -> None:
        self._transition(self.get(name), DeviceState.FROZEN,
                         "operator", reason=reason)

    def acquireable(self, name: str) -> bool:
        return self.get(name).state is DeviceState.IDLE
