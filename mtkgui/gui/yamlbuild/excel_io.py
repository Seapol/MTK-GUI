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
from openpyxl.worksheet.worksheet import Worksheet

from mtkgui.gui.yamlbuild.channel_allocation import (
    UNSET,
    AllocatedRow,
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
    "power": ("Net name", "Test point", "Impedance", "Power rails",
              "Voltage"),
    "clock": ("Net name", "Test point", "SE Clock Hz",
              "Frequency band"),
    "gpio": ("Net name", "Test point", "DIO Channel"),
}
#: row keys written per table kind (no auto Status column anywhere)
_ALLOC_ROW_KEYS = {
    "power": ("net", "test_point", "impedance", "power_rails",
              "voltage"),
    "clock": ("net", "test_point", "se_clock_hz", "band"),
    "gpio": ("net", "test_point", "dio_channel"),
}
#: per-cell dropdown enum validation (import pass 1)
_ALLOC_POOLS = {
    "power": {"impedance": DAQM908A_SENSE_CHANNELS,
              "power_rails": U2355A_AI_CHANNELS,
              "voltage": DAQM908A_SENSE_CHANNELS},
    "clock": {"se_clock_hz": CLOCK_CHANNELS,
              "band": tuple(dict.fromkeys(CLOCK_BANDS.values()))},
    "gpio": {"dio_channel": GPIO_DIO_CHANNELS},
}


@dataclass
class ImportReport:
    """Outcome of an Excel import.

    Attributes:
        applied:  True when the workbook was valid and applied.
        errors:   Row-attached validation errors (module-wide).
        imported: Number of parameter rows applied.
    """

    applied: bool = False
    errors: list[str] = field(default_factory=list)
    imported: int = 0


def export_to_excel(model: YamlBuildModel, path: str) -> int:
    """Export the full model (all modules, all fields) to an .xlsx
    file.

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
    wb.save(path)
    return rows


def import_from_excel(model: YamlBuildModel, path: str) -> ImportReport:
    """Import and validate an .xlsx workbook, then apply it.

    The workbook is validated completely BEFORE anything is applied:
    any invalid row aborts the import with the error list (batch
    import never leaves the model half-updated).

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
    alloc_data: dict[str, list[dict]] = {}
    for kind, _cols in TABLE_SPECS:
        sheet = ALLOCATION_SHEET_NAMES[kind]
        if sheet not in wb.sheetnames:
            continue
        aw: Worksheet = wb[sheet]
        for line_no, row in enumerate(
                aw.iter_rows(min_row=2, values_only=True), start=2):
            values = ["" if v is None else str(v).strip() for v in row]
            values += [""] * (len(ALLOCATION_HEADERS[kind])
                              - len(values))
            cells = dict(zip(_ALLOC_ROW_KEYS[kind], values))
            # only the GPIO sheet carries the auto Status column
            status_idx = len(_ALLOC_ROW_KEYS[kind])
            cells["status"] = (values[status_idx]
                               if len(values) > status_idx else "")
            prefix = f"{sheet} row {line_no}"
            if not cells["net"]:
                report.errors.append(f"{prefix}: Net name required")
                continue
            if not cells["test_point"]:
                report.errors.append(f"{prefix}: Test point required")
                continue
            for key, allowed in _ALLOC_POOLS[kind].items():
                text = cells[key]
                if text and text != UNSET and text not in allowed:
                    report.errors.append(
                        f"{prefix}: {key.replace('_', ' ').title()} "
                        f"{text!r} not in {'/'.join(allowed)}")
            if report.errors:
                continue
            cells.pop("status")
            # canonical persisted row dict (full AllocatedRow keys,
            # exactly like the GUI table save path)
            alloc_data.setdefault(kind, []).append(
                AllocatedRow.from_dict(cells).to_dict())
    wb.close()
    if report.errors:
        return report
    # pass 2: apply atomically
    for key, params in parsed.items():
        model.set_params(key, {**model.get_params(key), **params})
        report.imported += len(params)
    for key, state in enabled.items():
        model.set_enabled(key, state)
    if alloc_data:
        model.set_channel_allocation(alloc_data)
    report.applied = True
    return report
