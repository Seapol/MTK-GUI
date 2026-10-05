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

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.schema import MODULE_FIELDS, module_title
from mtkgui.gui.yamlbuild.stages import STAGE_KEYS

SHEET_NAME = "YamlBuild"
_HEADERS = ("Module", "Module Key", "Parameter", "Value", "Type",
            "Required", "Min", "Max", "Choices", "Enabled", "Remarks")


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
    wb.close()
    if report.errors:
        return report
    # pass 2: apply atomically
    for key, params in parsed.items():
        model.set_params(key, {**model.get_params(key), **params})
        report.imported += len(params)
    for key, state in enabled.items():
        model.set_enabled(key, state)
    report.applied = True
    return report
