# -*- coding: utf-8 -*-
"""Unit tests for the Design Input import parsers (acceptance
3.1.1): schematic filename Core ID, project-name extraction, netlist
parsing with TP tolerance, and the model backfill chain."""

from __future__ import annotations

import yaml
import pytest

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.parser import (
    core_id_from_filename,
    extract_project_name,
    parse_netlist,
    read_text_any_encoding,
)
from tests.yamlbuild.conftest import fill_required

NETLIST_WITH_TP = """\
*PADS-LIBRARY*
*PART*
U1 74HC595
*NET*
*SIGNAL* VDD_3V3
 U1.14 C10.1 TP3
*SIGNAL* CLK_RTC
 U1.1 R5.2 TP7
*SIGNAL* LED_STATUS
 R5.1 D2.2
"""

NETLIST_NO_TP = """\
NET VBAT
 C1.1 C2.1 U2.3
NET SW_CLK
 U2.1 R9.2
"""


# ---------------------------------------------------------------------------
# schematic filename -> Core ID
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("spf-92722_revB.pdf", "92722"),
        ("spf-1234567_revA2.PDF", "1234567"),
        ("/dir/sub/spf-92722_revB.pdf", "92722"),
        ("schematic_92722.pdf", "92722"),
        ("92722_revB.pdf", "92722"),
    ],
)
def test_core_id_from_filename(name, expected):
    """Standard names yield the first standalone 4..10 digit group."""
    assert core_id_from_filename(name) == expected


@pytest.mark.parametrize("name", ["spf-_revB.pdf", "layout_only.pdf",
                                  "readme.txt"])
def test_core_id_from_filename_no_digits(name):
    """Names without a digit group yield an empty Core ID."""
    assert core_id_from_filename(name) == ""


def test_extract_project_name_labelled():
    """An explicit 'Project:' title-block entry wins."""
    text = "SHEET 1 OF 5\nProject: FRDM-IMXRT700 REV B\ndate 2026"
    assert extract_project_name(text) == "FRDM-IMXRT700 REV B"


def test_extract_project_name_falls_back_to_title_line():
    """Without a label the first plausible line is the title."""
    assert extract_project_name("MTK Demo Board\n1\n2") == \
        "MTK Demo Board"
    assert extract_project_name("") == ""


# ---------------------------------------------------------------------------
# netlist parsing
# ---------------------------------------------------------------------------


def test_parse_netlist_with_tp():
    """Nets, member pins and TP members are extracted; no missing
    TP entries when every net carries one."""
    data = parse_netlist(NETLIST_WITH_TP)
    assert list(data.nets) == ["VDD_3V3", "CLK_RTC", "LED_STATUS"]
    assert data.nets["VDD_3V3"] == ["U1.14", "C10.1", "TP3"]
    assert data.tp_of("CLK_RTC") == "TP7"
    assert data.missing_tp == ["LED_STATUS"]


def test_parse_netlist_without_tp_flags_missing():
    """Nets without TP members are reported for manual resolution."""
    data = parse_netlist(NETLIST_NO_TP)
    assert set(data.nets) == {"VBAT", "SW_CLK"}
    assert data.missing_tp == ["VBAT", "SW_CLK"]


def test_netlist_decoding_tolerant(tmp_path):
    """GBK / latin-1 netlists decode without mojibake or errors."""
    path = tmp_path / "net.net"
    path.write_bytes("NET 网络1\n U1.1 TP1\n".encode("gbk"))
    text = read_text_any_encoding(str(path))
    data = parse_netlist(text)
    assert data.nets["网络1"] == ["U1.1", "TP1"]


# ---------------------------------------------------------------------------
# backfill into the model -> effective YAML (global design data)
# ---------------------------------------------------------------------------


def test_import_backfills_global_design_data():
    """Import results land in the model's shared design_data section
    (feeds every downstream module) and in the module params."""
    model = make_filled_model()
    schematic = {"file": "spf-92722_revB.pdf", "core_id": "92722",
                 "project_name": "MTK Demo Board"}
    model.set_params("design_input", {
        **model.get_params("design_input"),
        "core_id": "92722", "project_name": "MTK Demo Board",
        "schematic_file": "spf-92722_revB.pdf",
    })
    model.set_params("parse_ict", {
        **model.get_params("parse_ict"),
        "netlist_file": "design.net",
        "tp_resolutions": "VBAT=C1.1\nSW_CLK=skip",
    })
    model.imported["schematic"] = schematic
    model.imported["netlist"] = {
        "file": "design.net", "net_count": 2,
        "nets": {"VBAT": ["C1.1", "U2.3"], "SW_CLK": ["U2.1", "R9.2"]},
        "missing_tp": ["VBAT", "SW_CLK"],
    }
    model.imported["tp_resolutions"] = {"VBAT": "C1.1", "SW_CLK": "skip"}

    data = yaml.safe_load(model.to_effective_yaml())
    design_data = data["yaml_build"]["design_data"]
    assert design_data["schematic"]["core_id"] == "92722"
    assert design_data["schematic"]["project_name"] == "MTK Demo Board"
    assert design_data["netlist"]["net_count"] == 2
    assert design_data["netlist"]["nets"]["VBAT"] == ["C1.1", "U2.3"]
    assert design_data["tp_resolutions"] == {"VBAT": "C1.1",
                                             "SW_CLK": "skip"}
    modules = data["yaml_build"]["modules"]
    assert modules["parse_ict"]["tp_resolutions"] == [
        "VBAT=C1.1", "SW_CLK=skip"]


def test_imported_data_survives_persistence():
    """The imported design data round-trips through the state store
    (restart / project switch safe, traceable)."""
    model = make_filled_model()
    model.imported["schematic"] = {"file": "spf-92722_revB.pdf",
                                   "core_id": "92722"}
    model.imported["netlist"] = {"file": "design.net", "net_count": 1,
                                 "nets": {"VBAT": ["C1.1"]},
                                 "missing_tp": ["VBAT"]}
    model.imported["tp_resolutions"] = {"VBAT": "skip"}
    other = make_filled_model()
    other.apply_state(model.to_dict())
    assert other.imported["schematic"]["core_id"] == "92722"
    assert other.imported["netlist"]["nets"] == {"VBAT": ["C1.1"]}
    assert other.imported["tp_resolutions"] == {"VBAT": "skip"}


def make_filled_model(enabled=True) -> YamlBuildModel:
    """Local model builder with all required fields filled."""
    model = YamlBuildModel()
    if enabled:
        model.enable_all()
    fill_required(model)
    return model
