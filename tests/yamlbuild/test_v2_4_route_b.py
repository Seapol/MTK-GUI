# -*- coding: utf-8 -*-
"""v2-4 (node 02) Route B importer + rules.v2 schema — headless.

The Route B importer reads an ICT Excel ``RESULTS`` sheet and the
rules layer now refuses the superseded v1 schema.
"""
from __future__ import annotations

import json
import os

import pytest

from mtkgui.ict.netparse.route_b import (REASON_Y_DESIGNATOR,
                                         parse_results_sheet)
from mtkgui.ict.netparse.rule_layers import load_external

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
PROD = os.path.join(
    FIXTURES, "96317_FRDM-IMXRT700_SPREADSHEET_revA_for_production.xlsx")
VARIANT = os.path.join(
    FIXTURES,
    "96317_FRDM-IMXRT700_SPREADSHEET_revA_for_production_variant_TP11.xlsx")


# ---------------------------------------------------------- Route B parse
def test_route_b_parses_results_sheet():
    """The real workbook (Y3 -> TP1.1 variant) parses to the v2 counts.

    The sheet has 16 impedance power nets == 16 voltage power nets and
    one probeable clock (TP1.1).  It carries NO GND data row - the GND
    reference (TP6.1 TP46.1) only appears in the impedance PROCEDURE
    text, so the GND bucket is empty here (the directive's "GND 1 net /
    16 points" does not match this workbook).
    """
    result = parse_results_sheet(VARIANT)
    assert result.count("Power") == 16
    assert result.count("SE Clock") == 1
    assert result.count("GND") == 0
    assert result.count("Other") == 0
    assert result.gate_ok is True
    assert result.summary() == (
        "Power 16 · SE Clock 1 · GND 0 · Other 0 · skipped 2 rows")


def test_route_b_rejects_y_designator():
    """A crystal designator (Y1/Y2/Y3) is not probeable from MTK."""
    result = parse_results_sheet(PROD)
    assert result.count("SE Clock") == 0
    assert len(result.skipped) == 3
    for name, reason in result.skipped:
        assert reason == REASON_Y_DESIGNATOR
        assert name.startswith("XTAL")


def test_route_b_gnd_collapse(tmp_path):
    """A single GND row collapses its points into (N points)."""
    import openpyxl

    path = tmp_path / "gnd.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RESULTS"
    ws.append(["#", "TESTS", "PROCEDURE", "Refdes", "Expected"])
    ws.append([2, "STATIC IMPEDANCE TEST", "x", "Reference Designator",
               "Expected Value"])
    ws.append([None, None, "GND", "TP6.1 TP46.1", "> 10"])
    ws.append([None, None, "SYS_5V0", "TP35.1", "> 10"])
    ws.append([3, "VOLTAGE MEASUREMENTS", "x", "Reference Designator",
               "Min"])
    ws.append([None, None, "SYS_5V0", "TP35.1", "4.5"])
    wb.save(path)

    result = parse_results_sheet(str(path))
    assert result.count("GND") == 1
    assert result.gnd_points == 2
    assert result.count("Power") == 1
    gnd = [n for n in result.nets if n.category == "GND"][0]
    assert gnd.name == "GND"
    assert gnd.test_point == "(2 points)"


def test_route_b_missing_results_sheet(tmp_path):
    import openpyxl

    path = tmp_path / "noresults.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Other"
    wb.save(path)
    with pytest.raises(ValueError, match="has no 'RESULTS' sheet"):
        parse_results_sheet(str(path))


# ------------------------------------------------------------- rules v2
def test_rules_v1_is_refused(tmp_path):
    path = tmp_path / "v1.json"
    path.write_text(json.dumps({
        "schema": "mtkgui.ict.netparse.rules.v1",
        "tokens": {"add": {"power": ["NEWRAIL"]}},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match=(
            "Unsupported net-rule schema: mtkgui.ict.netparse.rules.v1. "
            "Re-export the rules as v2.")):
        load_external([str(path)])


def test_rules_v2_accepted(tmp_path):
    path = tmp_path / "v2.json"
    path.write_text(json.dumps({
        "schema": "mtkgui.ict.netparse.rules.v2",
        "tokens": {"add": {"power": ["NEWRAIL"]}},
    }), encoding="utf-8")
    merged = load_external([str(path)])
    assert "NEWRAIL" in merged["tokens"]["add"]["power"]
