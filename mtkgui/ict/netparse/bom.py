# -*- coding: utf-8 -*-
"""BOM import + component library (headless, no Qt) - M6 W1.

The BOM provides an authoritative ``RefDes -> MPN / DNP`` mapping that
enhances the component library and gives the net classifier its
device-role / input-rail evidence.  It never takes part in net
connectivity parsing / classification / filtering.

This module is the SINGLE source of truth used by BOTH the GUI
(Design Input "Import BOM…" + Parse Nets) and the headless CLI /
library builder - the legacy dead-code BOM / component modules were
merged here (M6 W1).

Supported input: ``.csv`` and ``.xlsx`` (``.xls`` is rejected with a
clear message - save it as ``.xlsx`` or ``.csv``).

Header detection scans the first :data:`HEADER_SCAN_ROWS` rows for a
row carrying both a Reference-Designator alias and a part-number
alias.  Real Innovator exports use ``Reference Designator`` /
``Name`` / ``Number`` / ``Description`` / ``Quantity`` - ``Name`` is
the internal ordering code, ``Number`` the manufacturer part number;
the part-number alias priority keeps an explicit ``MPN`` column
first.  A ``Quantity`` of 0 marks a DNP line when no DNP column
exists.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

HEADER_SCAN_ROWS = 20

#: maximum refdes range expansion (C1-C500); larger ranges are kept
#: as the original text and reported as a warning
MAX_RANGE = 500

_REFDES_ALIASES: tuple[str, ...] = (
    "reference designator", "ref des", "ref. des.", "refdes",
    "reference", "designator", "part reference", "component",
)
#: part-number aliases in priority order (higher = preferred)
_MPN_ALIASES: tuple[str, ...] = (
    "mpn", "manufacturer part number", "mfr part number",
    "part number", "part no", "part#", "part #", "pn",
    "ordering code", "name", "number",
)
_DESC_ALIASES: tuple[str, ...] = (
    "description", "desc", "value", "comment",
)
_DNP_ALIASES: tuple[str, ...] = (
    "dnp", "do not populate", "do not stuff", "not fitted",
    "not populated", "nf", "populate", "fitted",
)
_QTY_ALIASES: tuple[str, ...] = ("quantity", "qty")
#: vendor / manufacturer aliases (M2 A5; priority after part_number).
#: The Chinese column headers are written as unicode escapes so the
#: factory-floor English-UI guard sees no CJK source text; the values
#: are identical strings.
_VENDOR_ALIASES: tuple[str, ...] = (
    "vendor", "manufacturer", "mfr", "make",
    "\u5382\u5bb6", "\u5236\u9020\u5546", "\u5382\u5546",
)
#: value aliases (M2 A5: feeds the passive-bridge detection in the
#: netparse B0 stage - 0-ohm resistors / ferrite beads).  Priority
#: AFTER part_number; "value" here beats the description fallback.
_VALUE_ALIASES: tuple[str, ...] = (
    "value", "val", "resistance", "capacitance", "inductance",
    "impedance",
)

_DNP_TRUE = {"y", "yes", "1", "true", "dnp", "do not populate",
             "do not stuff", "not fitted", "not populated", "nf"}

_RANGE_RE = re.compile(
    r"^([A-Za-z_]+)(\d+)\s*(?:-|\.\.|~|\u2014|\u2013)\s*"
    r"([A-Za-z_]*)(\d+)$")
_REFDES_SPLIT_RE = re.compile(r"[,;/&\s]+")


@dataclass
class BomRecord:
    """One BOM line (a single RefDes after splitting/expansion)."""

    refdes: str
    part_number: str = ""
    description: str = ""
    dnp: bool = False
    vendor: str = ""
    value: str = ""


@dataclass
class BomData:
    """Parsed BOM content.

    Attributes:
        records:  One record per RefDes (order preserved).
        warnings: Non-fatal parse observations.
    """

    records: list[BomRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: detected column map (``refdes`` / ``mpn`` / ``description`` /
    #: ``vendor`` / ``value`` -> index; -1 = column genuinely absent).
    #: M2 Fix 4: lets callers report truthful per-column availability
    #: instead of silently showing empty vendor / value values.
    columns: dict[str, int] = field(default_factory=dict)


def _norm_header(value) -> str:
    """Normalize a header cell for alias matching."""
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text.rstrip(".:")


def _find_column(headers: list[str], aliases: tuple[str, ...],
                 taken: set[int] | None = None) -> int:
    """First alias match (in alias priority order), not already used."""
    taken = taken or set()
    for alias in aliases:
        for index, name in enumerate(headers):
            if index in taken:
                continue
            if name == alias:
                return index
    for alias in aliases:
        for index, name in enumerate(headers):
            if index in taken:
                continue
            if alias in name:
                return index
    return -1


def split_refdes(value: str) -> tuple[list[str], list[str]]:
    """Split a RefDes cell into individual designators.

    Supports comma / semicolon / slash / ampersand / whitespace
    separators and same-prefix numeric ranges (``C1-C3``, ``C1..C3``,
    ``C1~C3``, ``C1—C3``).  Duplicates are dropped preserving order.

    Returns:
        ``(refdes_list, warnings)``.
    """
    warnings: list[str] = []
    out: list[str] = []
    seen: set[str] = set()
    for token in _REFDES_SPLIT_RE.split(str(value or "").strip()):
        token = token.strip()
        if not token:
            continue
        expanded = _expand_range(token, warnings)
        for refdes in expanded:
            key = refdes.upper()
            if key in seen:
                continue
            seen.add(key)
            out.append(refdes)
    return out, warnings


def _expand_range(token: str, warnings: list[str]) -> list[str]:
    """Expand one ``C1-C3`` token (returns the token itself when it is
    not a range / the range exceeds :data:`MAX_RANGE`)."""
    match = _RANGE_RE.match(token)
    if not match:
        return [token]
    left_prefix, left_num, right_prefix, right_num = match.groups()
    right_prefix = right_prefix or left_prefix
    if right_prefix.upper() != left_prefix.upper():
        return [token]                 # different prefixes: not a range
    start, end = int(left_num), int(right_num)
    if end < start:
        start, end = end, start
    if end - start + 1 > MAX_RANGE:
        warnings.append(
            f"refdes range {token} exceeds {MAX_RANGE} items - kept "
            "unexpanded")
        return [token]
    digits = len(left_num)
    return [f"{left_prefix}{i:0{digits}d}"
            for i in range(start, end + 1)]


def _truthy_dnp(value) -> bool:
    """True for the accepted DNP truthy spellings."""
    return str(value or "").strip().lower() in _DNP_TRUE


def _zero_quantity(value) -> bool:
    """True when a Quantity cell is the number 0."""
    text = str(value if value is not None else "").strip()
    if not text:
        return False
    try:
        return float(text) == 0
    except ValueError:
        return False


def _read_rows(path: str) -> list[list]:
    """Read CSV / XLSX rows (list of cell values)."""
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if suffix == "xls":
        raise ValueError(
            "unsupported BOM type: .xls (save as .xlsx or .csv)")
    if suffix == "csv":
        from mtkgui.ict.netparse import read_text_any_encoding
        text = read_text_any_encoding(path)
        return [list(row) for row in csv.reader(io.StringIO(text))]
    if suffix in ("xlsx", "xlsm"):
        try:
            import openpyxl
        except ImportError as exc:      # pragma: no cover - env guard
            raise ValueError("openpyxl is required to read .xlsx BOMs") \
                from exc
        workbook = openpyxl.load_workbook(
            path, read_only=True, data_only=True)
        try:
            sheet = workbook.worksheets[0]
            return [list(row) for row in
                    sheet.iter_rows(values_only=True)]
        finally:
            workbook.close()
    raise ValueError(f"unsupported BOM type: .{suffix or '?'} "
                     "(use .csv or .xlsx)")


def parse_bom(path: str) -> BomData:
    """Parse a BOM file into :class:`BomData`.

    Args:
        path: ``.csv`` / ``.xlsx`` BOM file path.

    Returns:
        :class:`BomData` with one record per RefDes.

    Raises:
        ValueError: Unreadable/unsupported file, missing header or an
                    empty BOM.
    """
    try:
        rows = _read_rows(path)
    except OSError as exc:
        raise ValueError(f"cannot read BOM: {exc}") from exc
    if not rows:
        raise ValueError("BOM is empty")

    header_index = -1
    columns: dict[str, int] = {}
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        headers = [_norm_header(cell) for cell in row]
        ref_col = _find_column(headers, _REFDES_ALIASES)
        if ref_col < 0:
            continue
        mpn_col = _find_column(headers, _MPN_ALIASES, {ref_col})
        if mpn_col < 0:
            continue
        header_index = index
        value_col = _find_column(headers, _VALUE_ALIASES,
                                 {ref_col, mpn_col})
        desc_taken = {ref_col, mpn_col}
        if value_col >= 0:
            desc_taken.add(value_col)   # value beats description
        columns = {
            "refdes": ref_col,
            "mpn": mpn_col,
            "description": _find_column(headers, _DESC_ALIASES,
                                        desc_taken),
            "dnp": _find_column(
                headers, _DNP_ALIASES, {ref_col, mpn_col}),
            "quantity": _find_column(
                headers, _QTY_ALIASES, {ref_col, mpn_col}),
            "vendor": _find_column(
                headers, _VENDOR_ALIASES, {ref_col, mpn_col}),
            "value": value_col,
        }
        break
    if header_index < 0:
        raise ValueError(
            "BOM header not found: a Reference Designator column and a "
            "part-number column (MPN / Part Number / Name) are "
            "required")

    data = BomData()
    data.columns = dict(columns)
    for row in rows[header_index + 1:]:
        if not row or not any(str(cell or "").strip() for cell in row):
            continue
        refdes_cell = _cell(row, columns["refdes"])
        part = _cell(row, columns["mpn"])
        description = _cell(row, columns["description"])
        refdes_list, warnings = split_refdes(refdes_cell)
        data.warnings.extend(warnings)
        if not refdes_list:
            continue
        if not part:
            data.warnings.append(
                f"BOM line skipped (empty part number): {refdes_cell}")
            continue
        dnp = False
        if columns["dnp"] >= 0:
            dnp = _truthy_dnp(_cell(row, columns["dnp"]))
        elif columns["quantity"] >= 0:
            dnp = _zero_quantity(_cell(row, columns["quantity"]))
        for refdes in refdes_list:
            data.records.append(BomRecord(
                refdes=refdes, part_number=part,
                description=description, dnp=dnp,
                vendor=_cell(row, columns.get("vendor", -1)),
                value=_cell(row, columns.get("value", -1))))
    if not data.records:
        raise ValueError("BOM contains no component records")
    return data


def _cell(row: list, index: int) -> str:
    """One cell as stripped text ("" for missing / None)."""
    if index < 0 or index >= len(row):
        return ""
    value = row[index]
    return str(value).strip() if value is not None else ""


# ------------------------------------------------------- component library
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
        description: BOM device description ("" when the source has
                     none) - the netparse input-path / device-role
                     evidence reads it.
        dev_category: Fixed category set membership.
        note:        Free-form user note (empty until edited).
        dnp:         Do-Not-Populate flag (BOM OR-merged).
        vendor:      Manufacturer / vendor name ("" when unknown).
        value:       Passive value (``0R`` / ``1K`` / ``FB`` ...,
                     feeds the B0 passive-bridge detection).
    """

    refdes: str
    part_number: str = ""
    description: str = ""
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

    def netparse_library(self) -> dict:
        """The ONE library dict handed to ``parse_testable_nets``.

        PART 4: same ``ComponentLibrary`` records, no second BOM parse.
        DNP parts are KEPT (netparse's bridge / conflict logic handles
        them downstream).  Shape matches the headless library format
        ``{refdes: {part_number, description}}``; M7 adds the BOM
        ``dev_category`` so the DIO-write isolation assessment can
        flag active devices.
        """
        return {rec.refdes: {"part_number": rec.part_number,
                             "description": rec.description,
                             "dev_category": rec.dev_category}
                for rec in self.records}


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


def merge_bom(library: ComponentLibrary, bom: BomData) \
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
                description=entry.description, dev_category=category,
                dnp=entry.dnp, vendor=entry.vendor, value=entry.value))
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
        # PART 4: the BOM DESCRIPTION is the netparse input-path /
        # device-role evidence (single data source into both consumers)
        if entry.description:
            record.description = entry.description
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


# --------------------------------------------------------- GUI entry point
def load_bom_library(path: str) -> tuple[dict, BomMergeReport, BomData]:
    """Parse a BOM file into the netparse library dict.

    The GUI (Design Input Import BOM + Parse Nets) and the CLI share
    this ONE entry point, so ``parse_testable_nets`` receives the same
    library shape / evidence in both paths.

    Args:
        path: ``.csv`` / ``.xlsx`` BOM file path.

    Returns:
        ``(library, report, bom)`` - ``library`` is the
        ``{refdes: {part_number, description}}`` dict.

    Raises:
        ValueError: same reasons as :func:`parse_bom`.
    """
    bom = parse_bom(path)
    library = ComponentLibrary()
    report = merge_bom(library, bom)
    return library.netparse_library(), report, bom
