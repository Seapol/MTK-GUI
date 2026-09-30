# -*- coding: utf-8 -*-
"""Step definition helpers (mtkgui.engine.steps)."""
from __future__ import annotations

import pytest

from mtkgui.engine.results import StepStatus
from mtkgui.engine.steps import (
    CONSOLE_KINDS,
    FCT_METHODS,
    OP_STEPS,
    console_keyword_fallback,
    display_text,
    fct_kind_from_name,
    is_impedance_short,
    meas_instrument_abbr,
    op_instrument_abbr,
    op_status_lines,
    op_step,
    op_summary,
    parse_console_step,
    steps_template,
)


class TestOpCatalog:
    def test_op_step_default_params(self):
        step = op_step("Power On DUT")
        assert step[0] == "op"
        assert step[1] == "Power On DUT"
        assert step[6] == {"type": "power", "voltage": 5.0,
                           "current": 1.0}

    def test_op_step_params_are_copies(self):
        a, b = op_step("Power On DUT"), op_step("Power On DUT")
        assert a[6] == b[6] and a[6] is not b[6]

    def test_op_step_unknown_name_gets_empty_params(self):
        assert op_step("Custom Op")[6] == {}

    def test_op_summary_variants(self):
        assert op_summary({"type": "instruments",
                           "instruments": ["DAQM", "PSU"]}) == "DAQM+PSU"
        assert op_summary({"type": "fixture", "signal": "press",
                           "level": "H"}) == "press=H"
        assert op_summary({"type": "power", "voltage": 5.0,
                           "current": 1.0}) == "5V/1A"
        assert op_summary({"type": "flash", "slot": "fat",
                           "image": "fw.bin"}) == "JLink fat fw.bin"
        assert op_summary(None) == ""

    def test_op_status_lines_per_type(self):
        assert op_status_lines("Init Instruments", {
            "type": "instruments",
            "instruments": ["DAQM", "PSU"]}) == \
            ["DAQM init OK", "PSU init OK"]
        assert op_status_lines("Power On DUT", {
            "type": "power", "voltage": 5.0, "current": 1.0}) == [
            "N5747A set 5.00 V / 1.00 A -> output ON, readback OK"]
        assert op_status_lines("Power Off DUT", {"type": "power"}) == \
            ["N5747A output OFF"]
        # flash steps (FAT / OOBE firmware flash) produce J-Link lines
        lines = op_status_lines("Flash FAT Firmware", {
            "type": "flash", "slot": "fat", "image": "fw/fat.bin"})
        assert lines == ["J-Link loadfile fw/fat.bin",
                         "J-Link verify OK", "J-Link reset & run"]

    def test_op_instrument_abbr(self):
        assert op_instrument_abbr({"type": "power"}) == "PSU"
        assert op_instrument_abbr({"type": "fixture"}) == "DAQM"
        assert op_instrument_abbr({"type": "flash"}) == "JLINK"

    def test_meas_instrument_abbr(self):
        assert meas_instrument_abbr("Clock Hz",
                                    "CLKOUT2 - 6 MHz (TP_C02)") == "DAQ"
        assert meas_instrument_abbr("test", "DUT GPIO (24 ch)") == "DAQ"
        assert meas_instrument_abbr("Power Voltage", "TP_P01 x") == "DAQM"

    def test_flash_steps_in_catalog(self):
        # the production sequence drives FAT / OOBE flash as op steps
        assert OP_STEPS["Flash FAT Firmware"]["slot"] == "fat"
        assert OP_STEPS["Flash OOBE Firmware"]["slot"] == "oobe"


class TestFctKinds:
    def test_known_method_prefix(self):
        assert fct_kind_from_name("SendtoCLI: \"cmd\"") == "SendtoCLI"

    def test_op_name(self):
        assert fct_kind_from_name("Power On DUT") == "op"

    def test_unknown_falls_back_to_message_ok(self):
        assert fct_kind_from_name("Mystery check") == "MessageOK"

    def test_console_kinds_subset(self):
        assert set(CONSOLE_KINDS) <= set(FCT_METHODS)


class TestImpedanceShort:
    @pytest.mark.parametrize("step", [
        ("Static Impedance", "Net A-B", "Ω", "—", "1.5", ""),
        ("test", "Impedance Shorts (80 pts)", "Ω", "80/80", "1.5", ""),
        ("test", "TP_P01 net", "Ω", "—", "1.5", ""),
    ])
    def test_short_rows(self, step):
        assert is_impedance_short(step)

    def test_non_short_row(self):
        assert not is_impedance_short(
            ("Power Voltage", "TP_P01", "V", "—", "3.2", "3.4"))


class TestStepsTemplate:
    def test_both_stages_enabled(self):
        steps = steps_template(2, 3, [True, True])
        assert steps == [("ict", 0), ("ict", 1), ("stage", 0),
                         ("fctconn",), ("fct", 0), ("fct", 1),
                         ("fct", 2), ("stage", 1)]

    def test_ict_only(self):
        assert steps_template(1, 0, [True, False]) == \
            [("ict", 0), ("stage", 0)]

    def test_fct_only(self):
        assert steps_template(0, 2, [False, True]) == \
            [("fctconn",), ("fct", 0), ("fct", 1), ("stage", 1)]

    def test_fct_zero_rows_no_connect_step(self):
        assert ("fctconn",) not in steps_template(1, 0, [True, True])


class TestConsoleParsing:
    def test_parse_console_step(self):
        quotes, rest = parse_console_step(
            "SendtoCLI: \"wifi_test --scan\", 'Pass'/'Success' (expected)")
        assert quotes == ["wifi_test --scan", "Pass", "Success"]
        assert rest.startswith(' "wifi_test --scan"')
        assert "(expected)" in rest and "'Pass'" in rest

    def test_keyword_fallback(self):
        assert console_keyword_fallback(
            ": COM1, 'Boot OK' (expected)") == "Boot OK"


class TestDisplayText:
    def test_pass_for_op_is_done(self):
        assert display_text(StepStatus.PASS, "op") == "Done"

    def test_pass_for_measurement(self):
        assert display_text(StepStatus.PASS, "") == "PASS"
        assert display_text(StepStatus.PASS) == "PASS"

    def test_other_statuses(self):
        assert display_text(StepStatus.FAIL) == "FAIL"
        assert display_text(StepStatus.ERROR) == "Error"
        assert display_text(StepStatus.RUNNING) == "RUNNING"
        assert display_text(StepStatus.IGNORED) == "Ignore"

    def test_legacy_strings_pass_through(self):
        assert display_text("Pending") == "Pending"
        assert display_text("Done") == "Done"
