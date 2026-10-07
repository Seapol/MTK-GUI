# -*- coding: utf-8 -*-
"""Fixed workflow stage definitions for the Yaml Build page.

The twelve-stage sequence is FIXED (item 23 redefinition, supersedes
the M0 order for the 02/03 pair): the UI renders the blocks in this
exact order and the effective YAML emits the modules in this exact
order.  Nothing in the codebase may reorder, insert or drop stages.

Responsibility boundaries:

* 01 Design Input          - read-only global DesignModel source
* 02 Parse nets for ICT    - SPF+NET load & parse BEFORE instruments
* 03 Configure Instruments - the ONLY rack-ATE instrument editor
* 04/05/06                 - Build ICT (reuse 03 resources)
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
#: Item 23: Parse nets for ICT (02) runs BEFORE Configure
#: Instruments (03) - SPF+NET parsing first, then instrument setup.
WORKFLOW_STAGES: tuple[Stage, ...] = (
    Stage("design_input", "Design Input", "design"),
    Stage("parse_ict", "Parse nets for ICT", "ict"),
    Stage("instruments", "Configure Instruments", "instruments"),
    Stage("rails", "Build Impedance/Voltage/Power rails up sequence",
          "ict"),
    Stage("clocks", "Build Clocks", "clocks"),
    Stage("gpios", "Build GPIOs", "gpio"),
    Stage("programmer", "Configure Programmer/Debugger", "programmer"),
    Stage("peripherals", "Configure Peripherals", "peripherals"),
    Stage("fct_build", "Build FCT Test Work Flow Sequence", "fct"),
    Stage("validate_sequence", "Validate Full Test Sequence",
          "validate"),
    Stage("preview_export", "Preview & Export YAML", "export"),
)

#: Stage keys in workflow order.
STAGE_KEYS: tuple[str, ...] = tuple(s.key for s in WORKFLOW_STAGES)

#: key -> Stage lookup.
STAGE_BY_KEY: dict[str, Stage] = {s.key: s for s in WORKFLOW_STAGES}

#: merged UI display node (user direction): the 04/05/06 build cards
#: collapse into ONE "Build ICT Test Work Flow Sequence" card that
#: opens the Test Work Flow page (double-click); the underlying
#: rails / clocks / gpios YAML modules stay UNCHANGED (the Test Work
#: Flow page owns the ICT test cases editing).
DISPLAY_ICT_WORKFLOW = "ict_workflow"
WORKFLOW_DISPLAY_STAGES: tuple[Stage, ...] = (
    Stage("design_input", "Design Input", "design"),
    Stage("parse_ict", "Parse nets for ICT", "ict"),
    Stage(DISPLAY_ICT_WORKFLOW,
          "Build ICT Test Work Flow Sequence", "ict"),
    Stage("instruments", "Configure Instruments", "instruments"),
    Stage("programmer", "Configure Programmer/Debugger", "programmer"),
    Stage("peripherals", "Configure Peripherals", "peripherals"),
    Stage("fct_build", "Build FCT Test Work Flow Sequence", "fct"),
    Stage("validate_sequence", "Validate Full Test Sequence",
          "validate"),
    Stage("preview_export", "Preview & Export YAML", "export"),
)

#: display card -> the underlying YAML modules it represents (the
#: Enable / Disable context menu applies to ALL of them; the card
#: shows Enabled when ANY underlying module is enabled).
DISPLAY_CARD_MODULES: dict[str, tuple[str, ...]] = {
    DISPLAY_ICT_WORKFLOW: ("rails", "clocks", "gpios"),
}

#: Legacy (pre-M0) stage keys absorbed by the twelve-stage list:
#: the DUT power-up configuration moved into the rails block (04).
LEGACY_MODULE_MAP: dict[str, str] = {"power_dut": "rails"}

#: Legacy (pre-item-23) ordering: Configure Instruments was block 02,
#: Parse nets block 03.  Loading such a project file swaps the pair
#: back onto the canonical sequence instead of failing the order check.
LEGACY_ORDER_SWAP: tuple[str, str] = ("instruments", "parse_ict")
