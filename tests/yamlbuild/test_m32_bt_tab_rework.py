# -*- coding: utf-8 -*-
"""m32: Bluetooth tab rework - one-row layout, Host PC BT panel, scan,
DUT pair script, and the non-checkable A2DP tone module."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from mtkgui.engine import host_platform  # noqa: E402
from mtkgui.engine.fct_test_config import (  # noqa: E402
    BluetoothCfg,
    FctTestConfig,
    STEP_MESSAGE_CHECK,
    build_fct_steps,
    pair_script_command,
)
from mtkgui.engine.fct_test_runner import BT_MAC_CMDS  # noqa: E402
from mtkgui.engine.rf_adapters import PlatformBackendMissing  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
    _BtScanWorker,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- layout
def test_bt_tab_one_row_scroll(qapp):
    """m32: the BT tab is a scrollable one-row three-column grid with no
    master enable checkbox and a non-checkable tone module."""
    from PySide6.QtWidgets import QGridLayout, QScrollArea
    panel = FCTTestConfigPanel()
    assert isinstance(panel.bt_tab, QScrollArea)
    grid = panel.bt_tab.widget().layout()
    assert isinstance(grid, QGridLayout)

    def pos(widget):
        return grid.getItemPosition(grid.indexOf(widget))[:2]

    boxes = [pos(w) for w in (panel.bt_rssi_box, panel.bt_pair_box,
                              panel.bt_tone_box)]
    assert {r for r, _c in boxes} == {0}
    assert [c for _r, c in boxes] == [0, 1, 2]
    assert not hasattr(panel, "bt_enabled")
    assert not panel.bt_tone_box.isCheckable()
    assert panel.bt_rssi_box.isCheckable()
    assert panel.bt_pair_box.isCheckable()


def test_bt_tab_defaults(qapp):
    """m32/M45: L2CAP default 4, tone wav + total length + host status."""
    panel = FCTTestConfigPanel()
    assert panel.bt_l2ping.value() == 4
    assert panel.bt_tone_file.text() == "resources/tones/tone_1khz_6s.wav"
    # M45: the Play-Duration spin box is gone - the dual-node slider
    # spans the whole 6 s tone (Start 0 / End = total)
    assert panel.bt_tone_range.start_s() == 0.0
    assert panel.bt_tone_range.end_s() == 6.0
    assert "6.0 s" in panel.bt_tone_total.text()
    assert panel.bt_host_status.text() == "N/A"
    assert panel.bt_host_devices.text() == "\u2014"


# ------------------------------------------------------------- host panel
def test_parse_bt_status_on_off_na():
    """m32: parse_bt_status maps 1/0 (and unparseable/empty) to ON/OFF/N/A."""
    assert host_platform.parse_bt_status("1") == "ON"
    assert host_platform.parse_bt_status("0") == "OFF"
    assert host_platform.parse_bt_status("") == "N/A"
    assert host_platform.parse_bt_status("blueutil: command not found") \
        == "N/A"


def test_parse_bt_devices_mac_and_windows():
    """m32: mac system_profiler -> 'Name (addr)'; windows friendly names."""
    mac_text = (
        "Bluetooth:\n"
        "  Connected:\n"
        "    JBL Pulse 5:\n"
        "      Address: 40-C1-F6-84-8F-C5\n"
        "    FRDM-IMX93-DUT:\n"
        "      Address: AA-BB-CC-DD-EE-FF\n")
    assert host_platform.parse_bt_devices(mac_text) == [
        "JBL Pulse 5 (40:c1:f6:84:8f:c5)",
        "FRDM-IMX93-DUT (aa:bb:cc:dd:ee:ff)"]
    assert host_platform.parse_bt_devices(
        "FRDM-IMX93-DUT\nJBL Pulse 5\n") == ["FRDM-IMX93-DUT", "JBL Pulse 5"]


def test_rssi_render_windows_always_not_supported():
    """m32: Windows renders RSSI as -- dBm (Not supported by Windows 11)."""
    info = host_platform.format_bt_scan_result(
        "FRDM-IMX93-DUT\n", "", "FRDM-IMX93-DUT", is_windows=True)
    assert "-- dBm (Not supported by Windows 11)" in info["verdict"]
    assert any("Not supported by Windows 11" in l for l in info["lines"])


def test_rssi_render_mac_real_dbm():
    """m32: mac shows the real system_profiler dBm for the connected DUT."""
    scan = "address: aa-bb-cc-dd-ee-ff, name: FRDM-IMX93-DUT\n"
    rssi = ("Bluetooth:\n  Connected:\n    FRDM-IMX93-DUT:\n"
            "      Address: AA-BB-CC-DD-EE-FF\n      RSSI: -55\n")
    info = host_platform.format_bt_scan_result(
        scan, rssi, "FRDM-IMX93-DUT", is_windows=False)
    assert "RSSI: -55 dBm" in info["verdict"]
    assert any("RSSI: -55 dBm" in l for l in info["lines"])


def test_rssi_render_mac_no_rssi_falls_back():
    """m32: mac with no connected-device RSSI renders '-- dBm'."""
    info = host_platform.format_bt_scan_result(
        "address: aa-bb-cc-dd-ee-ff, name: FRDM-IMX93-DUT\n", "",
        "FRDM-IMX93-DUT", is_windows=False)
    assert "RSSI: -- dBm" in info["verdict"]


# --------------------------------------------------------------- scan UI
def _install_bt_scan_mocks(monkeypatch):
    monkeypatch.setattr(host_platform, "platform_key", lambda: "mac")
    monkeypatch.setattr(host_platform, "host_bt_scan_cmd",
                        lambda: "blueutil --inquiry 10")
    monkeypatch.setattr(host_platform, "host_bt_devices_cmd",
                        lambda: "system_profiler SPBluetoothDataType")

    def fake_run(cmd_line, timeout_s=15):
        if "inquiry" in cmd_line:
            return ("address: 40-c1-f6-84-8f-c5, name: JBL Pulse 5\n"
                    "address: aa-bb-cc-dd-ee-ff, name: FRDM-IMX93-DUT\n")
        if "system_profiler" in cmd_line:
            return ("Bluetooth:\n  Connected:\n    FRDM-IMX93-DUT:\n"
                    "      Address: AA-BB-CC-DD-EE-FF\n      RSSI: -55\n")
        return ""
    monkeypatch.setattr(host_platform, "run_link_cmd", fake_run)


def test_bt_scan_prefront_popup_and_worker(qapp, monkeypatch):
    """m32: the pre-front progress bar + the scan popup with the DUT found."""
    _install_bt_scan_mocks(monkeypatch)
    panel = FCTTestConfigPanel()
    panel.bt_name.setText("FRDM-IMX93-DUT")
    pops = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda parent, title, text:
                                    pops.append(text)))
    panel._on_bt_scan()
    assert panel.bt_scan_progress.isVisibleTo(panel.bt_tab)
    assert panel.bt_scan_progress.value() == 0
    assert panel.bt_scan_status.text() == "Scanning..."
    assert not panel.bt_scan_btn.isEnabled()
    worker = panel._bt_scan_worker
    assert isinstance(worker, _BtScanWorker)
    assert worker.wait(5000)
    for _ in range(10):
        qapp.processEvents()
    assert panel.bt_scan_progress.value() == 100
    assert pops and ("DUT BT name: FRDM-IMX93-DUT 信号已找到, RSSI: -55 dBm"
                     in pops[0])


def test_bt_scan_worker_emits_result_and_verdict(monkeypatch):
    """m32: the worker reports the device-list result + DUT-hit verdict."""
    _install_bt_scan_mocks(monkeypatch)
    worker = _BtScanWorker("FRDM-IMX93-DUT")
    result = []
    verdict = []
    worker.result.connect(result.append)
    worker.verdict.connect(verdict.append)
    worker.run()
    assert result and "FRDM-IMX93-DUT" in result[0]
    assert verdict and "信号已找到" in verdict[0]


# ---------------------------------------------------------------- pair
def test_pair_script_command_rendering():
    """m32: <script> <host_name> <host_addr>."""
    assert pair_script_command("bt_conn.sh", "MyHost", "AA:BB:CC:DD:EE:FF") \
        == "bt_conn.sh MyHost AA:BB:CC:DD:EE:FF"


def test_bt_subtest_steps_pair_script(monkeypatch):
    """m32: a configured DUT script generates one console MESSAGE_CHECK step
    whose send payload is <script> <host name> <host addr>."""
    monkeypatch.setattr(host_platform, "host_bt_identity",
                        lambda: ("MyHost", "AA:BB:CC:DD:EE:FF"))
    cfg = FctTestConfig(
        dut_type="linux",
        bluetooth=BluetoothCfg(
            rssi_enabled=True, expected_name="DUT-BT",
            pair_enabled=True, l2ping_count=0,
            bt_pair_script="/root/bt_conn.sh"))
    steps = build_fct_steps(cfg, channel_key="ser1")
    pair = next(s for s in steps if "Pair" in s.name)
    assert pair.step_type == STEP_MESSAGE_CHECK
    assert pair.channel == "ser1"
    assert pair.params["send"] == \
        "/root/bt_conn.sh MyHost AA:BB:CC:DD:EE:FF"


# ----------------------------------------------------------------- tone
def test_tone_cmd_carries_duration():
    """m32: the mac tone command renders afplay -t {{duration}} {{tone}}."""
    assert BT_MAC_CMDS["tone_cmd"] == "afplay -t {{duration}} {{tone}}"


def test_windows_bt_backend_still_raises(monkeypatch):
    """m32: Windows still raises the explicit guidance error."""
    monkeypatch.setattr(host_platform, "platform_key", lambda: "windows")
    with pytest.raises(PlatformBackendMissing):
        host_platform.bt_backend_cmds()


def test_bluetooth_cfg_new_fields_roundtrip():
    """m32/M45: test_tone / tone_start_s / tone_end_s / bt_pair_script."""
    cfg = FctTestConfig(bluetooth=BluetoothCfg(
        test_tone="resources/tones/tone_2khz_6s.wav",
        tone_start_s=1.5, tone_end_s=7.0, bt_pair_script="/root/bt.sh"))
    restored = FctTestConfig.from_dict(cfg.to_dict()).bluetooth
    assert restored.test_tone == "resources/tones/tone_2khz_6s.wav"
    assert (restored.tone_start_s, restored.tone_end_s) == (1.5, 7.0)
    assert restored.bt_pair_script == "/root/bt.sh"