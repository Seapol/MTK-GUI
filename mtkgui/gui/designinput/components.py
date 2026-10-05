# -*- coding: utf-8 -*-
"""Component-library construction and auto-classification
(spec B1-01-02).

Devices recovered from the schematic (text SPF or Smart-PDF) are
classified into the fixed category set:

``main_mcu / pmic / dcdc / ldo / transceiver / other``

Classification is a deterministic keyword pass over the part number
(with a RefDes fallback); anything unmatchable lands in ``other`` -
the caller logs a WARNING and the Device Library Editor lets the user
re-assign it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORY_MAIN_MCU = "main_mcu"
CATEGORY_PMIC = "pmic"
CATEGORY_DCDC = "dcdc"
CATEGORY_LDO = "ldo"
CATEGORY_TRANSCEIVER = "transceiver"
CATEGORY_OTHER = "other"

CATEGORIES = (CATEGORY_MAIN_MCU, CATEGORY_PMIC, CATEGORY_DCDC,
              CATEGORY_LDO, CATEGORY_TRANSCEIVER, CATEGORY_OTHER)

# ordered classification rules: (category, compiled keyword regex)
_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (CATEGORY_MAIN_MCU, re.compile(
        r"MMC?|MIMX|IMX|I\.MX|RT\d{4}|MCX|S32K|S32N|S32G|STM32|LPC|"
        r"KINETIS|K\d{2}[A-Z]\d|MW\d{4}", re.IGNORECASE)),
    (CATEGORY_PMIC, re.compile(
        r"PMIC|PF[0-9]{3}|MC34|MC94|PCA94[0-9]+PM|TPS65|BD71|BD72|"
        r"NX20|LPC55.*PMU|VREG", re.IGNORECASE)),
    (CATEGORY_DCDC, re.compile(
        r"BUCK|DC[- ]?DC|TPS6[0-9]|LTC3[0-9]|MP[0-9]{3}|NCP1[0-9]{2}|"
        r"BD9[0-9]|APW7|SY8[0-9]|MAX17", re.IGNORECASE)),
    (CATEGORY_LDO, re.compile(
        r"\bLDO|TPS7[0-9]|MIC5[0-9]|AP211|NCP7[0-9]|XC6[0-9]|"
        r"LD[0-9]{2}|REGULATOR", re.IGNORECASE)),
    (CATEGORY_TRANSCEIVER, re.compile(
        r"TRANSCEIVER|XCVR|TJA1[0-9]|SN65|SN66|MAX3[0-9]|LAN8[0-9]|"
        r"DP8[0-9]|KSZ[0-9]|CAN|RS485|RS232", re.IGNORECASE)),
)


@dataclass
class ComponentRecord:
    """One device-library entry.

    Attributes:
        refdes:      Reference designator (U1, R2, ...).
        part_number: Ordering code ("" when the source had none).
        dev_category: Fixed category set membership.
        note:        Free-form user note (empty until edited).
    """

    refdes: str
    part_number: str = ""
    dev_category: str = CATEGORY_OTHER
    note: str = ""


@dataclass
class ComponentLibrary:
    """Device library: ordered records + pin-net mapping view.

    Attributes:
        records:      ComponentRecord list in discovery order.
        unclassified: RefDes list auto-dumped into ``other`` (the
                      caller emits the WARNING per spec).
    """

    records: list[ComponentRecord] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)

    def by_refdes(self, refdes: str) -> ComponentRecord | None:
        """Return the record for *refdes* (None when absent)."""
        for rec in self.records:
            if rec.refdes == refdes:
                return rec
        return None

    def category_of(self, refdes: str) -> str:
        """Category of *refdes* (``other`` when unknown)."""
        rec = self.by_refdes(refdes)
        return rec.dev_category if rec else CATEGORY_OTHER

    def mains(self) -> list[ComponentRecord]:
        """All ``main_mcu`` records (project core-id derivation)."""
        return [r for r in self.records
                if r.dev_category == CATEGORY_MAIN_MCU]

    def regulators(self) -> list[ComponentRecord]:
        """All pmic / dcdc / ldo records (power-tree drafting)."""
        keep = (CATEGORY_PMIC, CATEGORY_DCDC, CATEGORY_LDO)
        return [r for r in self.records if r.dev_category in keep]


def categorize(part_number: str, refdes: str = "") -> str:
    """Classify one device from its part number / RefDes.

    Args:
        part_number: Ordering code ("" when unknown).
        refdes:      Reference designator (fallback hints).

    Returns:
        One of :data:`CATEGORIES`; unmatched -> ``other``.
    """
    haystack = f"{part_number} {refdes}"
    for category, pattern in _RULES:
        if pattern.search(haystack):
            return category
    return CATEGORY_OTHER


def build_library(components: list[tuple[str, str]]) -> ComponentLibrary:
    """Build the component library from parsed schematic pairs.

    Args:
        components: (refdes, part_number) pairs in discovery order
                    (native SPF or Smart-PDF source, see spec).

    Returns:
        :class:`ComponentLibrary`; every unclassifiable part lands in
        ``other`` and its RefDes is listed in ``unclassified``.
    """
    lib = ComponentLibrary()
    for refdes, part in components:
        category = categorize(part, refdes)
        if category == CATEGORY_OTHER:
            lib.unclassified.append(refdes)
        lib.records.append(
            ComponentRecord(refdes=refdes, part_number=part,
                            dev_category=category))
    return lib
