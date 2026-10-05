# -*- coding: utf-8 -*-
"""Component classification / library building tests."""
from __future__ import annotations

import pytest

from mtkgui.gui.designinput.components import (
    CATEGORY_DCDC,
    CATEGORY_LDO,
    CATEGORY_MAIN_MCU,
    CATEGORY_OTHER,
    CATEGORY_PMIC,
    CATEGORY_TRANSCEIVER,
    build_library,
    categorize,
)


@pytest.mark.parametrize("part,expected", [
    ("MIMXRT798S", CATEGORY_MAIN_MCU),
    ("MMC56XX", CATEGORY_MAIN_MCU),
    ("PF1500", CATEGORY_PMIC),
    ("TPS65987", CATEGORY_PMIC),
    ("TPS62840", CATEGORY_DCDC),
    ("LTC3406", CATEGORY_DCDC),
    ("AP2112", CATEGORY_LDO),
    ("TJA1051", CATEGORY_TRANSCEIVER),
    ("LAN8720", CATEGORY_TRANSCEIVER),
    ("10K resistor junk", CATEGORY_OTHER),
    ("", CATEGORY_OTHER),
])
def test_categorize_matrix(part, expected):
    assert categorize(part, "U1") == expected


def test_unclassified_tracked():
    lib = build_library([("U9", "MYSTERY-123"), ("U1", "MIMXRT798S")])
    assert lib.unclassified == ["U9"]
    assert lib.category_of("U9") == CATEGORY_OTHER
    assert lib.category_of("U1") == CATEGORY_MAIN_MCU


def test_mains_and_regulators_views():
    lib = build_library([
        ("U1", "MIMXRT798S"),
        ("U2", "PF1500"),          # pmic
        ("U3", "TPS62840"),        # dcdc
        ("U4", "AP2112"),          # ldo
        ("U5", "TJA1051"),         # transceiver
    ])
    assert [r.refdes for r in lib.mains()] == ["U1"]
    assert [r.refdes for r in lib.regulators()] == ["U2", "U3", "U4"]


def test_by_refdes_unknown_returns_none():
    lib = build_library([("U1", "MIMXRT798S")])
    assert lib.by_refdes("NOPE") is None
