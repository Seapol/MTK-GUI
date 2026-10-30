# -*- coding: utf-8 -*-
"""M40: Wi-Fi Hotspot AP / Host PC auto-detect + QSettings + SSID check.

Topology: Host PC <-> Hotspot AP <-> DUT on the SAME segment - the
Wi-Fi the Host PC is currently associated to IS the Hotspot AP under
test.  The tests use fixed mac / Windows command-output samples through
``host_platform.run_link_cmd`` (never the developer's real network).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine import host_platform  # noqa: E402
from mtkgui.gui.yamlbuild import FCTTestConfigWidget as fct_widget  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------- samples
MAC_ASSOC = """
Wi-Fi:

      Software Versions:
          CoreWLAN: 16.0
      Interfaces:
        en0:
          Card Type: Wi-Fi
          Firmware Version: 14.40.120
          Status: Connected
          Current Network Information:
            Shop-AP:
              PHY Mode: 802.11ax
              BSSID: 3c:2c:30:11:22:33
              Signal / Noise: -52 dBm / -91 dBm
"""

MAC_ASSOC_DISCONNECTED = """
Wi-Fi:

      Software Versions:
          CoreWLAN: 16.0
      Interfaces:
        en0:
          Card Type: Wi-Fi
          Status: Off
"""

MAC_IP = "192.168.1.23\n"

MAC_ROUTE = """
   route to: default
destination: default
       mask: default
    gateway: 192.168.1.1
  interface: en0
"""

WIN_NETSH = """
    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 7a1c8e2f-1111-2222-3333-444455556666
    Physical address       : 3c:58:c2:00:11:22
    State                  : connected
    SSID                   : Office-AP
    BSSID                  : aa:bb:cc:dd:ee:ff
    Signal                 : 85%
"""

WIN_IPCONFIG = """
Wireless LAN adapter Wi-Fi:

   Connection-specific DNS Suffix  . :
   Description.....................: Intel(R) Wi-Fi 6 AX201 160MHz
   IPv4 Address.....................: 192.168.1.44
   Subnet Mask.....................: 255.255.255.0
   Default Gateway.................: 192.168.1.254
"""


# --------------------------------------------------------------- parsing
def test_parse_mac_current_wifi():
    """mac: SSID + associated interface + IPv4 + default gateway."""
    assert host_platform.parse_mac_wifi(MAC_ASSOC) == ("Shop-AP", "en0")
    assert host_platform.parse_current_wifi(
        "mac", MAC_ASSOC, MAC_IP, MAC_ROUTE) == {
        "ssid": "Shop-AP", "ip": "192.168.1.23", "gateway": "192.168.1.1"}


def test_parse_mac_disconnected_is_none():
    """No ``Current Network Information`` -> all fields None."""
    assert host_platform.parse_mac_wifi(MAC_ASSOC_DISCONNECTED) == (None, None)
    assert host_platform.parse_current_wifi(
        "mac", MAC_ASSOC_DISCONNECTED, "", "") == {
        "ssid": None, "ip": None, "gateway": None}


def test_parse_windows_current_wifi():
    """Windows: netsh SSID + one ipconfig run (IPv4 + default gateway)."""
    assert host_platform.parse_current_wifi(
        "windows", WIN_NETSH, WIN_IPCONFIG, "") == {
        "ssid": "Office-AP", "ip": "192.168.1.44",
        "gateway": "192.168.1.254"}


def test_parse_missing_fields_are_none():
    """Empty / garbage outputs never raise - every field stays None."""
    assert host_platform.parse_current_wifi("mac", "", "", "") == {
        "ssid": None, "ip": None, "gateway": None}
    assert host_platform.parse_current_wifi(
        "windows", "", "", "") == {
        "ssid": None, "ip": None, "gateway": None}


def test_detect_current_wifi_mac(monkeypatch):
    """mac: three run_link_cmd calls (assoc / ipconfig / route)."""
    monkeypatch.setattr(host_platform, "platform_key", lambda: "mac")

    def fake_run(cmd_line, timeout_s=15):
        if cmd_line.startswith("system_profiler"):
            return MAC_ASSOC
        if cmd_line.startswith("ipconfig getifaddr"):
            return MAC_IP
        if cmd_line.startswith("route -n get default"):
            return MAC_ROUTE
        return ""

    monkeypatch.setattr(host_platform, "run_link_cmd", fake_run)
    assert host_platform.detect_current_wifi() == {
        "ssid": "Shop-AP", "ip": "192.168.1.23", "gateway": "192.168.1.1"}


def test_detect_current_wifi_windows(monkeypatch):
    """Windows: netsh + ipconfig (no explicit gateway command)."""
    monkeypatch.setattr(host_platform, "platform_key", lambda: "windows")

    def fake_run(cmd_line, timeout_s=15):
        if cmd_line.startswith("netsh wlan show interfaces"):
            return WIN_NETSH
        if cmd_line.startswith("ipconfig"):
            return WIN_IPCONFIG
        return ""

    monkeypatch.setattr(host_platform, "run_link_cmd", fake_run)
    assert host_platform.detect_current_wifi() == {
        "ssid": "Office-AP", "ip": "192.168.1.44",
        "gateway": "192.168.1.254"}


# ----------------------------------------------------------- panel wiring
@pytest.fixture
def panel_factory(tmp_path, monkeypatch):
    """Isolated QSettings store + panel factory (monkeypatches the
    module-level ``_wifi_settings`` before the panel loads its baseline)."""
    settings = QSettings(str(tmp_path / "settings.ini"),
                         QSettings.Format.IniFormat)
    monkeypatch.setattr(fct_widget, "_wifi_settings", lambda: settings)
    made = []

    def make():
        panel = fct_widget.FCTTestConfigPanel()
        made.append(panel)
        return panel

    yield make, settings
    for panel in made:
        panel.deleteLater()


def _seed(settings, ssid="BASE-AP", ap_ip="10.0.0.1", host_ip="10.0.0.2",
          password="base-pass"):
    settings.setValue(fct_widget.WIFI_KEY_SSID, ssid)
    settings.setValue(fct_widget.WIFI_KEY_AP_IP, ap_ip)
    settings.setValue(fct_widget.WIFI_KEY_HOST_IP, host_ip)
    settings.setValue(fct_widget.WIFI_KEY_PASSWORD, password)
    settings.sync()


def test_settings_baseline_loaded_at_init(panel_factory):
    """Init a: the fields start from the QSettings wifi/* baseline."""
    make, settings = panel_factory
    _seed(settings)
    panel = make()
    assert panel.wifi_ap_ssid.text() == "BASE-AP"
    assert panel.wifi_ap_ip.text() == "10.0.0.1"
    assert panel.wifi_host_ip.text() == "10.0.0.2"
    assert panel.wifi_ap_password.text() == "base-pass"


def test_init_order_detect_overwrites_baseline(panel_factory, monkeypatch):
    """Init b: a successful detection OVERWRITES the baseline fields
    AND becomes the new QSettings baseline."""
    make, settings = panel_factory
    _seed(settings)
    panel = make()
    monkeypatch.setattr(host_platform, "detect_current_wifi",
                        lambda: {"ssid": "CUR-AP", "ip": "192.168.1.20",
                                 "gateway": "192.168.1.1"})
    panel._on_tab_changed(panel.tabs.indexOf(panel.wifi_tab))
    assert panel.wifi_ap_ssid.text() == "CUR-AP"
    assert panel.wifi_ap_ip.text() == "192.168.1.1"
    assert panel.wifi_host_ip.text() == "192.168.1.20"
    assert settings.value(fct_widget.WIFI_KEY_SSID) == "CUR-AP"
    assert settings.value(fct_widget.WIFI_KEY_AP_IP) == "192.168.1.1"
    assert settings.value(fct_widget.WIFI_KEY_HOST_IP) == "192.168.1.20"
    # the detection runs once per panel (first Wi-Fi tab visit)
    monkeypatch.setattr(host_platform, "detect_current_wifi",
                        lambda: {"ssid": "SECOND", "ip": "1.2.3.4",
                                 "gateway": "1.2.3.1"})
    panel._on_tab_changed(panel.tabs.indexOf(panel.wifi_tab))
    assert panel.wifi_ap_ssid.text() == "CUR-AP"


def test_init_order_failure_keeps_baseline(panel_factory, monkeypatch):
    """Init b failure: no association keeps the baseline and notes it."""
    make, settings = panel_factory
    _seed(settings)
    panel = make()
    monkeypatch.setattr(host_platform, "detect_current_wifi",
                        lambda: {"ssid": None, "ip": None, "gateway": None})
    panel._on_tab_changed(panel.tabs.indexOf(panel.wifi_tab))
    assert panel.wifi_ap_ssid.text() == "BASE-AP"
    assert panel.wifi_ap_ip.text() == "10.0.0.1"
    assert panel.wifi_host_ip.text() == "10.0.0.2"
    assert "no Wi-Fi associated" in panel.wifi_autodetect_status.text()


def test_autodetect_button_fills_fields_password_untouched(
        panel_factory, monkeypatch):
    """One click fills AP SSID / AP IP (gateway) / Host PC IP; the
    password field is user-only and never rewritten."""
    make, settings = panel_factory
    panel = make()
    panel.wifi_ap_password.setText("my-secret")
    monkeypatch.setattr(host_platform, "detect_current_wifi",
                        lambda: {"ssid": "AP-1", "ip": "192.168.1.30",
                                 "gateway": "192.168.1.1"})
    panel.wifi_autodetect_btn.click()
    assert panel.wifi_ap_ssid.text() == "AP-1"
    assert panel.wifi_ap_ip.text() == "192.168.1.1"
    assert panel.wifi_host_ip.text() == "192.168.1.30"
    assert panel.wifi_ap_password.text() == "my-secret"
    assert settings.value(fct_widget.WIFI_KEY_PASSWORD) == "my-secret"
    assert "OK (AP-1)" in panel.wifi_autodetect_status.text()


def test_autodetect_missing_gateway_notes_it(panel_factory, monkeypatch):
    """A detected SSID without a gateway leaves the AP IP empty and
    notes ``gateway not found``."""
    make, _settings = panel_factory
    panel = make()
    monkeypatch.setattr(host_platform, "detect_current_wifi",
                        lambda: {"ssid": "AP-2", "ip": "192.168.1.31",
                                 "gateway": None})
    panel.wifi_autodetect_btn.click()
    assert panel.wifi_ap_ssid.text() == "AP-2"
    assert panel.wifi_ap_ip.text() == ""
    assert panel.wifi_host_ip.text() == "192.168.1.31"
    assert "gateway not found" in panel.wifi_autodetect_status.text()


def test_autodetect_backend_missing_keeps_baseline(panel_factory, monkeypatch):
    """A backend error (e.g. Linux host) leaves a note, never raises."""
    make, settings = panel_factory
    _seed(settings)
    panel = make()

    def boom():
        raise host_platform.PlatformBackendMissing("no linux backend")

    monkeypatch.setattr(host_platform, "detect_current_wifi", boom)
    panel.wifi_autodetect_btn.click()
    assert panel.wifi_ap_ssid.text() == "BASE-AP"
    assert "Auto-detect:" in panel.wifi_autodetect_status.text()


def test_wifi_settings_round_trip(panel_factory):
    """Write on Apply_Save yaml / password edit -> read at next init."""
    make, settings = panel_factory
    panel = make()
    panel.wifi_ap_ssid.setText("SAVED-AP")
    panel.wifi_ap_ip.setText("192.168.0.1")
    panel.wifi_host_ip.setText("192.168.0.20")
    panel.wifi_ap_password.setText("saved-pass")
    panel._persist_wifi_settings()
    assert settings.value(fct_widget.WIFI_KEY_SSID) == "SAVED-AP"
    assert settings.value(fct_widget.WIFI_KEY_AP_IP) == "192.168.0.1"
    assert settings.value(fct_widget.WIFI_KEY_HOST_IP) == "192.168.0.20"
    assert settings.value(fct_widget.WIFI_KEY_PASSWORD) == "saved-pass"
    fresh = make()
    assert fresh.wifi_ap_ssid.text() == "SAVED-AP"
    assert fresh.wifi_ap_ip.text() == "192.168.0.1"
    assert fresh.wifi_host_ip.text() == "192.168.0.20"
    assert fresh.wifi_ap_password.text() == "saved-pass"


# --------------------------------------------------- link-test SSID check
def _mac_link_cmds():
    return {
        "rssi_cmd": "rssi-cmd",
        "rssi_is_percent": False,
        "rssi_dbm_parse": r"Signal / Noise: (-?\d+) dBm",
        "rssi_pct_parse": None,
        "ping_cmd": "ping -c 3 {}",
    }


def _assoc_text(ssid, dbm=-50):
    if ssid is None:
        return "      Interfaces:\n        en0:\n          Status: Off\n"
    return (f"      Interfaces:\n        en0:\n"
            f"          Current Network Information:\n"
            f"            {ssid}:\n"
            f"              Signal / Noise: {dbm} dBm / -90 dBm\n")


def _install_probe(monkeypatch, ssid, replies=3, dbm=-50):
    monkeypatch.setattr(host_platform, "platform_key", lambda: "mac")
    monkeypatch.setattr(host_platform, "wifi_link_probe_cmds",
                        _mac_link_cmds)

    def fake_run(cmd_line, timeout_s=15):
        if cmd_line.startswith("rssi-cmd"):
            return _assoc_text(ssid, dbm)
        loss = 0 if replies else 100
        return (f"{replies + 1} packets transmitted, {replies} packets "
                f"received, {loss}.0% packet loss")
    monkeypatch.setattr(host_platform, "run_link_cmd", fake_run)


def test_probe_no_wifi_associated_fails(monkeypatch):
    """No association -> FAIL, never a misleading PASS."""
    _install_probe(monkeypatch, ssid=None)
    result = host_platform.probe_host_ap_link("192.168.1.1")
    assert result["ok"] is False
    assert result["error"] == "no Wi-Fi associated"
    assert any("no Wi-Fi associated" in line for line in result["lines"])


def test_probe_ssid_mismatch_fails(monkeypatch):
    """Associated to another AP -> FAIL naming both SSIDs; the current
    association's RSSI line stays visible."""
    _install_probe(monkeypatch, ssid="Other-AP", dbm=-50)
    result = host_platform.probe_host_ap_link(
        "192.168.1.1", expected_ssid="DUT-AP")
    assert result["ok"] is False
    assert ('Host PC connected to "Other-AP", not configured AP "DUT-AP"'
            in result["error"])
    assert any('not configured AP "DUT-AP"' in line
               for line in result["lines"])
    assert any("RSSI: -50 dBm" in line for line in result["lines"])


def test_probe_ssid_match_follows_current_behaviour(monkeypatch):
    """Matching SSID -> the normal RSSI + quality + ping verdict."""
    _install_probe(monkeypatch, ssid="DUT-AP", dbm=-45)
    result = host_platform.probe_host_ap_link(
        "192.168.1.1", expected_ssid="DUT-AP")
    assert result["ok"] is True
    assert any("Connection OK" in line for line in result["lines"])
    assert any("Signal Quality: Excellent" in line for line in result["lines"])


def test_probe_empty_expected_ssid_is_current_behaviour(monkeypatch):
    """No configured SSID -> only the ping gates the verdict (M31)."""
    _install_probe(monkeypatch, ssid="Whatever-AP", dbm=-55)
    result = host_platform.probe_host_ap_link("192.168.1.1")
    assert result["ok"] is True


def test_probe_empty_gateway_hints_autodetect(monkeypatch):
    """Empty AP IP -> the existing FAIL plus the Auto-detect hint."""
    _install_probe(monkeypatch, ssid="DUT-AP")
    result = host_platform.probe_host_ap_link("", expected_ssid="DUT-AP")
    assert result["ok"] is False
    assert result["error"] == "no AP IP / gateway"
    assert any("Auto-detect" in line for line in result["lines"])
