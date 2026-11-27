# -*- coding: utf-8 -*-
"""M107a: serial_pull honours the ``{{dut_report}}`` local-path token."""
from __future__ import annotations

import os

from mtkgui.engine import serial_transfer
from mtkgui.engine.fct_exec import (
    VERDICT_PASS,
    FctContext,
    _run_serial_transfer,
)
from mtkgui.gui.yamlbuild.fct_build import FctStep

DUT_REPORT = "/tmp/DUMMY/DUT Report/Part_1_2_3_SN_ts"


class _Channel:
    """Minimal console double: a push issues ``mkdir -p`` first."""

    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, text: str) -> None:
        self.writes.append(text)


def _step(direction: str, local: str, remote: str) -> FctStep:
    return FctStep(
        name="transfer", category="Transfer",
        type=("serial_pull" if direction == "pull" else "serial_put"),
        params={"fct_serial_transfer": {
            "direction": direction, "local": local, "remote": remote}})


def _record(monkeypatch) -> list:
    calls: list = []

    def fake_transfer(channel, direction, local_file, remote_file,
                      **_kwargs):
        calls.append((direction, local_file, remote_file))

    monkeypatch.setattr(serial_transfer, "transfer", fake_transfer)
    return calls


def test_serial_pull_resolves_dut_report_token(monkeypatch):
    calls = _record(monkeypatch)
    step = _step("pull", "{{dut_report}}/fat.log", "/root/fat.log")
    ctx = FctContext(dut_report=DUT_REPORT)
    outcome = _run_serial_transfer(step, ctx, _Channel())
    assert outcome.verdict == VERDICT_PASS
    assert calls == [("pull", os.path.join(DUT_REPORT, "fat.log"),
                      "/root/fat.log")]


def test_serial_push_without_token_is_unchanged(monkeypatch, tmp_path):
    calls = _record(monkeypatch)
    source = tmp_path / "asset.bin"
    source.write_bytes(b"x")
    step = _step("push", str(source), "/root/asset.bin")
    ctx = FctContext(dut_report=DUT_REPORT)
    outcome = _run_serial_transfer(step, ctx, _Channel())
    assert outcome.verdict == VERDICT_PASS
    assert calls == [("push", os.path.normpath(str(source)),
                      "/root/asset.bin")]


def test_empty_dut_report_leaves_the_token(monkeypatch):
    calls = _record(monkeypatch)
    step = _step("pull", "{{dut_report}}/fat.log", "/root/fat.log")
    outcome = _run_serial_transfer(step, FctContext(), _Channel())
    assert outcome.verdict == VERDICT_PASS
    assert calls[0][1] == os.path.normpath("{{dut_report}}/fat.log")
