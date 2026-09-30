# -*- coding: utf-8 -*-
"""RealGateway against mocked mtkgui.drivers responses (T1 API shape):
the engine decides PASS/FAIL from the YAML limits, the drivers only
report measurement facts; missing module/config degrades to Error."""
from __future__ import annotations

import pytest

from mtkgui.engine.instruments import (
    DriverUnavailable,
    GatewayOutcome,
    RealGateway,
    judge_limits,
)

EQUIPMENT = {
    "daq973a": {"fields": {"Address": "GPIB0::9::INSTR"}},
    "u2355a": {"fields": {"Address": "USB0::U2355A::INSTR"}},
    "psu": {"fields": {"Address": "TCPIP0::192.168.1.20::inst0"}},
    "jlink": {"fields": {"Address": "JLinkExe"}},
    "fixture": {"fields": {"Channel": "DIO16"}},
    "measure_channels": {"TP_P01": "CH101", "CLK1": "TOTAL1"},
    "rail_channels": ["AI1"],
}


@pytest.fixture
def gw(scripted_drivers):
    return RealGateway(EQUIPMENT)


class TestLimitJudgment:
    def test_inside_limits(self):
        assert judge_limits(3.3, "3.201", "3.399") is None

    def test_below_min(self):
        assert judge_limits(1.0, "1.5", "") == "FAIL"

    def test_above_max(self):
        assert judge_limits(3.5, "3.201", "3.399") == "FAIL"

    def test_open_bounds(self):
        assert judge_limits(-100.0, "—", "—") is None

    def test_record_only(self):
        assert judge_limits(42.0, "", "") is None


class TestDriverAvailability:
    def test_missing_module_reports_unavailable(self):
        # fixture not used: no mtkgui.drivers stub installed
        g = RealGateway(EQUIPMENT)
        if g.available:
            pytest.skip("real mtkgui.drivers importable")
        out = g.measure_row("Power Voltage", "TP_P01", "V",
                            "3.2", "3.4")
        assert out.verdict == "Error"
        assert "not available" in out.lines[0]

    def test_missing_module_rail_capture_is_error(self):
        g = RealGateway(EQUIPMENT)
        if g.available:
            pytest.skip("real mtkgui.drivers importable")
        frac, volts, anomaly = g.capture_rails(
            [("V", "#c00", 3.3, 0.0)], -0.5, 0.5, 100)
        assert anomaly == "error"


class TestOpSteps:
    def test_instruments_init_identifies(self, gw, scripted_drivers):
        out = gw.execute_op("Init Instruments", {
            "type": "instruments", "instruments": ["DAQM", "PSU"]})
        assert out.verdict == "Done"
        assert any("DAQM init OK" in ln for ln in out.lines)
        # addresses came from the YAML equipment section
        assert ("open", "DAQ973A", "GPIB0::9::INSTR") in \
            scripted_drivers._record.calls

    def test_reset_resets_psu(self, gw, scripted_drivers):
        out = gw.execute_op("Reset Instruments", {
            "type": "reset", "instruments": ["PSU"]})
        assert out.verdict == "Done"
        assert ("reset", "PSU") in scripted_drivers._record.calls

    def test_power_on_with_readback(self, gw, scripted_drivers):
        out = gw.execute_op("Power On DUT", {
            "type": "power", "voltage": 5.0, "current": 1.0})
        assert out.verdict == "Done"
        assert ("set_v", 5.0) in scripted_drivers._record.calls
        assert ("out_on",) in scripted_drivers._record.calls

    def test_power_off(self, gw, scripted_drivers):
        out = gw.execute_op("Power Off DUT", {"type": "power"})
        assert out.verdict == "Done"
        assert ("out_off",) in scripted_drivers._record.calls

    def test_fixture_writes_dio(self, gw, scripted_drivers):
        out = gw.execute_op("Fixture Clamp Down", {
            "type": "fixture", "signal": "press", "level": "H"})
        assert out.verdict == "Done"
        assert ("dio", "DIO16", 1) in scripted_drivers._record.calls

    def test_flash_uses_jlink(self, gw, scripted_drivers):
        out = gw.execute_op("Flash FAT Firmware", {
            "type": "flash", "slot": "fat",
            "image": "firmware/fat.bin"})
        assert out.verdict == "Done"
        assert out.value == 524288
        assert ("flash", "firmware/fat.bin", True) in \
            scripted_drivers._record.calls
        # device name came from op_params -> open call
        opens = [c for c in scripted_drivers._record.calls
                 if c[0] == "open" and c[1] == "JLINK"]
        # device only recorded when op_params carries it
        assert out.lines and "524288 bytes OK" in out.lines[0]

    def test_flash_without_image_is_config_error(self, gw):
        out = gw.execute_op("Flash OOBE Firmware",
                            {"type": "flash", "slot": "oobe"})
        assert out.verdict == "Error"
        assert "not configured" in out.lines[0]

    def test_missing_address_is_config_error(self, scripted_drivers):
        g = RealGateway({"daq973a": {"fields": {}}})
        out = g.execute_op("Init Instruments", {
            "type": "instruments", "instruments": ["DAQM"]})
        assert out.verdict == "Error"
        assert "no 'Address' field" in out.lines[0]

    def test_unknown_generic_op_done(self, gw):
        out = gw.execute_op("Custom Operation", {})
        assert out.verdict == "Done"


class TestMeasureRows:
    def test_resistance_within_limit_passes(self, gw):
        out = gw.measure_row("Static Impedance", "TP_P01", "Ω",
                             "1.5", "", force=None)
        assert out.verdict == "PASS"
        assert out.text == "12.34 Ω"

    def test_voltage_out_of_limit_fails_in_engine(self, gw,
                                                  scripted_drivers):
        # stub reports 3.301 V; the YAML max decides the verdict
        out = gw.measure_row("Power Voltage", "TP_P01", "V",
                             "3.201", "3.21")
        assert out.verdict == "FAIL"
        assert "out of limit" in out.lines[0]

    def test_frequency_dispatch_to_daqm(self, gw, scripted_drivers):
        out = gw.measure_row("Clock Hz", "CLK1", "Hz",
                             "3996000", "4004000")
        assert out.verdict == "PASS"

    def test_frequency_dispatch_to_u2355a_counter(self, gw):
        # CLK2/CLK3 channels run on the U2355A counters
        gw._equipment["measure_channels"]["CLKOUT2"] = "CLK2"
        out = gw.measure_row("Clock Hz", "CLKOUT2", "Hz",
                             "3996000", "4004000")
        assert out.verdict == "PASS"

    def test_unmapped_channel_is_config_error(self, gw):
        out = gw.measure_row("Power Voltage", "UNMAPPED", "V",
                             "3.2", "3.4")
        assert out.verdict == "Error"
        assert "measure_channels" in out.lines[0]

    def test_unsupported_kind_is_config_error(self, gw):
        out = gw.measure_row("test", "TP_P01", "kPa", "—", "—")
        assert out.verdict == "Error"

    def test_force_fail_hook(self, gw):
        out = gw.measure_row("Static Impedance", "TP_P01", "Ω",
                             "1.5", "", force="FAIL")
        assert out.verdict == "FAIL"


class TestRailCapture:
    def test_capture_shape(self, gw):
        rails = [("VDD_3V3", "#c00", 3.3, 0.0)]
        frac, volts, anomaly = gw.capture_rails(
            rails, -0.5, 0.5, 100, force=None)
        assert anomaly is None
        assert len(volts[0]) == 100
        assert len(frac[0]) == 100
        assert volts[0][-1] == pytest.approx(3.3)
        assert frac[0][-1] == pytest.approx(1.0)

    def test_forced_fail_flags_rail(self, gw):
        rails = [("VDD_3V3", "#c00", 3.3, 0.0)]
        _f, _v, anomaly = gw.capture_rails(
            rails, -0.5, 0.5, 100, force="FAIL")
        assert anomaly == "VDD_3V3"

    def test_missing_rail_channels_is_error(self, gw):
        gw._equipment.pop("rail_channels")
        frac, volts, anomaly = gw.capture_rails(
            [("V", "#c00", 3.3, 0.0)], 0.0, 0.1, 100)
        assert anomaly == "error"
        assert frac is None and volts is None


class TestRFTests:
    def test_wifi_pass(self, gw, scripted_drivers):
        cfg = {"ssid": "NET", "password": "pw", "target_ip": "1.2.3.4",
               "limits": {"min_rssi_dbm": -70}}
        out = gw.rf_test("WIFI", "WIFI: scan", cfg)
        assert out.verdict == "PASS"
        assert ("wifi", "NET") in scripted_drivers._record.calls

    def test_wifi_fail_verdict(self, gw):
        cfg = {"ssid": "NET", "password": "pw", "target_ip": "1.2.3.4",
               "limits": {}}   # min_rssi missing -> stub FAILs
        out = gw.rf_test("WIFI", "WIFI: scan", cfg)
        assert out.verdict == "FAIL"

    def test_wifi_missing_config_is_engine_error(self, gw):
        out = gw.rf_test("WIFI", "WIFI: scan", None)
        assert out.verdict == "Error"
        assert "missing" in out.lines[0]

    def test_bluetooth(self, gw):
        out = gw.rf_test("Bluetooth", "BT: pair", {"mac": "AA:BB"})
        assert out.verdict == "PASS"

    def test_unknown_rf_kind(self, gw):
        out = gw.rf_test("NFC", "NFC", {})
        assert out.verdict == "Error"


class TestOutcome:
    def test_gateway_outcome_defaults(self):
        out = GatewayOutcome("Done")
        assert out.lines == []
        assert out.value is None

    def test_close_is_safe(self, gw):
        gw.close()
        assert gw._drivers == {}
