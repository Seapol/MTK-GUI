# -*- coding: utf-8 -*-
"""M2 B7: full integration fixture - library + bridge + confidence +
capacity + conflict + overrides in ONE synthetic project."""
from __future__ import annotations

import json

from mtkgui.ict.netparse import (DEFAULT_LIMITS, parse_testable_nets,
                                 result_to_csv, result_to_dict)
from mtkgui.ict.netparse.parser import apply_user_overrides


def _fixture_text() -> str:
    lines = ["Allegro Report", "C:/work/b7.brd", "", "Net Name,Net Pins"]
    # 100 power nets: 70 high (voltage prefix), 20 medium (single
    # power token), 10 low (weak name, M1 power form only)
    for i in range(70):
        lines.append(f"1V8_A{i:02d},U5.{i} TP10.{i}")
    for i in range(20):
        lines.append(f"VDD_{i:02d},U5.{70 + i} TP11.{i}")
    for i in range(10):
        lines.append(f"VOUT_{i:02d},U5.{90 + i} TP12.{i}")
    # passive-bridge chains + 1K divider
    lines += ["VDD_A,R100.1 U2.5", "VDD_B,R100.2 L5.1",
              "VDD_C,L5.2 TP1.1",
              "SW_1V8,L6.1 TP2.1", "1V8_MAIN,L6.2 U5.95",
              "VDD_X,R101.1 U5.96", "VDD_Y,R101.2 U5.97"]
    # clocks: 2 LF + 6 HF (4 high, 1 medium MCLK, 1 weak)
    lines += ["SUSCLK_32K,U1.1 TP20.1", "RTC_XTAL,U1.2 TP20.2",
              "CLK_24M,U5.98 TP21.1", "REFCLK_25M,U5.99 TP21.2",
              "CLKOUT0,U1.3 TP21.3", "CLKOUT1,U1.4 TP21.4",
              "MCLK_OUT0,U5.5 TP21.5", "EEPROM_CLK,U9.1 TP21.6"]
    # control IO: 10 RST (5 on the control chip), 20 EN, 10 CS, 10 MODE
    for i in range(5):
        lines.append(f"RST_{i},U8.{i + 1} TP30.{i}")
    for i in range(5, 10):
        lines.append(f"RST_{i},U5.{100 + i} TP30.{i}")
    for i in range(20):
        lines.append(f"EN_{i},U5.{120 + i} TP31.{i}")
    for i in range(10):
        lines.append(f"CS{i},U5.{140 + i} TP32.{i}")
    for i in range(10):
        lines.append(f"MODE{i},U5.{150 + i} TP33.{i}")
    # reused / muxed / protocol / conflict / device-role specials
    lines += ["DUT_GPIO7_MAC2_RGMII_TXCLK,U5.160 TP34.1",
              "BB_MCLK_IN(MCLK_IN0),U5.161 TP34.2",
              "SPI0_CS,U5.162 TP34.3",
              "ETH0_RST,U5.163 TP34.4",
              "SDIO_EN,U5.164 TP34.5",
              "SI5332_CLK_VDDA,U1.7 TP40.1",
              "SI5332_CLK0_OUT,U1.8 TP40.2",
              "SJA1124_CLKIN,U2.3 TP41.1",
              "DUT_CLK1_FPGA_AG25,U3.4 TP42.1",
              "5V_SDA_PSW,U5.165 TP43.1",
              "PCIE_CLK_OE1,U5.166 TP43.2",
              "ENET1_REFCLK,U5.167 TP43.3"]
    return "\n".join(lines) + "\n"


B7_LIBRARY = {
    "U1": {"part_number": "SI5332AGM48"},
    "U2": {"part_number": "SJA1124"},
    "U3": {"part_number": "AG25F256"},
    "U5": {"part_number": "IMX93DQ"},
    "U8": {"part_number": "PCA9555"},
    "R100": {"part_number": "CRCW04020000Z0", "value": "0R"},
    "R101": {"part_number": "CRCW04021K00", "value": "1K"},
    "L5": {"part_number": "BLM18AG601", "value": "FB"},
    "L6": {"part_number": "SRP5030T", "value": "1UH"},
}


def _parse():
    return parse_testable_nets(_fixture_text(), library=B7_LIBRARY)


def _payload():
    return result_to_dict(_parse(), library=B7_LIBRARY)


# ------------------------------------------------------------ B0 merge
def test_b7_bridge_merge():
    result = _parse()
    power_names = {r.name for r in result.power}
    # one rail, TP side VDD_C is the representative
    assert result.bridge_report["VDD_C"] == ["VDD_A", "VDD_B"]
    # switch node with TP2 loses to the DC side
    assert result.bridge_report["1V8_MAIN"] == ["SW_1V8"]
    assert "VDD_C" in power_names and "1V8_MAIN" in power_names
    assert "VDD_A" not in power_names and "SW_1V8" not in power_names
    # 1K divider does NOT merge
    assert "VDD_X" in power_names and "VDD_Y" in power_names
    dupes = {r.name for r in result.others
             if r.sub_class == "bridge_duplicate"}
    assert dupes == {"VDD_A", "VDD_B", "SW_1V8"}


# ------------------------------------------------------- B1 confidence
def test_b7_confidence_levels():
    result = _parse()
    by_name = {}
    for bucket in (result.power, result.clock, result.control_io,
                   result.others):
        for rec in bucket:
            by_name[rec.name] = rec
    assert by_name["1V8_A00"].confidence == "high"
    assert by_name["VDD_00"].confidence == "medium"
    assert by_name["VOUT_00"].confidence == "low"
    assert by_name["SUSCLK_32K"].confidence == "high"
    assert by_name["EEPROM_CLK"].confidence == "low"
    assert by_name["DUT_CLK1_FPGA_AG25"].confidence == "high"  # FPGA
    assert by_name["RST_0"].confidence == "high"


# ------------------------------------------------------------ B3 power
def test_b7_power_capacity():
    result = _parse()
    payload = result_to_dict(result, library=B7_LIBRARY)
    report = payload["capacity_report"]["power"]
    assert len(report["selected"]) == 80
    # high-confidence overflow: none (72 high < 80); the 16 medium
    # overflow relax to Others/capacity
    assert report["overflow_high"] == []
    relaxed = {e["net"] for e in report["overflow"]}
    assert all(e["sub_class"] == "capacity" for e in report["overflow"])
    assert relaxed == ({f"VDD_{i:02d}" for i in range(8, 20)}
                       | {f"VOUT_{i:02d}" for i in range(10)}
                       | {"VDD_C", "VDD_X", "VDD_Y",
                          "SI5332_CLK_VDDA"})
    # rails-up = first 12 of the ranked selected list (tree flow)
    rails = [e["net"] for e in payload["rails_up"]]
    selected = [e["net"] for e in report["selected"]]
    assert rails == selected[:12]
    assert all(e["test_selected"] for e in report["selected"])


def test_b7_power_high_first_ranking():
    payload = _payload()
    selected = [e["net"] for e in
                payload["capacity_report"]["power"]["selected"]]
    # all 72 high-confidence power nets fill the capacity before any
    # medium net (1V8_MAIN / 5V_SDA_PSW included)
    assert "VOUT_00" not in selected and "VDD_19" not in selected
    assert "1V8_MAIN" in selected and "5V_SDA_PSW" in selected
    assert all(e["confidence"] == "high"
               for e in payload["capacity_report"]["power"]["selected"][:72])


# ------------------------------------------------------------ B3 clock
def test_b7_clock_capacity():
    payload = _payload()
    report = payload["capacity_report"]["clock"]
    selected = [e["net"] for e in report["selected"]]
    # 1 LF (SUSCLK_32K, high) + 2 HF by frequency ascending (24M, 25M)
    assert selected == ["SUSCLK_32K", "CLK_24M", "REFCLK_25M"]
    high = {e["net"] for e in report["overflow_high"]}
    relaxed = {e["net"] for e in report["overflow"]}
    # high-confidence overflow stays in the class (not selected)
    assert high == {"CLKOUT0", "CLKOUT1", "MCLK_OUT0",
                    "BB_MCLK_IN(MCLK_IN0)", "DUT_CLK1_FPGA_AG25"}
    # weak / medium clocks relax to Others/capacity
    assert relaxed == {"RTC_XTAL", "SI5332_CLK0_OUT", "EEPROM_CLK"}
    assert all(e["sub_class"] == "capacity" for e in report["overflow"])


# -------------------------------------------------------- B3 control IO
def test_b7_control_capacity_and_prefilter():
    result = _parse()
    ctrl_names = {r.name for r in result.control_io}
    # protocol / muxed / reused nets NEVER reach control IO
    assert "SPI0_CS" not in ctrl_names
    assert "SDIO_EN" not in ctrl_names
    assert "ETH0_RST" not in ctrl_names
    assert "DUT_GPIO7_MAC2_RGMII_TXCLK" not in ctrl_names
    assert "BB_MCLK_IN(MCLK_IN0)" not in ctrl_names
    payload = result_to_dict(result, library=B7_LIBRARY)
    report = payload["capacity_report"]["control_io"]
    selected = [e["net"] for e in report["selected"]]
    assert len(selected) == 24
    # control-chip (U8 = PCA9555) IO ranks FIRST
    assert selected[:5] == ["RST_0", "RST_1", "RST_2", "RST_3", "RST_4"]
    assert all(e["priority"]["control_chip"] for e in report["selected"][:5])
    # all control candidates are high confidence -> overflow stays
    assert report["overflow"] == []
    assert {e["net"] for e in report["overflow_high"]} == \
        {f"EN_{i}" for i in range(14, 20)} \
        | {f"CS{i}" for i in range(10)} \
        | {f"MODE{i}" for i in range(10)}


# ------------------------------------------------- B1.5 conflict + roles
def test_b7_conflict_and_device_roles():
    result = _parse()
    by_name = {}
    for bucket in (result.power, result.clock, result.control_io,
                   result.others):
        for rec in bucket:
            by_name[rec.name] = rec
    assert by_name["SI5332_CLK_VDDA"].net_type == "power"
    assert by_name["SI5332_CLK0_OUT"].net_type == "clock_single"
    assert by_name["DUT_CLK1_FPGA_AG25"].net_type == "clock_single"
    assert by_name["5V_SDA_PSW"].net_type == "power"
    # protocol negative evidence: no class reaches the threshold
    for net in ("PCIE_CLK_OE1", "ENET1_REFCLK", "SJA1124_CLKIN",
                "ETH0_RST", "DUT_GPIO7_MAC2_RGMII_TXCLK"):
        assert by_name[net] in result.others


# ---------------------------------------------------- B5 override loop
def test_b7_user_override_round_trip(tmp_path):
    result = _parse()
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"EEPROM_CLK": "control_io"}),
                    encoding="utf-8")
    applied = apply_user_overrides(
        result, json.loads(path.read_text(encoding="utf-8")))
    assert applied == {"EEPROM_CLK": "control_io"}
    assert any(r.name == "EEPROM_CLK" for r in result.control_io)
    payload = result_to_dict(result, library=B7_LIBRARY)
    assert payload["user_override"] == {"EEPROM_CLK": "control_io"}
    csv_text = result_to_csv(result, library=B7_LIBRARY)
    assert any(row.startswith("EEPROM_CLK,")
               and ",Un-reused" in row
               for row in csv_text.splitlines())


# -------------------------------------------------------- no-library
def test_b7_no_library_mode_unchanged():
    result = parse_testable_nets(_fixture_text())
    power_names = {r.name for r in result.power}
    others = {r.name for r in result.others}
    # M1 fallbacks unchanged, no bridge merge, no conflict audit
    assert result.bridge_report == {}
    assert "SI5332_CLK_VDDA" in others
    assert "SW_1V8" in power_names      # no library -> no merge
    assert "VDD_A" in power_names
    assert all(r.sub_class == "unclassified"
               for r in result.others)


def test_b7_limit_overrides():
    payload = result_to_dict(_parse(), DEFAULT_LIMITS, B7_LIBRARY)
    assert payload["resource_limits"]["power_pts"] == 80
    assert payload["resource_limits"]["ctrl_io"] == 24
