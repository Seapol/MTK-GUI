# -*- coding: utf-8 -*-
"""M83 C11: Wi-Fi / Bluetooth editors show the Equipment truth."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QLabel,
)

from mtkgui.engine.fct_test_config import (  # noqa: E402
    STEP_TYPE_BT_PAIR,
    STEP_TYPE_BT_RSSI,
    STEP_TYPE_BT_TONE,
    STEP_TYPE_WIFI_IPERF,
    STEP_TYPE_WIFI_PING,
    STEP_TYPE_WIFI_SCAN,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    RF_EQUIPMENT_KEYS,
    FCTTestConfigPanel,
    _ToneRangeSlider,
)

EQUIPMENT = {"equipment": {
    "peripherals": {"router": {
        "router_ap_ssid": "SmartLab-5G", "hotspot_ssid": "",
        "wifi_host_ip": "192.168.1.10", "dut_ip": "192.168.1.50"}},
    "dut": {"wifi": {"ssid": "DUT-NET"},
            "bluetooth": {"name": "MTK-DUT",
                          "bd_addr": "11:22:33:44:55:66"}},
}}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _open(monkeypatch, label: str, equipment=EQUIPMENT,
          row_setup=None) -> QDialog:
    panel = FCTTestConfigPanel(equipment_provider=lambda: equipment)
    panel.set_values({})
    panel._add_row_for_label(label)
    row = panel.cmd_table.rowCount() - 1
    if row_setup is not None:
        row_setup(panel, row)
    seen: list = []

    def fake_exec(dlg):
        seen.append(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(row)
    assert seen, "the RF editor never opened"
    seen[0]._test_panel = panel
    seen[0]._test_row = row
    return seen[0]


def _labels(dlg) -> list:
    return [label.text() for label in dlg.findChildren(QLabel)]


def test_m83_wifi_scan_shows_read_only_ap_and_dut_ssid(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_WIFI_SCAN)
    texts = _labels(dlg)
    assert any("SmartLab-5G" in text
               and "Equipment ▸ Wired & Wireless Network" in text
               for text in texts)
    assert any("DUT-NET" in text and "Equipment ▸ DUT" in text
               for text in texts)


def test_m83_wifi_ping_shows_read_only_target(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_WIFI_PING)
    texts = _labels(dlg)
    assert any("192.168.1.50" in text
               and "Equipment ▸ Wired & Wireless Network" in text
               for text in texts)


def test_m83_wifi_iperf_shows_read_only_host_ip(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_WIFI_IPERF)
    texts = _labels(dlg)
    assert any("192.168.1.10" in text
               and "Equipment ▸ Wired & Wireless Network" in text
               for text in texts)


def test_m83_bt_rssi_shows_read_only_name_and_addr(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_BT_RSSI)
    texts = _labels(dlg)
    assert any("MTK-DUT" in text and "Equipment ▸ DUT" in text
               for text in texts)
    assert any("11:22:33:44:55:66" in text for text in texts)


def test_m83_missing_equipment_value_shows_warning_banner(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_WIFI_SCAN, equipment={})
    texts = _labels(dlg)
    assert any("Missing in Equipment:" in text for text in texts)
    assert any("—" in text and "not set in Equipment" in text
               for text in texts)


def test_m83_rf_equipment_keys_resolve_against_m65_fields(qapp):
    scan = RF_EQUIPMENT_KEYS[("wifi", "scan")]
    assert scan["ap_ssid"][0] == \
        "equipment.peripherals.router.router_ap_ssid"
    assert "equipment.peripherals.router.hotspot_ssid" in scan["ap_ssid"]
    assert RF_EQUIPMENT_KEYS[("wifi", "ping")]["target"][0] == \
        "equipment.peripherals.router.dut_ip"
    assert RF_EQUIPMENT_KEYS[("wifi", "iperf")]["target"][0] == \
        "equipment.peripherals.router.wifi_host_ip"


def test_m83_bt_pair_count_minimum_is_one(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_BT_PAIR)
    spins = dlg.findChildren(QDoubleSpinBox)
    l2ping = [spin for spin in spins if spin.decimals() == 0
              and spin.value() == 1.0 and spin.minimum() == 1.0]
    assert l2ping, "the L2CAP ping count spin has no minimum of 1"


def test_m83_bt_pair_shows_read_only_console_channel(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_BT_PAIR)
    texts = _labels(dlg)
    assert any("Console channel: ser1 (from Console module)" in text
               for text in texts)
    assert any("runs through the console serial channel" in text
               for text in texts)


def test_m83_tone_start_end_spinboxes_removed(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_BT_TONE)
    texts = _labels(dlg)
    assert not any(text.startswith("Start:") for text in texts)
    assert not any(text.startswith("End:") for text in texts)
    assert not dlg.findChildren(QDoubleSpinBox)


def test_m83_tone_slider_readout_has_tenth_second_precision(
        qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_BT_TONE)
    slider = dlg.findChild(_ToneRangeSlider)
    assert slider is not None
    readout = [label for label in dlg.findChildren(QLabel)
               if label.text().startswith("Start ")]
    assert readout and "End " in readout[0].text()
    # 0.1 s precision, updated while dragging
    slider.changed.emit(7.04, 16.06)
    assert readout[0].text() == "Start 7.0 s — End 16.1 s"


def test_m83_tone_save_reads_slider_only(qapp, monkeypatch):
    def _legacy(panel, row):
        cmd = panel._get_row_cmd(row)
        cmd.step_params = {"file": "tone.wav", "start_s": 1.0, "end_s": 6.0}
        panel._save_row_cmd(row, cmd)

    panel = FCTTestConfigPanel(equipment_provider=lambda: EQUIPMENT)
    panel.set_values({})
    panel._add_row_for_label(STEP_TYPE_BT_TONE)
    row = panel.cmd_table.rowCount() - 1
    _legacy(panel, row)
    seen: list = []

    def fake_exec(dlg):
        seen.append(dlg)
        slider = dlg.findChild(_ToneRangeSlider)
        slider.set_values(3.0, 4.0)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(row)
    params = panel._get_row_cmd(row).step_params
    assert params["start_s"] == 3.0 and params["end_s"] == 4.0
    panel.deleteLater()
