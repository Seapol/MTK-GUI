# -*- coding: utf-8 -*-
"""DIO-write isolation assessment for control-IO nets (M7 W6, headless).

Driving a DUT control net (RESET / EN / CS / MODE ...) from the U2355A
DIO bank is SAFE only when the net's upstream is passive (push-button,
jumper, test point).  When the same net also reaches an ACTIVE IO (MCU
GPIO, PMIC, FPGA, transceiver ...) the driven level can conflict or
short against that active source.

This module stamps two fields on every control-IO :class:`NetRecord`:

* ``isolated``       - True (passive only) / False (active source
                       found) / None (cannot confirm);
* ``active_drivers`` - refdes list of the active sources (empty when
                       isolated / unknown).

The ACTIVE / PASSIVE tables below are the frozen base; an external
rule layer may extend them (same learnable-rule mechanism as
:mod:`.rule_layers`, ``isolation`` section).
"""
from __future__ import annotations

import re

from .device_roles import (CLOCK_GEN, CONTROL_CHIP, FPGA,
                           INTERFACE_CHIP, LOAD, role_for_part_number)

#: device roles that always count as an active IO source
ACTIVE_ROLES = frozenset({LOAD, CONTROL_CHIP, FPGA, INTERFACE_CHIP,
                          CLOCK_GEN})

#: BOM device categories that always count as an active IO source
ACTIVE_CATEGORIES = frozenset({"main_mcu", "pmic", "dcdc", "ldo",
                               "transceiver", "fpga", "memory"})

#: passive refdes prefixes - never flagged (R / C / L / FB / ferrite /
#: J / SJ / TP / test-point / diode D; SW / BTN / KEY = the push-button /
#: DIP-switch upstream the user direction names as a passive source)
PASSIVE_PREFIXES = frozenset({"R", "C", "L", "FB", "FER", "FERRITE",
                              "FL", "J", "SJ", "TP", "TEST", "D",
                              "SW", "BTN", "KEY"})

_REFDES_RE = re.compile(r"^([A-Za-z_]+)")


def refdes_of(token: str) -> str:
    """Pin token -> owning refdes (``U1.5`` -> ``U1``, ``TP4`` -> ``TP4``)."""
    return str(token or "").split(".", 1)[0].strip()


def is_passive(refdes: str) -> bool:
    """True when *refdes* belongs to the passive table (R/C/L/FB/...)."""
    match = _REFDES_RE.match(str(refdes or ""))
    return bool(match) and match.group(1).upper() in PASSIVE_PREFIXES


def assess_net(members: list[str], library: dict | None,
               passive_prefixes: frozenset | None = None,
               active_roles: frozenset | None = None,
               active_categories: frozenset | None = None) \
        -> tuple[bool | None, list[str]]:
    """Assess one control net -> ``(isolated, active_drivers)``.

    Rules (conservative):
      * passive member refdes -> never flagged;
      * in-library, non-passive refdes -> ACTIVE (every IC counts as a
        potential driver);
      * refdes missing from the library (or a net without pin info)
        -> unknown -> ``isolated = None``;
      * any ACTIVE refdes -> ``isolated = False`` + refdes list;
      * only PASSIVE members -> ``isolated = True``.
    """
    passive_prefixes = passive_prefixes or PASSIVE_PREFIXES
    active_roles = active_roles or ACTIVE_ROLES
    active_categories = active_categories or ACTIVE_CATEGORIES
    members = [m for m in (members or []) if m]
    if not members:
        return None, []
    active: list[str] = []
    unknown: list[str] = []

    def _passive(refdes: str) -> bool:
        match = _REFDES_RE.match(refdes)
        return bool(match) and match.group(1).upper() in passive_prefixes

    for token in members:
        refdes = refdes_of(token)
        if not refdes:
            unknown.append(str(token))
            continue
        if _passive(refdes):
            continue
        info = (library or {}).get(refdes)
        if info is None:
            unknown.append(refdes)
            continue
        if isinstance(info, str):
            info = {"part_number": info}
        role = role_for_part_number(str(info.get("part_number") or ""),
                                    str(info.get("description") or ""))
        category = str(info.get("dev_category") or "")
        # passive table wins over the library category, every other
        # populated device counts as a potential active driver
        if role in active_roles or category in active_categories:
            if refdes not in active:
                active.append(refdes)
        else:
            if refdes not in active:
                active.append(refdes)
    if active:
        return False, active
    if unknown:
        return None, []
    return True, []


def external_tables(external: dict | None) -> tuple[frozenset, ...]:
    """(passive_prefixes, active_roles, active_categories) for one run -
    the base tables extended by the external rule layer."""
    passive = set(PASSIVE_PREFIXES)
    roles = set(ACTIVE_ROLES)
    categories = set(ACTIVE_CATEGORIES)
    section = (external or {}).get("isolation") or {}
    passive |= {str(p).upper() for p in
                section.get("passive_prefixes") or []}
    roles |= {str(r).lower() for r in section.get("active_roles") or []}
    categories |= {str(c).lower() for c in
                   section.get("active_categories") or []}
    return (frozenset(passive), frozenset(roles), frozenset(categories))


def annotate_control_io(result, library: dict | None,
                        external: dict | None = None) -> None:
    """Stamp ``isolated`` / ``active_drivers`` on every control-IO net."""
    passive, roles, categories = external_tables(external)
    for rec in result.control_io:
        isolated, drivers = assess_net(rec.members, library, passive,
                                       roles, categories)
        rec.isolated = isolated
        rec.active_drivers = drivers
        rec.isolation_checked = True
