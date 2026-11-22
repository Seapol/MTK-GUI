# -*- coding: utf-8 -*-
"""Excel export for the Yaml Build modules (V4.0 rule 5.3).

One normalized worksheet (``YamlBuild``): one row per module
parameter plus one per-module ``__module__`` row carrying the
Enable/Disable state and remarks, plus the three Channel Allocation
sheets.  M103: the config workbook is **export-only** - the import
chain was deleted (the MTK ICT Excel Sheet is the only writable
limits carrier).
"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import PatternFill, Protection
from openpyxl.worksheet.worksheet import Worksheet

from mtkgui.gui.yamlbuild.channel_allocation import (
    ChannelAllocationData,
    TABLE_SPECS,
)
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.schema import (
    MODULE_FIELDS,
    T_FLOAT,
    T_INT,
    module_title,
)
from mtkgui.gui.yamlbuild.stages import STAGE_KEYS

SHEET_NAME = "YamlBuild"
_HEADERS = ("Module", "Module Key", "Parameter", "Value", "Type",
            "Required", "Min", "Max", "Choices", "Enabled", "Remarks")
#: 1-based columns of the two cells the M91 per-cell lock reads
_VALUE_COLUMN = 4
_TYPE_COLUMN = 5

# ------------------------------------------------------------------
# item 18: Channel Allocation three-table sheets (Power / Clock /
# GPIO) - the Excel layout maps one-to-one onto the ``yaml_build ->
# channel_allocation`` YAML nodes.  Every config cell carries the
# SAME dropdown enum values as the GUI tables (no free text); the
# Status column is auto OK/NOK on export and READ-ONLY on import
# (recomputed by the GUI validation rules).
# ------------------------------------------------------------------
ALLOCATION_SHEET_NAMES = {"power": "Power", "clock": "Clock",
                          "gpio": "GPIO"}
ALLOCATION_HEADERS = {
    "power": ("Net name", "Test point", "R-GND", "Power rails",
              "Voltage", "R-GND Min limit (ohm)", "Nominal (V)",
              "Lower (V)", "Upper (V)"),
    "clock": ("Net name", "Test point", "SE Clock Hz",
              "Frequency band", "Nominal (kHz)", "Lower (kHz)",
              "Upper (kHz)"),
    "gpio": ("Net name", "Test point", "DIO Channel"),
}
#: row keys written per table kind (no auto Status column anywhere)
_ALLOC_ROW_KEYS = {
    "power": ("net", "test_point", "impedance", "power_rails",
              "voltage", "r_gnd_min_ohm", "nominal_v", "lower_v",
              "upper_v"),
    "clock": ("net", "test_point", "se_clock_hz", "band",
              "nominal_khz", "lower_khz", "upper_khz"),
    "gpio": ("net", "test_point", "dio_channel"),
}
#: M73 review-only guard: Excel is the "no-GUI quick review / light
#: limits edit" carrier.  ONLY these limit fields are applied on import;
#: every structural field stays owned by the GUI.
ALLOC_LIMIT_KEYS = {
    "power": ("r_gnd_min_ohm", "nominal_v", "lower_v", "upper_v"),
    "clock": ("nominal_khz", "lower_khz", "upper_khz"),
    "gpio": (),
}
READONLY_SUFFIX = " (Read-only \u2014 edit in MTK GUI)"
EDITABLE_SUFFIX = " (editable \u2014 limits only)"
#: M103: the allocation limit columns are a snapshot, never a second
#: editable copy of the limits (contract §6 / §2.4)
MIRROR_SUFFIX = " (read-only mirror)"
STRUCTURE_EDITABLE_SUFFIX = " (editable)"
READONLY_FILL_RGB = "D9D9D9"
EDITABLE_FILL_RGB = "FFF2CC"

#: allocation columns that stay editable (identity only, never limits)
_ALLOC_EDITABLE_KEYS = ("net", "test_point")

#: parameter types whose Value cell is editable in Excel (M91).  Numbers only:
#: limits, nominals, timings and counts.  Free text / enums / booleans stay
#: read-only so an Excel edit can never reshape a YAML section.
PARAM_EDITABLE_TYPES = (T_INT, T_FLOAT)


def _base_header(text: str) -> str:
    """Header text without any read-only / editable suffix."""
    text = str(text or "").strip()
    for suffix in (READONLY_SUFFIX, EDITABLE_SUFFIX, MIRROR_SUFFIX,
                   STRUCTURE_EDITABLE_SUFFIX):
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


def _style_cell(cell, editable: bool) -> None:
    if editable:
        cell.fill = PatternFill(fill_type="solid",
                                start_color=EDITABLE_FILL_RGB,
                                end_color=EDITABLE_FILL_RGB)
    else:
        cell.fill = PatternFill(fill_type="solid",
                                start_color=READONLY_FILL_RGB,
                                end_color=READONLY_FILL_RGB)
    cell.protection = Protection(locked=not editable)


def _style_sheet(ws: Worksheet, editable_columns: set,
                 mirror_columns: set = frozenset()) -> None:
    """Apply the review-only guard to one allocation sheet.

    Identity columns (``net`` / ``test_point``) are light yellow
    (FFF2CC) and unlocked; the M103 limit columns are grey (D9D9D9),
    locked and labelled ``(read-only mirror)``; every other column
    keeps the M73 read-only treatment.  The sheet is protected without
    a password."""
    max_col = ws.max_column
    for idx in range(1, max_col + 1):
        header = ws.cell(row=1, column=idx)
        editable = idx in editable_columns
        base = _base_header(header.value)
        if editable:
            suffix = STRUCTURE_EDITABLE_SUFFIX
        elif idx in mirror_columns:
            suffix = MIRROR_SUFFIX
        else:
            suffix = READONLY_SUFFIX
        header.value = base + suffix
        _style_cell(header, editable)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row,
                            min_col=1, max_col=max_col):
        for cell in row:
            _style_cell(cell, cell.column in editable_columns)
    ws.protection.sheet = True


def _style_param_sheet(ws: Worksheet) -> None:
    """M91: per-cell lock on the parameter sheet.

    The header row keeps the read-only suffix everywhere except ``Value``;
    a data row's ``Value`` cell is editable only when its ``Type`` cell is
    ``int`` or ``float``.  Every other cell (Module / Module Key / Parameter /
    Required / Min / Max / Choices / Enabled / Remarks) stays grey and locked,
    so the sheet cannot grow, shrink or reshape a module from Excel.
    """
    max_col = ws.max_column
    for idx in range(1, max_col + 1):
        header = ws.cell(row=1, column=idx)
        editable = idx == _VALUE_COLUMN
        base = _base_header(header.value)
        suffix = EDITABLE_SUFFIX if editable else READONLY_SUFFIX
        header.value = base + suffix
        _style_cell(header, editable)
    for row_index in range(2, ws.max_row + 1):
        type_text = str(ws.cell(row=row_index, column=_TYPE_COLUMN).value
                        or "").strip().lower()
        editable_row = type_text in PARAM_EDITABLE_TYPES
        for idx in range(1, max_col + 1):
            cell = ws.cell(row=row_index, column=idx)
            _style_cell(cell, editable_row and idx == _VALUE_COLUMN)
    ws.protection.sheet = True


def _alloc_editable_columns(kind: str) -> set:
    """1-based column indices of the identity cells (net / TP)."""
    return {i + 1 for i, key in enumerate(_ALLOC_ROW_KEYS[kind])
            if key in _ALLOC_EDITABLE_KEYS}


def _alloc_mirror_columns(kind: str) -> set:
    """1-based column indices of the limit columns (read-only mirror)."""
    limits = ALLOC_LIMIT_KEYS[kind]
    return {i + 1 for i, key in enumerate(_ALLOC_ROW_KEYS[kind])
            if key in limits}


def export_to_excel(model: YamlBuildModel, path: str) -> int:
    """Export the full model (all modules, all fields) to an .xlsx
    file as a REVIEW-ONLY workbook: the YamlBuild sheet is fully
    read-only, the allocation sheets unlock only ``net`` / ``test_point``
    (M103: the limit columns are a read-only mirror) and every sheet is
    protected without a password.

    Args:
        model: The data model.
        path:  Target .xlsx path.

    Returns:
        Number of rows written.

    Raises:
        OSError: The file could not be written.
    """
    wb = Workbook()
    ws: Worksheet = wb.active
    ws.title = SHEET_NAME
    ws.append(_HEADERS)
    rows = 0
    for key in STAGE_KEYS:
        specs = MODULE_FIELDS.get(key, ())
        enabled = model.is_enabled(key)
        params = model.get_params(key)
        ws.append([module_title(key), key, "__module__",
                   "", "", "", "", "", "", enabled, ""])
        rows += 1
        for spec in specs:
            ws.append([
                module_title(key), key, spec.name,
                params.get(spec.name, spec.default), spec.ftype,
                "yes" if spec.required else "no",
                spec.minimum if spec.minimum is not None else "",
                spec.maximum if spec.maximum is not None else "",
                "/".join(spec.choices), enabled, spec.remarks,
            ])
            rows += 1
    # item 18: the three Channel Allocation tables (Power / Clock /
    # GPIO) as dedicated sheets - one-to-one mapped with the
    # ``channel_allocation`` YAML nodes; Status is auto OK/NOK
    alloc = ChannelAllocationData.from_dict(model.get_channel_allocation())
    for kind, _cols in TABLE_SPECS:
        aw: Worksheet = wb.create_sheet(ALLOCATION_SHEET_NAMES[kind])
        aw.append(ALLOCATION_HEADERS[kind])
        keys = _ALLOC_ROW_KEYS[kind]
        for row in getattr(alloc, kind):
            values = {key: getattr(row, key) for key in keys}
            aw.append([values[key] for key in keys])
            rows += 1
        _style_sheet(aw, _alloc_editable_columns(kind),
                     _alloc_mirror_columns(kind))
    # M91: numeric YamlBuild parameters are editable in Excel; every
    # non-numeric cell stays grey / locked (structure is never adjustable)
    _style_param_sheet(ws)
    wb.save(path)
    return rows


