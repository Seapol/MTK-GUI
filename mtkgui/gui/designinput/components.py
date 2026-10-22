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
from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # pragma: no cover - typing only
    from .bom import BomData

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
        dnp:         Do-Not-Populate flag (BOM OR-merged).
        vendor:      Manufacturer / vendor name ("" when unknown).
        value:       Passive value (``0R`` / ``1K`` / ``FB`` ...,
                     feeds the B0 passive-bridge detection).
    """

    refdes: str
    part_number: str = ""
    dev_category: str = CATEGORY_OTHER
    note: str = ""
    dnp: bool = False
    vendor: str = ""
    value: str = ""


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
        """All non-DNP ``main_mcu`` records (core-id derivation).

        DNP parts are excluded (M2 A1): a not-populated MCU must not
        drive the project core id.
        """
        return [r for r in self.records
                if r.dev_category == CATEGORY_MAIN_MCU and not r.dnp]

    def regulators(self) -> list[ComponentRecord]:
        """All non-DNP pmic / dcdc / ldo records (power-tree drafting).

        DNP parts are excluded (M2 A1): a not-populated regulator
        never becomes a draft main / regulator node.
        """
        keep = (CATEGORY_PMIC, CATEGORY_DCDC, CATEGORY_LDO)
        return [r for r in self.records
                if r.dev_category in keep and not r.dnp]

    def dnp_regulators(self) -> list[ComponentRecord]:
        """DNP pmic / dcdc / ldo records (DNP-only rail warning)."""
        keep = (CATEGORY_PMIC, CATEGORY_DCDC, CATEGORY_LDO)
        return [r for r in self.records
                if r.dev_category in keep and r.dnp]


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


#: BOM ``Description`` fallback hints - the internal ordering code
#: alone is often not classifiable, while the description names the
#: device family (``IC MCU ...`` / ``IC VREG LDO ...``).
_BOM_DESCRIPTION_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (CATEGORY_MAIN_MCU, re.compile(
        r"\bMCU\b|\bMPU\b|\bCPU\b|MICROCONTROLLER|MICROPROCESSOR|"
        r"\bPROCESSOR\b", re.IGNORECASE)),
    (CATEGORY_PMIC, re.compile(
        r"\bPMIC\b|POWER MANAGEMENT", re.IGNORECASE)),
    (CATEGORY_DCDC, re.compile(
        r"\bBUCK\b|DC[-/ ]?DC|SWITCHING REGULATOR", re.IGNORECASE)),
    (CATEGORY_LDO, re.compile(
        r"\bLDO\b|LINEAR REGULATOR|\bVREG\b", re.IGNORECASE)),
    (CATEGORY_TRANSCEIVER, re.compile(
        r"TRANSCEIVER|\bPHY\b|ETHERNET", re.IGNORECASE)),
)

#: descriptions that must NOT be promoted to ``main_mcu`` even when
#: they mention MCU / MPU: memory parts ("IC MCU SEMPERFLASH") and
#: support circuits ("IC MPU RESET CIRC") are not the core device.
_BOM_NOT_MAIN_RE = re.compile(
    r"SEMPER|EEPROM|\bMEM\b|DRAM|RESET|\bCIRC\b", re.IGNORECASE)


def _categorize_bom(part_number: str, refdes: str,
                    description: str) -> str:
    """Classify a BOM device (PN/RefDes first, description fallback)."""
    category = categorize(part_number, refdes)
    if category != CATEGORY_OTHER:
        return category
    text = description or ""
    if _BOM_NOT_MAIN_RE.search(text):
        return CATEGORY_OTHER
    for category, pattern in _BOM_DESCRIPTION_RULES:
        if pattern.search(text):
            return category
    return CATEGORY_OTHER


@dataclass
class BomMergeReport:
    """BOM merge statistics (Event-Log summary).

    Attributes:
        records:   BOM records processed.
        updated:   Existing library PNs overwritten by the BOM.
        added:     BOM-only RefDes appended to the library.
        dnp:       BOM records flagged Do-Not-Populate.
        conflicts: ``(refdes, old_pn, new_pn)`` for review.
    """

    records: int = 0
    updated: int = 0
    added: int = 0
    dnp: int = 0
    conflicts: list[tuple[str, str, str]] = field(default_factory=list)


def merge_bom(library: ComponentLibrary, bom: "BomData") \
        -> BomMergeReport:
    """Merge BOM RefDes -> MPN / DNP data into the component library.

    The BOM is authoritative: a non-empty MPN overwrites the
    schematic-derived PN and the record is re-categorized.  BOM-only
    RefDes are appended (original order kept), DNP is OR-merged, and
    devices missing from the BOM are never removed.

    Args:
        library: Component library built from the schematic.
        bom:     Parsed BOM data.

    Returns:
        :class:`BomMergeReport` with update / conflict statistics.
    """
    report = BomMergeReport(records=len(bom.records))
    for entry in bom.records:
        record = library.by_refdes(entry.refdes)
        if entry.dnp:
            report.dnp += 1
        if record is None:
            category = _categorize_bom(
                entry.part_number, entry.refdes, entry.description)
            library.records.append(ComponentRecord(
                refdes=entry.refdes, part_number=entry.part_number,
                dev_category=category, dnp=entry.dnp,
                vendor=entry.vendor, value=entry.value))
            if category == CATEGORY_OTHER:
                library.unclassified.append(entry.refdes)
            report.added += 1
            continue
        if entry.part_number and entry.part_number != record.part_number:
            if record.part_number:
                report.conflicts.append(
                    (entry.refdes, record.part_number, entry.part_number))
            record.part_number = entry.part_number
            report.updated += 1
        # M2 Fix 4: the BOM is authoritative even when the part number
        # is unchanged - its DESCRIPTION carries the device family
        # (``IC MCU ...`` / ``IC VREG ...``), so re-categorize always.
        category = _categorize_bom(
            entry.part_number, entry.refdes, entry.description)
        if category != record.dev_category:
            record.dev_category = category
            _sync_unclassified(library, record)
        record.dnp = record.dnp or entry.dnp
        record.vendor = record.vendor or entry.vendor
        record.value = record.value or entry.value
    return report


def pdf_only_refdes(components: list[tuple[str, str]],
                    bom_records) -> tuple[list[str], str]:
    """RefDes found ONLY in the PDF schematic (M2 A2).

    The BOM is the authoritative RefDes list: PDF-only RefDes carry
    no BOM record and are dropped from power / clock candidates.

    Args:
        components:  (refdes, part_number) pairs from the PDF parser.
        bom_records: ``BomRecord`` iterable (the authoritative list).

    Returns:
        ``(dropped, warning)`` - the ordered unique dropped RefDes
        list and ONE aggregated warning line ("" when nothing is
        dropped).
    """
    bom_refs = {rec.refdes.upper() for rec in bom_records}
    seen: set[str] = set()
    pdf_refs: list[str] = []
    for refdes, _part in components:
        key = refdes.upper()
        if key not in seen:
            seen.add(key)
            pdf_refs.append(refdes)
    dropped = [r for r in pdf_refs if r.upper() not in bom_refs]
    if not dropped:
        return [], ""
    warning = (f"{len(dropped)} PDF-only RefDes dropped (not present "
               f"in BOM): {', '.join(dropped[:3])} ...")
    return dropped, warning


def _sync_unclassified(library: ComponentLibrary,
                       record: ComponentRecord) -> None:
    """Keep ``unclassified`` in sync after a category change."""
    listed = record.refdes in library.unclassified
    if record.dev_category == CATEGORY_OTHER and not listed:
        library.unclassified.append(record.refdes)
    elif record.dev_category != CATEGORY_OTHER and listed:
        library.unclassified.remove(record.refdes)
