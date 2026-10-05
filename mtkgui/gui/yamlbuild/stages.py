# -*- coding: utf-8 -*-
"""Fixed workflow stage definitions for the Yaml Build page.

The twelve-stage sequence is FIXED (M0 redefinition, supersedes the
old ten-stage list): the UI renders the blocks in this exact order
and the effective YAML emits the modules in this exact order.
Nothing in the codebase may reorder, insert or drop stages.

Responsibility boundaries (M0, no duplication/conflict/missing):

* 01 Design Input          - read-only global DesignModel source
* 02 Configure Instruments - the ONLY rack-ATE instrument editor
* 03/04/05/06              - Parse/Build ICT (reuse 02 resources)
* 07 Programmer            - debug resource, separate from the rack
* 08 Peripherals           - DUT on-board peripherals
* 09/10                    - Parse/Build FCT (reuse all models)
* 11 Validate              - read-only cross-node validation, gates 12
* 12 Preview & Export      - final workflow exit
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    """One workflow block.

    Attributes:
        key:   Stable module identifier (YAML section key).
        title: UI label shown on the block.
        group: Functional family (design / instruments / ict / clocks /
               gpio / programmer / peripherals / fct / validate /
               export).
    """

    key: str
    title: str
    group: str


#: The fixed twelve-stage workflow sequence - DO NOT REORDER.
WORKFLOW_STAGES: tuple[Stage, ...] = (
    Stage("design_input", "Design Input", "design"),
    Stage("instruments", "Configure Instruments", "instruments"),
    Stage("parse_ict", "Parse nets for ICT", "ict"),
    Stage("rails", "Build Impedance/Voltage/Power rails up sequence",
          "ict"),
    Stage("clocks", "Build Clocks", "clocks"),
    Stage("gpios", "Build GPIOs", "gpio"),
    Stage("programmer", "Configure Programmer/Debugger", "programmer"),
    Stage("peripherals", "Configure Peripherals", "peripherals"),
    Stage("fct_parse", "Parse Func/Interface for FCT", "fct"),
    Stage("fct_build", "Build Func/Interface for FCT", "fct"),
    Stage("validate_sequence", "Validate Full Test Sequence",
          "validate"),
    Stage("preview_export", "Preview & Export YAML", "export"),
)

#: Stage keys in workflow order.
STAGE_KEYS: tuple[str, ...] = tuple(s.key for s in WORKFLOW_STAGES)

#: key -> Stage lookup.
STAGE_BY_KEY: dict[str, Stage] = {s.key: s for s in WORKFLOW_STAGES}

#: Legacy (pre-M0) stage keys absorbed by the twelve-stage list:
#: the DUT power-up configuration moved into the rails block (04).
LEGACY_MODULE_MAP: dict[str, str] = {"power_dut": "rails"}
