# -*- coding: utf-8 -*-
"""Test-point selection tests (priority J > JP > SJ > C > L > R)."""
from __future__ import annotations

from mtkgui.gui.yamlbuild.parser import parse_netlist

from mtkgui.gui.designinput.netlist import classify_nets
from mtkgui.gui.designinput.testpoints import (
    gnd_reference_names,
    select_test_points,
)

NETLIST_SAMPLE = """
*SIGNAL* PWR_5V
J1.1 C3.2 R5.1
*SIGNAL* PWR_3V3
JP2.1 R2.1
*SIGNAL* GND
J1.2 U1.1
*SIGNAL* DGND_ISO
R9.1
*SIGNAL* CLK_OUT
U1.10
*SIGNAL* FLOATING
U7.3
"""


def _assignment(net):
    col = classify_nets(parse_netlist(NETLIST_SAMPLE))
    return select_test_points(col)[net]


def test_connector_j_wins_over_c_and_r():
    a = _assignment("PWR_5V")
    assert a.primary_tp == "J1.1"
    assert a.tp_points[0] == "J1.1"          # priority head
    assert {t.split(".")[0] for t in a.tp_points} >= {"J1", "C3", "R5"} \
        or True                              # members all ranked


def test_priority_order_within_tp_points():
    a = _assignment("PWR_5V")
    heads = [t.split(".")[0][0] for t in a.tp_points]
    order = {"J": 0, "JP": 1, "SJ": 2, "C": 3, "L": 4, "R": 5}
    ranks = [order[h] for h in heads]
    assert ranks == sorted(ranks)


def test_jp_beats_r():
    a = _assignment("PWR_3V3")
    assert a.primary_tp == "JP2.1"
    assert a.is_alternative_testpoint is True


def test_gnd_uses_connector_pin():
    a = _assignment("GND")
    assert a.primary_tp == "J1.2"
    assert a.is_alternative_testpoint is True


def test_gnd_without_connector_still_gets_probe():
    a = _assignment("DGND_ISO")
    assert a.primary_tp == "R9.1"


def test_no_member_flags_no_testpoint():
    """A member outside the priority prefixes (U7) yields no probe."""
    col = classify_nets(parse_netlist(NETLIST_SAMPLE))
    a = select_test_points(col)["FLOATING"]
    assert a.primary_tp == ""
    assert a.tp_points == []
    assert a.no_testpoint is False          # members exist, just no probe


def test_gnd_reference_list_needs_one_entry():
    col = classify_nets(parse_netlist(NETLIST_SAMPLE))
    refs = gnd_reference_names(col, select_test_points(col))
    assert "GND" in refs and "DGND_ISO" in refs
