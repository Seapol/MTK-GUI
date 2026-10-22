# -*- coding: utf-8 -*-
"""Device-role clock knowledge base (M2 PART B, headless - no Qt).

Maps BOM part numbers onto DEVICE ROLES that drive the netlist
classification when a component library is supplied:

* ``clock_gen``  - clock generator / buffer / oscillator chip
                   (SI5332 ...): power straps -> Power, clock
                   outputs -> Clock;
* ``interface``  - PHY / transceiver / LIN-CAN bus driver
                   (SJA1124 / TJA1230 / SGMII PHY ...): clock inputs
                   stay untested (Others);
* ``fpga``       - programmable logic: clock inputs from the DUT
                   (``DUT_CLK*``) count as Clock;
* ``load``       - MCU / SoC / memory (unused by classification for
                   now, recorded for the M2+ knowledge base).

The M1 chip-model exclusion table stays as the NO-LIBRARY fallback -
without a library the M1 behaviour is unchanged.

Boundary (M4 PART 5): these roles drive NET classification only; the
GUI ``designinput.components.dev_category`` (main_mcu / pmic / dcdc /
ldo / transceiver) drives board-level views.  Both stay - the only
shared input is the BOM-derived library dict.
"""
from __future__ import annotations

import re

CLOCK_GEN = "clock_gen"      # clock generator / buffer / oscillator chip
INTERFACE_CHIP = "interface"  # PHY, transceiver, LIN/CAN/bus driver
FPGA = "fpga"                # programmable logic
LOAD = "load"                # MCU/SoC/memory
CONTROL_CHIP = "control_chip"  # MCU/CPLD/EC/SIO/BMC/GPIO-expander;
                               # PMIC control side: control IO here
                               # ranks first (owner rule, M2 B2)

#: part-number / family markers -> role.  Extendable; M2 ships with
#: the set below (``MT[0-9]{4}``-style entries are regexes, the rest
#: match literally, case-insensitive, as substrings).
_ROLE_MARKERS: dict[str, tuple[str, ...]] = {
    CLOCK_GEN: ("SI5332", "SI5211", "SI5221", "SI5341", "SI5381",
                "8N4DV85", "8N4Q001"),
    INTERFACE_CHIP: ("SJA1124", "TJA1230", "TJA1044", "TJA1051",
                     "TJA1462", "SGMII", "88E1512", "88E1543",
                     "DP83867", "KSZ9031", "KSZ8795"),
    FPGA: ("FPGA", "XC7", "XCU", "AG25", "AG32", "CYCLONE", "A2F",
           "ARTIX", "KINTEX", "VIRTEX"),
    LOAD: ("IMX93", "IMX8", "S32", "MT[0-9]{4}", "STM32", "GD32"),
    CONTROL_CHIP: ("CPLD", "EC", "SIO", "BMC", "PCA95", "TCA95",
                   "M051", "N76", "PIC", "ATTINY", "STM32F0",
                   "MSP430", "XILINX_CPLD", "LATTICE"),
}

def _is_regex(marker: str) -> bool:
    """True for markers that carry regex syntax (``[`` / ``{``)."""
    return bool(re.search(r"[\[\]{}]", marker))


def build_ordered(markers: dict[str, tuple[str, ...]]) \
        -> list[tuple[str, re.Pattern]]:
    """Longest-marker-first (role, pattern) lookup from a markers map."""
    return sorted(
        ((role, re.compile(re.escape(marker)
                           if not _is_regex(marker) else marker,
                           re.IGNORECASE))
         for role, role_markers in markers.items()
         for marker in role_markers),
        key=lambda item: -len(item[1].pattern))


#: longest-marker-first lookup (longest match wins, case-insensitive)
_ORDERED: list[tuple[str, re.Pattern]] = build_ordered(_ROLE_MARKERS)

#: REAL Innovator BOMs carry internal ordering codes (``312-10382``)
#: instead of MPNs - the device family shows up in the DESCRIPTION
#: (``IC CLK GEN LOW JITTER ...`` / ``IC TRANSCEIVER ...``).  These
#: description markers back the part-number markers up; a part-number
#: match always wins.
_DESC_MARKERS: dict[str, tuple[str, ...]] = {
    CLOCK_GEN: ("CLK GEN", "CLOCK GEN", "CLOCK GENERATOR",
                "CLOCK BUFFER", "OSCILLATOR"),
    INTERFACE_CHIP: ("TRANSCEIVER", "ETHERNET PHY", " CAN ",
                     "LIN DRIVER"),
    FPGA: ("FPGA", "SOC FPGA"),
    LOAD: ("MICROCONTROLLER", "MICROPROCESSOR", "APPLICATION "
           "PROCESSOR", "MEMORY", "DRAM"),
}
_DESC_ORDERED: list[tuple[str, re.Pattern]] = [
    (role, re.compile(re.escape(marker), re.IGNORECASE))
    for role, markers in _DESC_MARKERS.items() for marker in markers]
_NAME_FPGA_RE = re.compile(
    r"(FPGA|AG25|AG32|XC7|XCU|ARTIX|KINTEX|VIRTEX)", re.IGNORECASE)


def role_for_part_number(pn: str, description: str = "") -> str | None:
    """Device role of *pn* / *description* (None when unknown).

    Longest part-number marker match wins (case-insensitive); the
    description markers back the PN up (real BOMs carry internal
    ordering codes, the family lives in the description).  Accepts
    the bare part number from ``BomRecord.part_number`` and the
    merged component record's ``part_number`` field.
    """
    text = str(pn or "").upper()
    if text:
        for role, pattern in _ORDERED:
            if pattern.search(text):
                return role
    desc = str(description or "").upper()
    if desc:
        for role, pattern in _DESC_ORDERED:
            if pattern.search(desc):
                return role
    return None
