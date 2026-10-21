# -*- coding: utf-8 -*-
"""M2 PART B: device-role clock knowledge base (library mode)."""
from __future__ import annotations

import json

from mtkgui.ict.netparse import (ROLE_CLOCK_GEN, ROLE_FPGA,
                                 ROLE_INTERFACE, NET_TYPE_CLOCK_SINGLE,
                                 NET_TYPE_POWER, NET_TYPE_SIGNAL,
                                 classify_nets, parse_netlist_auto,
                                 parse_testable_nets,
                                 role_for_part_number)
from mtkgui.ict.netparse.cli import main

REPORT = """Allegro Report
C:/work/board.brd

Net Name,Net Pins
SI5332_CLK_VDDA,U1.1
SI5332_CLK0_OUT,U1.2 TP1.1
SJA1124_CLKIN,U2.3
DUT_CLK1_FPGA_AG25,U3.4 TP2.1
UNKNOWN_XTAL,U4.5 TP3.1
3V3,U5.1 TP4.1
"""

LIBRARY = {
    "U1": {"part_number": "SI5332AGM48"},
    "U2": {"part_number": "SJA1124"},
    "U3": {"part_number": "AG25F256"},
    "U4": {"part_number": "MYSTERY-1"},
    "U5": {"part_number": "PF1500"},
}


# ----------------------------------------------------------------- B1
def test_role_matrix():
    assert role_for_part_number("SI5332AGM48") == ROLE_CLOCK_GEN
    assert role_for_part_number("8N4Q001K") == ROLE_CLOCK_GEN
    assert role_for_part_number("SJA1124") == ROLE_INTERFACE
    assert role_for_part_number("TJA1230ATK") == ROLE_INTERFACE
    assert role_for_part_number("88E1512") == ROLE_INTERFACE
    assert role_for_part_number("AG25F256") == ROLE_FPGA
    assert role_for_part_number("XC7A100T") == ROLE_FPGA
    assert role_for_part_number("IMX93DQ") == "load"
    assert role_for_part_number("MT8195") == "load"
    assert role_for_part_number("TPS62840") is None
    assert role_for_part_number("") is None
    # real Innovator BOMs: internal ordering code + description
    assert role_for_part_number(
        "312-10382", "IC CLK GEN LOW JITTER 6-OUT LVDS") == ROLE_CLOCK_GEN
    assert role_for_part_number(
        "211-10234", "IC TRANSCEIVER CANFD 8VHSOIC") == ROLE_INTERFACE


# ----------------------------------------------------------------- B2
def _collection(library):
    return classify_nets(parse_netlist_auto(REPORT), library=library)


def test_library_mode_integration():
    col = _collection(LIBRARY)
    types = {rec.name: rec.net_type for rec in col.nets}
    provenance = {rec.name: rec.provenance for rec in col.nets}
    assert types["SI5332_CLK_VDDA"] == NET_TYPE_POWER
    assert provenance["SI5332_CLK_VDDA"] == "device_role:clock_gen_power"
    assert types["SI5332_CLK0_OUT"] == NET_TYPE_CLOCK_SINGLE
    assert provenance["SI5332_CLK0_OUT"] == "device_role:clock_gen"
    # interface chip: clock inputs stay untested (signal -> others)
    assert types["SJA1124_CLKIN"] == NET_TYPE_SIGNAL
    assert provenance["SJA1124_CLKIN"] == "device_role:interface"
    # FPGA clock input from the DUT counts as Clock
    assert types["DUT_CLK1_FPGA_AG25"] == NET_TYPE_CLOCK_SINGLE
    assert provenance["DUT_CLK1_FPGA_AG25"] == "device_role:fpga"
    # unknown role: M1 rules unchanged (XTAL token -> clock)
    assert types["UNKNOWN_XTAL"] == NET_TYPE_CLOCK_SINGLE


def test_no_library_mode_unchanged():
    col = classify_nets(parse_netlist_auto(REPORT))
    types = {rec.name: rec.net_type for rec in col.nets}
    # chip-model exclusion fallback: SI5332 straps stay signal/Others
    assert types["SI5332_CLK_VDDA"] == NET_TYPE_SIGNAL
    assert types["SI5332_CLK0_OUT"] == NET_TYPE_SIGNAL
    assert types["SJA1124_CLKIN"] == NET_TYPE_SIGNAL
    assert types["DUT_CLK1_FPGA_AG25"] == NET_TYPE_SIGNAL
    assert types["UNKNOWN_XTAL"] == NET_TYPE_CLOCK_SINGLE


def test_testable_nets_library_path_others_split():
    result = parse_testable_nets(REPORT, library=LIBRARY)
    others = {rec.name for rec in result.others}
    assert "SJA1124_CLKIN" in others            # interface: not tested
    assert any(rec.name == "SI5332_CLK0_OUT"
               for rec in result.clock)
    assert any(rec.name == "SI5332_CLK_VDDA"
               for rec in result.power)


# ----------------------------------------------------------------- CLI
def test_cli_library_flag(tmp_path, capsys):
    lib_file = tmp_path / "library.json"
    lib_file.write_text(json.dumps(LIBRARY), encoding="utf-8")
    net_file = tmp_path / "board.net"
    net_file.write_text(REPORT, encoding="utf-8")
    code = main([str(net_file), "--library", str(lib_file)])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    power_names = [r["net"] for r in payload["nets"]["power"]["nets"]]
    assert "SI5332_CLK_VDDA" in power_names
    names = [row["net"] for row in payload["nets"]["clock"]["nets"]]
    assert "SI5332_CLK0_OUT" in names
    assert "DUT_CLK1_FPGA_AG25" in names


def test_cli_library_missing_file_returns_2(tmp_path, capsys):
    net_file = tmp_path / "board.net"
    net_file.write_text(REPORT, encoding="utf-8")
    code = main([str(net_file), "--library",
                 str(tmp_path / "nope.json")])
    captured = capsys.readouterr()
    assert code == 2
    assert "cannot read library file" in captured.err
