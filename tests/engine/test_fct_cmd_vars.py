# -*- coding: utf-8 -*-
"""m109: {{host_bt_addr}} deployment token in the FCT console cmd map."""
from __future__ import annotations

from mtkgui.engine import fct_test_runner as ftr
from mtkgui.engine.fct_test_config import BluetoothCfg, WifiCfg


def _cfg(host_ip: str = ""):
    w = WifiCfg(ap_ssid="SiteSSID", ap_password="SitePass", host_ip=host_ip)
    b = BluetoothCfg(expected_name="FRDM-IMX93-DUT")
    return w, b


def test_build_cmd_vars_includes_host_bt_addr(monkeypatch):
    monkeypatch.setattr(ftr, "host_bt_identity",
                        lambda: ("HOST-PC", "AA:BB:CC:DD:EE:FF"))
    monkeypatch.setattr(ftr, "host_lan_ip", lambda: "192.168.71.8")
    w, b = _cfg()
    v = ftr._build_cmd_vars(w, b)
    assert v["host_bt_addr"] == "AA:BB:CC:DD:EE:FF"
    assert v["ssid"] == "SiteSSID"
    assert v["password"] == "SitePass"
    assert v["host_ip"] == "192.168.71.8"
    assert v["bt_name"] == "FRDM-IMX93-DUT"


def test_build_cmd_vars_host_bt_token_stays_unresolved(monkeypatch):
    """M117: an unknown address keeps the literal token, so the DUT-side
    guard still reports BT_L2CAP_UNCONFIGURED instead of `l2ping ""`."""
    monkeypatch.setattr(ftr, "host_bt_identity", lambda: ("DLRM9K3", ""))
    monkeypatch.setattr(ftr, "host_lan_ip", lambda: "192.168.71.8")
    w, b = _cfg()
    v = ftr._build_cmd_vars(w, b)
    assert v["host_bt_addr"] == "{{host_bt_addr}}"


def test_build_cmd_vars_host_bt_addr_keeps_placeholder_when_unknown(
        monkeypatch):
    monkeypatch.setattr(ftr, "host_bt_identity", lambda: ("", ""))
    monkeypatch.setattr(ftr, "host_lan_ip", lambda: "192.168.71.8")
    w, b = _cfg()
    v = ftr._build_cmd_vars(w, b)
    assert v["host_bt_addr"] == "{{host_bt_addr}}"
    # the replace is idempotent: the braces survive to the DUT guard
    command = 'P="{{host_bt_addr}}"; echo "$P" | grep -q "{"'
    rendered = command.replace("{{host_bt_addr}}", v["host_bt_addr"])
    assert '"{{host_bt_addr}}"' in rendered
