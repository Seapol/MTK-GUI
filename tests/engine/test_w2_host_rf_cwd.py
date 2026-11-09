# -*- coding: utf-8 -*-
"""W2-3: the host Wi-Fi scan runs lswifi from a dump folder, never the CWD."""
from __future__ import annotations

import tempfile
from pathlib import Path

from mtkgui.engine import host_rf as hr


def test_wifi_scan_runs_lswifi_from_the_dump_folder(monkeypatch):
    calls = []

    def fake(cmd_line, timeout_s=30, *, keep_stderr=True, cwd=None):
        calls.append((cmd_line, keep_stderr, cwd))
        return '[{"SSID": "AP-1", "RSSI": -60}]'

    monkeypatch.setattr(hr, "run_command", fake)
    assert hr.wifi_scan(["AP-1"], timeout_s=5, key="windows") == {"AP-1": -60}
    cmd_line, keep_stderr, cwd = calls[0]
    assert cmd_line == hr._LSWIFI_CMD
    assert keep_stderr is False
    assert Path(cwd).name == "mtkgui_host_rf"
    assert Path(cwd).parent == Path(tempfile.gettempdir())
    assert Path(cwd).is_dir()
