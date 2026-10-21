# -*- coding: utf-8 -*-
"""M2 PART B1-B3 + B6: priority ranking, capacity truncation and the
library + capacity integration fixture."""
from __future__ import annotations

import json

import pytest

from mtkgui.ict.netparse import (DEFAULT_LIMITS, NET_TYPE_POWER,
                                 parse_limits, parse_testable_nets,
                                 rank_result, result_to_csv,
                                 result_to_dict, result_to_json, truncate)
from mtkgui.ict.netparse.capacity import ResourceLimits
from mtkgui.ict.netparse.model import ParseNetsResult, NetRecord

# ------------------------------------------------------------- B1 rank
def _result(**buckets) -> ParseNetsResult:
    result = ParseNetsResult()
    for bucket, names in buckets.items():
        setattr(result, bucket, [
            NetRecord(name=n, members=[f"U1.{i}", "TP1.1"])
            for i, n in enumerate(names)])
    return result


def test_power_rank_stage_then_voltage():
    result = _result(power=["VDD_00", "DCDC_3V3_OUT", "VBAT",
                            "VIN_12V", "VDD_01"])
    rank_result(result)
    names = [r.name for r in result.power]
    # stage 0 first (voltage desc), stage 1, then stage 2 input order
    assert names == ["VIN_12V", "VBAT", "DCDC_3V3_OUT",
                     "VDD_00", "VDD_01"]
    assert result.power[0].priority["stage"] == 0
    assert result.power[2].priority["stage"] == 1


def test_clock_band_and_importance():
    result = _result(clock=["CLKOUT0", "MCLK_OUT0", "RTC_XTAL",
                            "SYS_CLK0"])
    rank_result(result)
    ranked = [(r.name, r.priority["band"], r.priority["score"])
              for r in result.clock]
    # LF first (band split), then HF by score desc, stable tie-break
    assert ranked == [("RTC_XTAL", "LF", 1), ("SYS_CLK0", "HF", 3),
                      ("MCLK_OUT0", "HF", 2), ("CLKOUT0", "HF", 1)]


def test_control_io_weight_rst_en_cs_mode():
    result = _result(control_io=["MODE0", "CS0", "EN0", "RST0"])
    rank_result(result)
    assert [r.name for r in result.control_io] == \
        ["RST0", "EN0", "CS0", "MODE0"]
    assert result.control_io[0].priority["score"] == 4


def test_clock_score_load_role_library():
    library = {"U9": {"part_number": "IMX93DQ"}}
    result = _result(clock=["CLKOUT0", "CLKOUT1"])
    result.clock[1].members = ["U9.5", "TP2.1"]
    rank_result(result, library)
    assert result.clock[0].name == "CLKOUT1"   # LOAD member: +3
    assert result.clock[0].priority["score"] == 3


# ------------------------------------------------------------ B2 limits
def test_parse_limits_matrix():
    assert parse_limits(None) == DEFAULT_LIMITS
    limits = parse_limits("power=40,rails=6,clock_lf=2,clock_hf=4,"
                          "ctrl=10")
    assert limits == ResourceLimits(power_pts=40, rails_up=6,
                                    clock_lf=2, clock_hf=4, ctrl_io=10)
    with pytest.raises(ValueError):
        parse_limits("bogus=1")
    with pytest.raises(ValueError):
        parse_limits("power=many")


def test_truncate_and_overflow_subclass():
    result = ParseNetsResult()
    result.power = [NetRecord(name=f"VDD_{i:02d}", members=["U1.1"])
                    for i in range(100)]
    truncate_report = truncate(result, DEFAULT_LIMITS)
    assert truncate_report["power"]["limit"] == 80
    assert len(truncate_report["power"]["selected"]) == 80
    assert len(truncate_report["power"]["overflow"]) == 20
    rank_result(result)
    report = truncate(result, DEFAULT_LIMITS)
    assert report["power"]["selected"][0].name == "VDD_00"
    assert report["power"]["overflow"][0].name == "VDD_80"


# --------------------------------------------------- B6 integration fix
def _b6_net_text() -> str:
    lines = ["Allegro Report", "C:/work/board.brd", "", 
             "Net Name,Net Pins"]
    for i in range(100):
        lines.append(f"VDD_{i:02d},U5.{i} TP10.{i}")
    lines += ["VBAT,U5.90 TP11.1", "VIN_12V,U5.91 TP11.2",
              "DCDC_3V3_OUT,U5.92 TP11.3",
              "RTC_XTAL,U1.1 TP20.1", "SUSCLK_32K,U1.2 TP20.2",
              "SYS_CLK0,U5.93 TP21.1", "CLKOUT0,U1.3 TP21.2",
              "MCLK_OUT0,U5.94 TP21.3", "REFCLK0,U1.4 TP21.4",
              "AUXCLK1,U1.5 TP21.5", "CLK_IN0,U1.6 TP21.6"]
    for i in range(10):
        lines.append(f"RST_{i},U5.{100 + i} TP30.{i}")
    for i in range(15):
        lines.append(f"EN_{i},U5.{110 + i} TP31.{i}")
    for i in range(15):
        lines.append(f"CS{i},U5.{125 + i} TP32.{i}")
    for i in range(10):
        lines.append(f"MODE{i},U5.{140 + i} TP33.{i}")
    lines += ["SI5332_CLK_VDDA,U1.7 TP40.1",
              "SI5332_CLK0_OUT,U1.8 TP40.2",
              "SJA1124_CLKIN,U2.3 TP41.1",
              "DUT_CLK1_FPGA_AG25,U3.4 TP42.1"]
    return "\n".join(lines) + "\n"


B6_LIBRARY = {
    "U1": {"part_number": "SI5332AGM48"},
    "U2": {"part_number": "SJA1124"},
    "U3": {"part_number": "AG25F256"},
    "U5": {"part_number": "IMX93DQ"},
}


def _b6_dict():
    result = parse_testable_nets(_b6_net_text(), library=B6_LIBRARY)
    return result_to_dict(result, library=B6_LIBRARY), result


def test_b6_device_role_nets():
    result = parse_testable_nets(_b6_net_text(), library=B6_LIBRARY)
    power_names = {r.name for r in result.power}
    clock_names = {r.name for r in result.clock}
    others_names = {r.name for r in result.others}
    assert "SI5332_CLK_VDDA" in power_names     # clock-gen strap
    assert "SI5332_CLK0_OUT" in clock_names     # clock-gen output
    assert "SJA1124_CLKIN" in others_names      # interface: untested
    assert "DUT_CLK1_FPGA_AG25" in clock_names  # FPGA clock from DUT


def test_b6_capacity_report():
    payload, result = _b6_dict()
    report = payload["capacity_report"]
    total_power = len(result.power)
    assert report["power"]["limit"] == 80
    assert len(report["power"]["selected"]) == 80
    assert len(report["power"]["overflow"]) == total_power - 80
    assert report["clock"]["limit"] == 3
    assert len(report["clock"]["selected"]) == 3
    assert len(report["clock"]["overflow"]) == len(result.clock) - 3
    assert report["control_io"]["limit"] == 24
    assert len(report["control_io"]["selected"]) == 24
    assert len(report["control_io"]["overflow"]) == \
        len(result.control_io) - 24
    # rails-up list = first 12 of the ranked power candidates
    rails = [e["net"] for e in payload["rails_up"]]
    selected = [e["net"] for e in report["power"]["selected"]]
    assert rails == selected[:12]
    # overflow entries carry the audit reason
    overflow = report["power"]["overflow"][0]
    assert overflow["sub_class"] == "capacity"
    assert overflow["priority"]["capacity_reason"] == \
        "capacity_exceeded(power:80)"


def test_b6_power_ranked_tree_flow():
    payload, _ = _b6_dict()
    top5 = [e["net"] for e in payload["capacity_report"]["power"]
            ["selected"][:5]]
    # input rails first (voltage desc), then converter output
    assert top5 == ["VIN_12V", "VBAT", "DCDC_3V3_OUT",
                    "VDD_00", "VDD_01"]


def test_b6_clock_selected_top3():
    payload, _ = _b6_dict()
    selected = [e["net"] for e in payload["capacity_report"]["clock"]
                ["selected"]]
    # 1 LF (stable input order) + 2 HF by score (SoC +3, MCLK +2)
    assert selected == ["RTC_XTAL", "SYS_CLK0", "MCLK_OUT0"]


def test_b6_ctrl_selected_rst_first():
    payload, _ = _b6_dict()
    selected = [e["net"] for e in payload["capacity_report"]
                ["control_io"]["selected"]]
    assert selected[0] == "RST_0"
    assert selected[10] == "EN_0"
    assert selected[23] == "EN_13"    # 10 RST + 14 EN fill the 24 DIO
    overflow = [e["net"] for e in payload["capacity_report"]
                ["control_io"]["overflow"]]
    assert overflow[0] == "EN_14"     # rest of the EN family first


def test_b6_csv_overflow_under_others():
    result = parse_testable_nets(_b6_net_text(), library=B6_LIBRARY)
    text = result_to_csv(result, library=B6_LIBRARY)
    lines = text.splitlines()
    # power rows stop at the limit; overflow re-labelled Others
    power_rows = [l for l in lines if ",Power," in l]
    assert len(power_rows) == 80
    assert any(l.startswith("VDD_80,Others,")
               and ",capacity," in l for l in lines)
    clock_rows = [l for l in lines if l.split(",")[1] == "Clock"]
    assert len(clock_rows) == 3


def test_b6_no_library_mode_unchanged_classification():
    result = parse_testable_nets(_b6_net_text())
    power_names = {r.name for r in result.power}
    others_names = {r.name for r in result.others}
    # no-library: the SI5332 strap stays Others (M1 fallback), the
    # FPGA / clock-gen outputs stay excluded by the chip-model table
    assert "SI5332_CLK_VDDA" in others_names
    assert "SI5332_CLK0_OUT" in others_names
    assert "DUT_CLK1_FPGA_AG25" in others_names
    assert "VBAT" in power_names


def test_json_compact_and_limits_override():
    result = parse_testable_nets(_b6_net_text(), library=B6_LIBRARY)
    limits = ResourceLimits(power_pts=10, rails_up=2, clock_lf=1,
                            clock_hf=1, ctrl_io=5)
    payload = json.loads(result_to_json(
        result, limits, B6_LIBRARY, indent=0))
    assert payload["resource_limits"]["power_pts"] == 10
    assert len(payload["capacity_report"]["power"]["selected"]) == 10
    assert payload["capacity_report"]["power"]["limit"] == 10
