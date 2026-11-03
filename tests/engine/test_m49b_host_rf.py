# -*- coding: utf-8 -*-
"""M49b: host-side Wi-Fi / Bluetooth RSSI scanning.

Covers the host_rf adapter (lswifi JSON, CoreWLAN text, bleak devices)
and the two executors that consume it (Wifi_Scan dual target, BT_RSSI)
without touching real hardware: the host command seam is monkeypatched.
"""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

import mtkgui.engine.host_rf as hr
import mtkgui.engine.fct_exec as fe
from mtkgui.engine.fct_test_config import (
    BluetoothCfg,
    FctTestConfig,
    WifiCfg,
    build_fct_steps,
)

LSWIFI_REAL_26_AP_JSON = """
[
  {"SSID": "ChinaNet-4zEc-5G", "BSSID": "aa:bb:cc:00:11:22", "RSSI": -76},
  {"SSID": "ChinaNet-4zEc", "BSSID": "aa:bb:cc:00:11:23", "RSSI": -68},
  {"SSID": "CMCC-5G-01", "BSSID": "aa:bb:cc:00:11:24", "RSSI": -82},
  {"SSID": "CMCC-2.4G-01", "BSSID": "aa:bb:cc:00:11:25", "RSSI": -74},
  {"SSID": "TP-LINK_5G_1", "BSSID": "aa:bb:cc:00:11:26", "RSSI": -61},
  {"SSID": "TP-LINK_2G_1", "BSSID": "aa:bb:cc:00:11:27", "RSSI": -70},
  {"SSID": "Xiaomi_Router_5G", "BSSID": "aa:bb:cc:00:11:28", "RSSI": -79},
  {"SSID": "Xiaomi_Router", "BSSID": "aa:bb:cc:00:11:29", "RSSI": -66},
  {"SSID": "HUAWEI-5G-2", "BSSID": "aa:bb:cc:00:11:2a", "RSSI": -85},
  {"SSID": "HUAWEI-2.4G", "BSSID": "aa:bb:cc:00:11:2b", "RSSI": -72},
  {"SSID": "FAST_5G", "BSSID": "aa:bb:cc:00:11:2c", "RSSI": -88},
  {"SSID": "FAST_2.4G", "BSSID": "aa:bb:cc:00:11:2d", "RSSI": -64},
  {"SSID": "MERCURY_5G", "BSSID": "aa:bb:cc:00:11:2e", "RSSI": -81},
  {"SSID": "MERCURY_2.4G", "BSSID": "aa:bb:cc:00:11:2f", "RSSI": -58},
  {"SSID": "Tenda_5G", "BSSID": "aa:bb:cc:00:11:30", "RSSI": -90},
  {"SSID": "Tenda_2.4G", "BSSID": "aa:bb:cc:00:11:31", "RSSI": -75},
  {"SSID": "ASUS_RT_5G", "BSSID": "aa:bb:cc:00:11:32", "RSSI": -80},
  {"SSID": "ASUS_RT_2G", "BSSID": "aa:bb:cc:00:11:33", "RSSI": -69},
  {"SSID": "Netgear-5G", "BSSID": "aa:bb:cc:00:11:34", "RSSI": -83},
  {"SSID": "Netgear-2.4G", "BSSID": "aa:bb:cc:00:11:35", "RSSI": -71},
  {"SSID": "OfficeWiFi", "BSSID": "aa:bb:cc:00:11:36", "RSSI": -55},
  {"SSID": "OfficeWiFi_5G", "BSSID": "aa:bb:cc:00:11:37", "RSSI": -60},
  {"SSID": "GuestWiFi", "BSSID": "aa:bb:cc:00:11:38", "RSSI": -77},
  {"SSID": "Lab-AP", "BSSID": "aa:bb:cc:00:11:39", "RSSI": -63},
  {"SSID": "Lab-AP-5G", "BSSID": "aa:bb:cc:00:11:3a", "RSSI": -67},
  {"SSID": "Factory-AP", "BSSID": "aa:bb:cc:00:11:3b", "RSSI": -73}
]
"""


LSWIFI_LIST_JSON = """
[
  {"ssid": "AP-Office", "bssid": "aa:bb:cc:dd:ee:01",
   "channel": 149, "rssi": -48},
  {"ssid": "AP-Office", "bssid": "aa:bb:cc:dd:ee:02",
   "channel": 44, "rssi": -61},
  {"ssid": "DUT-SoftAP", "bssid": "11:22:33:44:55:66",
   "channel": 6, "rssi": -55},
  {"ssid": "Neighbour", "bssid": "99:88:77:66:55:44",
   "channel": 11, "rssi": -80}
]
"""


COREWLAN_TEXT = """
Wi-Fi:

      Interfaces:
        en0:
          Current Network Information:
            OfficeWiFi:
              PHY Mode: 802.11ac
              Signal / Noise: -45 dBm / -92 dBm
              Channel: 149 (5GHz, 80MHz)

          Other Local Wi-Fi Networks:
            DUT-SoftAP:
              PHY Mode: 802.11n
              Signal / Noise: -55 dBm / -89 dBm
"""


class _Device:
    def __init__(self, name="", address="", rssi=None):
        self.name = name
        self.address = address
        self.rssi = rssi


def _rf_step(family, cfg, timeout_s=15.0):
    return fe.FctStep(
        name="rf", step_type="EXTERNAL_TOOL", channel="", timeout_s=timeout_s,
        params={"tool_family": family, "fct_rf": dict(cfg)})


class _Log:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


# ------------------------------------------------------- lswifi JSON parse
def test_parse_lswifi_list_shape_strongest_bssid_wins():
    found = hr.parse_lswifi_json(LSWIFI_LIST_JSON)
    assert found["AP-Office"] == -48          # two BSSIDs -> strongest
    assert found["DUT-SoftAP"] == -55
    assert found["Neighbour"] == -80


def test_parse_lswifi_networks_wrapper_and_mapping_shapes():
    wrapped = '{"networks": [{"SSID": "AP", "RSSI": -50}]}'
    assert hr.parse_lswifi_json(wrapped) == {"AP": -50}
    mapped = '{"DUT": {"rssi": -62, "channel": 6}}'
    assert hr.parse_lswifi_json(mapped) == {"DUT": -62}


def test_parse_lswifi_percentage_field_is_normalised_to_dbm():
    """M66: only an explicitly percentage-shaped field is converted."""
    found = hr.parse_lswifi_json('[{"ssid": "Pct", "Signal %": 76}]')
    assert found["Pct"] == -62                # 76 % -> -62 dBm


def test_parse_lswifi_real_26_ap_sample_keeps_the_dbm_reading():
    """M66 regression: a realistic 26-AP scan keeps ChinaNet-4zEc-5G at
    -76 dBm (the GUI used to report -24 dBm)."""
    found = hr.parse_lswifi_json(LSWIFI_REAL_26_AP_JSON)
    assert len(found) == 26
    assert found["ChinaNet-4zEc-5G"] == -76
    assert found["OfficeWiFi"] == -55
    assert -24 not in found.values()


def test_parse_lswifi_positive_dbm_field_is_not_a_percentage():
    """A positive value on a dBm field is rejected (no silent -100%)."""
    assert hr.parse_lswifi_json('[{"SSID": "X", "RSSI": 76}]') == {}


def test_parse_lswifi_skips_rows_without_ssid_or_rssi():
    found = hr.parse_lswifi_json(
        '[{"bssid": "aa", "rssi": -50}, {"ssid": "NoRssi"},'
        ' {"ssid": "", "rssi": -60}]')
    assert found == {}


def test_parse_lswifi_malformed_json_raises():
    with pytest.raises(hr.HostRfError) as exc:
        hr.parse_lswifi_json("this is not json")
    assert "lswifi output is not valid JSON" in str(exc.value)


# ----------------------------------------------------------- wifi_scan
def test_wifi_scan_windows_parses_canned_output(monkeypatch):
    monkeypatch.setattr(hr, "run_command",
                        lambda cmd, timeout_s=30, **kw: LSWIFI_LIST_JSON)
    found = hr.wifi_scan(["AP-Office", "Missing-SSID"], key="windows")
    assert found == {"AP-Office": -48, "Missing-SSID": None}


def test_wifi_scan_windows_missing_lswifi_is_error(monkeypatch):
    monkeypatch.setattr(
        hr, "run_command",
        lambda cmd, timeout_s=30, **kw:
        "'lswifi' is not recognized as an internal or external command")
    with pytest.raises(hr.HostRfError) as exc:
        hr.wifi_scan(["AP"], key="windows")
    assert "lswifi not found / scan failed" in str(exc.value)
    assert "pip install lswifi" in str(exc.value)


def test_wifi_scan_windows_malformed_output_is_error(monkeypatch):
    monkeypatch.setattr(hr, "run_command",
                        lambda cmd, timeout_s=30, **kw:
                        "<html>gateway</html>")
    with pytest.raises(hr.HostRfError) as exc:
        hr.wifi_scan(["AP"], key="windows")
    assert "not valid JSON" in str(exc.value)


def test_wifi_scan_mac_parses_corewlan_text(monkeypatch):
    monkeypatch.setattr(hr, "run_command",
                        lambda cmd, timeout_s=30, **kw: COREWLAN_TEXT)
    found = hr.wifi_scan(["OfficeWiFi", "DUT-SoftAP"], key="mac")
    assert found == {"OfficeWiFi": -45, "DUT-SoftAP": -55}


# --------------------------------------------------- M63: keep_stderr=False
def test_run_command_keep_stderr_false_strips_logs(monkeypatch):
    """M63: lswifi INFO logs go to stderr; keep_stderr=False returns
    stdout only so the JSON payload stays parseable."""
    fake = SimpleNamespace(
        stdout=LSWIFI_LIST_JSON,
        stderr="2026-11-03 13:15:23,814 [INFO] lswifi.app: "
               "exporting scans as JSON to lswifi_2026-11-03T13_15_21.json")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
    out = hr.run_command("lswifi --json", keep_stderr=False)
    assert out == LSWIFI_LIST_JSON
    assert "INFO" not in out


def test_run_command_keep_stderr_default_keeps_diagnostics(monkeypatch):
    fake = SimpleNamespace(stdout="ok", stderr="warning noise")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
    out = hr.run_command("tool")
    assert out == "ok\nwarning noise"


def test_run_command_keep_stderr_false_still_reports_missing_cmd(
        monkeypatch):
    """A missing-command marker on stderr must survive keep_stderr=False
    so the lswifi-not-installed path still triggers."""
    fake = SimpleNamespace(
        stdout="",
        stderr="'lswifi' is not recognized as an internal or external "
               "command")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
    out = hr.run_command("lswifi --json", keep_stderr=False)
    assert "'lswifi' is not recognized" in out


def test_wifi_scan_windows_ignores_stderr_logs(monkeypatch):
    """M63 end-to-end: run_command keeps stdout only, wifi_scan parses
    the scan result even though the tool wrote INFO logs to stderr."""
    fake = SimpleNamespace(
        stdout=LSWIFI_LIST_JSON,
        stderr="2026-11-03 13:15:23,814 [INFO] lswifi.app: "
               "display filter sensitivity -82; output includes 19 of "
               "21 BSSIDs")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
    found = hr.wifi_scan(["AP-Office", "DUT-SoftAP", "Missing"],
                         key="windows")
    assert found == {"AP-Office": -48, "DUT-SoftAP": -55, "Missing": None}


def test_parse_corewlan_text_ignores_section_headers():
    assert hr.parse_corewlan_text(COREWLAN_TEXT) == {
        "OfficeWiFi": -45, "DUT-SoftAP": -55}


def test_wifi_scan_unsupported_host_is_error():
    with pytest.raises(hr.HostRfError) as exc:
        hr.wifi_scan(["AP"], key="linux")
    assert "Windows (lswifi) and macOS" in str(exc.value)


def test_wifi_scan_empty_targets_is_error():
    with pytest.raises(hr.HostRfError) as exc:
        hr.wifi_scan([])
    assert "no Wi-Fi scan target configured" in str(exc.value)


def test_wifi_scan_virtual_mode_is_deterministic():
    assert hr.wifi_scan(["AP", "DUT"], virtual=True) == {
        "AP": hr.VIRTUAL_RSSI_DBM, "DUT": hr.VIRTUAL_RSSI_DBM}
    assert hr.wifi_scan(["AP"], virtual=True, virtual_rssi=-72) == {
        "AP": -72}


# ------------------------------------------------------------- bt_scan
def test_parse_bleak_devices_matches_by_address_and_name():
    devices = [
        _Device("DUT-BT", "aa-bb-cc-dd-ee-ff", -50),
        _Device("Other", "11:22:33:44:55:66", -70),
    ]
    assert hr.parse_bleak_devices(devices, "AA:BB:CC:DD:EE:FF") == -50
    assert hr.parse_bleak_devices(devices, "dut-bt") == -50
    assert hr.parse_bleak_devices(devices, "DUT") == -50      # containment
    assert hr.parse_bleak_devices(devices, "Nope") is None


def test_parse_bleak_devices_exact_name_wins_over_partial():
    devices = [
        _Device("DUT-BT", "aa:aa:aa:aa:aa:aa", -50),
        _Device("DUT-BT-Extra", "bb:bb:bb:bb:bb:bb", -30),
    ]
    assert hr.parse_bleak_devices(devices, "DUT-BT") == -50


# ------------------------------- M63: bleak callback tuples (address, name)
def test_bt_scan_parses_tuple_devices(monkeypatch):
    """M63: _bleak_discover returns (address, name, rssi) tuples; bt_scan
    matches address / exact name / containment, strongest RSSI wins -
    same semantics as the legacy _Device objects."""
    monkeypatch.setattr(
        hr, "_bleak_discover",
        lambda timeout_s=10.0: [
            ("aa:bb:cc:dd:ee:ff", "DUT-BT", -52),
            ("11:22:33:44:55:66", "Other", -70)])
    assert hr.bt_scan("AA:BB:CC:DD:EE:FF") == -52   # address, hyphen form
    assert hr.bt_scan("dut-bt") == -52              # exact name
    assert hr.bt_scan("DUT") == -52                 # containment
    assert hr.bt_scan("Nope") is None


def test_parse_bleak_devices_tuple_strongest_rssi_wins():
    devices = [("aa:aa:aa:aa:aa:aa", "DUT-BT", -60),
               ("bb:bb:bb:bb:bb:bb", "DUT-BT", -45)]
    assert hr.parse_bleak_devices(devices, "DUT-BT") == -45


def test_parse_bleak_devices_tuple_skips_missing_rssi():
    devices = [("aa:aa:aa:aa:aa:aa", "DUT-BT", None),
               ("bb:bb:bb:bb:bb:bb", "DUT-BT", -40)]
    assert hr.parse_bleak_devices(devices, "DUT-BT") == -40


def test_parse_bleak_devices_mixed_tuple_and_object():
    devices = [("aa:aa:aa:aa:aa:aa", "DUT-BT", -52),
               _Device("Other", "11:22:33:44:55:66", -70)]
    assert hr.parse_bleak_devices(devices, "dut-bt") == -52
    assert hr.parse_bleak_devices(devices, "other") == -70


def test_bt_scan_uses_discovery_seam(monkeypatch):
    monkeypatch.setattr(
        hr, "_bleak_discover",
        lambda timeout_s=10.0: [_Device("DUT-BT", "aa:bb:cc:dd:ee:ff", -52)])
    assert hr.bt_scan("DUT-BT") == -52
    assert hr.bt_scan("cc:dd") is None


def test_bt_scan_virtual_mode_is_deterministic():
    assert hr.bt_scan("DUT", virtual=True) == hr.VIRTUAL_RSSI_DBM
    assert hr.bt_scan("DUT", virtual=True, virtual_rssi=-80) == -80


def test_bleak_import_missing_is_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "bleak", None)
    with pytest.raises(hr.HostRfError) as exc:
        hr._bleak_discover()
    assert "bleak is not installed" in str(exc.value)
    assert "pip install bleak" in str(exc.value)


# ------------------------------------------- Wifi_Scan step (dual target)
def test_wifi_step_dual_target_each_own_threshold_pass(monkeypatch):
    seen = {}

    def fake_scan(ssids, **kw):
        seen["ssids"] = list(ssids)
        return {"AP-Office": -48, "DUT-SoftAP": -55}

    monkeypatch.setattr(hr, "wifi_scan", fake_scan)
    out = fe._run_rf_tool(_rf_step("wifi", {
        "mode": "rssi_only",
        "targets": [{"role": "AP", "ssid": "AP-Office", "rssi_min": -60},
                    {"role": "DUT", "ssid": "DUT-SoftAP",
                     "rssi_min": -58}]}), "wifi", fe.FctContext())
    assert seen["ssids"] == ["AP-Office", "DUT-SoftAP"]
    assert out.verdict == fe.VERDICT_PASS
    assert 'AP "AP-Office": -48 dBm (min -60 dBm) PASS' in out.reason
    assert 'DUT "DUT-SoftAP": -55 dBm (min -58 dBm) PASS' in out.reason


def test_wifi_step_below_own_threshold_fails_with_attribution(monkeypatch):
    monkeypatch.setattr(hr, "wifi_scan",
                        lambda ssids, **kw: {"AP-Office": -48,
                                             "DUT-SoftAP": -55})
    out = fe._run_rf_tool(_rf_step("wifi", {
        "mode": "rssi_only",
        "targets": [{"role": "AP", "ssid": "AP-Office", "rssi_min": -60},
                    {"role": "DUT", "ssid": "DUT-SoftAP",
                     "rssi_min": -50}]}), "wifi", fe.FctContext())
    assert out.verdict == fe.VERDICT_FAIL
    assert 'AP "AP-Office": -48 dBm (min -60 dBm) PASS' in out.reason
    assert 'DUT "DUT-SoftAP": -55 dBm (min -50 dBm) FAIL' in out.reason


def test_wifi_step_missing_ssid_is_fail_with_cause(monkeypatch):
    monkeypatch.setattr(hr, "wifi_scan",
                        lambda ssids, **kw: {s: None for s in ssids})
    out = fe._run_rf_tool(_rf_step("wifi", {
        "mode": "rssi_only",
        "targets": [{"role": "DUT", "ssid": "DUT-SoftAP",
                     "rssi_min": -60}]}), "wifi", fe.FctContext())
    assert out.verdict == fe.VERDICT_FAIL
    assert 'DUT "DUT-SoftAP": not found' in out.reason


def test_wifi_step_no_target_is_error():
    out = fe._run_rf_tool(_rf_step("wifi", {"mode": "rssi_only"}),
                          "wifi", fe.FctContext())
    assert out.verdict == fe.VERDICT_ERROR
    assert "no Wi-Fi scan target" in out.reason


def test_wifi_step_host_backend_error_is_error(monkeypatch):
    def _boom(ssids, **kw):
        raise hr.HostRfError("lswifi not found / scan failed")

    monkeypatch.setattr(hr, "wifi_scan", _boom)
    log = _Log()
    ctx = fe.FctContext(log_sink=log)
    out = fe._run_rf_tool(_rf_step("wifi", {
        "mode": "rssi_only",
        "targets": [{"role": "AP", "ssid": "AP-Office",
                     "rssi_min": -60}]}), "wifi", ctx)
    assert out.verdict == fe.VERDICT_ERROR
    assert "lswifi not found" in out.reason
    assert any("wifi scan failed" in line for line in log.lines)


def test_wifi_step_virtual_mode_pass_and_fail():
    find = fe._run_rf_tool(_rf_step("wifi", {
        "mode": "rssi_only", "virtual": True,
        "targets": [{"role": "AP", "ssid": "AP", "rssi_min": -60}]}),
        "wifi", fe.FctContext())
    assert find.verdict == fe.VERDICT_PASS
    fail = fe._run_rf_tool(_rf_step("wifi", {
        "mode": "rssi_only", "virtual": True, "virtual_rssi": -80,
        "targets": [{"role": "AP", "ssid": "AP", "rssi_min": -60}]}),
        "wifi", fe.FctContext())
    assert fail.verdict == fe.VERDICT_FAIL


def test_wifi_scan_targets_legacy_single_target():
    assert fe._wifi_scan_targets({"ssid": "AP", "rssi_min": -60}) == [
        {"role": "AP", "ssid": "AP", "rssi_min": -60}]
    assert fe._wifi_scan_targets({}) == []


# --------------------------------------------------- BT_RSSI step (bleak)
def test_bt_step_match_by_name(monkeypatch):
    monkeypatch.setattr(hr, "bt_scan", lambda target, **kw: -50)
    out = fe._run_rf_tool(_rf_step("bluetooth", {
        "mode": "rssi_only", "expected_name": "DUT-BT",
        "rssi_min": -70}), "bluetooth", fe.FctContext())
    assert out.verdict == fe.VERDICT_PASS
    assert 'BT "DUT-BT": -50 dBm (min -70 dBm) PASS' in out.reason


def test_bt_step_match_by_addr(monkeypatch):
    monkeypatch.setattr(hr, "bt_scan", lambda target, **kw: -55)
    out = fe._run_rf_tool(_rf_step("bluetooth", {
        "mode": "rssi_only", "expected_addr": "AA:BB:CC:DD:EE:FF",
        "expected_name": "DUT-BT", "rssi_min": -70}),
        "bluetooth", fe.FctContext())
    assert out.verdict == fe.VERDICT_PASS
    assert "AA:BB:CC:DD:EE:FF" in out.reason


def test_bt_step_not_found_is_fail_with_cause(monkeypatch):
    monkeypatch.setattr(hr, "bt_scan", lambda target, **kw: None)
    log = _Log()
    ctx = fe.FctContext(log_sink=log)
    out = fe._run_rf_tool(_rf_step("bluetooth", {
        "mode": "rssi_only", "expected_name": "DUT-BT",
        "rssi_min": -70}), "bluetooth", ctx)
    assert out.verdict == fe.VERDICT_FAIL
    assert 'BT scan failed / DUT "DUT-BT" not found' in out.reason
    assert "is it broadcasting?" in out.reason
    assert any("BT RSSI" in line for line in log.lines)


def test_bt_step_below_threshold_fails(monkeypatch):
    monkeypatch.setattr(hr, "bt_scan", lambda target, **kw: -78)
    out = fe._run_rf_tool(_rf_step("bluetooth", {
        "mode": "rssi_only", "expected_name": "DUT-BT",
        "rssi_min": -70}), "bluetooth", fe.FctContext())
    assert out.verdict == fe.VERDICT_FAIL
    assert "min -70 dBm) FAIL" in out.reason


def test_bt_step_no_target_is_error():
    out = fe._run_rf_tool(_rf_step("bluetooth", {"mode": "rssi_only"}),
                          "bluetooth", fe.FctContext())
    assert out.verdict == fe.VERDICT_ERROR
    assert "no Bluetooth target" in out.reason


def test_bt_step_host_backend_error_is_error(monkeypatch):
    def _boom(target, **kw):
        raise hr.HostRfError("bleak is not installed")

    monkeypatch.setattr(hr, "bt_scan", _boom)
    out = fe._run_rf_tool(_rf_step("bluetooth", {
        "mode": "rssi_only", "expected_name": "DUT-BT"}),
        "bluetooth", fe.FctContext())
    assert out.verdict == fe.VERDICT_ERROR
    assert "bleak" in out.reason


def test_bt_step_virtual_mode_pass_and_fail():
    find = fe._run_rf_tool(_rf_step("bluetooth", {
        "mode": "rssi_only", "virtual": True,
        "expected_name": "DUT-BT", "rssi_min": -60}),
        "bluetooth", fe.FctContext())
    assert find.verdict == fe.VERDICT_PASS
    fail = fe._run_rf_tool(_rf_step("bluetooth", {
        "mode": "rssi_only", "virtual": True, "virtual_rssi": -80,
        "expected_name": "DUT-BT", "rssi_min": -60}),
        "bluetooth", fe.FctContext())
    assert fail.verdict == fe.VERDICT_FAIL


# ----------------------------------- built steps carry the host scan cfg
def test_built_wifi_step_carries_dual_targets():
    cfg = FctTestConfig(dut_type="bare_metal",
                        wifi=WifiCfg(scan_enabled=True, ap_ssid="AP-Office",
                                     rssi_min=-60, dut_ssid="DUT-SoftAP",
                                     dut_rssi_min=-58))
    steps = build_fct_steps(cfg)
    wifi = next(s for s in steps
                if s.params.get("tool_family") == "wifi")
    assert wifi.name == "Wi-Fi Scan / RSSI"
    assert wifi.params["fct_rf"]["mode"] == "rssi_only"
    assert wifi.params["fct_rf"]["targets"] == [
        {"role": "AP", "ssid": "AP-Office", "rssi_min": -60},
        {"role": "DUT", "ssid": "DUT-SoftAP", "rssi_min": -58}]


def test_built_wifi_step_single_target_without_dut_ssid():
    cfg = FctTestConfig(dut_type="bare_metal",
                        wifi=WifiCfg(scan_enabled=True, ap_ssid="AP-Office",
                                     rssi_min=-60))
    step = build_fct_steps(cfg)[0]
    assert step.params["fct_rf"]["targets"] == [
        {"role": "AP", "ssid": "AP-Office", "rssi_min": -60}]


def test_built_bt_step_carries_addr_and_name():
    cfg = FctTestConfig(dut_type="bare_metal",
                        bluetooth=BluetoothCfg(
                            rssi_enabled=True, expected_name="DUT-BT",
                            expected_addr="AA:BB:CC:DD:EE:FF",
                            rssi_min=-70))
    step = build_fct_steps(cfg)[-1]
    assert step.name == "Bluetooth RSSI"
    assert step.params["fct_rf"]["mode"] == "rssi_only"
    assert step.params["fct_rf"]["expected_addr"] == "AA:BB:CC:DD:EE:FF"
    assert step.params["fct_rf"]["expected_name"] == "DUT-BT"
