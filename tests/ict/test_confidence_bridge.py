# -*- coding: utf-8 -*-
"""M2 PART B0/B1/B1.5/B5/B7: confidence, passive-bridge rail merge,
cross-class conflict resolution and the user-override round-trip."""
from __future__ import annotations

import json

from mtkgui.ict.netparse import (parse_testable_nets, result_to_csv,
                                 result_to_dict)
from mtkgui.ict.netparse.bridge import merge_power_bridges
from mtkgui.ict.netparse.confidence import (HIGH, LOW, MEDIUM,
                                            clock_freq_hz)
from mtkgui.ict.netparse.model import NetRecord, ParseNetsResult
from mtkgui.ict.netparse.parser import apply_user_overrides

# ------------------------------------------------------------- B1 conf
def test_clock_freq_extraction():
    assert clock_freq_hz("SUSCLK_32KHZ(SCU_GPIO0_07)") == 32768.0
    assert clock_freq_hz("RTC_XTAL") == 32768.0
    assert clock_freq_hz("CLK_24M") == 24e6
    assert clock_freq_hz("CLK_12P288M") == 12.288e6
    assert clock_freq_hz("SYS_CLK0") == 0.0      # unknown -> last


def test_confidence_power_rules():
    result = ParseNetsResult()
    result.power = [NetRecord(name=n, members=["U1.1"],
                              net_type="power") for n in
                    ("VBAT", "VIN_12V", "5V_PSW", "VDD_00", "WEIRD")]
    from mtkgui.ict.netparse.confidence import stamp_confidence
    stamp_confidence(result)
    conf = {r.name: r.confidence for r in result.power}
    assert conf["VBAT"] == HIGH          # strong rail alone
    assert conf["VIN_12V"] == HIGH       # strong rail + voltage prefix
    assert conf["5V_PSW"] == HIGH        # voltage prefix + power token
    assert conf["VDD_00"] == MEDIUM      # single power token
    assert conf["WEIRD"] == LOW          # inferred only


def test_confidence_others_low():
    result = ParseNetsResult()
    result.others = [NetRecord(name="SOME_NET", members=["U1.1"],
                               sub_class="unclassified")]
    from mtkgui.ict.netparse.confidence import stamp_confidence
    stamp_confidence(result)
    assert result.others[0].confidence == LOW


# ------------------------------------------- B0 passive-bridge merge
def _bridge_result() -> tuple[ParseNetsResult, dict]:
    result = ParseNetsResult()
    result.power = [
        NetRecord(name="VDD_A", members=["R100.1", "U2.5"]),
        NetRecord(name="VDD_B", members=["R100.2", "L5.1"]),
        NetRecord(name="VDD_C", members=["L5.2", "TP1.1"]),
        NetRecord(name="SW_1V8", members=["L6.1", "TP2.1"]),
        NetRecord(name="1V8_MAIN", members=["L6.2", "U5.7"]),
        NetRecord(name="VDD_X", members=["R101.1", "U5.8"]),
        NetRecord(name="VDD_Y", members=["R101.2", "U5.9"]),
    ]
    library = {
        "R100": {"part_number": "CRCW04020000Z0", "value": "0R"},
        "R101": {"part_number": "CRCW04021K00", "value": "1K"},
        "L5": {"part_number": "BLM18AG601", "value": "FB"},
        "L6": {"part_number": "SRP5030T", "value": "1UH"},
    }
    report = merge_power_bridges(result, library)
    return result, report


def test_bridge_merge_chain_and_switch_node():
    result, report = _bridge_result()
    power_names = [r.name for r in result.power]
    # VDD_A --R100(0R)-- VDD_B --L5(FB)-- VDD_C: ONE rail, the TP side
    assert "VDD_C" in power_names
    assert "VDD_A" not in power_names and "VDD_B" not in power_names
    # switch node keeps its TP but loses: DC side is the representative
    assert "1V8_MAIN" in power_names and "SW_1V8" not in power_names
    # 1K divider: both nets stay classified (no merge)
    assert "VDD_X" in power_names and "VDD_Y" in power_names
    dupes = {r.name: r for r in result.others
             if r.sub_class == "bridge_duplicate"}
    assert set(dupes) == {"VDD_A", "VDD_B", "SW_1V8"}
    assert "R100" in dupes["VDD_A"].provenance
    assert "->VDD_C" in dupes["VDD_A"].provenance
    assert report["VDD_C"] == ["VDD_A", "VDD_B"]
    assert report["1V8_MAIN"] == ["SW_1V8"]


def test_bridge_unknown_value_assumed_and_budgeted():
    result = ParseNetsResult()
    result.power = [
        NetRecord(name="VDD_P", members=["R7.1", "TP9.1"]),
        NetRecord(name="VDD_Q", members=["R7.2", "U3.1"]),
    ]
    report = merge_power_bridges(result, {"R7": {"part_number": "R"}})
    assert [r.name for r in result.power] == ["VDD_P"]  # TP side wins
    assert result.warnings == [
        "bridge value unknown, assumed low-impedance: R7"]
    assert report == {"VDD_P": ["VDD_Q"]}


def test_bridge_nonzero_resistor_never_merges():
    result = ParseNetsResult()
    result.power = [
        NetRecord(name="VDD_M", members=["R9.1", "TP9.1"]),
        NetRecord(name="VDD_N", members=["R9.2", "U3.1"]),
    ]
    report = merge_power_bridges(
        result, {"R9": {"part_number": "R", "value": "10K"}})
    assert len(result.power) == 2 and report == {}


# ------------------------------------------------- B1.5 conflict rules
_CONFLICT_LIBRARY = {
    "U1": {"part_number": "SI5332AGM48"},
    "U2": {"part_number": "SJA1124"},
    "U3": {"part_number": "AG25F256"},
    "U5": {"part_number": "IMX93DQ"},
    "U8": {"part_number": "PCA9555"},
}


def _conflict_text() -> str:
    lines = ["Allegro Report", "C:/work/board.brd", "",
             "Net Name,Net Pins"]
    nets = [
        "SI5332_CLK_VDDA,U1.7 TP40.1",       # clock-gen strap -> Power
        "5V_SDA_PSW,U5.1 TP40.2",            # voltage+PSW -> Power
        "PCIE_CLK_OE1,U5.2 TP40.3",          # protocol -3 -> ambiguous
        "ENET1_REFCLK,U5.3 TP40.4",          # protocol -3 -> ambiguous
        "SI5332_CLK0_OUT,U1.8 TP40.5",       # clock-gen output -> Clock
        "SJA1124_CLKIN,U2.3 TP40.6",         # interface -> Others
        "DUT_CLK1_FPGA_AG25,U3.4 TP40.7",    # FPGA clock -> Clock
    ]
    lines += nets
    return "\n".join(lines) + "\n"


def test_conflict_resolution_library_mode():
    result = parse_testable_nets(_conflict_text(),
                                 library=_CONFLICT_LIBRARY)
    by_name = {r.name: r for bucket in
               (result.power, result.clock, result.others)
               for r in bucket}
    assert by_name["SI5332_CLK_VDDA"].net_type == "power"
    assert by_name["5V_SDA_PSW"].net_type == "power"
    assert by_name["SI5332_CLK0_OUT"].net_type == "clock_single"
    assert by_name["DUT_CLK1_FPGA_AG25"].net_type == "clock_single"
    # determined not-tested: protocol nets are labelled interface,
    # never mislabeled ambiguous (M2 Fix 1)
    for net in ("PCIE_CLK_OE1", "ENET1_REFCLK"):
        rec = by_name[net]
        assert rec in result.others
        assert rec.sub_class == "interface"
        assert rec.provenance.startswith("interface:")
    assert not any(r.sub_class == "ambiguous" for r in result.others)


def test_no_library_mode_conflict_path_untouched():
    result = parse_testable_nets(_conflict_text())
    others = {r.name: r for r in result.others}
    # M1 fallback unchanged (chip-model table, no ambiguous sub-class)
    assert others["SI5332_CLK_VDDA"].sub_class == "unclassified"
    assert all(r.sub_class == "unclassified"
               for r in result.others)


# ------------------------------------------------------ B5 overrides
def test_user_override_round_trip(tmp_path):
    result = parse_testable_nets(_conflict_text(),
                                 library=_CONFLICT_LIBRARY)
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"ENET1_REFCLK": "control_io"}),
                    encoding="utf-8")
    applied = apply_user_overrides(
        result, json.loads(path.read_text(encoding="utf-8")))
    assert applied == {"ENET1_REFCLK": "control_io"}
    assert any(r.name == "ENET1_REFCLK" for r in result.control_io)
    assert result.user_override == {"ENET1_REFCLK": "control_io"}
    payload = result_to_dict(result, library=_CONFLICT_LIBRARY)
    assert payload["user_override"] == {"ENET1_REFCLK": "control_io"}


def test_payload_fields_confidence_rank_test_selected():
    result = parse_testable_nets(_conflict_text(),
                                 library=_CONFLICT_LIBRARY)
    payload = result_to_dict(result, library=_CONFLICT_LIBRARY)
    entry = payload["nets"]["power"]["selected"][0]
    assert entry["confidence"] in ("high", "medium", "low")
    assert entry["rank"] == 0
    assert entry["test_selected"] is True
    assert payload["bridge_report"] == {}
    csv_text = result_to_csv(result, library=_CONFLICT_LIBRARY)
    assert csv_text.splitlines()[0].endswith(
        ",confidence,isolated,active_drivers")
