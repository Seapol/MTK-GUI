# -*- coding: utf-8 -*-
"""v2 node 05 Build ICT Test Sequence — headless model (Qt-free).

Arranges the ICT sequence as **one flat list** grouped for display into
six virtual blocks; the engine never sees a block marker.  Owns only the
order and the per-row timeout.  Limits, channels and rails come from
node 04 and are read-only here.

This is the v2-11 model.  The v1 dialog keeps living in
``ict_sequence.py`` (block 04 editor); it is not imported here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # type hints only - never Qt
    from mtkgui.gui.yamlbuild.equipment_config import EquipmentConfig

#: step kinds - three test kinds, then op and neutral rows
KIND_RGND = "R-GND"
KIND_POWER_VOLTAGE = "Power Voltage"
KIND_CLOCK_HZ = "Clock Hz"
KIND_OP = "op"
KIND_DELAY = "delay"
KIND_MESSAGE_OK = "message_ok"
KIND_MESSAGE_YES_NO = "message_yes_no"
KIND_MESSAGE_GO_STOP = "message_go_stop"

TEST_KINDS = (KIND_RGND, KIND_POWER_VOLTAGE, KIND_CLOCK_HZ)
NEUTRAL_KINDS = (KIND_DELAY, KIND_MESSAGE_OK, KIND_MESSAGE_YES_NO,
                 KIND_MESSAGE_GO_STOP)

#: op sub-types
OP_INSTRUMENTS = "instruments"
OP_FIXTURE_READY = "fixture_ready"
OP_DAQ_AI_START = "daq_ai_start"
OP_DAQ_AI_END = "daq_ai_end"
OP_POWER = "power"
OP_RESET = "reset"

POWER_ON = "on"
POWER_OFF = "off"

#: display blocks, fixed order (§4)
BLOCK_SETUP = "SETUP"
BLOCK_OHM = "OHM"
BLOCK_POWER = "POWER"
BLOCK_DCV = "DCV"
BLOCK_CLK = "CLK"
BLOCK_TEARDOWN = "TEARDOWN"
BLOCKS = (BLOCK_SETUP, BLOCK_OHM, BLOCK_POWER, BLOCK_DCV, BLOCK_CLK,
          BLOCK_TEARDOWN)

BLOCK_LABELS = {
    BLOCK_SETUP: "Setup",
    BLOCK_OHM: "Unpowered measurement",
    BLOCK_POWER: "Power up",
    BLOCK_DCV: "Powered measurement - voltage",
    BLOCK_CLK: "Powered measurement - clock",
    BLOCK_TEARDOWN: "Teardown",
}

#: empty-block grey lines (§4.2)
EMPTY_BLOCK_TEXT = {
    BLOCK_OHM: "no power nets in this project",
    BLOCK_DCV: "no power nets in this project",
    BLOCK_CLK: "no clock nets in this project",
}


@dataclass
class IctStep:
    """One row of the flat ICT sequence."""

    name: str
    kind: str
    net: str = ""
    tp: str = ""
    op_type: str = ""          # for kind == "op"
    power_state: str = ""      # "on" / "off" for op_type == "power"
    params: dict = field(default_factory=dict)
    timeout_ms: int | None = None
    not_tested: bool = False

    def is_test(self) -> bool:
        return self.kind in TEST_KINDS

    def is_neutral(self) -> bool:
        return self.kind in NEUTRAL_KINDS


def block_of(step: IctStep) -> str:
    """The display block a step belongs to (§4)."""
    if step.kind == KIND_RGND:
        return BLOCK_OHM
    if step.kind == KIND_POWER_VOLTAGE:
        return BLOCK_DCV
    if step.kind == KIND_CLOCK_HZ:
        return BLOCK_CLK
    if step.kind == KIND_OP:
        if step.op_type == OP_POWER:
            return BLOCK_POWER if step.power_state == POWER_ON \
                else BLOCK_TEARDOWN
        if step.op_type in (OP_DAQ_AI_START, OP_DAQ_AI_END):
            return BLOCK_POWER
        if step.op_type == OP_RESET:
            return BLOCK_TEARDOWN
        if step.op_type == OP_FIXTURE_READY:
            return BLOCK_SETUP
        if step.op_type == OP_INSTRUMENTS:
            return BLOCK_SETUP
    return BLOCK_SETUP


def _init_step(instruments: list[str] | None = None) -> IctStep:
    params = {}
    if instruments:
        params["instruments"] = list(instruments)
    return IctStep(name="Init Instruments", kind=KIND_OP,
                   op_type=OP_INSTRUMENTS, params=params)


def _fixture_ready_step() -> IctStep:
    return IctStep(name="Fixture Ready", kind=KIND_OP,
                   op_type=OP_FIXTURE_READY)


def _daq_start_step(rails: dict) -> IctStep:
    return IctStep(name="DAQ AI Start", kind=KIND_OP,
                   op_type=OP_DAQ_AI_START,
                   params={"rate_hz": rails.get("rate_hz", 20000),
                           "window_ms": rails.get("window_ms", 1000),
                           "arm_lead_ms": rails.get("arm_lead_ms", 100)})


def _daq_end_step() -> IctStep:
    return IctStep(name="DAQ AI End", kind=KIND_OP,
                   op_type=OP_DAQ_AI_END)


def _power_on_step() -> IctStep:
    return IctStep(name="Power On DUT", kind=KIND_OP, op_type=OP_POWER,
                   power_state=POWER_ON)


def _power_off_step() -> IctStep:
    return IctStep(name="Power Off DUT", kind=KIND_OP, op_type=OP_POWER,
                   power_state=POWER_OFF)


def _reset_step(instruments: list[str] | None = None) -> IctStep:
    params = {}
    if instruments:
        params["instruments"] = list(instruments)
    return IctStep(name="Reset Instruments", kind=KIND_OP, op_type=OP_RESET,
                   params=params)


def generate_sequence(power_nets, clock_nets, rails_enabled: bool,
                      fixture_type: str = "ate",
                      instruments: list[str] | None = None) -> list[IctStep]:
    """Build the generated order from node 02 + 04 facts (§3)."""
    steps = [_init_step(instruments)]
    if fixture_type == "ate":
        steps.append(_fixture_ready_step())
    steps += [IctStep(name=f"R-GND - {n}", kind=KIND_RGND, net=n)
              for n in power_nets]
    if rails_enabled:
        steps.append(_daq_start_step({}))
    steps.append(_power_on_step())
    if rails_enabled:
        steps.append(_daq_end_step())
    steps += [IctStep(name=f"Power Voltage - {n}",
                      kind=KIND_POWER_VOLTAGE, net=n)
              for n in power_nets]
    steps += [IctStep(name=f"Clock Hz - {n}", kind=KIND_CLOCK_HZ, net=n)
              for n in clock_nets]
    steps.append(_power_off_step())
    steps.append(_reset_step(instruments))
    return steps


# ---------------------------------------------------------------------------
# Validation (§8)
# ---------------------------------------------------------------------------
def validate_sequence(steps: list[IctStep]) -> tuple[bool, str]:
    if not steps:
        return False, "no test rows left - nothing to run"

    # rule 8: Init first, Reset last
    if steps[0].op_type != OP_INSTRUMENTS:
        return False, ("the sequence must start with Init Instruments - "
                       "without it the instruments run on their reset "
                       "defaults")
    if steps[-1].op_type != OP_RESET:
        return False, ("the sequence must end with Reset Instruments - "
                       "the rack is left with this project's settings")

    power_on = [s for s in steps if s.op_type == OP_POWER
                and s.power_state == POWER_ON]
    power_off = [s for s in steps if s.op_type == OP_POWER
                 and s.power_state == POWER_OFF]

    # rule 1: exactly one power-on
    if len(power_on) != 1:
        return False, "one power-on per sequence - a re-power needs its own YAML"
    # rule 2: exactly one power-off
    if len(power_off) != 1:
        return False, ("one power-off per sequence - the board must be left "
                       "unpowered")

    # rule 6: power-on after every R-GND and before every voltage/clock
    power_idx = steps.index(power_on[0])
    for i, s in enumerate(steps):
        if s.kind == KIND_RGND and i > power_idx:
            return False, f"{s.name} runs on the wrong side of the power step"
        if s.kind in (KIND_POWER_VOLTAGE, KIND_CLOCK_HZ) and i < power_idx:
            return False, f"{s.name} runs on the wrong side of the power step"

    # rule 3: daq_ai pair around the power row
    starts = [i for i, s in enumerate(steps)
              if s.op_type == OP_DAQ_AI_START]
    ends = [i for i, s in enumerate(steps) if s.op_type == OP_DAQ_AI_END]
    if len(starts) > 1 or len(ends) > 1:
        return False, "Only one rails capture per run"
    if len(starts) != len(ends):
        if len(starts) > len(ends):
            return False, ("DAQ AI capture is not closed - add the DAQ AI "
                           "End step")
        return False, ("DAQ AI capture is not armed - add the DAQ AI Start "
                       "step")
    if starts:
        s0, e0 = starts[0], ends[0]
        if e0 - s0 != 2 or steps[s0 + 1].op_type != OP_POWER:
            return False, ("Rails capture window may only contain the power "
                           "step")

    # rule 5: at least one test row not not_tested
    if not any(s.is_test() and not s.not_tested for s in steps):
        return False, "no test rows left - nothing to run"

    # rule 7: timeout empty or positive integer
    for s in steps:
        if s.timeout_ms is not None:
            if not isinstance(s.timeout_ms, int) or s.timeout_ms <= 0:
                return False, ("Timeout must be a positive number of "
                               "milliseconds, or empty")

    # rule 4: class matches block (test rows only)
    expected = {KIND_RGND: BLOCK_OHM, KIND_POWER_VOLTAGE: BLOCK_DCV,
                KIND_CLOCK_HZ: BLOCK_CLK}
    for s in steps:
        if s.is_test() and block_of(s) != expected[s.kind]:
            return False, (f"{s.name} does not belong in the "
                           f"{block_of(s)} block")

    return True, ""


# ---------------------------------------------------------------------------
# Engine contract (v2-11b A)
# ---------------------------------------------------------------------------
#: test kind -> engine unit
_ENGINE_UNITS = {KIND_RGND: "Ω", KIND_POWER_VOLTAGE: "V",
                 KIND_CLOCK_HZ: "Hz"}

MISSING_LIMIT = "—"


def _power_row(equipment_config, net: str):
    for row in (getattr(equipment_config, "power_rows", None) or []):
        if str(getattr(row, "net", "")) == net:
            return row
    return None


def _clock_row(equipment_config, net: str):
    for row in (getattr(equipment_config, "clock_rows", None) or []):
        if str(getattr(row, "net", "")) == net:
            return row
    return None


def _test_limits(step: IctStep, equipment_config) -> dict:
    """The engine ``unit`` / ``threshold_min`` / ``threshold_max`` cells.

    Limits are joined from node 04 by net name; a net with no 04 row
    keeps the missing limit (``—``) - nothing is invented here."""
    unit = _ENGINE_UNITS.get(step.kind, MISSING_LIMIT)
    lo = hi = MISSING_LIMIT
    if step.kind == KIND_RGND:
        row = _power_row(equipment_config, step.net)
        if row is not None:
            lo = row.r_gnd_min_ohm
    elif step.kind == KIND_POWER_VOLTAGE:
        row = _power_row(equipment_config, step.net)
        if row is not None:
            lo, hi = row.min_v, row.max_v
    elif step.kind == KIND_CLOCK_HZ:
        row = _clock_row(equipment_config, step.net)
        if row is not None:
            nominal = float(row.nominal_hz)
            ppm = float(row.ppm)
            lo = round(nominal * (1 - ppm / 1e6), 2)
            hi = round(nominal * (1 + ppm / 1e6), 2)
    return {"unit": unit, "threshold_min": lo, "threshold_max": hi}


def to_engine_cases(steps: list[IctStep], equipment_config) -> list[dict]:
    """Flat ICT steps -> engine ``ict_test_cases`` rows.

    Joins node 04 limits by net name; ``not_tested`` becomes ``enable``.
    """
    cases: list[dict] = []
    for step in steps:
        row = {"name": step.name, "kind": step.kind,
               "enable": not step.not_tested,
               "timeout_ms": step.timeout_ms}
        if step.kind == KIND_OP:
            params = dict(step.params)
            params["type"] = step.op_type
            if step.power_state:
                params["state"] = step.power_state
            row["op_params"] = params
        elif step.is_test():
            row.update(_test_limits(step, equipment_config))
        cases.append(row)
    return cases


# ---------------------------------------------------------------------------
# YAML round-trip (flat list, no block markers)
# ---------------------------------------------------------------------------
def emit_sequence(steps: list[IctStep]) -> list[dict]:
    """Serialize the flat ``ict_test_cases`` list (§10)."""
    out = []
    for s in steps:
        row = {"name": s.name, "kind": s.kind,
               "timeout_ms": s.timeout_ms, "not_tested": s.not_tested}
        if s.kind == KIND_OP:
            params = dict(s.params)
            params["type"] = s.op_type
            if s.power_state:
                params["state"] = s.power_state
            row["op_params"] = params
        else:
            if s.net:
                row["net"] = s.net
            if s.tp:
                row["tp"] = s.tp
        out.append(row)
    return out


def parse_sequence(rows: list[dict]) -> list[IctStep]:
    """Parse the flat ``ict_test_cases`` list back to steps."""
    steps: list[IctStep] = []
    for r in rows:
        kind = r.get("kind", "")
        op_type = ""
        power_state = ""
        params: dict = {}
        if kind == KIND_OP:
            op = r.get("op_params") or {}
            op_type = op.get("type", "")
            power_state = op.get("state", "")
            params = {k: v for k, v in op.items()
                      if k not in ("type", "state")}
        steps.append(IctStep(
            name=r.get("name", ""), kind=kind,
            net=r.get("net", ""), tp=r.get("tp", ""),
            op_type=op_type, power_state=power_state, params=params,
            timeout_ms=r.get("timeout_ms"), not_tested=bool(r.get(
                "not_tested", False))))
    return steps
