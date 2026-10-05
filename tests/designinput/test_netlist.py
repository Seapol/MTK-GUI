# -*- coding: utf-8 -*-
"""Net classification tests (gnd_ref / diff_pair / power / clock)."""
from __future__ import annotations

from mtkgui.gui.yamlbuild.parser import parse_netlist

from mtkgui.gui.designinput.netlist import (
    NET_TYPE_CLOCK_SINGLE,
    NET_TYPE_DIFF_PAIR,
    NET_TYPE_GND_REF,
    NET_TYPE_POWER,
    NET_TYPE_SIGNAL,
    classify_nets,
    parse_netlist_file,
)

NETLIST_SAMPLE = """
* Allegro netlist
*SIGNAL* GND
U1.1 U2.2 J1.3
*SIGNAL* AGND
U1.2
*SIGNAL* 3V3
U1.5 U2.4
*SIGNAL* VDD_CORE
U2.6 U1.8
*SIGNAL* VPRE
U2.7 U3.1
*SIGNAL* USB_P
J1.4 U1.20
*SIGNAL* USB_N
J1.5 U1.21
*SIGNAL* CLK_24M
U1.10 TP4
*SIGNAL* SDA
U1.11 U2.12
"""


def _collection():
    return classify_nets(parse_netlist(NETLIST_SAMPLE))


def test_gnd_ref_detection():
    col = _collection()
    assert col.by_name("GND").net_type == NET_TYPE_GND_REF
    assert col.by_name("AGND").net_type == NET_TYPE_GND_REF


def test_power_detection():
    col = _collection()
    assert col.by_name("3V3").net_type == NET_TYPE_POWER
    assert col.by_name("VDD_CORE").net_type == NET_TYPE_POWER
    assert col.by_name("VPRE").net_type == NET_TYPE_POWER


def test_diff_pair_excluded_from_clock():
    col = _collection()
    assert col.by_name("USB_P").net_type == NET_TYPE_DIFF_PAIR
    assert col.by_name("USB_N").net_type == NET_TYPE_DIFF_PAIR
    assert col.diff_pairs == [("USB_P", "USB_N")]


def test_clock_single():
    col = _collection()
    assert col.by_name("CLK_24M").net_type == NET_TYPE_CLOCK_SINGLE


def test_signal_fallback():
    col = _collection()
    assert col.by_name("SDA").net_type == NET_TYPE_SIGNAL


def test_pins_of_component_view():
    col = _collection()
    pins = col.pins_of("U1")
    assert pins["5"] == "3V3"
    assert pins["1"] == "GND"


def test_parse_netlist_file_missing(tmp_path):
    """A missing file degrades to an empty netlist (never raises)."""
    data, text = parse_netlist_file(str(tmp_path / "nope.net"))
    assert data.nets == {} and text == ""
