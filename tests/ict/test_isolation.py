# -*- coding: utf-8 -*-
"""M7 W6: control-IO DIO-write isolation assessment.

A control net is safe to drive from the U2355A DIO bank only when its
upstream is passive.  The parser stamps ``isolated`` / ``active_drivers``
on every control-IO record; the CSV / JSON / evidence md exports and the
external rule layer carry the same evidence.
"""
from __future__ import annotations

import json

from mtkgui.ict.netparse import (DEFAULT_LIMITS, parse_testable_nets,
                                 result_to_csv, result_to_dict)
from mtkgui.ict.netparse.export_testplan import build_testplan_markdown
from mtkgui.ict.netparse.isolation import assess_net
from mtkgui.ict.netparse.rule_layers import export_base_rules, load_external

NET_SAMPLE = """*SIGNAL* SOC_RST0
U1.3 TP3.1
*SIGNAL* BOOT_MODE0
R10.1 SW1.2
*SIGNAL* WIFI_EN0
Q9.1
"""

LIBRARY = {
    "U1": {"part_number": "STM32F103", "description": "IC MCU",
           "dev_category": "other"},
    "R10": {"part_number": "RES 10K", "description": "RES 10K 0402",
            "dev_category": "other"},
    "SW1": {"part_number": "SW DIP", "description": "SW SPST DIP",
            "dev_category": "other"},
    "TP3": {"part_number": "TP", "description": "TEST POINT",
            "dev_category": "other"},
}


def test_assess_net_active_passive_unknown():
    # active IC in the library -> NOT isolated + refdes list
    isolated, drivers = assess_net(["U1.3", "TP3.1"], LIBRARY)
    assert isolated is False
    assert drivers == ["U1"]
    # only passive members (R / SW / TP) -> isolated
    isolated, drivers = assess_net(["R10.1", "SW1.2"], LIBRARY)
    assert isolated is True
    assert drivers == []
    # refdes missing from the library -> cannot confirm
    isolated, drivers = assess_net(["Q9.1"], LIBRARY)
    assert isolated is None
    assert drivers == []
    # a net without pin info cannot be confirmed either
    assert assess_net([], LIBRARY) == (None, [])


def test_parser_stamps_control_io_records():
    result = parse_testable_nets(NET_SAMPLE, library=LIBRARY)
    by_name = {rec.name: rec for rec in result.control_io}
    assert by_name["SOC_RST0"].isolated is False
    assert by_name["SOC_RST0"].active_drivers == ["U1"]
    assert by_name["BOOT_MODE0"].isolated is True
    assert by_name["BOOT_MODE0"].active_drivers == []
    assert by_name["WIFI_EN0"].isolated is None
    assert all(rec.isolation_checked for rec in result.control_io)


def test_csv_json_carry_isolation_evidence():
    result = parse_testable_nets(NET_SAMPLE, library=LIBRARY)
    lines = result_to_csv(result).splitlines()
    assert lines[0].endswith(",isolated,active_drivers")
    row = next(line for line in lines[1:]
               if line.startswith("SOC_RST0,"))
    assert row.endswith(",false,U1")
    boot = next(line for line in lines[1:]
                if line.startswith("BOOT_MODE0,"))
    assert boot.endswith(",true,")
    payload = result_to_dict(result)
    entry = next(e for e in payload["nets"]["control_io"]["nets"]
                 if e["net"] == "SOC_RST0")
    assert entry["isolated"] is False
    assert entry["active_drivers"] == ["U1"]


def test_evidence_md_carries_isolation_fields():
    result = parse_testable_nets(NET_SAMPLE, library=LIBRARY)
    text = build_testplan_markdown(result, DEFAULT_LIMITS, "TEST",
                                   library=LIBRARY)
    assert "- isolated: false" in text
    assert "- active_drivers: U1" in text
    assert "- isolated: true" in text


def test_base_rules_expose_isolation_tables():
    base = export_base_rules()
    assert base["isolation"]["active_roles"]
    assert base["isolation"]["active_categories"]
    assert "R" in base["isolation"]["passive_prefixes"]
    assert "SW" in base["isolation"]["passive_prefixes"]


def test_external_layer_extends_isolation(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({
        "schema": "mtkgui.ict.netparse.rules.v1",
        "isolation": {"passive_prefixes": ["X"],
                      "active_roles": ["custom_role"],
                      "active_categories": ["custom_cat"]},
    }), encoding="utf-8")
    merged = load_external([str(path)])
    assert "X" in merged["isolation"]["passive_prefixes"]
    assert "custom_role" in merged["isolation"]["active_roles"]
    assert "custom_cat" in merged["isolation"]["active_categories"]


def test_external_passive_prefix_applied(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({
        "schema": "mtkgui.ict.netparse.rules.v1",
        "isolation": {"passive_prefixes": ["Q"]},
    }), encoding="utf-8")
    external = load_external([str(path)])
    result = parse_testable_nets(NET_SAMPLE, library=LIBRARY,
                                 external=external)
    by_name = {rec.name: rec for rec in result.control_io}
    # Q9 becomes passive -> the WIFI_EN0 net is now fully passive
    assert by_name["WIFI_EN0"].isolated is True
