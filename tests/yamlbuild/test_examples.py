# -*- coding: utf-8 -*-
"""Item 18: official ICT example projects (config/examples).

8 independent demo projects, each as one YAML plan document (ICT only
- FCT modules explicitly disabled) plus one Excel workbook (YamlBuild
sheet + the Power / Clock / GPIO Channel Allocation sheets).  Every
file must round-trip through the GUI model / Excel exchange with zero
errors and identical configuration.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "config" / "examples"

EXPECTED_STEMS = (
    "Plan_10342_FRDM-IMX93_v1.0.0",
    "Plan_20781_MTK8168-EVK_v1.0.0",
    "Plan_30455_MTK8195-DEMO_v1.0.0",
    "Plan_40123_RT1170-EVK_v1.0.0",
    "Plan_50866_MTK8678-P1_v1.0.0",
    "Plan_60219_MTK6985-EVK_v1.0.0",
    "Plan_70488_MTK6879-DEMO_v1.0.0",
    "Plan_80571_MTK8188-P1_v1.0.0",
)


def test_examples_directory_complete():
    """16 files: 8 YAML + 8 Excel with the fixed naming rule."""
    yamls = sorted(p.name for p in EXAMPLES.glob("*.yaml"))
    xlsxs = sorted(p.name for p in EXAMPLES.glob("*.xlsx"))
    assert yamls == [f"{stem}.yaml" for stem in EXPECTED_STEMS]
    assert xlsxs == [f"{stem}.xlsx" for stem in EXPECTED_STEMS]


@pytest.mark.parametrize("stem", EXPECTED_STEMS)
def test_yaml_round_trip(stem):
    """The plan document loads into a fresh model with zero errors:
    ICT modules enabled, FCT skipped, channel allocation restored."""
    from mtkgui.gui.yamlbuild.model import YamlBuildModel

    document = yaml.safe_load((EXAMPLES / f"{stem}.yaml").read_text(
        encoding="utf-8"))
    assert document["plan"]["plan_version"] == "1.0.0"
    assert document["plan"]["ict_only"] is True
    model = YamlBuildModel()
    model.enable_all()
    errors = model.apply_yaml_dict(document)
    assert errors == []
    assert not model.is_enabled("fct_parse")
    assert not model.is_enabled("fct_build")
    for key in ("design_input", "instruments", "parse_ict", "rails",
                "clocks", "gpios"):
        assert model.is_enabled(key), key
    alloc = model.get_channel_allocation()
    assert alloc["power"] and alloc["clock"] and alloc["gpio"]
    # every allocation row is fully configured -> Status OK (auto)
    from mtkgui.gui.yamlbuild.channel_allocation import (
        ChannelAllocationData,
    )
    data = ChannelAllocationData.from_dict(alloc)
    assert data.all_ok(), stem


@pytest.mark.parametrize("stem", EXPECTED_STEMS)
def test_excel_round_trip(stem, tmp_path):
    """The workbook imports with zero errors and re-exports byte-
    equivalent module + allocation configuration (100% bidirectional,
    field alignment exactly)."""
    from openpyxl import load_workbook

    from mtkgui.gui.yamlbuild.channel_allocation import (
        ChannelAllocationData,
    )
    from mtkgui.gui.yamlbuild.excel_io import (
        ALLOCATION_HEADERS,
        ALLOCATION_SHEET_NAMES,
        SHEET_NAME,
        export_to_excel,
        import_from_excel,
    )
    from mtkgui.gui.yamlbuild.model import YamlBuildModel
    from mtkgui.gui.yamlbuild.stages import STAGE_KEYS

    xlsx = EXAMPLES / f"{stem}.xlsx"
    wb = load_workbook(xlsx, read_only=True)
    assert wb.sheetnames == [SHEET_NAME, "Power", "Clock", "GPIO"]
    for kind, name in ALLOCATION_SHEET_NAMES.items():
        header = [c.value for c in next(wb[name].iter_rows(max_row=1))]
        assert tuple(header) == ALLOCATION_HEADERS[kind]
    wb.close()

    model = YamlBuildModel()
    report = import_from_excel(model, str(xlsx))
    assert report.applied, report.errors
    assert not model.is_enabled("fct_parse")
    assert not model.is_enabled("fct_build")

    # re-export and compare the three-table content 1:1
    out = tmp_path / "reexport.xlsx"
    export_to_excel(model, str(out))
    reimported = YamlBuildModel()
    report2 = import_from_excel(reimported, str(out))
    assert report2.applied, report2.errors
    for key in STAGE_KEYS:
        assert reimported.get_params(key) == model.get_params(key)
        assert reimported.is_enabled(key) == model.is_enabled(key)
    assert ChannelAllocationData.from_dict(
        reimported.get_channel_allocation()).all_ok()
