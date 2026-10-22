# -*- coding: utf-8 -*-
"""Test-role split inside the Signal class.

Signal nets split into ``control_io`` (chip-control tokens on an
un-reused IO) and ``others`` (``system_random`` / ``unclassified``),
while the physical ``net_type`` values stay unchanged.  The Exclude
regex always wins over a Control-IO keyword.
"""
from __future__ import annotations

from mtkgui.ict.netparse import (
    CATEGORY_CONTROL_IO_LABEL,
    CATEGORY_OTHERS,
    NET_TYPE_POWER,
    NET_TYPE_SIGNAL,
    RESULT_SCHEMA,
    SUBCLASS_SYSTEM_RANDOM,
    SUBCLASS_UNCLASSIFIED,
    SYSTEM_RANDOM_RE,
    parse_testable_nets,
    result_to_csv,
    result_to_dict,
)

NET_SAMPLE = """*SIGNAL* VDD_3V3
U1.1 TP1.1
*SIGNAL* CLK_24M
U1.2 TP2.1
*SIGNAL* SOC_RST0
U1.3 TP3.1
*SIGNAL* WIFI_EN0
U1.4 TP4.1
*SIGNAL* SOC_CS0
U1.5 TP5.1
*SIGNAL* BOOT_MODE0
U1.6 TP6.1
*SIGNAL* GPIO_LED1
U1.7 TP7.1
*SIGNAL* ETH0_RXCLK
U1.8 TP8.1
*SIGNAL* GPIO7(MAC2_RGMII_TXCLK)
U1.9 TP9.1
*SIGNAL* ETH_RST
U1.10 TP10.1
*SIGNAL* SPI0_CS
U1.11 TP11.1
*SIGNAL* N12345
U1.12 TP12.1
*SIGNAL* WIFI_EN
U1.13 TP13.1
"""

CONTROL_NAMES = ["SOC_RST0", "WIFI_EN0", "SOC_CS0", "BOOT_MODE0"]
OTHERS_NAMES = ["GPIO_LED1", "ETH0_RXCLK", "GPIO7(MAC2_RGMII_TXCLK)",
                "ETH_RST"]
FILTERED_NAMES = {"SPI0_CS", "N12345", "WIFI_EN"}


def test_signal_split_control_io_vs_others():
    result = parse_testable_nets(NET_SAMPLE)
    assert [r.name for r in result.power] == ["VDD_3V3"]
    assert [r.name for r in result.clock] == ["CLK_24M"]
    assert [r.name for r in result.control_io] == CONTROL_NAMES
    assert [r.name for r in result.others] == OTHERS_NAMES
    assert result.total == 13
    # the physical type is never renamed by the test-role split
    assert all(r.net_type == NET_TYPE_SIGNAL
               for r in result.control_io + result.others)
    assert result.power[0].net_type == NET_TYPE_POWER


def test_control_io_rule_provenance():
    result = parse_testable_nets(NET_SAMPLE)
    provenance = {r.name: r.provenance for r in result.control_io}
    assert provenance == {
        "SOC_RST0": "control_io:reset",
        "WIFI_EN0": "control_io:enable",
        "SOC_CS0": "control_io:cs",
        "BOOT_MODE0": "control_io:mode",
    }
    assert all(r.sub_class == "" for r in result.control_io)


def test_others_sub_class_and_provenance():
    result = parse_testable_nets(NET_SAMPLE)
    by_name = {r.name: r for r in result.others}
    assert by_name["GPIO_LED1"].sub_class == SUBCLASS_UNCLASSIFIED
    assert by_name["GPIO_LED1"].provenance == "fallback:unclassified"
    # interface / reused IO is never control IO
    assert by_name["ETH0_RXCLK"].sub_class == SUBCLASS_UNCLASSIFIED
    assert by_name["GPIO7(MAC2_RGMII_TXCLK)"].sub_class == \
        SUBCLASS_UNCLASSIFIED
    assert by_name["ETH_RST"].sub_class == SUBCLASS_UNCLASSIFIED


def test_exclude_wins_over_control_io_keywords():
    """Interface-bus nets stay filtered even when they carry CS / EN."""
    result = parse_testable_nets(NET_SAMPLE)
    assert {name for name, _reason in result.filtered} == FILTERED_NAMES
    control_names = {r.name for r in result.control_io}
    assert "SPI0_CS" not in control_names
    assert "WIFI_EN" not in control_names
    records = {r.name: r for r in result.filtered_records}
    assert records["SPI0_CS"].provenance == "exclude:regex"
    assert records["SPI0_CS"].sub_class == SUBCLASS_UNCLASSIFIED
    assert records["N12345"].sub_class == SUBCLASS_SYSTEM_RANDOM
    assert records["WIFI_EN"].sub_class == SUBCLASS_UNCLASSIFIED


def test_exclude_disabled_restores_control_io_and_random():
    result = parse_testable_nets(NET_SAMPLE, rules={"exclude": ""})
    control = {r.name: r for r in result.control_io}
    # M2 Fix 2: the protocol pre-filter is independent of the user
    # Exclude regex - SPI0_CS is never control IO
    assert "SPI0_CS" not in control
    assert control["WIFI_EN"].provenance == "control_io:enable"
    others = {r.name: r for r in result.others}
    assert others["SPI0_CS"].sub_class == SUBCLASS_UNCLASSIFIED
    assert others["N12345"].sub_class == SUBCLASS_SYSTEM_RANDOM
    assert others["N12345"].provenance == "rule:system_random"


def test_system_random_rule_fires_on_synthetic_names():
    """M1 Fix 4 finding: the Allegro random-name rule
    ``^\\$?N?\\d+$`` fires on ``N0007`` / ``N12345`` / ``1234`` style
    names, but NOT on the ``$1N123`` variant (an ``N`` BETWEEN digits
    is outside the pattern - ``rules.py`` is out of the Fix-1 scope,
    so the limitation is documented here rather than fixed)."""
    assert SYSTEM_RANDOM_RE.match("N0007")
    assert SYSTEM_RANDOM_RE.match("N12345")
    assert SYSTEM_RANDOM_RE.match("1234")
    assert not SYSTEM_RANDOM_RE.match("$1N123")
    sample = """*SIGNAL* N0007
U1.1 TP1.1
*SIGNAL* $1N123
U1.2 TP2.1
"""
    result = parse_testable_nets(sample)
    # N0007 also hits the DEFAULT exclude regex (it embeds the
    # random-name pattern) -> filtered, sub_class still recorded
    filtered = {r.name: r for r in result.filtered_records}
    assert filtered["N0007"].sub_class == SUBCLASS_SYSTEM_RANDOM
    assert filtered["N0007"].provenance == "exclude:regex"
    # the $-variant falls through to others.unclassified for now
    by_name = {r.name: r for r in result.others}
    assert by_name["$1N123"].sub_class == SUBCLASS_UNCLASSIFIED
    # with the exclusion disabled both land in others.system_random
    result2 = parse_testable_nets(sample, rules={"exclude": ""})
    by_name2 = {r.name: r for r in result2.others}
    assert by_name2["N0007"].sub_class == SUBCLASS_SYSTEM_RANDOM
    assert by_name2["N0007"].provenance == "rule:system_random"


def test_gpio_compatible_view():
    """``gpio`` stays the sum control_io + others for old consumers."""
    result = parse_testable_nets(NET_SAMPLE)
    assert [r.name for r in result.gpio] == CONTROL_NAMES + OTHERS_NAMES


def test_category_lookup_and_human_label():
    result = parse_testable_nets(NET_SAMPLE)
    assert result.category("SOC_RST0") == CATEGORY_CONTROL_IO_LABEL
    assert result.category("GPIO_LED1") == CATEGORY_OTHERS
    assert "Un-reused GPIO" in CATEGORY_CONTROL_IO_LABEL
    assert result.summary().startswith(
        "power=1 clock=1 control_io=4 others=4 gnd=0 filtered=3")


def test_json_v2_export():
    result = parse_testable_nets(NET_SAMPLE)
    payload = result_to_dict(result)
    assert payload["schema"] == RESULT_SCHEMA
    assert payload["schema"] == "mtkgui.ict.netparse.v3"
    assert payload["summary"]["control_io"] == 4
    assert payload["summary"]["others"] == 4
    assert payload["summary"]["gpio"] == 8
    control = payload["nets"]["control_io"]["nets"][0]
    assert control["net"] == "SOC_RST0"
    assert control["provenance"] == "control_io:reset"
    others = payload["nets"]["others"][0]
    assert others["sub_class"] == SUBCLASS_UNCLASSIFIED
    assert others["provenance"] == "fallback:unclassified"


def test_csv_sub_class_column():
    lines = result_to_csv(parse_testable_nets(NET_SAMPLE)).splitlines()
    assert lines[0] == ("net,category,test_point,alternatives,members,"
                        "sub_class,reason,priority,rank,confidence")
    assert any(line.startswith(
        f"SOC_RST0,{CATEGORY_CONTROL_IO_LABEL},") for line in lines[1:])
    assert any(line.startswith("GPIO_LED1,Others,")
               and ",unclassified," in line for line in lines[1:])
    filtered = [line for line in lines[1:]
                if line.startswith("SPI0_CS,Filtered,")]
    assert filtered and filtered[0].split(",")[5] == ""
