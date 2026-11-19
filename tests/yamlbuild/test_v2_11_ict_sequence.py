# -*- coding: utf-8 -*-
"""v2-11 (node 05) Build ICT Test Sequence headless model."""
from __future__ import annotations

from mtkgui.gui.yamlbuild.ict_sequence_v2 import (
    BLOCK_CLK, BLOCK_DCV, BLOCK_OHM, BLOCK_POWER, BLOCK_SETUP,
    BLOCK_TEARDOWN, IctStep, KIND_CLOCK_HZ, KIND_OP, KIND_RGND,
    OP_DAQ_AI_END, OP_DAQ_AI_START, OP_INSTRUMENTS, OP_POWER,
    OP_RESET, POWER_OFF, POWER_ON, block_of, emit_sequence,
    generate_sequence, parse_sequence, to_engine_cases,
    validate_sequence)
from mtkgui.gui.yamlbuild.equipment_config import (
    ClockRow, EquipmentConfig, PowerRow)

POWER_NETS = ["VDD1", "VDD2"]
CLOCK_NETS = ["CLK1"]


def test_generate_sequence_blocks():
    steps = generate_sequence(POWER_NETS, CLOCK_NETS, rails_enabled=False)
    blocks = [block_of(s) for s in steps]
    assert blocks == [
        BLOCK_SETUP, BLOCK_SETUP,          # Init + Fixture Ready
        BLOCK_OHM, BLOCK_OHM,              # R-GND x2
        BLOCK_POWER,                       # Power On DUT
        BLOCK_DCV, BLOCK_DCV,              # Power Voltage x2
        BLOCK_CLK,                         # Clock Hz
        BLOCK_TEARDOWN, BLOCK_TEARDOWN,    # Power Off + Reset
    ]
    assert steps[0].name == "Init Instruments"
    assert steps[-1].name == "Reset Instruments"


def test_generate_sequence_with_rails():
    steps = generate_sequence(POWER_NETS, CLOCK_NETS, rails_enabled=True)
    power_block = [s for s in steps if block_of(s) == BLOCK_POWER]
    assert [s.name for s in power_block] == [
        "DAQ AI Start", "Power On DUT", "DAQ AI End"]


def test_validate_sequence_ok():
    steps = generate_sequence(POWER_NETS, CLOCK_NETS, rails_enabled=True)
    assert validate_sequence(steps) == (True, "")


def test_validate_requires_init_reset():
    steps = generate_sequence(POWER_NETS, CLOCK_NETS, rails_enabled=False)
    steps = steps[1:-1]  # drop Init + Reset
    ok, msg = validate_sequence(steps)
    assert not ok
    assert "start with Init Instruments" in msg


def test_validate_two_power_on():
    steps = generate_sequence(POWER_NETS, CLOCK_NETS, rails_enabled=False)
    extra = IctStep(name="Power On DUT", kind=KIND_OP, op_type=OP_POWER,
                    power_state=POWER_ON)
    steps.insert(4, extra)
    ok, msg = validate_sequence(steps)
    assert not ok
    assert "one power-on per sequence" in msg


def test_validate_unpaired_daq_ai():
    steps = generate_sequence(POWER_NETS, CLOCK_NETS, rails_enabled=True)
    # remove the End step -> unpaired
    steps = [s for s in steps if s.op_type != OP_DAQ_AI_END]
    ok, msg = validate_sequence(steps)
    assert not ok
    assert "not closed" in msg


def test_validate_timeout_bad():
    steps = generate_sequence(POWER_NETS, CLOCK_NETS, rails_enabled=False)
    steps[2].timeout_ms = -5
    ok, msg = validate_sequence(steps)
    assert not ok
    assert "positive number" in msg


def test_yaml_round_trip_flat():
    steps = generate_sequence(POWER_NETS, CLOCK_NETS, rails_enabled=True)
    rows = emit_sequence(steps)
    # no block markers: every row is a step
    assert all("kind" in r for r in rows)
    back = parse_sequence(rows)
    assert [s.name for s in back] == [s.name for s in steps]
    assert back[0].op_type == OP_INSTRUMENTS
    assert back[-1].op_type == OP_RESET
    # power state round-trips
    power = [s for s in back if s.op_type == OP_POWER]
    assert [s.power_state for s in power] == [POWER_ON, POWER_OFF]


def test_block_of_test_kinds():
    assert block_of(IctStep("r", KIND_RGND)) == BLOCK_OHM
    assert block_of(IctStep("v", "Power Voltage")) == BLOCK_DCV
    assert block_of(IctStep("c", KIND_CLOCK_HZ)) == BLOCK_CLK


def test_init_reset_carry_enabled_instruments():
    instruments = ["daq973a", "u2355a", "n5747a"]
    steps = generate_sequence(POWER_NETS, CLOCK_NETS, rails_enabled=False,
                              instruments=instruments)
    assert steps[0].params.get("instruments") == instruments
    assert steps[-1].params.get("instruments") == instruments
    # without instruments, the param is absent (empty params dict)
    bare = generate_sequence([], [], rails_enabled=False)
    assert "instruments" not in bare[0].params


# ---------------------------------------------------------------------------
# v2-11b A: the engine's ict_test_cases shape
# ---------------------------------------------------------------------------
def _equipment() -> EquipmentConfig:
    return EquipmentConfig(
        power_rows=[PowerRow(net="VDD1", r_gnd_min_ohm=1.5,
                             min_v=3.135, max_v=3.465)],
        clock_rows=[ClockRow(net="CLK1", nominal_hz=24000000.0, ppm=50)])


def _test_steps() -> list:
    return [IctStep("R-GND - VDD1", KIND_RGND, net="VDD1"),
            IctStep("Power Voltage - VDD1", "Power Voltage", net="VDD1"),
            IctStep("Clock Hz - CLK1", KIND_CLOCK_HZ, net="CLK1")]


def test_to_engine_cases_test_row_shape():
    cases = to_engine_cases(_test_steps(), _equipment())
    for case in cases:
        assert {"unit", "threshold_min", "threshold_max",
                "enable"} <= set(case)
        assert "not_tested" not in case


def test_to_engine_cases_r_gnd_min_only():
    case = to_engine_cases(_test_steps(), _equipment())[0]
    assert case["kind"] == KIND_RGND
    assert case["threshold_min"] == 1.5
    assert case["threshold_max"] == "—"
    assert case["unit"] == "Ω"


def test_to_engine_cases_clock_ppm_window():
    case = to_engine_cases(_test_steps(), _equipment())[2]
    assert case["kind"] == KIND_CLOCK_HZ
    assert case["threshold_min"] == 23998800.0
    assert case["threshold_max"] == 24001200.0
    assert case["unit"] == "Hz"


def test_to_engine_cases_op_row_has_enable_and_op_params():
    step = IctStep("Power On DUT", KIND_OP, op_type=OP_POWER,
                   power_state=POWER_ON)
    case = to_engine_cases([step], _equipment())[0]
    assert case["kind"] == "op"
    assert case["op_params"]["type"] == OP_POWER
    assert case["op_params"]["state"] == POWER_ON
    assert case["enable"] is True
