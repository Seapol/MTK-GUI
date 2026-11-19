# -*- coding: utf-8 -*-
"""v2-10 (node 04) Equipment Config headless model."""
from __future__ import annotations

from mtkgui.gui.yamlbuild.equipment_config import (
    MECHANISM_MANUAL, MECHANISM_PSU, MECHANISM_PSU_RELAY,
    MECHANISM_RELAY, RESOURCE_COUNTER, RESOURCE_OUT_OF_RANGE,
    RESOURCE_TOTALIZER, SOURCE_ADAPTER, SOURCE_PSU, ClockRow,
    EquipmentConfig, PowerRow, RailRow, capacity_components,
    capacity_line, clock_limits_hz, clock_resolution_ppm,
    derive_mechanism, emit_equipment_config, map_clock_resource,
    parse_equipment_config, rail_limits_v, validate)


# ------------------------------------------------------------- instruments
def test_capacity_line_full_rack():
    cfg = EquipmentConfig()
    assert capacity_components(cfg.instruments) == {
        "v_ohm_pts": 80, "dio_out": 8, "dio_in": 8, "counters": 2,
        "psu": 1}
    assert capacity_line(cfg.instruments) == (
        "80 V/Ohm pts | 8 DIO out / 8 DIO in (907A) | "
        "2 counters (U2355A) | 1 PSU")


def test_capacity_line_one_module_off():
    cfg = EquipmentConfig()
    cfg.instruments["daqm908a_2"] = False
    assert capacity_components(cfg.instruments)["v_ohm_pts"] == 40


# ------------------------------------------------------------- mechanism
def test_derive_mechanism_four_combos():
    assert derive_mechanism(SOURCE_PSU, False) == MECHANISM_PSU
    assert derive_mechanism(SOURCE_PSU, True) == MECHANISM_PSU_RELAY
    assert derive_mechanism(SOURCE_ADAPTER, True) == MECHANISM_RELAY
    assert derive_mechanism(SOURCE_ADAPTER, False) == MECHANISM_MANUAL


# ------------------------------------------------------------- clock
def test_map_clock_resource_three_ranges():
    assert map_clock_resource(32_768) == RESOURCE_TOTALIZER
    assert map_clock_resource(1_000_000) == RESOURCE_COUNTER
    assert map_clock_resource(100_000) == RESOURCE_TOTALIZER     # boundary
    assert map_clock_resource(6_000_000) == RESOURCE_COUNTER     # boundary
    assert map_clock_resource(7_000_000) == RESOURCE_OUT_OF_RANGE


def test_clock_limits_and_resolution():
    lo, hi = clock_limits_hz(32_768, 50)
    assert round(lo, 4) == 32_766.3616
    assert round(hi, 4) == 32_769.6384
    # resolution at 32.768 kHz / 1 s ~= 30.5 ppm (inside 50 ppm)
    assert 30 < clock_resolution_ppm(32_768, 1.0) < 31
    # 0.1 s gate -> ~305 ppm (coarser than tolerance)
    assert clock_resolution_ppm(32_768, 0.1) > 300


# ------------------------------------------------------------- rails
def test_rail_limits_five_percent():
    lo, hi = rail_limits_v(1.8)
    assert round(lo, 4) == 1.71
    assert round(hi, 4) == 1.89


# ------------------------------------------------------------- gate
def _allocated() -> EquipmentConfig:
    cfg = EquipmentConfig()
    cfg.check_run = True
    cfg.power_rows = [PowerRow(net="VDD1", channel="daqm908a_1:1")]
    cfg.clock_rows = [ClockRow(net="CLK1", nominal_hz=32768,
                               resource=RESOURCE_TOTALIZER)]
    return cfg


def test_validate_requires_instrument_check():
    cfg = EquipmentConfig()
    ok, item = validate(cfg)
    assert not ok
    assert item == "instrument check not run"


def test_validate_power_not_allocated():
    cfg = _allocated()
    cfg.power_rows.append(PowerRow(net="VDD2", channel=""))
    ok, item = validate(cfg)
    assert not ok
    assert item == "1 power nets not allocated"


def test_validate_adapter_needs_relay_or_prompt():
    cfg = _allocated()
    cfg.source = SOURCE_ADAPTER
    cfg.prompt_on = ""
    cfg.prompt_off = ""
    cfg.fixture.relay_channel = ""
    ok, item = validate(cfg)
    assert not ok
    assert item == "adapter power needs the fixture relay or a prompt"
    # both prompts non-empty satisfies it (default prompt_off stays set)
    cfg.prompt_on = "Insert the DUT power adapter, then press Go."
    cfg.prompt_off = "Remove the DUT power adapter, then press Go."
    assert validate(cfg)[0] is True


def test_validate_duplicate_rail_ai():
    cfg = _allocated()
    cfg.rails.rows = [
        RailRow(rail="VDD1", ai_channel="u2355a:ai1", order=1),
        RailRow(rail="VDD2", ai_channel="u2355a:ai1", order=2),
    ]
    ok, item = validate(cfg)
    assert not ok
    assert item == "duplicate rail AI channel"


def test_validate_malformed_port():
    cfg = _allocated()
    cfg.fixture.port1 = "30"
    ok, item = validate(cfg)
    assert not ok
    assert item == "fixture port address malformed"


# ------------------------------------------------------------- yaml
def test_yaml_round_trip():
    cfg = _allocated()
    cfg.source = SOURCE_ADAPTER
    cfg.fixture.relay_channel = "daqm907a:1:0"
    cfg.rails.rows = [RailRow(rail="VDD1", nominal_v=1.8, min_v=1.71,
                              max_v=1.89, ai_channel="u2355a:ai1",
                              order=1)]
    cfg.peripherals.wifi = True
    out = parse_equipment_config(emit_equipment_config(cfg))
    assert out.source == SOURCE_ADAPTER
    assert out.fixture.relay_channel == "daqm907a:1:0"
    assert out.power_rows[0].channel == "daqm908a_1:1"
    assert out.rails.rows[0].ai_channel == "u2355a:ai1"
    assert out.peripherals.wifi is True
    # check_run is a build-session gate, intentionally not persisted
