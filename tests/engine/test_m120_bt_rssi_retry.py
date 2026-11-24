# -*- coding: utf-8 -*-
"""M120: a BT RSSI scan gets a second look, and a row budget that cannot
outlast its own sub-timeout is called out before the work starts."""
from __future__ import annotations

import pytest

from mtkgui.engine.fct_exec import FctContext, _bt_rssi_host
from mtkgui.gui.yamlbuild.fct_build import STEP_EXTERNAL_TOOL, FctStep


def _rssi_step(rf_timeout_s=10.0, attempts=2, row_timeout=35.0):
    return FctStep(
        name="Bluetooth RSSI", step_type=STEP_EXTERNAL_TOOL, channel="",
        timeout_s=row_timeout,
        params={"tool_family": "bluetooth",
                "fct_rf": {"mode": "rssi_only",
                           "expected_name": "FRDM-IMX93-DUT",
                           "rssi_min": -70,
                           "rf_timeout_s": rf_timeout_s,
                           "scan_attempts": attempts}})


class _Log:
    def __init__(self):
        self.lines = []

    def __call__(self, text):
        self.lines.append(str(text))


def _ctx(log):
    return FctContext(log_sink=log)


def _patch_scan(monkeypatch, values):
    """Feed ``values`` to bt_scan one call at a time; record the calls."""
    from mtkgui.engine import host_rf
    calls = []

    def fake(target, *, virtual=False, virtual_rssi=None, timeout_s=10.0):
        calls.append((target, timeout_s))
        return values.pop(0) if values else None

    monkeypatch.setattr(host_rf, "bt_scan", fake)
    return calls


def test_m120_missed_advertisement_is_scanned_again(monkeypatch):
    """The first scan may miss a 100 ms advertising DUT - that is a timing
    event, so attempt 2 decides the verdict instead of a premature FAIL."""
    calls = _patch_scan(monkeypatch, [None, -54])
    monkeypatch.setattr("time.sleep", lambda *_a: None)
    log = _Log()
    out = _bt_rssi_host(_rssi_step(), dict(_rssi_step().params["fct_rf"]),
                        _ctx(log))
    assert out.verdict == "PASS"
    assert "-54 dBm" in out.reason
    assert len(calls) == 2, "the scan must be retried exactly once"
    assert calls[0][1] == 10.0, "each attempt uses rf_timeout_s"


def test_m120_two_misses_still_fail_the_dut(monkeypatch):
    """A DUT that stays invisible across every attempt is a real FAIL."""
    calls = _patch_scan(monkeypatch, [None, None])
    monkeypatch.setattr("time.sleep", lambda *_a: None)
    log = _Log()
    out = _bt_rssi_host(_rssi_step(), dict(_rssi_step().params["fct_rf"]),
                        _ctx(log))
    assert out.verdict == "FAIL"
    assert len(calls) == 2
    assert any("attempt 1/2" in line for line in log.lines)
    assert any("attempt 2/2" in line for line in log.lines)


def test_m120_scan_attempts_one_keeps_the_old_behaviour(monkeypatch):
    calls = _patch_scan(monkeypatch, [None, -40])
    log = _Log()
    step = _rssi_step(attempts=1)
    out = _bt_rssi_host(step, dict(step.params["fct_rf"]), _ctx(log))
    assert out.verdict == "FAIL"
    assert len(calls) == 1


def test_m120_scan_backend_error_is_an_error_not_a_fail(monkeypatch):
    from mtkgui.engine import host_rf

    def boom(*_a, **_k):
        raise host_rf.HostRfError("BT scan failed: no adapter")

    monkeypatch.setattr(host_rf, "bt_scan", boom)
    log = _Log()
    out = _bt_rssi_host(_rssi_step(), dict(_rssi_step().params["fct_rf"]),
                        _ctx(log))
    assert out.verdict == "ERROR"
