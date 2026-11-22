# -*- coding: utf-8 -*-
"""Route C importer: parse the MTK ICT Excel Sheet into nets.

Headless (no Qt, no ``mtkgui.gui`` imports) - same style as
:mod:`mtkgui.ict.netparse.route_b`.  Route C is the "MTK ICT Excel
Sheet" design-input route from node 01: one workbook authored by the
MTK ICT team, with four fixed sheets ``Info`` / ``R-GND`` / ``Voltage``
/ ``Clock`` at absolute row/column positions.

Contract highlights:

* ``R-GND`` and ``Voltage`` describe the same power-net set - the
  cross-sheet gate rejects a name-set / count / test-point mismatch;
* ``Clock`` is authored as ``Nominal (kHz)`` + ``Tolerance (±ppm)``;
  ``Clock!E`` / ``F`` ship as formulas and stay unlocked, so a user may
  overwrite them with constants for an asymmetric crystal.  Limits are
  derived **ppm -> min/max only** - ``ppm`` is never recomputed from the
  limits;
* the ``SN`` row and the DUT-result columns are never read.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

#: the four sheets the workbook must carry
SHEETS = ("Info", "R-GND", "Voltage", "Clock")

#: the model's route name (``_parsed_nets_dict`` carries it verbatim)
ROUTE_C = "mtk_sheet"

#: absolute layout: sheet -> (header row, first data row)
_LAYOUT = {
    "R-GND": (4, 6),
    "Voltage": (7, 9),
    "Clock": (4, 6),
}

#: expected header keys per sheet (the text before the first "(",
#: stripped + casefolded, so the Ω / ± characters never enter the
#: comparison)
_HEADERS = {
    "R-GND": {4: {"A": "net", "B": "test point", "C": "r-gnd min"}},
    "Voltage": {7: {"A": "net", "B": "test point", "C": "lower",
                    "D": "nominal", "E": "upper"}},
    "Clock": {4: {"A": "net", "B": "test point", "C": "nominal",
                  "D": "tolerance", "E": "lower", "F": "upper"}},
}
_INFO_HEADER_ROW = 24
_INFO_HEADER = {"A": "gnd net", "B": "test point"}
_INFO_FIRST_DATA_ROW = 25


@dataclass
class RouteCPowerNet:
    """One power net (R-GND Min + Voltage limits merged by name)."""

    name: str
    test_point: str
    r_gnd_min_ohm: float
    nominal_v: float
    lower_v: float
    upper_v: float


@dataclass
class RouteCClockNet:
    """One clock net.

    ``limits_source`` is ``"ppm"`` for the symmetric formula path and
    ``"manual"`` when the sheet's ``Clock!E`` / ``F`` hold constants.
    """

    name: str
    test_point: str
    nominal_khz: float
    ppm: float
    min_khz: float
    max_khz: float
    limits_source: str


@dataclass
class RouteCGndNet:
    """One GND block row from ``Info`` (``test_points`` may be empty)."""

    name: str
    test_points: str


@dataclass
class RouteCResult:
    """Parsed Route C workbook.

    The cross-sheet gate lands on the object (``gate_ok`` /
    ``gate_error``) instead of raising, so the caller can report it
    without catching.  Every other rejection raises ``ValueError``.
    """

    power: list[RouteCPowerNet] = field(default_factory=list)
    clock: list[RouteCClockNet] = field(default_factory=list)
    gnd: list[RouteCGndNet] = field(default_factory=list)
    gate_ok: bool = True
    gate_error: str = ""
    warnings: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        """One-line import summary shown on node 01."""
        return (f"Power {len(self.power)} · Clock {len(self.clock)} · "
                f"GND {len(self.gnd)} · warnings {len(self.warnings)}")

    def to_parsed_nets(self) -> dict:
        """The model's ``parsed_nets`` shape (``_parsed_nets_dict``)."""
        return {
            "route": ROUTE_C,
            "gate_ok": self.gate_ok,
            "gate_error": self.gate_error,
            "power_nets": [n.name for n in self.power],
            "clock_nets": [n.name for n in self.clock],
            "gnd_nets": [n.name for n in self.gnd],
            "other_nets": [],
        }

    def to_allocation_rows(self) -> dict:
        """Channel-allocation rows (all values are strings)."""
        power_rows = [{
            "net": n.name,
            "test_point": n.test_point,
            "r_gnd_min_ohm": f"{n.r_gnd_min_ohm:g}",
            "nominal_v": f"{n.nominal_v:.3f}",
            "lower_v": f"{n.lower_v:.3f}",
            "upper_v": f"{n.upper_v:.3f}",
        } for n in self.power]
        clock_rows = []
        for n in self.clock:
            row = {
                "net": n.name,
                "test_point": n.test_point,
                "nominal_khz": f"{n.nominal_khz:.3f}",
                "lower_khz": f"{n.min_khz:.3f}",
                "upper_khz": f"{n.max_khz:.3f}",
                "tolerance_ppm": f"{n.ppm:g}",
            }
            # symmetric rows omit the key so old lean YAML stays lean
            if n.limits_source == "manual":
                row["limits_source"] = "manual"
            clock_rows.append(row)
        return {"power": power_rows, "clock": clock_rows}


def parse_mtk_sheet(path: str) -> RouteCResult:
    """Parse one MTK ICT Excel Sheet workbook.

    Args:
        path: Path to the ``.xlsx`` workbook.

    Returns:
        :class:`RouteCResult`; the cross-sheet gate is reported on the
        object (``gate_ok`` / ``gate_error``).

    Raises:
        ValueError: a sheet is missing, a header is unexpected, a data
            row is invalid or a net is duplicated.
    """
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(path, data_only=False)
    except Exception as exc:  # noqa: BLE001 - surface a clean error
        raise ValueError(
            f"cannot open MTK ICT Excel workbook {path!r}: {exc}") from exc
    try:
        for sheet in SHEETS:
            if sheet not in workbook.sheetnames:
                raise ValueError(f"Sheet not found: {sheet}")
        result = RouteCResult()
        rgnd = _read_rgnd(workbook["R-GND"], result)
        voltage = _read_voltage(workbook["Voltage"], result)
        clock = _read_clock(workbook["Clock"], result)
        gnd = _read_info(workbook["Info"])

        _reject_duplicates(rgnd, "Duplicate power net in R-GND: {net}")
        _reject_duplicates(voltage, "Duplicate power net in Voltage: {net}")
        _reject_duplicates(clock, "Duplicate clock net: {net}")

        result.gate_ok, result.gate_error = check_power_gate(rgnd, voltage)

        voltage_by_name = {row[0]: row for row in voltage}
        for name, test_point, min_ohm in rgnd:
            v = voltage_by_name.get(name)
            result.power.append(RouteCPowerNet(
                name=name,
                test_point=test_point,
                r_gnd_min_ohm=min_ohm,
                nominal_v=v[3] if v else 0.0,
                lower_v=v[2] if v else 0.0,
                upper_v=v[4] if v else 0.0,
            ))
        for name, test_point, nominal, ppm, lo, hi, source in clock:
            result.clock.append(RouteCClockNet(
                name=name, test_point=test_point, nominal_khz=nominal,
                ppm=ppm, min_khz=lo, max_khz=hi, limits_source=source))
        result.gnd.extend(gnd)
        return result
    finally:
        workbook.close()


def check_power_gate(rgnd_rows, voltage_rows) -> tuple[bool, str]:
    """Cross-sheet power-net gate (name set, then count, then points).

    Args:
        rgnd_rows: ``(name, test_point, min_ohm)`` rows.
        voltage_rows: ``(name, test_point, lower, nominal, upper)`` rows.

    Returns:
        ``(ok, message)`` - the message is the exact rejection text.
    """
    rgnd_by = {row[0]: row for row in rgnd_rows}
    voltage_by = {row[0]: row for row in voltage_rows}
    only_rgnd = sorted(set(rgnd_by) - set(voltage_by))
    only_voltage = sorted(set(voltage_by) - set(rgnd_by))
    if only_rgnd or only_voltage:
        return False, (
            "R-GND and Voltage power nets do not match — "
            f"only in R-GND: {only_rgnd}; only in Voltage: {only_voltage}")
    if len(rgnd_rows) != len(voltage_rows):
        return False, (f"Power net count mismatch: R-GND {len(rgnd_rows)} "
                       f"vs Voltage {len(voltage_rows)}")
    for name in [row[0] for row in rgnd_rows]:
        tp_a = rgnd_by[name][1]
        tp_b = voltage_by[name][1]
        if tp_a != tp_b:
            return False, (f"Test point mismatch for {name}: "
                           f"R-GND {tp_a} vs Voltage {tp_b}")
    return True, ""


# --------------------------------------------------------------------------
# sheet readers
# --------------------------------------------------------------------------
def _read_rgnd(ws, result: RouteCResult) -> list[tuple]:
    """Read the R-GND power rows (name, test point, min ohm)."""
    _check_headers(ws, "R-GND")
    rows: list[tuple] = []
    for row, name in _data_rows(ws, "R-GND", result):
        test_point = _text(ws.cell(row=row, column=2).value)
        if not test_point:
            raise ValueError(f"Test point is empty in R-GND row {row}")
        raw = ws.cell(row=row, column=3).value
        min_ohm = _as_float(raw)
        if (min_ohm is None or min_ohm <= 0
                or abs(min_ohm - round(min_ohm)) > 1e-9):
            raise ValueError(
                "R-GND Min must be a positive integer ohm: "
                f"{name} = {_fmt(raw)}")
        rows.append((name, test_point, float(round(min_ohm))))
    return rows


def _read_voltage(ws, result: RouteCResult) -> list[tuple]:
    """Read the Voltage power rows (name, tp, lower, nominal, upper)."""
    _check_headers(ws, "Voltage")
    rows: list[tuple] = []
    for row, name in _data_rows(ws, "Voltage", result):
        test_point = _text(ws.cell(row=row, column=2).value)
        if not test_point:
            raise ValueError(f"Test point is empty in Voltage row {row}")
        raw_lower = ws.cell(row=row, column=3).value
        raw_nominal = ws.cell(row=row, column=4).value
        raw_upper = ws.cell(row=row, column=5).value
        lower = _as_float(raw_lower)
        nominal = _as_float(raw_nominal)
        upper = _as_float(raw_upper)
        if (lower is None or nominal is None or upper is None
                or not (lower < nominal < upper)):
            raise ValueError(
                f"Lower < Nominal < Upper required for {name}: "
                f"{_fmt(raw_lower)} / {_fmt(raw_nominal)} / "
                f"{_fmt(raw_upper)}")
        rows.append((name, test_point, lower, nominal, upper))
    return rows


def _read_clock(ws, result: RouteCResult) -> list[tuple]:
    """Read the Clock rows; ``E`` / ``F`` decide symmetric vs manual."""
    _check_headers(ws, "Clock")
    rows: list[tuple] = []
    for row, name in _data_rows(ws, "Clock", result):
        test_point = _text(ws.cell(row=row, column=2).value)
        if not test_point:
            raise ValueError(f"Test point is empty in Clock row {row}")
        nominal = _as_float(ws.cell(row=row, column=3).value)
        if nominal is None or nominal <= 0:
            raise ValueError(f"Clock nominal must be > 0: {name}")
        raw_tolerance = ws.cell(row=row, column=4).value
        raw_lower = ws.cell(row=row, column=5).value
        raw_upper = ws.cell(row=row, column=6).value
        if _is_plain_number(raw_lower) and _is_plain_number(raw_upper):
            # the legal manual path: hand-authored asymmetric limits
            lo = float(raw_lower)
            hi = float(raw_upper)
            if not (0 < lo < nominal < hi):
                raise ValueError(
                    "Clock manual limits violate 0 < min < nominal < max: "
                    f"{name} = {_fmt(lo)} / {_fmt(nominal)} / {_fmt(hi)}")
            implied_ppm = (hi - lo) / (2 * nominal) * 1e6
            if implied_ppm > 1000:
                raise ValueError(
                    "Clock manual limits exceed 1000 ppm implied "
                    f"tolerance: {name}")
            ppm = _as_float(raw_tolerance) or 0.0
            rows.append((name, test_point, nominal, ppm, lo, hi, "manual"))
            continue
        # symmetric: recompute from C / D, never trust the cached value
        ppm = _as_float(raw_tolerance)
        if ppm is None or not (0.1 < ppm <= 1000):
            raise ValueError(
                "Clock tolerance out of range (0.1, 1000] ppm: "
                f"{name} = {_fmt(raw_tolerance)}")
        lo = _round3(nominal * (1 - ppm / 1e6))
        hi = _round3(nominal * (1 + ppm / 1e6))
        rows.append((name, test_point, nominal, ppm, lo, hi, "ppm"))
    return rows


def _read_info(ws) -> list[RouteCGndNet]:
    """Read the ``Info`` GND block (ends at the first fully blank row)."""
    _check_info_header(ws)
    nets: list[RouteCGndNet] = []
    for row in range(_INFO_FIRST_DATA_ROW, ws.max_row + 1):
        name = _text(ws.cell(row=row, column=1).value)
        points = _text(ws.cell(row=row, column=2).value)
        if not name and not points:
            break
        if not name:
            raise ValueError(f"Net name is empty in Info row {row}")
        if not points:
            raise ValueError(f"Test point is empty in Info row {row}")
        nets.append(RouteCGndNet(name=name, test_points=points))
    return nets


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _data_rows(ws, sheet: str, result: RouteCResult):
    """Yield ``(row, net name)`` pairs; stop at the first blank A cell.

    Every non-empty row below the first blank A cell is reported as a
    non-fatal warning (the sheet still imports).
    """
    _header_row, first_data = _LAYOUT[sheet]
    blank_seen = False
    for row in range(first_data, ws.max_row + 1):
        name = _text(ws.cell(row=row, column=1).value)
        if blank_seen:
            if _row_has_content(ws, row):
                result.warnings.append(
                    f"Row {row} ignored after the first blank row on "
                    f"{sheet}")
            continue
        if not name:
            blank_seen = True
            continue
        yield row, name


def _check_headers(ws, sheet: str) -> None:
    header_row, _first = _LAYOUT[sheet]
    for cell, key in _HEADERS[sheet][header_row].items():
        raw = ws[f"{cell}{header_row}"].value
        if _header_key(raw) != key:
            raise ValueError(
                f"Unexpected header at {sheet}!{cell}{header_row}: "
                f"{_text(raw)}")


def _check_info_header(ws) -> None:
    for cell, key in _INFO_HEADER.items():
        raw = ws[f"{cell}{_INFO_HEADER_ROW}"].value
        if _header_key(raw) != key:
            raise ValueError(
                f"Unexpected header at Info!{cell}{_INFO_HEADER_ROW}: "
                f"{_text(raw)}")


def _header_key(value) -> str:
    """Header comparison key: text before the first "(", casefolded."""
    text = _text(value)
    return text.split("(", 1)[0].strip().casefold()


def _reject_duplicates(rows, template: str) -> None:
    seen = set()
    for row in rows:
        name = row[0]
        if name in seen:
            raise ValueError(template.format(net=name))
        seen.add(name)


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_plain_number(value) -> bool:
    """True for a numeric constant cell (never for a ``=…`` formula)."""
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        text = value.strip()
        if not text or text.startswith("="):
            return False
        try:
            float(text)
            return True
        except ValueError:
            return False
    return False


def _fmt(value) -> str:
    """Compact text for an error message (numbers with ``:g``)."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{float(value):g}"
    return _text(value)


def _round3(value: float) -> float:
    """Excel ``ROUND(value, 3)`` (half-up), not banker's rounding."""
    return float(Decimal(str(value)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP))


def _row_has_content(ws, row: int) -> bool:
    """Any non-blank cell in columns A..P of one row."""
    for column in range(1, 17):
        if _text(ws.cell(row=row, column=column).value):
            return True
    return False
