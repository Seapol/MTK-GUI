# -*- coding: utf-8 -*-
"""GUI test-point view tests (M4 PART 2).

The ranking itself lives in ``mtkgui.ict.netparse.testpoints`` - these
tests pin the GUI view helpers to that single implementation and the
GUI-only reference-GND ordering (pcb first).
"""
from __future__ import annotations

from mtkgui.ict.netparse import parse_testable_nets, select_test_points

from mtkgui.gui.designinput.model import net_collection_from_result
from mtkgui.gui.designinput.testpoints import (
    gnd_reference_names,
    probe_of,
)

NETLIST_SAMPLE = """
*SIGNAL* PWR_5V
J1.1 C3.2 R5.1
*SIGNAL* PWR_3V3
JP2.1 R2.1
*SIGNAL* PWR_1V8
TP7 J4.1
*SIGNAL* GND
J1.2 U1.1
*SIGNAL* DGND_ISO
R9.1
*SIGNAL* FLOATING
U7.3
"""

NETLIST_GND = """
*SIGNAL* GND_EARTH
J1.1
*SIGNAL* GND_SH_P5
R3.1
*SIGNAL* GND
J2.1
"""


def _collection(text):
    return net_collection_from_result(parse_testable_nets(text))


def test_test_point_of_uses_netparse_ranking():
    best, alternatives = probe_of(["J1.1", "C3.2", "R5.1"])
    assert best == "J1.1"
    assert alternatives == ["C3.2", "R5.1"]


def test_gui_ranking_equals_headless_ranking():
    members = ["R5.1", "C3.2", "J1.1"]
    assert probe_of(members)[0] == select_test_points(members)[0]


def test_jp_is_an_alternative_probe():
    col = _collection(NETLIST_SAMPLE)
    rec = col.by_name("PWR_3V3")
    assert rec.is_alternative_testpoint is True
    assert rec.is_reference_gnd is False


def test_dedicated_tp_is_not_an_alternative_probe():
    col = _collection(NETLIST_SAMPLE)
    rec = col.by_name("PWR_1V8")
    assert rec.is_alternative_testpoint is False


def test_gnd_defaults_to_reference():
    col = _collection(NETLIST_SAMPLE)
    assert col.by_name("GND").is_reference_gnd is True
    assert col.by_name("DGND_ISO").is_reference_gnd is True


def test_unknown_prefix_member_is_last_resort():
    """Netparse ranks unknown prefixes last but never drops the only
    candidate; an empty member list has no test point at all."""
    assert probe_of(["U7.3"]) == ("U7.3", [])
    assert probe_of([]) == ("", [])


def test_gnd_reference_names_pcb_first_then_chassis_shield():
    refs = gnd_reference_names(_collection(NETLIST_GND))
    assert refs == ["GND", "GND_EARTH", "GND_SH_P5"]
