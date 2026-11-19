# -*- coding: utf-8 -*-
"""Route B importer: parse an ICT Excel ``RESULTS`` sheet into nets.

Headless (no Qt, no ``mtkgui.gui`` imports).  Route B is the
"ICT Excel Spreadsheet" design-input route from node 01.  The workbook
carries the board's ICT measurements instead of an SPF+NET netlist, so
the classification comes from the BLOCK HEADING above each row, not
from the net name.

Contract (v2-4, C5):

* sheet ``RESULTS`` only; column C = net name, column D = reference
  designator / test point; every other column and sheet is ignored.
* classification is read from the block heading (impedance / voltage /
  frequency), never from the net name;
* a clock row is accepted only when column D matches ``TP\\d+\\.\\d+``;
  a crystal designator (``Y1`` / ``Y2`` / ``XTAL…``) is unprobeable and
  is skipped with the named reason
  ``Y-designator is not probeable from MTK``;
* ``GND`` is a single row from the impedance block whose points collapse
  into ``(N points)``; its net name is simply ``GND``;
* ``Other`` is always empty on this route;
* the consistency gate: the impedance-block power-net set must equal the
  voltage-block power-net set (power nets only, GND excluded).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import (CATEGORY_GND, CATEGORY_OTHER, CATEGORY_POWER,
                    CATEGORY_SE_CLOCK)

RESULTS_SHEET = "RESULTS"
REASON_Y_DESIGNATOR = "Y-designator is not probeable from MTK"

#: probeable clock test point: ``TP35.1``
_PROBEABLE_TP_RE = re.compile(r"^TP\d+\.\d+$")
#: crystal designator: ``Y1`` / ``Y2`` / ``XTAL…`` (unprobeable)
_CRYSTAL_DESIGNATOR_RE = re.compile(r"^(Y\d+|XTAL)", re.IGNORECASE)
#: GND net name (same matcher as the netlist classifier)
_GND_RE = re.compile(
    r"^(GND|AGND|DGND|PGND|VSS|GROUND)([_\W].*)?$", re.IGNORECASE)
#: a reference-designator cell (``TP35.1`` / ``Y1`` / ``D1,D2``) - a
#: net DATA row, as opposed to a procedure/instruction row whose column
#: D carries free text (``POWER ON DUT STEPS`` -> ``1.Add DC 5V...``)
_REFDES_RE = re.compile(r"^[A-Za-z]+\d[\d.,]*$")

#: block headings recognised by the importer
_IMPEDANCE_RE = re.compile(r"IMPEDANCE", re.IGNORECASE)
_VOLTAGE_RE = re.compile(r"VOLTAGE", re.IGNORECASE)
_FREQUENCY_RE = re.compile(r"FREQUEN", re.IGNORECASE)


@dataclass
class RouteBNet:
    """One parsed net on Route B.

    Attributes:
        name:       Net name (column C).
        category:   One of Power / SE Clock / GND / Other.
        block:      Source block heading (impedance / voltage /
                    frequency).
        test_point: Reference designator / test point (column D).
        min_v / nominal / max_v: Measurement limits from the sheet
                    (empty when the block has no such column).
        points:     Collapsed point count (GND nets only; 1 otherwise).
    """

    name: str
    category: str
    block: str
    test_point: str = ""
    min_v: str = ""
    nominal: str = ""
    max_v: str = ""
    points: int = 1


@dataclass
class RouteBResult:
    """Parsed Route B workbook.

    Attributes:
        nets:       Power / SE Clock / GND nets, in sheet order.
        skipped:    ``(net name, reason)`` for every rejected row.
        gate_ok:    True when the impedance/voltage power-net sets
                    match (or a block is absent).
        gate_error: Human-readable mismatch description ("" when OK).
    """

    nets: list[RouteBNet] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    gate_ok: bool = True
    gate_error: str = ""

    # -- counts ----------------------------------------------------
    def count(self, category: str) -> int:
        return sum(1 for n in self.nets if n.category == category)

    @property
    def gnd_points(self) -> int:
        for net in self.nets:
            if net.category == CATEGORY_GND:
                return net.points
        return 0

    def summary(self) -> str:
        return (f"Power {self.count(CATEGORY_POWER)} · "
                f"SE Clock {self.count(CATEGORY_SE_CLOCK)} · "
                f"GND {self.count(CATEGORY_GND)} · "
                f"Other {self.count(CATEGORY_OTHER)} · "
                f"skipped {len(self.skipped)} rows")


def parse_results_sheet(path: str) -> RouteBResult:
    """Parse one ICT Excel workbook's ``RESULTS`` sheet.

    Args:
        path: Path to the ``.xlsx`` workbook.

    Returns:
        :class:`RouteBResult`.

    Raises:
        ValueError: the workbook has no ``RESULTS`` sheet or cannot be
            opened.
    """
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(path, read_only=True,
                                          data_only=True)
    except Exception as exc:  # noqa: BLE001 - surface a clean error
        raise ValueError(f"cannot open ICT Excel workbook {path!r}: "
                         f"{exc}") from exc
    try:
        if RESULTS_SHEET not in workbook.sheetnames:
            raise ValueError(
                f"ICT Excel workbook {path!r} has no {RESULTS_SHEET!r} "
                f"sheet (found {workbook.sheetnames})")
        sheet = workbook[RESULTS_SHEET]
        return _parse_sheet(sheet)
    finally:
        workbook.close()


def _parse_sheet(sheet) -> RouteBResult:
    rows = list(sheet.iter_rows(values_only=True))
    result = RouteBResult()
    impedance_power: list[str] = []
    voltage_power: list[str] = []
    gnd_points: int = 0

    block = ""              # current block heading
    for row in rows:
        col_b = _text(row, 1)      # TESTS (block heading)
        col_c = _text(row, 2)      # net name
        col_d = _text(row, 3)      # reference designator / test point

        if col_b:
            # a block heading row switches the active block
            block = _block_kind(col_b)
            continue
        if not col_c:
            continue                # empty / separator row
        is_gnd = bool(_GND_RE.match(col_c))
        if not is_gnd and not _REFDES_RE.match(col_d):
            continue                # procedure/instruction row

        if block == "impedance":
            if is_gnd:
                gnd_points += _count_points(col_d)
                continue
            impedance_power.append(col_c)
            result.nets.append(RouteBNet(
                name=col_c, category=CATEGORY_POWER, block=block,
                test_point=col_d,
                min_v=_text(row, 4)))   # Expected Value (ohm)
        elif block == "voltage":
            voltage_power.append(col_c)
            # the voltage block duplicates the impedance power nets;
            # it is recorded only for the consistency gate
        elif block == "frequency":
            if _PROBEABLE_TP_RE.match(col_d):
                result.nets.append(RouteBNet(
                    name=col_c, category=CATEGORY_SE_CLOCK, block=block,
                    test_point=col_d,
                    min_v=_text(row, 4), nominal=_text(row, 5),
                    max_v=_text(row, 6)))
            elif _CRYSTAL_DESIGNATOR_RE.match(col_d):
                result.skipped.append((col_c, REASON_Y_DESIGNATOR))
            else:
                result.skipped.append(
                    (col_c, "not probeable from MTK"))

    # GND collapses into one net (the points come from a single row)
    if gnd_points:
        result.nets.append(RouteBNet(
            name=CATEGORY_GND, category=CATEGORY_GND,
            block="impedance", test_point=f"({gnd_points} points)",
            points=gnd_points))

    # consistency gate: impedance power set == voltage power set
    result.gate_ok, result.gate_error = _gate(
        impedance_power, voltage_power)
    return result


def _gate(impedance: list[str], voltage: list[str]) -> tuple[bool, str]:
    """Impedance power nets must equal voltage power nets (GND excluded).

    Returns ``(ok, error)``.  A block with no nets is not compared
    (nothing was enumerated, so nothing can contradict).
    """
    imp = set(impedance)
    vol = set(voltage)
    if not imp or not vol:
        return True, ""
    missing = sorted(imp - vol)
    extra = sorted(vol - imp)
    if not missing and not extra:
        return True, ""
    parts = []
    if missing:
        parts.append(f"impedance-only {missing}")
    if extra:
        parts.append(f"voltage-only {extra}")
    return False, (
        "the impedance power nets do not match the voltage power nets "
        "(same test point serves both): " + "; ".join(parts))


def _text(row: tuple, index: int) -> str:
    """Cell text at *index* (0-based), whitespace-stripped."""
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def _block_kind(heading: str) -> str:
    if _IMPEDANCE_RE.search(heading):
        return "impedance"
    if _VOLTAGE_RE.search(heading):
        return "voltage"
    if _FREQUENCY_RE.search(heading):
        return "frequency"
    return ""


def _count_points(designator: str) -> int:
    """Count the test points in one designator cell.

    ``TP6.1 TP46.1`` -> 2; a single ``TP6.1`` -> 1; empty -> 1.
    """
    if not designator:
        return 1
    return len(designator.split())
