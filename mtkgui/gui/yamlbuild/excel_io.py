# -*- coding: utf-8 -*-
"""Excel round-trip for the Yaml Build modules (V4.0 rule 5.3).

One normalized worksheet (``YamlBuild``): one row per module
parameter plus one per-module ``__module__`` row carrying the
Enable/Disable state and remarks.  Export writes the full model;
Import validates every row against the field schema first and
applies only a fully-valid workbook (batch import with error
listing, no partial overwrites).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Protection
from openpyxl.worksheet.worksheet import Worksheet

from mtkgui.gui.yamlbuild.channel_allocation import (
    DRIVE_LEVELS,
    OP_CHOICES,
    UNSET,
    ChannelAllocationData,
    TABLE_SPECS,
)
from mtkgui.gui.yamlbuild.power_alloc import (
    CLOCK_BANDS,
    CLOCK_CHANNELS,
    DAQM908A_SENSE_CHANNELS,
    GPIO_DIO_CHANNELS,
    U2355A_AI_CHANNELS,
)
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.schema import MODULE_FIELDS, module_title
from mtkgui.gui.yamlbuild.stages import STAGE_KEYS

SHEET_NAME = "YamlBuild"
_HEADERS = ("Module", "Module Key", "Parameter", "Value", "Type",
            "Required", "Min", "Max", "Choices", "Enabled", "Remarks")

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
    "gpio": ("Net name", "Test point", "DIO Channel", "Op Type",
             "Drive Level"),
}
#: row keys written per table kind (no auto Status column anywhere)
_ALLOC_ROW_KEYS = {
    "power": ("net", "test_point", "impedance", "power_rails",
              "voltage", "r_gnd_min_ohm", "nominal_v", "lower_v",
              "upper_v"),
    "clock": ("net", "test_point", "se_clock_hz", "band",
              "nominal_khz", "lower_khz", "upper_khz"),
    "gpio": ("net", "test_point", "dio_channel", "op_type",
             "drive_level"),
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
READONLY_FILL_RGB = "D9D9D9"
EDITABLE_FILL_RGB = "FFF2CC"

#: per-cell dropdown enum validation (import pass 1)
_ALLOC_POOLS = {
    "power": {"impedance": DAQM908A_SENSE_CHANNELS,
              "power_rails": U2355A_AI_CHANNELS,
              "voltage": DAQM908A_SENSE_CHANNELS},
    "clock": {"se_clock_hz": CLOCK_CHANNELS,
              "band": tuple(dict.fromkeys(CLOCK_BANDS.values()))},
    "gpio": {"dio_channel": GPIO_DIO_CHANNELS,
             "op_type": OP_CHOICES,
             "drive_level": DRIVE_LEVELS},
}


@dataclass
class ImportReport:
    """Outcome of an Excel import.

    Attributes:
        applied:  True when the workbook was valid and processed.
        errors:   Row-attached validation errors (module-wide).
        imported: Number of changes applied (kept for old callers; equal
                  to ``len(applied_changes)``).
        applied_changes: Editable limit changes written to the model.
        ignored_changes: Read-only values found in the workbook but NOT
                  applied (structure / module parameters / enable flags).
    """

    applied: bool = False
    errors: list[str] = field(default_factory=list)
    imported: int = 0
    applied_changes: list[str] = field(default_factory=list)
    ignored_changes: list[str] = field(default_factory=list)


def _base_header(text: str) -> str:
    """Header text without the M73 read-only / editable suffix."""
    text = str(text or "").strip()
    for suffix in (READONLY_SUFFIX, EDITABLE_SUFFIX):
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


def _style_sheet(ws: Worksheet, editable_columns: set) -> None:
    """Apply the M73 review-only guard to one sheet.

    Every header gets the read-only / editable suffix, read-only
    columns are grey (D9D9D9) and locked, editable limit columns are
    light yellow (FFF2CC) and unlocked, and the sheet is protected
    without a password."""
    max_col = ws.max_column
    for idx in range(1, max_col + 1):
        header = ws.cell(row=1, column=idx)
        editable = idx in editable_columns
        base = _base_header(header.value)
        suffix = EDITABLE_SUFFIX if editable else READONLY_SUFFIX
        header.value = base + suffix
        _style_cell(header, editable)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row,
                            min_col=1, max_col=max_col):
        for cell in row:
            _style_cell(cell, cell.column in editable_columns)
    ws.protection.sheet = True


def _alloc_editable_columns(kind: str) -> set:
    """1-based column indices of the whitelisted limit fields."""
    limits = ALLOC_LIMIT_KEYS[kind]
    return {i + 1 for i, key in enumerate(_ALLOC_ROW_KEYS[kind])
            if key in limits}


def export_to_excel(model: YamlBuildModel, path: str) -> int:
    """Export the full model (all modules, all fields) to an .xlsx
    file as a REVIEW-ONLY workbook (M73): the YamlBuild sheet is fully
    read-only, the allocation sheets unlock only the limit columns and
    every sheet is protected without a password.

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
        _style_sheet(aw, _alloc_editable_columns(kind))
    # M73: the YamlBuild sheet is a pure review sheet - nothing on it
    # may be edited in Excel (all cells grey / locked)
    _style_sheet(ws, set())
    wb.save(path)
    return rows


def import_from_excel(model: YamlBuildModel, path: str) -> ImportReport:
    """Import and validate an .xlsx review workbook, then apply the
    whitelisted LIMIT columns only (M73).

    The workbook is validated completely BEFORE anything is applied:
    any invalid structural row (unknown module / parameter / bad value,
    missing Net name or Test point, invalid dropdown enum) aborts the
    import with the error list and applies NOTHING.  The ``YamlBuild``
    sheet is review-only - its module parameters and enable flags are
    validated but never applied (differences are reported as ignored).
    On the allocation sheets only ``ALLOC_LIMIT_KEYS`` are applied;
    every structural cell is read-only and skipped with an ignored
    entry.

    Args:
        model: The data model to update.
        path:  Source .xlsx path.

    Returns:
        :class:`ImportReport` with the outcome.
    """
    report = ImportReport()
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
    except OSError as exc:
        report.errors.append(f"cannot open file: {exc}")
        return report
    if SHEET_NAME not in wb.sheetnames:
        report.errors.append(f"missing worksheet {SHEET_NAME!r}")
        return report
    ws: Worksheet = wb[SHEET_NAME]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    # pass 1: validate everything
    parsed: dict[str, dict[str, str]] = {}
    enabled: dict[str, bool] = {}
    for line_no, row in enumerate(rows, start=2):
        values = ["" if v is None else str(v).strip() for v in row]
        values += [""] * (len(_HEADERS) - len(values))
        _module, key, param, value = values[0], values[1], values[2], \
            values[3]
        enabled_text = values[9].lower()
        if key not in STAGE_KEYS:
            if key:
                report.errors.append(
                    f"row {line_no}: unknown module key {key!r}")
            continue
        if param == "__module__":
            enabled[key] = enabled_text in ("true", "yes", "1", "enabled")
            continue
        specs = {s.name: s for s in MODULE_FIELDS.get(key, ())}
        if param not in specs:
            report.errors.append(
                f"row {line_no}: unknown parameter {param!r} "
                f"for module {key}")
            continue
        spec = specs[param]
        error = spec.validate(value)
        if error:
            report.errors.append(f"row {line_no}: {error}")
            continue
        parsed.setdefault(key, {})[param] = value
    # item 18: the three Channel Allocation sheets (Power / Clock /
    # GPIO) - optional (legacy workbooks stay importable); every
    # config cell must carry a valid dropdown enum value (no free
    # text); the Status column is read-only and ignored (auto).
    # M70: a pre-M70 workbook without the new limit / op_type /
    # drive_level columns still imports - the missing field keeps the
    # CURRENT model value (matched by net + test point), never reset.
    # M73 review-only guard: the allocation data stays fully GUI-owned
    # except for the whitelisted limit fields.  Start from the CURRENT
    # model so structural values (and fields the sheet does not carry)
    # are preserved; only limit cells are overwritten.
    alloc_final: dict[str, list[dict]] = {}
    current = ChannelAllocationData.from_dict(model.get_channel_allocation())
    for kind, _cols in TABLE_SPECS:
        alloc_final[kind] = [dict(row.to_dict())
                             for row in getattr(current, kind)]
    limit_changed = False
    for kind, _cols in TABLE_SPECS:
        sheet = ALLOCATION_SHEET_NAMES[kind]
        if sheet not in wb.sheetnames:
            continue
        aw: Worksheet = wb[sheet]
        sheet_rows = list(aw.iter_rows(values_only=True))
        if not sheet_rows:
            continue
        # M73: the exported headers carry the read-only / editable
        # suffix - match on the base title
        header = [_base_header("" if cell is None else str(cell))
                  for cell in sheet_rows[0]]
        keys = _ALLOC_ROW_KEYS[kind]
        #: column index for every key present in this workbook
        present = {key: header.index(title)
                   for key, title in zip(keys, ALLOCATION_HEADERS[kind])
                   if title in header}
        status_idx = header.index("Status") if "Status" in header else None
        previous = {str(getattr(row, "net", "")): row
                    for row in getattr(current, kind)}
        rows_out = alloc_final[kind]
        by_net = {str(row.get("net", "")): row for row in rows_out}
        limit_keys = ALLOC_LIMIT_KEYS[kind]
        structure_keys = tuple(key for key in keys
                               if key not in limit_keys)
        for line_no, row in enumerate(sheet_rows[1:], start=2):
            values = ["" if v is None else str(v).strip() for v in row]
            net = (values[present["net"]]
                   if "net" in present and present["net"] < len(values)
                   else "")
            old = previous.get(net)
            cells = {}
            for key in keys:
                if key in present and present[key] < len(values):
                    cells[key] = values[present[key]]
                else:
                    # legacy workbook: keep the value already on the model
                    cells[key] = str(getattr(old, key, "")) \
                        if old is not None else ""
            if status_idx is not None:
                cells["status"] = (values[status_idx]
                                   if status_idx < len(values) else "")
            prefix = f"{sheet} row {line_no}"
            if not cells.get("net"):
                report.errors.append(f"{prefix}: Net name required")
                continue
            if not cells.get("test_point"):
                report.errors.append(f"{prefix}: Test point required")
                continue
            for key, allowed in _ALLOC_POOLS[kind].items():
                text = cells.get(key, "")
                if text and text != UNSET and text not in allowed:
                    report.errors.append(
                        f"{prefix}: {key.replace('_', ' ').title()} "
                        f"{text!r} not in {'/'.join(allowed)}")
            if report.errors:
                continue
            target = by_net.get(net)
            if target is None:
                # a brand-new row has no GUI-owned structure to keep -
                # it is never created from Excel
                for key in limit_keys:
                    value = cells.get(key, "")
                    if key in present and value:
                        report.ignored_changes.append(
                            f"{prefix}: {key} (row not on the model)")
                continue
            # structural cells are read-only: differences are ignored
            for key in structure_keys:
                if key not in present:
                    continue
                value = cells.get(key, "")
                if value and value != str(target.get(key, "")):
                    report.ignored_changes.append(
                        f"{prefix}: {key.replace('_', ' ')} "
                        f"({value!r}, read-only)")
            # only the whitelisted limits are applied
            for key in limit_keys:
                if key not in present:
                    continue         # legacy workbook: keep model value
                value = cells.get(key, "")
                if not value or value == str(target.get(key, "")):
                    continue
                target[key] = value
                limit_changed = True
                report.applied_changes.append(f"{sheet} {net}: {key}")
    wb.close()
    if report.errors:
        return report
    # YamlBuild sheet: review-only - validated above, never applied
    for key, params in parsed.items():
        current_params = model.get_params(key)
        for name, value in params.items():
            if str(current_params.get(name, "")) != str(value):
                report.ignored_changes.append(f"YamlBuild {key}.{name}")
    for key, state in enabled.items():
        if model.is_enabled(key) != state:
            report.ignored_changes.append(f"YamlBuild {key}.enabled")
    # pass 2: apply the whitelisted limit changes atomically
    if limit_changed:
        model.set_channel_allocation(alloc_final)
    report.imported = len(report.applied_changes)
    report.applied = True
    return report
