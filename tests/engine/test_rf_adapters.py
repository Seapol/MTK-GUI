# -*- coding: utf-8 -*-
"""P3-B4 Modules D/E/F: rf_adapters unit tests (stubbed commands)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from mtkgui.engine.host_cli import HostCliRunner
from mtkgui.engine.rf_adapters import (
    BluetoothAdapter,
    PlatformBackendMissing,
    WifiAdapter,
    _backend_section,
    backend_key_for,
)


class StubRunner(HostCliRunner):
    """Scripted runner: maps command templates to canned outputs."""

    def __init__(self, script: dict) -> None:
        super().__init__(station_id="ST", user="t")
        self.script = script
        self.calls: list = []

    def run(self, template, params=None, **kw):    # noqa: D102
        cmd = template
        for k, v in (params or {}).items():
            cmd = cmd.replace("{{" + k + "}}", str(v))
        self.calls.append(cmd)
        exit_code, lines = self.script.get(cmd, (0, []))
        return self._make(cmd, lines, exit_code,
                          kw.get("regex_extracts"))

    @staticmethod
    def _make(cmd, lines, exit_code, regex_extracts=None):
        from mtkgui.engine.host_cli import HostCliResult
        from mtkgui.engine.host_cli import judge_keywords, extract_items
        verdict, reason = judge_keywords(lines, exit_code=exit_code)
        return HostCliResult(cmd, list(lines), exit_code, 0.0,
                             verdict, reason,
                             extract_items(lines, regex_extracts))


WIFI_CFG = {
    "wifi": {
        "mode": "full_stack",
        "expected_ssid": "DUT-AP",
        "password": "pw",
        "gateway": "192.168.1.1",
        "rssi_min": -70,
        "cmds": {
            "mac": {
                "list_networks_cmd": "networksetup -listpreferredwirelessnetworks en0",
                "remove_network_cmd": "networksetup -removepreferredwirelessnetwork en0 {{ssid}}",
                "connect_cmd": "networksetup -setairportnetwork en0 {{ssid}} {{password}}",
                "add_network_cmd": "networksetup -addpreferredwirelessnetwork en0 {{ssid}}",
                "rssi_cmd": "system_profiler SPAirPortDataType",
                "rssi_parse": r"Signal / Noise: (-?\d+) dBm",
                "ping_cmd": "ping -c {{count}} {{gateway}}",
            },
            "windows": {"_todo": "pending Windows acceptance"},
        },
    },
}

RSSI_OK = ("SSID: DUT-AP\n"
           "  Signal / Noise: -41 dBm")
RSSI_BAD = ("SSID: DUT-AP\n"
            "  Signal / Noise: -85 dBm")
PING_OK = ("20 packets transmitted, 20 received\n"
           "0.0% packet loss")


def _wifi_script():
    return {
        "networksetup -listpreferredwirelessnetworks en0":
            (0, ["Preferred networks on en0:", "HomeNet", "Office"]),
        "networksetup -removepreferredwirelessnetwork en0 HomeNet": (0, []),
        "networksetup -removepreferredwirelessnetwork en0 Office": (0, []),
        "networksetup -setairportnetwork en0 DUT-AP pw": (0, []),
        "networksetup -addpreferredwirelessnetwork en0 HomeNet": (0, []),
        "networksetup -addpreferredwirelessnetwork en0 Office": (0, []),
        "system_profiler SPAirPortDataType": (0, RSSI_OK.split("\n")),
        "ping -c 20 192.168.1.1": (0, PING_OK.split("\n")),
    }


# ------------------------------------------------------------------ F: keys
def test_backend_key_mapping():
    assert backend_key_for("Darwin") == "mac"
    assert backend_key_for("Windows") == "windows"
    assert backend_key_for("Unknown") == "unknown"


def test_windows_todo_backend_raises_explicitly():
    with pytest.raises(PlatformBackendMissing):
        _backend_section(WIFI_CFG, "wifi", key="windows")


def test_missing_backend_raises_not_silent():
    cfg = {"wifi": {"cmds": {"mac": {"rssi_cmd": "x"}}}}
    with pytest.raises(PlatformBackendMissing):
        _backend_section(cfg, "bluetooth")


# ------------------------------------------------------------------ D: wifi
def test_wifi_full_stack_pass():
    r = StubRunner(_wifi_script())
    ad = WifiAdapter(WIFI_CFG, r)
    out = ad.run_test()
    assert out["verdict"] == "Pass"
    assert out["items"]["rssi"] == -41
    assert out["items"]["loss_pct"] == 0.0
    joined = "\n".join(r.calls)
    # competing networks removed then restored
    assert joined.count("removepreferredwirelessnetwork") == 2
    assert joined.count("addpreferredwirelessnetwork") == 2
    assert "system_profiler SPAirPortDataType" in joined
    assert "ping -c 20 192.168.1.1" in joined


def test_wifi_full_stack_rssi_fail():
    s = _wifi_script()
    s["system_profiler SPAirPortDataType"] = (0, RSSI_BAD.split("\n"))
    ad = WifiAdapter(WIFI_CFG, StubRunner(s))
    assert ad.run_test()["verdict"] == "Fail"


def test_wifi_full_stack_ping_loss_fail():
    s = _wifi_script()
    s["ping -c 20 192.168.1.1"] = (
        0, ["30.0% packet loss"])
    ad = WifiAdapter(WIFI_CFG, StubRunner(s))
    out = ad.run_test()
    assert out["verdict"] == "Fail"
    assert out["items"]["loss_pct"] == 30.0


def test_wifi_rssi_only_never_connects():
    cfg = {"wifi": dict(WIFI_CFG["wifi"], mode="rssi_only")}
    r = StubRunner({"system_profiler SPAirPortDataType":
                    (0, RSSI_OK.split("\n"))})
    ad = WifiAdapter(cfg, r)
    out = ad.run_test()
    assert out["verdict"] == "Pass" and out["items"]["rssi"] == -41
    joined = "\n".join(r.calls)
    assert "setairportnetwork" not in joined
    assert "ping" not in joined


def test_wifi_rssi_only_ssid_not_found():
    cfg = {"wifi": dict(WIFI_CFG["wifi"], mode="rssi_only")}
    ad = WifiAdapter(cfg, StubRunner({}))
    assert ad.run_test()["verdict"] == "Fail"


def test_wifi_iperf3_receiver_line_parsed():
    """iperf item must come from the RECEIVER summary line, not an
    intermediate interval row."""
    cfg = {"wifi": dict(WIFI_CFG["wifi"], iperf3=True,
                        iperf_timeout_s=20)}
    s = _wifi_script()
    s["iperf3 -c 127.0.0.1 -t 5 -O 1"] = (0, [
        "[  5]   0.00-1.00   sec  1.10 MBytes  9.2 Mbits/sec  0.1 ms",
        "- - - - - - - - - - - - - - - - - - - - - - - - -",
        "[ ID] Interval        Transfer     Bitrate",
        "[  5]   0.00-5.00   sec  55.0 MBytes  92.3 Mbits/sec  receiver",
        "iperf Done."])
    cfg["wifi"]["cmds"]["mac"]["iperf_cmd"] = "iperf3 -c {{ip}} -t 5 -O 1"
    ad = WifiAdapter(cfg, StubRunner(s))
    out = ad.run_test(test_vars={"dut_ip": "127.0.0.1"})
    assert out["items"]["throughput"] == "92.3"
    assert out["verdict"] == "Pass"          # iperf does not gate


def test_wifi_iperf3_disabled_is_absent():
    ad = WifiAdapter(WIFI_CFG, StubRunner(_wifi_script()))
    out = ad.run_test()
    assert "throughput" not in out["items"]


# ---------------------------------------------------------------- E: bt
BT_CFG = {
    "bluetooth": {
        "mode": "a2dp_sink",
        "expected_name": "JBL Pulse 5",
        "rssi_min": -70,
        "cmds": {
            "mac": {
                "scan_cmd": "blueutil --inquiry {{seconds}}",
                "addr_parse": r"address: ([0-9a-fA-F:-]{17})",
                "connect_cmd": "blueutil --connect {{addr}}",
                "verify_cmd": "blueutil --is-connected {{addr}}",
                "disconnect_cmd": "blueutil --disconnect {{addr}}",
                "rssi_cmd": "system_profiler SPBluetoothDataType",
                "rssi_parse": r"RSSI: (-?\d+)",
                "audio_switch_cmd": "switchaudio-output {{name}}",
                "tone_cmd": "afplay {{tone}}",
            },
            "windows": {"_todo": "pending Windows acceptance"},
        },
    },
}

INQUIRY_HIT = ("address: 40-c1-f6-84-8f-c5, name: JBL Pulse 5, "
               "RSSI: -55 dBm")


def test_bt_a2dp_sink_pass():
    script = {
        "blueutil --inquiry 10": (0, [INQUIRY_HIT]),
        "blueutil --connect 40:c1:f6:84:8f:c5": (0, []),
        "blueutil --is-connected 40:c1:f6:84:8f:c5": (0, ["1"]),
        "system_profiler SPBluetoothDataType": (
            0, ["JBL Pulse 5", "RSSI: -55"]),
        "switchaudio-output JBL Pulse 5": (0, []),
        "afplay resources/test_tone.wav": (0, ["Success"]),
        "blueutil --disconnect 40:c1:f6:84:8f:c5": (0, []),
    }
    confirms = []
    ad = BluetoothAdapter(BT_CFG, StubRunner(script),
                          human_confirm=lambda q: (confirms.append(q),
                                                   True)[1])
    out = ad.run_test()
    assert out["verdict"] == "Pass"
    assert out["items"]["connected"] == 1
    assert out["items"]["operator_confirmed"] == 1
    assert "Do you hear audio" in confirms[0]
    joined = "\n".join(script)  # noqa: F841
    calls = ad._runner.calls
    assert calls[-1].startswith("blueutil --disconnect")


def test_bt_a2dp_sink_operator_fail():
    script = {
        "blueutil --inquiry 10": (0, [INQUIRY_HIT]),
        "blueutil --connect 40:c1:f6:84:8f:c5": (0, []),
        "blueutil --is-connected 40:c1:f6:84:8f:c5": (0, ["1"]),
        "system_profiler SPBluetoothDataType": (0, ["RSSI: -55"]),
        "switchaudio-output JBL Pulse 5": (0, []),
        "afplay resources/test_tone.wav": (0, []),
        "blueutil --disconnect 40:c1:f6:84:8f:c5": (0, []),
    }
    ad = BluetoothAdapter(BT_CFG, StubRunner(script),
                          human_confirm=lambda q: False)
    assert ad.run_test()["verdict"] == "Fail"


def test_bt_a2dp_sink_not_found():
    ad = BluetoothAdapter(BT_CFG, StubRunner({}),
                          human_confirm=lambda q: True)
    out = ad.run_test()
    assert out["verdict"] == "Fail"
    assert any("not found" in l for l in out["lines"])


def test_bt_rssi_only_never_connects():
    cfg = {"bluetooth": dict(BT_CFG["bluetooth"], mode="rssi_only")}
    r = StubRunner({"blueutil --inquiry 10": (0, [INQUIRY_HIT])})
    out = BluetoothAdapter(cfg, r).run_test()
    assert out["verdict"] == "Pass" and out["items"]["rssi"] == -55
    joined = "\n".join(r.calls)
    assert "connect" not in joined
    assert "afplay" not in joined
