# -*- coding: utf-8 -*-
"""M103: fresh four-sheet MTK ICT Excel Sheet writer (Route C export).

Qt-free (openpyxl + stdlib only), mirroring :mod:`mtkgui.gui.yamlbuild.
excel_io`.  The writer is the single export implementation for rule
R14a: node 07's ``Export MTK ICT Excel Sheet…`` button and
``File ▸ Excel ▸ Export MTK ICT Sheet (Route C)…`` both land here.

The workbook is a **fresh template** (R13): limits filled, DUT result
columns and the SN row never carry a measurement.  Fixed layout:
``R-GND`` header 4 / SN 5 / data 6…, ``Voltage`` header 7 / SN 8 /
data 9…, ``Clock`` header 4 / SN 5 / data 6…; ``Clock!A2:P2`` merged.

``Clock!E`` / ``F`` carry the formula pair for the symmetric (``ppm``)
path and plain constants when ``limits_source == "manual"`` (§9 of the
contract).  Both cells are unlocked in either case.
"""

from __future__ import annotations

import warnings

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill, Protection
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.properties import PageSetupProperties

#: the four fixed sheets, in write order
SHEETS = ("Info", "R-GND", "Voltage", "Clock")

#: 10 DUT result columns per data sheet
RESULT_COUNT = 10

#: stored limit placeholders that mean "no value"
_UNSET = ("", "\u2014")

#: GND rows with no probe point are exported with this cell text
NO_TEST_POINT = "\u2014 (no test point)"

#: illegal filename characters + whitespace (rule R16)
_ILLEGAL = '\\/:*?"<>| \t'

#: two fixed colour families from the sample workbook
CONFIG_HEADER_RGB = "2F6FB3"
RESULT_HEADER_RGB = "7F9AB8"
NET_FILL_RGB = "EEF1F4"
SN_FILL_RGB = "FFF2CC"
TITLE_RGB = "22303F"
MUTED_RGB = "5B6B7A"
WARN_RGB = "B3261E"

TITLE_FONT = Font(bold=True, size=12, color=TITLE_RGB)
LABEL_FONT = Font(bold=True)
VALUE_FONT = Font(size=10, color=MUTED_RGB)
WARN_FONT = Font(bold=True, size=10, color=WARN_RGB)


def _solid(rgb: str) -> PatternFill:
    return PatternFill(fill_type="solid", start_color=rgb, end_color=rgb)


def _clean(value) -> str:
    """A stored cell as stripped text (``""`` for None)."""
    if value is None:
        return ""
    return str(value).strip()


def _num(value) -> float | None:
    """A stored limit as float; the UNSET placeholder is ``None``."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text in _UNSET:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _name_part(value) -> str:
    """One filename segment (rule R16): blanks → ``unknown``."""
    text = _clean(value)
    if not text:
        return "unknown"
    return "".join("-" if ch in _ILLEGAL else ch for ch in text)


def _rev_token(value) -> str:
    """``A`` / ``Rev A`` / ``REV-A`` → ``revA``; blank → ``unknown``."""
    text = _clean(value)
    if not text:
        return "unknown"
    alnum = "".join(ch for ch in text if ch.isalnum())
    if not alnum:
        return "unknown"
    if len(alnum) > 3 and alnum[:3].lower() == "rev":
        alnum = alnum[3:]
    return "rev" + alnum


def default_mtk_sheet_name(model) -> str:
    """Rule R16 default filename for the save dialog."""
    design = model.get_params("design_input") or {}
    core = _name_part(design.get("product_id"))
    part = _name_part(design.get("part_number"))
    return f"MTK_ICT_{core}_{part}_{_rev_token(design.get('hw_version'))}.xlsx"


def _source_note(design: dict) -> str:
    """Info!B5 - the derived route C marker (contract §2)."""
    return (f"{_name_part(design.get('part_number'))}_"
            f"{_name_part(design.get('product_id'))}_"
            f"MTK_ICT_SHEET_{_rev_token(design.get('hw_version'))} "
            f"(route C)")


def _power_on_steps(model) -> list[str]:
    """The Equipment Config power-on steps, when the model carries them.

    M103 finding: :class:`~mtkgui.gui.yamlbuild.equipment_config.
    EquipmentConfig` holds ``prompt_on`` / ``prompt_off`` but **no**
    ``steps`` list, so this returns ``[]`` today and the writer takes
    the contract R15 empty branch (``Voltage!A3:A5`` omitted, Info row
    ``none defined``).  Kept accessor-driven so node 04 can grow the
    field without touching the writer.
    """
    getter = getattr(model, "get_equipment_config", None)
    if getter is None:
        return []
    steps = getattr(getter(), "steps", None) or ()
    return [str(step).strip() for step in steps if str(step).strip()]


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------
def export_mtk_sheet(model, path: str) -> int:
    """Write the fresh four-sheet workbook.

    Args:
        model: The Yaml Build model (duck-typed; no Qt involved).
        path:  Target ``.xlsx`` path.

    Returns:
        The number of data rows written across the three data sheets.

    Raises:
        ValueError: no power rows or no clock rows (R14), or a sheet
            has no writable row.
        OSError: the file could not be written.
    """
    alloc = model.get_channel_allocation() or {}
    power = [row for row in (alloc.get("power") or [])
             if isinstance(row, dict)]
    clock = [row for row in (alloc.get("clock") or [])
             if isinstance(row, dict)]
    if not power:
        raise ValueError(
            "Cannot export the MTK ICT Excel Sheet: no power nets")
    if not clock:
        raise ValueError(
            "Cannot export the MTK ICT Excel Sheet: no clock nets")

    design = model.get_params("design_input") or {}
    parsed = model.get_parsed_nets() or {}
    gnd_names = [_clean(name) for name in (parsed.get("gnd_nets") or [])
                 if _clean(name)]
    steps = _power_on_steps(model)

    wb = Workbook()
    info = wb.active
    info.title = "Info"
    _write_info(info, design, gnd_names, steps)

    rgnd = wb.create_sheet("R-GND")
    written = _write_rgnd(rgnd, power)
    voltage = wb.create_sheet("Voltage")
    written += _write_voltage(voltage, power, steps)
    clock_ws = wb.create_sheet("Clock")
    written += _write_clock(clock_ws, clock)

    wb.save(path)
    return written


# ---------------------------------------------------------------------------
# Info
# ---------------------------------------------------------------------------
def _put(ws, row: int, column: int, value, *, font=None, fill=None,
         number_format=None, locked=True) -> None:
    """Write one styled cell."""
    cell = ws.cell(row=row, column=column, value=value)
    if font is not None:
        cell.font = font
    if fill is not None:
        cell.fill = fill
    if number_format is not None:
        cell.number_format = number_format
    cell.protection = Protection(locked=locked)


_DOCUMENTATION = (
    (7, "purpose",
     "Exported from the ICT section of the project YAML. For off-MTK "
     "review / light edit, and usable directly as an ICT manual test "
     "report."),
    (8, "result columns",
     "10 DUT result columns per test sheet (lighter blue header = manual "
     "recording only), always blank in a freshly exported template. Enter "
     "the serial number in the SN row, then the measured value below."),
    (9, "scope",
     "ICT numeric tests only: R-GND (unpowered) / Voltage / Clock"),
    (10, "excluded",
     "Power rails up sequence (timing test), Control IO (GPIO/DIO), "
     "GND/Others, all FCT"),
    (12, "R-GND",
     "single-ended resistance to GND. DUT must be POWERED OFF (static "
     "test). Min-threshold only; \u00b11.5 \u03a9 tolerance; precision "
     "1 \u03a9 (integer)"),
    (13, "Voltage",
     "powered rail voltage. DUT must be POWERED ON (power-on steps at the "
     "top of the sheet). Lower/Nominal/Upper and results in V, always 3 "
     "decimals (e.g. 3.300 / 5.000)"),
    (14, "Clock",
     "crystal / clock frequency. Enter Nominal (kHz) + Tolerance "
     "(\u00b1ppm) only \u2014 Lower / Upper are derived automatically "
     "and locked (ROUND to 3 dp). Keep DUT POWERED ON during "
     "measurement; POWER OFF after the clock test. Displayed with 3 "
     "decimals (e.g. 24.000 / 32.768), precision 1 Hz"),
    (16, "YAML round-trip",
     "Export (YAML -> Excel) always builds a FRESH template from the "
     "current YAML: Net / Test Point(s) / limits filled in, plus 10 blank "
     "DUT result columns and a blank SN row for manual entry. Import "
     "(Excel -> YAML) reads Net / Test Point(s) / limits only and IGNORES "
     "every DUT result cell and the SN row \u2014 measured data never "
     "enters the YAML."),
    (17, "input validation",
     "result cells accept plain numbers only (no units, no text). Values "
     "display with fixed decimals (1 \u03a9 integer / 3 decimals for V "
     "and kHz). In-range = green, out-of-range = red."),
    (18, "locked columns",
     "Net (from netlist, read-only) \u00b7 Clock Lower / Upper "
     "(auto-derived, read-only)"),
    (19, "editable columns",
     "Test Point(s), limit columns (including Clock E/F), SN row, DUT "
     "result columns"),
    (21, "rules",
     "non-empty Net & limits \u00b7 numbers only \u00b7 "
     "Lower \u2264 Nominal \u2264 Upper \u00b7 Net unique per sheet"),
    (23, "GND nets",
     "Reference grounds exported from the ICT GND category \u2014 never "
     "tested. Net and probe point(s) listed below; Import reads them "
     "back into the YAML."),
)

_TRAILING_DOCUMENTATION = (
    (0, "design input route",
     "Route C \u2014 MTK ICT Excel Sheet. Mutually exclusive with Route A "
     "(SPF + NET + BoM) and Route B (traditional ICT Excel): exactly one "
     "route per project."),
    (1, "import gate",
     "The R-GND sheet and the Voltage sheet MUST carry the same power "
     "nets: identical names and identical count (order does not matter). "
     "Any mismatch is a validation error \u2014 the workbook is REJECTED "
     "and nothing is loaded."),
    (2, "parse replacement",
     "A valid import already carries the complete ICT net set (power from "
     "R-GND + Voltage, clocks from Clock, grounds from this page), so "
     "node 02 Parse Nets is SKIPPED for ICT."),
)

_POWER_ON_NOTE = (
    "Mirrored from Equipment Config -> Power On/Off DUT "
    "(equipment_config.power_on_off.steps) and shown at the top of the "
    "Voltage sheet. Read-only here: edit them in the GUI. Route C import "
    "ignores this block. May be empty: the step lines are then omitted "
    "and a warning is shown (recommended to fill even on a fully "
    "automatic ATE line)."
)


def _write_info(ws, design: dict, gnd_names: list[str],
                steps: list[str]) -> None:
    """Identity + documentation + GND block (contract §1/§2)."""
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 78
    _put(ws, 1, 1, "MTK ICT Excel Sheet", font=TITLE_FONT)
    _put(ws, 3, 1, "project_name", font=LABEL_FONT)
    _put(ws, 3, 2, _clean(design.get("part_number")) or "unknown",
         font=VALUE_FONT)
    _put(ws, 4, 1, "product", font=LABEL_FONT)
    _put(ws, 4, 2, _clean(design.get("product_id")) or "unknown",
         font=VALUE_FONT)
    _put(ws, 5, 1, "source", font=LABEL_FONT)
    _put(ws, 5, 2, _source_note(design), font=VALUE_FONT)

    for row, label, text in _DOCUMENTATION:
        _put(ws, row, 1, label, font=LABEL_FONT)
        _put(ws, row, 2, text, font=VALUE_FONT)

    # GND block: header row 24, data from 25 until one blank separator
    header_fill = _solid(NET_FILL_RGB)
    _put(ws, 24, 1, "GND net",
         font=Font(bold=True, size=10, color=TITLE_RGB), fill=header_fill)
    _put(ws, 24, 2, "Test Point(s)",
         font=Font(bold=True, size=10, color=TITLE_RGB), fill=header_fill)
    row = 25
    for name in gnd_names:
        _put(ws, row, 1, name, font=LABEL_FONT)
        _put(ws, row, 2, NO_TEST_POINT, font=VALUE_FONT)
        row += 1

    # trailing documentation block, one blank row after the GND list
    start = max(28, row + 1)
    for offset, label, text in _TRAILING_DOCUMENTATION:
        _put(ws, start + offset, 1, label, font=LABEL_FONT)
        _put(ws, start + offset, 2, text, font=VALUE_FONT)
    _put(ws, start + 4, 1, "power-on steps", font=LABEL_FONT)
    _put(ws, start + 4, 2,
         _POWER_ON_NOTE if steps else "none defined", font=VALUE_FONT)

    ws.row_dimensions[14].height = 44
    ws.row_dimensions[23].height = 30
    ws.row_dimensions[start].height = 30
    ws.row_dimensions[start + 1].height = 42
    ws.row_dimensions[start + 2].height = 30
    ws.row_dimensions[start + 4].height = 46
    _page_setup(ws)
    ws.protection.sheet = True


# ---------------------------------------------------------------------------
# data sheets
# ---------------------------------------------------------------------------
def _page_setup(ws) -> None:
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0


def _header(ws, row: int, column: int, text: str, result: bool = False) -> None:
    _put(ws, row, column, text,
         font=Font(bold=True, size=10, color="FFFFFF"),
         fill=_solid(RESULT_HEADER_RGB if result else CONFIG_HEADER_RGB))


def _sn_row(ws, row: int, first_column: int) -> None:
    for index in range(RESULT_COUNT):
        _put(ws, row, first_column + index, "SN Here",
             font=Font(size=11), fill=_solid(SN_FILL_RGB), locked=False)


def _net_cell(ws, row: int, value: str) -> None:
    _put(ws, row, 1, value, font=Font(size=11), fill=_solid(NET_FILL_RGB))


def _row_cell(ws, row: int, column: int, value, number_format: str,
              *, font=None) -> None:
    _put(ws, row, column, value, font=font or Font(size=11),
         number_format=number_format, locked=False)


def _decimal_dv(ws, cell_range: str, low: str, high: str) -> None:
    dv = DataValidation(type="decimal", operator="between",
                        formula1=low, formula2=high, allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(cell_range)


def _result_format(ws, cell_range: str, ok_formula: str,
                   bad_formula: str) -> None:
    ws.conditional_formatting.add(
        cell_range, FormulaRule(formula=[ok_formula],
                                font=Font(color="006100")))
    ws.conditional_formatting.add(
        cell_range, FormulaRule(formula=[bad_formula],
                                font=Font(color="9C0006")))


def _write_rgnd(ws, power: list[dict]) -> int:
    """R-GND: header 4, SN 5, data 6… - net / TP / R-GND min."""
    widths = {"A": 22, "B": 16, "C": 14}
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = width
    for index in range(4, 4 + RESULT_COUNT):
        ws.column_dimensions[chr(64 + index)].width = 13
    _put(ws, 1, 1, "R-GND", font=TITLE_FONT)
    _put(ws, 2, 1,
         "DUT must be POWERED OFF \u2014 static test. Do not measure "
         "resistance with the board powered.", font=WARN_FONT)
    _header(ws, 4, 1, "Net")
    _header(ws, 4, 2, "Test Point(s)")
    _header(ws, 4, 3, "R-GND Min (\u03a9)")
    for index in range(RESULT_COUNT):
        _header(ws, 4, 4 + index, f"DUT{index + 1} Result (\u03a9)",
                result=True)
    _sn_row(ws, 5, 4)

    row = 6
    for data in power:
        net = _clean(data.get("net"))
        min_ohm = _num(data.get("r_gnd_min_ohm"))
        if min_ohm is None:
            warnings.warn(
                f"MTK ICT export: R-GND row skipped, R-GND Min is not a "
                f"number for {net or '?'}", RuntimeWarning, stacklevel=2)
            continue
        _net_cell(ws, row, net)
        _row_cell(ws, row, 2, _clean(data.get("test_point")), "0")
        _row_cell(ws, row, 3, min_ohm, "0")
        row += 1

    last = max(21, row - 1)
    _decimal_dv(ws, f"D6:M{last}", "0", "1000000000")
    _result_format(ws, f"D6:M{last}",
                   "AND(ISNUMBER(D6),D6>=$C6)",
                   "AND(ISNUMBER(D6),D6<$C6)")
    ws.freeze_panes = "A6"
    _page_setup(ws)
    ws.protection.sheet = True
    return row - 6


def _write_voltage(ws, power: list[dict], steps: list[str]) -> int:
    """Voltage: header 7, SN 8, data 9… - net / TP / lower / nom / upper."""
    for letter, width in (("A", 22), ("B", 16), ("C", 14), ("D", 14),
                          ("E", 14)):
        ws.column_dimensions[letter].width = width
    for index in range(6, 6 + RESULT_COUNT):
        ws.column_dimensions[chr(64 + index)].width = 13
    _put(ws, 1, 1, "Voltage", font=TITLE_FONT)
    _put(ws, 2, 1,
         "DUT must be POWERED ON before measurement. Power-on steps:",
         font=WARN_FONT)
    if steps:
        for index, step in enumerate(steps[:3]):
            _put(ws, 3 + index, 1, f"{index + 1}. {step}",
                 font=Font(size=10, color=TITLE_RGB))
    _header(ws, 7, 1, "Net")
    _header(ws, 7, 2, "Test Point(s)")
    _header(ws, 7, 3, "Lower (V)")
    _header(ws, 7, 4, "Nominal (V)")
    _header(ws, 7, 5, "Upper (V)")
    for index in range(RESULT_COUNT):
        _header(ws, 7, 6 + index, f"DUT{index + 1} Result (V)", result=True)
    _sn_row(ws, 8, 6)

    row = 9
    for data in power:
        net = _clean(data.get("net"))
        lower = _num(data.get("lower_v"))
        nominal = _num(data.get("nominal_v"))
        upper = _num(data.get("upper_v"))
        if lower is None or nominal is None or upper is None:
            warnings.warn(
                f"MTK ICT export: Voltage row skipped, Lower / Nominal / "
                f"Upper must be numbers for {net or '?'}",
                RuntimeWarning, stacklevel=2)
            continue
        _net_cell(ws, row, net)
        _row_cell(ws, row, 2, _clean(data.get("test_point")), "0.000")
        _row_cell(ws, row, 3, lower, "0.000")
        _row_cell(ws, row, 4, nominal, "0.000")
        _row_cell(ws, row, 5, upper, "0.000")
        row += 1

    last = max(24, row - 1)
    _decimal_dv(ws, f"F9:O{last}", "0", "1000000000")
    _result_format(ws, f"F9:O{last}",
                   "AND(ISNUMBER(F9),F9>=$C9,F9<=$E9)",
                   "AND(ISNUMBER(F9),OR(F9<$C9,F9>$E9))")
    ws.freeze_panes = "A9"
    _page_setup(ws)
    ws.protection.sheet = True
    return row - 9


def _write_clock(ws, clock: list[dict]) -> int:
    """Clock: header 4, SN 5, data 6… - nominal / ppm / lower / upper."""
    for letter, width in (("A", 22), ("B", 16), ("C", 14), ("D", 15),
                          ("E", 15), ("F", 15)):
        ws.column_dimensions[letter].width = width
    for index in range(7, 7 + RESULT_COUNT):
        ws.column_dimensions[chr(64 + index)].width = 13
    _put(ws, 1, 1, "Clock", font=TITLE_FONT)
    _put(ws, 2, 1,
         "Fill C and D; E and F follow automatically. Overwrite E and F "
         "with constants for an asymmetric window - ppm is not "
         "recomputed from them.", font=WARN_FONT)
    ws.merge_cells("A2:P2")
    ws.row_dimensions[2].height = 20
    _header(ws, 4, 1, "Net")
    _header(ws, 4, 2, "Test Point(s)")
    _header(ws, 4, 3, "Nominal (kHz)")
    _header(ws, 4, 4, "Tolerance (\u00b1ppm)")
    _header(ws, 4, 5, "Lower (kHz, auto)")
    _header(ws, 4, 6, "Upper (kHz, auto)")
    for index in range(RESULT_COUNT):
        _header(ws, 4, 7 + index, f"DUT{index + 1} Result (kHz)",
                result=True)
    ws.row_dimensions[4].height = 30
    _sn_row(ws, 5, 7)

    row = 6
    for data in clock:
        net = _clean(data.get("net"))
        nominal = _num(data.get("nominal_khz"))
        ppm = _num(data.get("tolerance_ppm"))
        manual = _clean(data.get("limits_source")) == "manual"
        lower = _num(data.get("lower_khz"))
        upper = _num(data.get("upper_khz"))
        if nominal is None or ppm is None or (
                manual and (lower is None or upper is None)):
            warnings.warn(
                f"MTK ICT export: Clock row skipped, Nominal / Tolerance "
                f"must be numbers for {net or '?'}",
                RuntimeWarning, stacklevel=2)
            continue
        _net_cell(ws, row, net)
        _row_cell(ws, row, 2, _clean(data.get("test_point")), "0.000")
        _row_cell(ws, row, 3, nominal, "0.000")
        _row_cell(ws, row, 4, ppm, "0.0")
        limit_font = Font(bold=True, size=10, color=MUTED_RGB)
        if manual:
            _row_cell(ws, row, 5, lower, "0.000", font=limit_font)
            _row_cell(ws, row, 6, upper, "0.000", font=limit_font)
        else:
            _row_cell(ws, row, 5,
                      f"=ROUND(C{row}*(1-D{row}/1e6),3)", "0.000",
                      font=limit_font)
            _row_cell(ws, row, 6,
                      f"=ROUND(C{row}*(1+D{row}/1e6),3)", "0.000",
                      font=limit_font)
        row += 1

    last = max(8, row - 1)
    _decimal_dv(ws, f"G6:P{last}", "0", "1000000000")
    _decimal_dv(ws, "C6:C8", "0", "1000000000")
    _decimal_dv(ws, "D6:D8", "0.1", "1000")
    _result_format(ws, f"G6:P{last}",
                   "AND(ISNUMBER(G6),G6>=$E6,G6<=$F6)",
                   "AND(ISNUMBER(G6),OR(G6<$E6,G6>$F6))")
    _page_setup(ws)
    ws.protection.sheet = True
    return row - 6
