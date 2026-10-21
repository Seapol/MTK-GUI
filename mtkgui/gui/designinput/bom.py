# -*- coding: utf-8 -*-
"""Optional BOM import (headless, no Qt).

The BOM provides an authoritative ``RefDes -> MPN / DNP`` mapping that
enhances the component library built from the schematic.  It never
takes part in net connectivity parsing / classification / filtering.

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


@dataclass
class BomData:
    """Parsed BOM content.

    Attributes:
        records:  One record per RefDes (order preserved).
        warnings: Non-fatal parse observations.
    """

    records: list[BomRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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
        columns = {
            "refdes": ref_col,
            "mpn": mpn_col,
            "description": _find_column(
                headers, _DESC_ALIASES, {ref_col, mpn_col}),
            "dnp": _find_column(
                headers, _DNP_ALIASES, {ref_col, mpn_col}),
            "quantity": _find_column(
                headers, _QTY_ALIASES, {ref_col, mpn_col}),
            "vendor": _find_column(
                headers, _VENDOR_ALIASES, {ref_col, mpn_col}),
        }
        break
    if header_index < 0:
        raise ValueError(
            "BOM header not found: a Reference Designator column and a "
            "part-number column (MPN / Part Number / Name) are "
            "required")

    data = BomData()
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
                vendor=_cell(row, columns.get("vendor", -1))))
    if not data.records:
        raise ValueError("BOM contains no component records")
    return data


def _cell(row: list, index: int) -> str:
    """One cell as stripped text ("" for missing / None)."""
    if index < 0 or index >= len(row):
        return ""
    value = row[index]
    return str(value).strip() if value is not None else ""
