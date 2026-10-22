# -*- coding: utf-8 -*-
"""M3 GND-plane subtypes + input-rail recognition + control-conflict fix."""
from __future__ import annotations

from mtkgui.ict.netparse.model import NET_TYPE_POWER, ParseNetsResult, \
    NetRecord
from mtkgui.ict.netparse.priority import rank_result
from mtkgui.ict.netparse.rules import conflict_device_class, \
    gnd_sub_class, is_control_conflict_name, is_input_rail
from mtkgui.ict.netparse.export import RESULT_SCHEMA, result_to_dict

# ------------------------------------------------------------ GND subtype
def test_gnd_sub_class_pcb_default():
    assert gnd_sub_class("GND") == "pcb"
    assert gnd_sub_class("GND_DIN") == "pcb"
    assert gnd_sub_class("GND_USB3") == "pcb"
    assert gnd_sub_class("VSS") == "pcb"
    assert gnd_sub_class("GROUND") == "pcb"


def test_gnd_sub_class_chassis_shield():
    assert gnd_sub_class("GND_EARTH") == "chassis"
    assert gnd_sub_class("CHASSIS_GND") == "chassis"
    assert gnd_sub_class("GND_FRAME") == "chassis"
    assert gnd_sub_class("GND_SH_P5") == "shield"
    assert gnd_sub_class("SHIELD_GND") == "shield"
    assert gnd_sub_class("SGND") == "shield"


def test_gnd_ranking_pcb_first_then_chassis_then_shield():
    recs = [NetRecord(name=n, members=["TP1"], net_type="gnd_ref")
            for n in ("GND_EARTH", "GND_SH_P5", "GND", "GND_SH_P7",
                      "GND_DIN")]
    result = ParseNetsResult(gnd=list(recs))
    rank_result(result)
    assert [r.name for r in result.gnd] == [
        "GND", "GND_DIN", "GND_EARTH", "GND_SH_P5", "GND_SH_P7"]
    assert [r.priority["rank"] for r in result.gnd] == [0, 1, 2, 3, 4]
    assert {r.sub_class for r in result.gnd} == {
        "pcb", "chassis", "shield"}


# -------------------------------------------------------------- input rail
def test_is_input_rail_connector_plus_fuse():
    assert is_input_rail(["J45.1", "F1.1", "TP72.1"])


def test_is_input_rail_connector_plus_input_inductor():
    # M2: connector + FL input inductor
    assert is_input_rail(["J2.A8", "FL6.2", "U49.1"])


def test_is_input_rail_output_beads_not_evidence():
    # FB/L beads + plain connectors are output distribution (fix2)
    assert not is_input_rail(["J7.1", "L46.1", "L49.1", "U10.1"])
    assert not is_input_rail(["FB1.1", "FB7.1", "L13.1", "TP3.1"])


def test_is_input_rail_power_jack_and_rated_switch():
    # S2: P<n> PWR jack / SW<n> with an amperage rating
    lib = {"P1": {"part_number": "210-1", "description": "CON 2 PWR JACK"},
           "SW1": {"part_number": "312-2",
                   "description": "SW SPDT 5A@125VAC"}}
    assert is_input_rail(["P1.1", "SW1.1", "TP2.1"], lib)
    # tact / config switches are NOT power switches
    lib_tact = {"SW7": {"part_number": "312-3",
                        "description": "SW SPST PB MOM TACT 0.02A 15V"}}
    assert not is_input_rail(["SW7.1", "J52.1"], lib_tact)


def test_is_input_rail_usb_pd_current_limited_pwr_sw():
    # M1b: input-path power switch even WITHOUT a connector
    lib = {"U17": {"part_number": "312-81574",
                   "description": "IC USB PD TYPE C CURRENT LIMITED "
                                  "PWR SW 2.5-5.5V WLCSP12"}}
    assert is_input_rail(["D43.A", "U17.1"], lib)


def test_is_input_rail_output_side_chips_not_evidence():
    # LOAD SW / plain CURRENT LIMITED / TVS diodes are NOT input evidence
    lib = {"U132": {"part_number": "315-84100",
                    "description": "IC LOAD SWITCH 10A"},
           "U7": {"part_number": "315-81584",
                  "description": "IC SW CURRENT LIMITED FOR USB"},
           "D83": {"part_number": "480-79770",
                   "description": "DIODE TVS UNIDIR 5V 600W"}}
    assert not is_input_rail(["U132.1", "TP220.1"], lib)
    assert not is_input_rail(["U7.1", "J6.1"], lib)
    assert not is_input_rail(["D83.1", "J1.1"], lib)


def test_is_input_rail_usb_pd_phy_is_not_power():
    lib = {"U37": {"part_number": "315-81118",
                   "description": "IC USB PD PHY 1PORT 2.7-5.5V"}}
    assert not is_input_rail(["U37.1", "TP3.1"], lib)


def test_is_input_rail_plain_power_ic_not_enough():
    assert not is_input_rail(["U49.1", "C10.1", "R2.1"])


def test_input_rail_ranked_first():
    recs = [
        NetRecord(name="VDD_3V3", members=["U1.5", "C1.1"],
                  net_type=NET_TYPE_POWER, confidence="high"),
        NetRecord(name="VCC_12V0", members=["J2.A8", "FL6.2", "U49.1"],
                  net_type=NET_TYPE_POWER, confidence="medium"),
    ]
    result = ParseNetsResult(power=list(recs))
    rank_result(result)
    assert result.power[0].name == "VCC_12V0"
    assert result.power[0].input_rail is True
    assert result.power[1].input_rail is False


# --------------------------------------------------------- control conflict
def test_is_control_conflict_name():
    assert is_control_conflict_name("RCON_BUF_CTL_1V8_B")
    assert is_control_conflict_name("PWR_EN_N")
    assert not is_control_conflict_name("DC_5V_IN")
    assert not is_control_conflict_name("VDD_3V3")


def test_conflict_device_class():
    assert conflict_device_class("SN74LVC1G17", "single buffer") == "logic"
    assert conflict_device_class("TPS62823", "3A buck dcdc") == "power"
    assert conflict_device_class("0402", "resistor") is None


def test_power_input_rail_exported_v4():
    recs = [NetRecord(name="VCC_12V0", members=["J2.A8", "FL6.2"],
                      net_type=NET_TYPE_POWER, confidence="high")]
    result = ParseNetsResult(power=list(recs))
    payload = result_to_dict(result)
    assert payload["schema"] == RESULT_SCHEMA
    assert RESULT_SCHEMA.endswith(".v4")
    entry = payload["nets"]["power"]["nets"][0]
    assert entry["input_rail"] is True
    assert entry["note"] == ""
