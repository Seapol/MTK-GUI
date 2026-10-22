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


def test_is_input_rail_connector_plus_bead():
    assert is_input_rail(["J2.A8", "FL6.2", "U49.1"])


def test_is_input_rail_diode_plus_inductor():
    assert is_input_rail(["D42.A", "L25.2", "U45.5"])


def test_is_input_rail_diode_plus_ic_library_role():
    lib = {"D43": {"part_number": "SMAJ5.0A",
                   "description": "TVS input protection"}}
    assert is_input_rail(["D43.A", "U17.1"], lib)
    # no library / no input-protection role -> not evidence-based
    assert not is_input_rail(["D43.A", "U17.1"])


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
