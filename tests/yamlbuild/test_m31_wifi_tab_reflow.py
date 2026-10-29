# -*- coding: utf-8 -*-
"""m31: Wi-Fi tab reflow + Host PC <-> AP connection test.

The Wi-Fi tab is now a scrollable adaptive THREE-column grid (DUT /
Hotspot AP / Host PC in one row; Scan / RSSI, Ping, iPerf in one row) and
gains a "Test Host PC <-> Hotspot AP connection" button whose worker
reports Connection OK / RSSI / Signal Quality over a pre-front progress
bar.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine import host_platform  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
    _WifiLinkProbeWorker,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


#: a fixed, Mac-shaped link command table so the probe tests do not
#: depend on the host's ``platform.system()``
def _mac_link_cmds():
    return {
        "rssi_cmd": "rssi-cmd",
        "rssi_is_percent": False,
        "rssi_dbm_parse": r"Signal / Noise: (-?\d+) dBm",
        "rssi_pct_parse": None,
        "ping_cmd": "ping -c 3 {}",
    }


def _install_probe_mocks(monkeypatch, dbm=-45, replies=3):
    """Mock ``host_platform`` for a deterministic probe: RSSI `dbm` and a
    ping with `replies` received packets (0 => ping fails)."""
    monkeypatch.setattr(host_platform, "wifi_link_probe_cmds",
                        _mac_link_cmds)

    def fake_run(cmd_line, timeout_s=15):
        if cmd_line.startswith("rssi-cmd"):
            return f"Signal / Noise: {dbm} dBm"
        loss = 0 if replies else 100
        return (f"{replies + 1} packets transmitted, {replies} packets "
                f"received, {loss}.0% packet loss")
    monkeypatch.setattr(host_platform, "run_link_cmd", fake_run)


def test_wifi_tab_scroll_area_three_column_rows(qapp):
    """m31: Wi-Fi tab body is a QScrollArea whose inner QGridLayout keeps
    DUT/AP/Host in one row and Scan/Ping/iPerf in one row."""
    from PySide6.QtWidgets import QGridLayout, QScrollArea
    panel = FCTTestConfigPanel()
    assert isinstance(panel.wifi_tab, QScrollArea)
    grid = panel.wifi_tab.widget().layout()
    assert isinstance(grid, QGridLayout)

    def pos(widget):
        return grid.getItemPosition(grid.indexOf(widget))[:2]

    cfg = [pos(w) for w in (panel.wifi_base, panel.wifi_ap_box,
                           panel.wifi_host_box)]
    assert {r for r, _c in cfg} == {1}
    assert [c for _r, c in cfg] == [0, 1, 2]

    tests = [pos(w) for w in (panel.wifi_scan_box, panel.wifi_ping_box,
                              panel.wifi_iperf_box)]
    assert {r for r, _c in tests} == {2}
    assert [c for _r, c in tests] == [0, 1, 2]


def test_signal_quality_tiers():
    """m31: signal-quality thresholds at -45/-55/-65/-75/-85 dBm (and
    no association -> No Signal)."""
    expected = {-45: "Excellent", -55: "Good", -65: "Weak",
                -75: "Bad", -85: "No Signal"}
    for dbm, tier in expected.items():
        assert host_platform.signal_quality(dbm) == tier
    assert host_platform.signal_quality(None) == "No Signal"


def test_percent_to_rssi_dbm():
    """m31: the documented Windows % -> dBm approximation is
    ``pct // 2 - 100``."""
    assert host_platform.percent_to_rssi_dbm(100) == -50
    assert host_platform.percent_to_rssi_dbm(50) == -75
    assert host_platform.percent_to_rssi_dbm(0) == -100


def test_probe_host_ap_link_ok(monkeypatch):
    """m31: RSSI -45 dBm + ping replies => ok + RSSI + Excellent."""
    _install_probe_mocks(monkeypatch, dbm=-45, replies=3)
    result = host_platform.probe_host_ap_link("192.168.1.1")
    assert result["ok"] is True
    assert result["rssi"] == -45.0
    assert result["quality"] == "Excellent"
    assert "Connection OK" in result["lines"]
    assert "RSSI: -45 dBm" in result["lines"]
    assert "Signal Quality: Excellent" in result["lines"]


def test_probe_host_ap_link_ping_fail(monkeypatch):
    """m31: 0 ping replies => ok=False + Connection FAILED with error."""
    _install_probe_mocks(monkeypatch, dbm=-65, replies=0)
    result = host_platform.probe_host_ap_link("192.168.1.1")
    assert result["ok"] is False
    assert any("Connection FAILED" in line for line in result["lines"])
    assert result["error"] == "no reply from 192.168.1.1"
    assert result["quality"] == "Weak"


def test_wifi_link_probe_worker(monkeypatch):
    """m31: the probe worker emits the verdict lines and a True done."""
    _install_probe_mocks(monkeypatch, dbm=-45, replies=3)
    worker = _WifiLinkProbeWorker("192.168.1.1")
    lines = []
    progress = []
    done = []
    worker.line.connect(lines.append)
    worker.progress.connect(lambda d, t: progress.append((d, t)))
    worker.done.connect(lambda ok, summary: done.append((ok, summary)))
    worker.run()
    assert any("Connection OK" in line for line in lines)
    assert any("RSSI: -45 dBm" in line for line in lines)
    assert any("Signal Quality: Excellent" in line for line in lines)
    assert progress[-1] == (3, 3)
    assert done and done[0][0] is True


def test_wifi_conn_test_prefront_and_complete(qapp, monkeypatch):
    """m31: the button shows the pre-front progress bar at 0 +
    "Connecting...", then the worker ends at 100%."""
    _install_probe_mocks(monkeypatch, dbm=-55, replies=3)
    panel = FCTTestConfigPanel()
    panel.wifi_ap_ip.setText("192.168.1.1")
    panel._on_wifi_conn_test()
    assert panel.wifi_conn_progress.isVisibleTo(panel.wifi_tab)
    assert panel.wifi_conn_progress.value() == 0
    assert panel.wifi_conn_status.text() == "Connecting..."
    assert not panel.wifi_conn_test_btn.isEnabled()
    worker = panel._wifi_probe
    assert worker is not None
    assert worker.wait(5000)
    for _ in range(10):
        qapp.processEvents()
    assert panel.wifi_conn_progress.value() == 100
    assert "Connection OK" in panel.wifi_conn_status.text()
    assert panel.wifi_conn_test_btn.isEnabled()