# -*- coding: utf-8 -*-
"""M99: classification by evidence - bare P/N diff pairs, rail topology
and the low-confidence rail guard in the sequence generator."""
from __future__ import annotations

from pathlib import Path

from mtkgui.gui.yamlbuild.ict_sequence import generate_sequence
from mtkgui.ict.netparse import parse_testable_nets
from mtkgui.ict.netparse.classify import _diff_pair_map, _pair_tuples

REAL_FIXTURE = (Path(__file__).resolve().parents[1]
                / "yamlbuild" / "fixtures" / "NET-96317_A.net")

MINI_NET = """Allegro Report
C:/work/board.brd
Thu Apr 09 17:21:38 2026

Net Name,Net Pins
DIV_VREF,C1.1 R1.2 R2.1 U1.1
REAL_3V3,C2.1 C3.1 R3.1 U1.2
"""


def _pairs(names: list[str]) -> list[tuple[str, str]]:
    return _pair_tuples(_diff_pair_map(names))


def test_diff_pair_without_underscore_pairs_only_when_both_exist():
    """A bare trailing P/N pairs when (and only when) the sibling is in
    the file; the _P/_N spelling keeps winning and stays positive-first."""
    assert _pairs(["CPVOUTN", "CPVOUTP"]) == [("CPVOUTN", "CPVOUTP")]
    assert _pairs(["CLK_N", "CLK_P"]) == [("CLK_P", "CLK_N")]
    # the explicit spelling wins when both rules would match
    assert _pairs(["ABCD_P", "ABCD_N"]) == [("ABCD_P", "ABCD_N")]


def test_bare_suffix_does_not_pair_a_lone_name():
    """No invented sibling: one member alone pairs nothing, and a name
    shorter than 4 characters never qualifies."""
    assert _pairs(["CPVOUTP"]) == []
    assert _pairs(["CPVOUTN"]) == []
    assert _pairs(["ABP", "ABN"]) == []
    assert _pairs(["GND", "VIN"]) == []


def test_rail_with_resistor_divider_moves_to_others():
    """Two series resistors + at most one cap is a divider, not a rail."""
    result = parse_testable_nets(MINI_NET)
    assert {rec.name for rec in result.power} == {"REAL_3V3"}
    demoted = next(rec for rec in result.others if rec.name == "DIV_VREF")
    assert demoted.sub_class == "ambiguous"
    assert demoted.confidence == "low"
    assert demoted.provenance == "evidence:rail-topology"


def test_rail_topology_keeps_real_rails():
    """The 96317 rails keep their power class (caps >= 2 or < 2 R)."""
    text = REAL_FIXTURE.read_text(encoding="utf-8")
    result = parse_testable_nets(text)
    assert {rec.name for rec in result.power} == {
        "5V_SDA_PSW", "5V_USB0_OTG", "CODEC_1V8", "DCDC_1V0",
        "DCDC_1V8", "DCDC_3V3", "DC_5V_IN"}
    assert "DBGIF_VREF" not in {rec.name for rec in result.power}


def test_ict_sequence_skips_low_confidence_rail():
    """A low-confidence rail without a strong power token generates no
    ICT rows; a strong name keeps its rows."""
    testable = {
        "DBGIF_VREF": {"category": "Power", "confidence": "low"},
        "3V3_SENSE": {"category": "Power", "confidence": "low"},
        "DCDC_1V0": {"category": "Power", "confidence": "high"},
    }
    labels = [row[1] for row in generate_sequence(testable)
              if row[0] == "test"]
    assert "R-GND - DBGIF_VREF" not in labels
    assert "Power Voltage - DBGIF_VREF" not in labels
    assert "Power Voltage - DCDC_1V0" in labels
    assert "Power Voltage - 3V3_SENSE" in labels
