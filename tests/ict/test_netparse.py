# -*- coding: utf-8 -*-
"""Headless netparse package: format routing, classification, export."""
from __future__ import annotations

import json

import pytest

from mtkgui.ict.netparse import (
    NET_TYPE_DIFF_PAIR,
    NET_TYPE_GND_REF,
    NET_TYPE_POWER,
    RESULT_SCHEMA,
    classify_nets,
    detect_netlist_format,
    parse_netlist_auto,
    parse_netlist_file,
    parse_nets_file,
    parse_testable_nets,
    result_to_csv,
    result_to_dict,
    result_to_json,
)

ALLEGRO_REPORT = """Allegro Report
C:/work/board.brd
Thu Aug 28 16:08:46 2025

Net Name,Net Pins
5V_SDA_PSW,C48.1 D43.A U17.C2
AGND,C186.2 C190.2 R2174.1
USB_P,J1.4 U1.20
USB_N,J1.5 U1.21
CLK_24M,TP4.1 U1.10
"""

PSTXNET = """FILE_TYPE=NETLIST;
PART_NAME
 'U1'
 'MIMXRT798S';

NET_NAME
 'GND'
 '@NETLIST_LIB.GND(SCH_1):INS1'
 P U1.1;
 P C1.2;
NET_NAME
 '3V3'
 P U2.VOUT;
 P U1.5;
"""

SPF = """[Document]
Revision: B

[Drawing]
FRDM-IMXRT700 CPU Board

[Component]
U1 ; MIMXRT798S

[Net]
3V3 U1.5 U2.4
GND U1.1
"""

ALLEGRO_REPORT_QUOTED = """Allegro Report
C:/work/board.brd

Net Name,Net Pins
"A,B",C1.1 U1.2
"3V3",TP1.1 U2.VOUT
"""


def test_detect_allegro_report():
    assert detect_netlist_format(ALLEGRO_REPORT) == "allegro_report"


def test_detect_spf():
    assert detect_netlist_format(SPF) == "spf"


def test_detect_pstxnet():
    assert detect_netlist_format(PSTXNET) == "pstxnet"


def test_parse_allegro_report_nets():
    data = parse_netlist_auto(ALLEGRO_REPORT)
    assert set(data.nets) == {"5V_SDA_PSW", "AGND", "USB_P", "USB_N",
                              "CLK_24M"}
    assert data.nets["5V_SDA_PSW"] == ["C48.1", "D43.A", "U17.C2"]
    assert "AGND" in data.missing_tp       # no TP member
    assert "CLK_24M" not in data.missing_tp


def test_parse_pstxnet_nets_and_pins():
    data = parse_netlist_auto(PSTXNET)
    assert set(data.nets) == {"GND", "3V3"}
    assert "U1.1" in data.nets["GND"]
    assert "U2.VOUT" in data.nets["3V3"]


def test_parse_netlist_file_auto_detects(tmp_path):
    path = tmp_path / "board.net"
    path.write_text(ALLEGRO_REPORT, encoding="utf-8")
    data, text = parse_netlist_file(str(path))
    assert len(data.nets) == 5
    assert text.startswith("Allegro Report")


def test_parse_allegro_report_quoted_net_name():
    """Quoted names with embedded commas stay one net name."""
    data = parse_netlist_auto(ALLEGRO_REPORT_QUOTED)
    assert set(data.nets) == {"A,B", "3V3"}
    assert data.nets["A,B"] == ["C1.1", "U1.2"]
    assert data.nets["3V3"] == ["TP1.1", "U2.VOUT"]


def test_allegro_report_header_case_insensitive():
    text = ALLEGRO_REPORT.replace("Net Name,Net Pins", "NET NAME,NET PINS")
    assert detect_netlist_format(text) == "allegro_report"
    assert len(parse_netlist_auto(text).nets) == 5


def test_report_metadata_lines_never_become_nets():
    data = parse_netlist_auto(ALLEGRO_REPORT)
    assert "Allegro Report" not in data.nets
    assert not any("board.brd" in name for name in data.nets)


def test_detect_and_parse_net_format():
    text = "*SIGNAL* 3V3\nU1.5\n*SIGNAL* GND\nJ1.2\n"
    assert detect_netlist_format(text) == "net"
    assert parse_netlist_auto(text).nets == {"3V3": ["U1.5"],
                                              "GND": ["J1.2"]}


def test_parse_netlist_file_empty_degrades(tmp_path):
    path = tmp_path / "empty.net"
    path.write_text("", encoding="utf-8")
    data, text = parse_netlist_file(str(path))
    assert data.nets == {} and text == ""


def test_classification_counts():
    result = parse_testable_nets(ALLEGRO_REPORT)
    assert result.total == 5
    assert result.format == "allegro_report"
    assert [r.name for r in result.power] == ["5V_SDA_PSW"]
    assert [r.name for r in result.clock] == ["CLK_24M"]
    assert [r.name for r in result.gnd] == ["AGND"]
    names = [r.name for r in result.gpio]
    assert names == []                       # both GPIO are a diff pair
    assert {n for n, _r in result.filtered} == {"USB_P", "USB_N"}


def test_classify_direct_types():
    collection = classify_nets(parse_netlist_auto(ALLEGRO_REPORT))
    assert collection.by_name("5V_SDA_PSW").net_type == NET_TYPE_POWER
    assert collection.by_name("AGND").net_type == NET_TYPE_GND_REF
    assert collection.by_name("USB_P").net_type == NET_TYPE_DIFF_PAIR


def test_parse_testable_rejects_garbage():
    with pytest.raises(ValueError, match="no nets found"):
        parse_testable_nets("just some words\nnothing else")


def test_parse_nets_file_sets_source(tmp_path):
    path = tmp_path / "report.net"
    path.write_text(ALLEGRO_REPORT, encoding="utf-8")
    result = parse_nets_file(str(path))
    assert result.source == "report.net"
    assert result.total == 5


def test_parse_nets_file_missing():
    with pytest.raises(FileNotFoundError):
        parse_nets_file("/definitely/missing.net")


def test_result_to_dict_schema_and_test_points():
    result = parse_testable_nets(ALLEGRO_REPORT)
    payload = result_to_dict(result)
    assert payload["schema"] == RESULT_SCHEMA
    assert payload["format"] == "allegro_report"
    assert payload["summary"]["power"] == 1
    assert payload["summary"]["filtered"] == 2
    power = payload["nets"]["power"][0]
    assert power["test_point"] == "C48.1"      # C beats unranked D/U
    assert "D43.A" in power["alternatives"]


def test_result_to_csv_rows():
    result = parse_testable_nets(ALLEGRO_REPORT)
    text = result_to_csv(result)
    lines = text.splitlines()
    assert lines[0] == ("net,category,test_point,alternatives,members,"
                        "sub_class,reason")
    assert any(line.startswith("5V_SDA_PSW,Power,") for line in lines[1:])
    assert any(",Filtered," in line and "differential" in line
               for line in lines[1:])


def test_json_round_trip():
    result = parse_testable_nets(ALLEGRO_REPORT)
    payload = json.loads(result_to_json(result))
    assert payload["nets"]["gnd"][0]["net"] == "AGND"
