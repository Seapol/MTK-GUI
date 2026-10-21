# -*- coding: utf-8 -*-
"""M2 PART A downstream fixes: DNP, PDF-only, core_id, budget, vendor."""
from __future__ import annotations

from mtkgui.gui.designinput.bom import parse_bom
from mtkgui.gui.designinput.components import (
    CATEGORY_DCDC,
    CATEGORY_MAIN_MCU,
    CATEGORY_OTHER,
    CATEGORY_PMIC,
    ComponentLibrary,
    ComponentRecord,
    build_library,
    merge_bom,
    pdf_only_refdes,
)
from mtkgui.gui.designinput.model import DesignDataModel, WARNING_BUDGET, \
    collapse_warnings
from mtkgui.gui.designinput.power_tree_draft import derive_candidate_tree
from mtkgui.ict.netparse import classify_nets, parse_netlist_auto
from mtkgui.ict.netparse.model import NetCollection, NetRecord


# ----------------------------------------------------------------- A1
def _collection(nets: dict[str, list[str]]) -> NetCollection:
    col = NetCollection()
    for name, members in nets.items():
        col.nets.append(NetRecord(name=name, members=list(members),
                                  net_type="power" if "V" in name
                                  else "signal"))
    return col


def test_dnp_regulator_excluded_from_tree():
    lib = ComponentLibrary(records=[
        ComponentRecord(refdes="U1", part_number="TPS62840",
                        dev_category=CATEGORY_DCDC, dnp=True),
        ComponentRecord(refdes="U2", part_number="PF1500",
                        dev_category=CATEGORY_PMIC),
    ])
    assert lib.regulators() == [lib.records[1]]
    assert [r.refdes for r in lib.dnp_regulators()] == ["U1"]


def test_dnp_only_rail_warns_once():
    lib = ComponentLibrary(records=[
        ComponentRecord(refdes="U9", part_number="TPS62840",
                        dev_category=CATEGORY_DCDC, dnp=True),
    ])
    col = _collection({"VDD_CORE": ["U9.OUT", "U9.IN"]})
    tree = derive_candidate_tree(lib, col)
    assert sum("served by DNP part only" in w
               for w in tree.warnings) == 1
    assert tree.by_name("VDD_CORE") is None


def test_dnp_passive_not_main():
    lib = ComponentLibrary(records=[
        ComponentRecord(refdes="U1", part_number="MIMXRT798S",
                        dev_category=CATEGORY_MAIN_MCU, dnp=True),
        ComponentRecord(refdes="U2", part_number="MIMXRT798S",
                        dev_category=CATEGORY_MAIN_MCU),
    ])
    assert [r.refdes for r in lib.mains()] == ["U2"]


# ----------------------------------------------------------------- A2
def test_pdf_only_refdes_drop_list_and_warning():
    bom_records = [type("R", (), {"refdes": "U1"})()]
    dropped, warning = pdf_only_refdes(
        [("U1", "A"), ("U7", ""), ("U8", "")], bom_records)
    assert dropped == ["U7", "U8"]
    assert warning == ("2 PDF-only RefDes dropped (not present in "
                       "BOM): U7, U8 ...")
    assert pdf_only_refdes([("U1", "A")], bom_records) == ([], "")


def test_pdf_only_rail_not_auto_selected():
    lib = ComponentLibrary()
    col = _collection({"VDD_AUX": ["U7.1"]})
    tree = derive_candidate_tree(lib, col, pdf_only={"U7"})
    node = tree.by_name("VDD_AUX")
    assert node is not None and node.pdf_only
    assert any("PDF-only" in w for w in tree.warnings)


# ----------------------------------------------------------------- A3
def test_core_id_suggestion_dedup_sort_cap():
    model = DesignDataModel()
    model.component_library = build_library([])
    model.component_library.records = [
        ComponentRecord(refdes="U5", part_number="JUNK-1",
                        dev_category=CATEGORY_MAIN_MCU),
        ComponentRecord(refdes="U6", part_number="JUNK-2",
                        dev_category=CATEGORY_MAIN_MCU),
        ComponentRecord(refdes="U1", part_number="IMX93_GENERIC",
                        dev_category=CATEGORY_MAIN_MCU),
        ComponentRecord(refdes="U2", part_number="IMX93_GENERIC",
                        dev_category=CATEGORY_MAIN_MCU),
        ComponentRecord(refdes="U3", part_number="GKI_PAD_9",
                        dev_category=CATEGORY_MAIN_MCU),
        ComponentRecord(refdes="U4", part_number="GKI_PAD_9",
                        dev_category=CATEGORY_MAIN_MCU),
        ComponentRecord(refdes="U9", part_number="SEMPER_FLASH_X",
                        dev_category=CATEGORY_MAIN_MCU),
    ]
    suggestion = model.core_id_suggestion()
    parts = suggestion.split("+")
    assert len(parts) == 3
    assert parts[0].startswith("IMX93")
    assert len(set(parts)) == 3
    assert not any("SEMPER" in p for p in parts)


# ----------------------------------------------------------------- A4
def test_passive_warnings_one_line_per_family():
    model = DesignDataModel()
    model.component_library.records = [
        ComponentRecord(refdes=f"R{i}", dev_category=CATEGORY_OTHER)
        for i in range(214)]
    model.component_library.records += [
        ComponentRecord(refdes=f"C{i}", dev_category=CATEGORY_OTHER)
        for i in range(98)]
    warnings = model._unclassified_warnings()
    assert "unrecognized R* parts: 214" in warnings
    assert "unrecognized C* parts: 98" in warnings
    assert len(warnings) == 2


def test_warning_budget_collapse():
    warnings = [f"no OUT pin found U{i}" for i in range(300)]
    collapsed = collapse_warnings(warnings)
    assert len(collapsed) <= WARNING_BUDGET
    assert any("suppressed (budget)" in w for w in collapsed)
    assert collapse_warnings(["a", "b"]) == ["a", "b"]


# ----------------------------------------------------------------- A5
def test_bom_vendor_column(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(
        "Manufacturer,Part Number,Reference Designator\n"
        "NXP,MIMXRT798S,U1\n", encoding="utf-8")
    data = parse_bom(str(path))
    assert data.records[0].vendor == "NXP"
    assert data.records[0].part_number == "MIMXRT798S"


def test_vendor_merged_and_persisted():
    lib = build_library([("U1", "OLD-1")])
    bom = type("B", (), {"records": [
        type("E", (), {"refdes": "U1", "part_number": "NEW-2",
                       "description": "", "dnp": False,
                       "vendor": "NXP", "value": "0R"})()]})()
    merge_bom(lib, bom)
    assert lib.records[0].vendor == "NXP"
    assert lib.records[0].value == "0R"
    model = DesignDataModel()
    model.component_library = lib
    payload = model.to_dict(official=False)
    assert payload["component_library"][0]["vendor"] == "NXP"


# ----------------------------------------------------------------- A5
def test_bom_vendor_and_value_columns_separated(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(
        "Manufacturer,Part Number,Value,Reference Designator\n"
        "NXP,PCA9555,0R,U1\n", encoding="utf-8")
    data = parse_bom(str(path))
    record = data.records[0]
    assert record.vendor == "NXP"
    assert record.part_number == "PCA9555"
    assert record.value == "0R"


# ------------------------------------------- library-mode smoke (B2)
def test_library_mode_classifies_si5332_strap_as_power():
    netlist = parse_netlist_auto(
        "Net Name,Net Pins\nSI5332_CLK_VDDA,U1.1\n")
    collection = classify_nets(
        netlist, library={"U1": "SI5332AGM48"})
    assert collection.nets[0].net_type == "power"
    assert collection.nets[0].provenance == "device_role:clock_gen_power"
    # no-library: chip-model fallback keeps signal
    fallback = classify_nets(parse_netlist_auto(
        "Net Name,Net Pins\nSI5332_CLK_VDDA,U1.1\n"))
    assert fallback.nets[0].net_type == "signal"
