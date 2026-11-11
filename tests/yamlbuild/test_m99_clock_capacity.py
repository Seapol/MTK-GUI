# -*- coding: utf-8 -*-
"""M99-2: the clock must fit the channel it is measured on - capacity
check, gate-resolution limits and the virtual range guard."""
from __future__ import annotations

import random

from mtkgui.gui.yamlbuild.channel_allocation import (
    AllocatedRow,
    ChannelAllocationData,
    _pick_clock_channel,
    allocation_configured_ok,
    clock_range_message,
)
from mtkgui.gui.yamlbuild.ict_sequence import auto_fill_limits
from mtkgui.gui.yamlbuild.power_alloc import CLOCK_CHANNELS
from mtkgui.virtual_hardware import VirtualDAQ973A, VirtualU2355A


def _clock_row(channel: str = "DAQM907A TOT",
               band: str = "0 ~ 100 kHz") -> AllocatedRow:
    return AllocatedRow(net="DMIC_CLK", test_point="SJ210.1",
                        se_clock_hz=channel, band=band,
                        nominal_khz="3072", lower_khz="3071.8464",
                        upper_khz="3072.1536")


def test_clock_channel_range_rejects_totalizer_for_mhz_clock():
    """3.072 MHz on the 100 kHz totalizer is out of range: the row
    reports the channel to use and the build stays disabled."""
    row = _clock_row()
    assert clock_range_message(row) == (
        "Clock out of range: DMIC_CLK 3072 kHz > DAQM907A TOT "
        "0 ~ 100 kHz - use U2355A CTR0/CTR1")
    assert allocation_configured_ok(ChannelAllocationData(clock=[row])) \
        is False
    row.se_clock_hz = "U2355A CTR0"
    row.band = "0.1 Hz ~ 6 MHz"
    assert clock_range_message(row) == ""
    assert allocation_configured_ok(ChannelAllocationData(clock=[row])) \
        is True


def test_clock_auto_allocation_prefers_counter_above_100khz():
    """Auto picks a counter for > 100 kHz, the totalizer otherwise and
    for an unknown nominal; the two counters are handed out in order."""
    free = list(CLOCK_CHANNELS)
    assert _pick_clock_channel(free, 3.072e6) == "U2355A CTR0"
    assert _pick_clock_channel(free, 4.0e6) == "U2355A CTR1"
    assert _pick_clock_channel(free, 32.768e3) == "DAQM907A TOT"
    assert _pick_clock_channel(free, None) is None      # pool exhausted
    free = list(CLOCK_CHANNELS)
    assert _pick_clock_channel(free, None) == "DAQM907A TOT"


def test_clock_limits_print_at_gate_resolution():
    """A 1 s gate resolves whole Hz: 3.072 MHz +/- 50 ppm prints
    3071846 / 3072154 without decimals."""
    rows = [("test", "Clock Hz - DMIC_CLK", "Hz", "—", "—", "—")]
    testable = {"DMIC_CLK": {"category": "Clock", "nominal_khz": 3072.0}}
    _kind, _name, _unit, expected, low, high = auto_fill_limits(
        rows, testable)[0][:6]
    assert (expected, low, high) == ("3072000", "3071846", "3072154")


def test_virtual_counter_refuses_out_of_range_nominal():
    """The 100 kHz totalizer must ERROR on a 3.072 MHz nominal and never
    produce a number (the old virtual PASS on an impossible reading)."""
    daqm = VirtualDAQ973A(random.Random(7))
    out = daqm.measure_totalizer("DMIC_CLK", 3071846.0, 3072154.0,
                                 powered=True, fault=None)
    assert out.verdict == "Error"
    assert out.value is None
    assert "out of range for this counter" in out.lines[0]
    # an unknown channel label is unverified, still no number
    from mtkgui.virtual_hardware import _counter_range_error
    unknown = _counter_range_error("U2355A CTR9", "X", 1.0e6)
    assert unknown.verdict == "Error"
    assert unknown.value is None
    assert "unverified: channel capability unknown" in unknown.lines[0]


def test_virtual_counter_value_sits_on_gate_grid():
    """A 1 s gate resolves 1 Hz - the synthesised counter reading is an
    integer, not a fabricated 0.1 Hz digit."""
    daq = VirtualU2355A(random.Random(3))
    out = daq.measure_counter(1, "CLK2 - 4 MHz", 3_999_000.0, 4_001_000.0,
                              powered=True, fault=None)
    assert out.verdict == "PASS"
    assert out.value == round(out.value)
    assert "." not in out.text
