# -*- coding: utf-8 -*-
"""Fixed workflow stage definitions for the Yaml Build page.

The ten-stage sequence is FIXED and irreversible (V4.0 instruction
section 5.1): the UI renders the blocks in this exact order and the
effective YAML emits the modules in this exact order.  Nothing in the
codebase may reorder, insert or drop stages.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    """One workflow block.

    Attributes:
        key:   Stable module identifier (YAML section key).
        title: UI label shown on the block.
        group: Functional family (design / power / ict / clocks /
               gpio / programmer / peripherals / fct).
    """

    key: str
    title: str
    group: str


#: The fixed ten-stage workflow sequence - DO NOT REORDER.
WORKFLOW_STAGES: tuple[Stage, ...] = (
    Stage("design_input", "Design Input", "design"),
    Stage("power_dut", "Configure Power On/Off DUT", "power"),
    Stage("parse_ict", "Parse nets for ICT", "ict"),
    Stage("rails", "Build Impedance/Voltage/Power rails up sequence",
          "ict"),
    Stage("clocks", "Build Clocks", "clocks"),
    Stage("gpios", "Build GPIOs", "gpio"),
    Stage("programmer", "Configure Programmer/Debugger", "programmer"),
    Stage("peripherals", "Configure Peripherials", "peripherals"),
    Stage("fct_parse", "Parse Func/Interface for FCT", "fct"),
    Stage("fct_build", "Build Func/Interface for FCT", "fct"),
)

#: Stage keys in workflow order.
STAGE_KEYS: tuple[str, ...] = tuple(s.key for s in WORKFLOW_STAGES)

#: key -> Stage lookup.
STAGE_BY_KEY: dict[str, Stage] = {s.key: s for s in WORKFLOW_STAGES}
