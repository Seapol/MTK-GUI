# -*- coding: utf-8 -*-
"""Fixed workflow stage definitions for the Yaml Build page.

The stage sequence is FIXED: the UI renders the blocks in this exact
order and the effective YAML emits the modules in this exact order.
Nothing in the codebase may reorder, insert or drop stages.

2026-10-13 simplification (user direction): the Programmer/Debugger,
Peripherals, Validate and Preview & Export stages are RETIRED - their
parameters had no runtime consumer, the instrument / programmer /
peripheral hardware is configured on the Equipment page, the full
sequence validation runs automatically before every publish and the
YAML preview stays the always-visible right pane.  Old files carrying
the removed modules load cleanly (dropped silently, see
``REMOVED_MODULES``).  The underlying ``instruments`` YAML module
stays (Equipment page holds the values) but shows NO card.

Responsibility boundaries:

* 01 Design Input          - read-only global DesignModel source
* 02 Parse nets for ICT    - SPF+NET load & parse BEFORE instruments
* 03 Channel Allocation    - INLINE embedded tables (nav card, not a
                             YAML module of its own)
* 04 Build ICT             - rails/clocks/gpios (merged display card
                             "Build ICT Test Work Flow Sequence")
* 05 Build FCT             - fct_build (reuses all models)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    """One workflow block.

    Attributes:
        key:   Stable module identifier (YAML section key).
        title: UI label shown on the block.
        group: Functional family (design / ict / instruments / clocks /
               gpio / fct).
    """

    key: str
    title: str
    group: str


#: The fixed workflow module sequence - DO NOT REORDER.  Parse nets
#: for ICT runs BEFORE the ICT build stages (SPF+NET parsing first).
#: The retired programmer / peripherals / validate_sequence /
#: preview_export stages are gone (see REMOVED_MODULES).
WORKFLOW_STAGES: tuple[Stage, ...] = (
    Stage("design_input", "Design Input", "design"),
    Stage("parse_ict", "Parse nets for ICT", "ict"),
    Stage("instruments", "Configure Instruments", "instruments"),
    Stage("rails", "Build Impedance/Voltage/Power rails up sequence",
          "ict"),
    Stage("clocks", "Build Clocks", "clocks"),
    Stage("gpios", "Build GPIOs", "gpio"),
    Stage("fct_build", "Build FCT Test Work Flow Sequence", "fct"),
)

#: Stage keys in workflow order.
STAGE_KEYS: tuple[str, ...] = tuple(s.key for s in WORKFLOW_STAGES)

#: key -> Stage lookup.
STAGE_BY_KEY: dict[str, Stage] = {s.key: s for s in WORKFLOW_STAGES}

#: Modules RETIRED by the 2026-10-13 simplification: old YAML files
#: and saved states carrying them load cleanly - the entries are
#: dropped silently by the model migration (no error, no data use).
REMOVED_MODULES: tuple[str, ...] = (
    "programmer", "peripherals", "validate_sequence", "preview_export",
)

#: merged UI display node (user direction): the rails/clocks/gpios
#: build cards collapse into ONE "Build ICT Test Work Flow Sequence"
#: card that opens the Test Work Flow page (double-click); the
#: underlying rails / clocks / gpios YAML modules stay UNCHANGED (the
#: Test Work Flow page owns the ICT test cases editing).
DISPLAY_ICT_WORKFLOW = "ict_workflow"

#: navigation-only display card: the Channel Allocation tables are
#: EMBEDDED below the cards on the same page (user direction: one
#: page, top-to-bottom, no missed steps); the card scrolls there and
#: is NOT a YAML module (no enable / disable, no mark).
DISPLAY_CHANNEL_ALLOC = "channel_alloc"

#: display cards with no underlying YAML module (pure navigation).
NAV_CARD_KEYS: frozenset[str] = frozenset({DISPLAY_CHANNEL_ALLOC})

WORKFLOW_DISPLAY_STAGES: tuple[Stage, ...] = (
    Stage("design_input", "Design Input", "design"),
    Stage("parse_ict", "Parse nets for ICT", "ict"),
    Stage(DISPLAY_CHANNEL_ALLOC, "Channel Allocation", "ict"),
    Stage(DISPLAY_ICT_WORKFLOW,
          "Build ICT Test Work Flow Sequence", "ict"),
    Stage("fct_build", "Build FCT Test Work Flow Sequence", "fct"),
)

#: display card -> the underlying YAML modules it represents (the
#: Enable / Disable context menu applies to ALL of them; the card
#: shows Enabled when ANY underlying module is enabled).
DISPLAY_CARD_MODULES: dict[str, tuple[str, ...]] = {
    DISPLAY_ICT_WORKFLOW: ("rails", "clocks", "gpios"),
}

#: Legacy (pre-M0) stage key absorbed into the workflow list: the DUT
#: power-up configuration moved into the rails block.
LEGACY_MODULE_MAP: dict[str, str] = {"power_dut": "rails"}

#: Legacy (pre-item-23) ordering: Configure Instruments was block 02,
#: Parse nets block 03.  Loading such a project file swaps the pair
#: back onto the canonical sequence instead of failing the order check.
LEGACY_ORDER_SWAP: tuple[str, str] = ("instruments", "parse_ict")
