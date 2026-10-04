# -*- coding: utf-8 -*-
"""Device state management (P1 Task10): five states, token locks,
heartbeat probing, forced release, multi-device isolation."""
from __future__ import annotations

import pytest

from mtkgui.engine.device_manager import (DeviceManager, DeviceState,
                                          DeviceStateError)


@pytest.fixture()
def dm():
    lines: list[str] = []
    m = DeviceManager(log_fn=lines.append)
    m.lines = lines
    m.register("psu")
    m.register("daq")
    return m


class TestStates:
    def test_five_states_exist_and_are_exclusive(self):
        assert {s.value for s in DeviceState} == \
            {"IDLE", "OCCUPIED", "OFFLINE", "ERROR", "FROZEN"}
        dev = dm_singleton()
        assert dev.state is DeviceState.IDLE   # exactly one at a time

    def test_acquire_occupies_with_token(self, dm):
        tok = dm.acquire("psu", "runner-1")
        assert tok and dm.state("psu") is DeviceState.OCCUPIED
        dev = dm.get("psu")
        assert dev.owner == "runner-1"

    def test_double_acquire_rejected(self, dm):
        dm.acquire("psu", "task-a")
        with pytest.raises(DeviceStateError, match="held by 'task-a'"):
            dm.acquire("psu", "task-b")

    def test_verified_release(self, dm):
        tok = dm.acquire("psu", "task-a")
        with pytest.raises(DeviceStateError, match="token mismatch"):
            dm.release("psu", "wrong-token")
        dm.release("psu", tok)
        assert dm.state("psu") is DeviceState.IDLE
        assert dm.get("psu").owner == ""

    def test_illegal_transition_rejected(self, dm):
        dm.freeze("psu")
        with pytest.raises(DeviceStateError):
            dm.acquire("psu", "x")            # FROZEN not acquireable
        assert dm.acquireable("psu") is False

    def test_unknown_and_duplicate_devices_rejected(self, dm):
        with pytest.raises(DeviceStateError, match="unknown"):
            dm.acquire("scope", "x")
        with pytest.raises(DeviceStateError, match="register again"):
            dm.register("psu")


class TestHeartbeat:
    def test_missed_heartbeat_marks_offline(self, dm):
        dm.acquire("psu", "task-a")
        assert dm.heartbeat("psu", alive=False) is DeviceState.OFFLINE
        # occupancy preserved while offline (no silent steal)
        assert dm.get("psu").owner == "task-a"

    def test_recovery_returns_to_idle(self, dm):
        dm.heartbeat("psu", alive=False)
        assert dm.heartbeat("psu", alive=True) is DeviceState.IDLE
        # acquireable again after recovery
        tok = dm.acquire("psu", "task-a")
        assert tok

    def test_probe_all_refreshes_every_device(self, dm):
        result = dm.probe_all(lambda name: name != "daq")
        assert result == {"psu": DeviceState.IDLE,
                          "daq": DeviceState.OFFLINE}

    def test_repeated_heartbeat_is_idempotent(self, dm):
        dm.heartbeat("psu", alive=False)
        assert dm.heartbeat("psu", alive=False) is DeviceState.OFFLINE


class TestErrorAndFreeze:
    def test_error_and_clear(self, dm):
        dm.mark_error("psu", "fuse blown")
        assert dm.state("psu") is DeviceState.ERROR
        with pytest.raises(DeviceStateError):
            dm.acquire("psu", "x")
        dm.clear_error("psu")
        assert dm.state("psu") is DeviceState.IDLE

    def test_clear_error_only_from_error_state(self, dm):
        with pytest.raises(DeviceStateError):
            dm.clear_error("psu")

    def test_freeze_and_force_release(self, dm):
        tok = dm.acquire("psu", "task-a")
        dm.freeze("psu", "maintenance window")
        assert dm.state("psu") is DeviceState.FROZEN
        dm.force_release("psu", "maintenance done")
        assert dm.state("psu") is DeviceState.IDLE

    def test_force_release_from_any_state(self, dm):
        dm.acquire("psu", "zombie-task")
        dm.mark_error("psu")                  # stuck occupied+error
        dm.force_release("psu", "stale occupation")
        assert dm.state("psu") is DeviceState.IDLE


class TestMultiDevice:
    def test_independent_isolation(self, dm):
        t1 = dm.acquire("psu", "flow-1")
        t2 = dm.acquire("daq", "flow-2")      # parallel, no clash
        dm.release("psu", t1)
        assert dm.state("psu") is DeviceState.IDLE
        assert dm.state("daq") is DeviceState.OCCUPIED  # untouched
        dm.release("daq", t2)

    def test_heartbeat_of_one_device_leaves_other(self, dm):
        dm.acquire("psu", "t")
        dm.heartbeat("daq", alive=False)
        assert dm.state("psu") is DeviceState.OCCUPIED
        assert dm.state("daq") is DeviceState.OFFLINE


class TestTraceability:
    def test_dev_state_log_lines(self, dm):
        tok = dm.acquire("psu", "runner-1")
        dm.heartbeat("psu", alive=False)
        dm.force_release("psu", "stale")
        text = "\n".join(dm.lines)
        assert "[DEV_STATE] device 'psu' IDLE -> OCCUPIED " \
               "(trigger=operator, owner=runner-1)" in text
        assert "OFFLINE -> IDLE" in text or \
            "OCCUPIED -> OFFLINE" in text
        assert "forced: stale" in text


def dm_singleton() -> object:
    m = DeviceManager(log_fn=lambda line: None)
    return m.register("solo")
