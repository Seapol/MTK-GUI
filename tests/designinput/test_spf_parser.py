# -*- coding: utf-8 -*-
"""Native text-SPF parser + SPF/netlist cross-check tests."""
from __future__ import annotations

import pytest

from mtkgui.gui.designinput.spf_parser import (
    SpfParseError,
    cross_check_nets,
    parse_spf,
)

SPF_SAMPLE = """# Concept-HDL SPF export
[Document]
Revision: B
Designer: NXP

[Drawing]
FRDM-IMXRT700 CPU Board

[Component]
U1 ; MIMXRT798S
U2 ; PF1500
R1 ; 10K
J2 ; HDR-2X5

[Net]
NET_3V3 U1.5 U2.4 J2.1
GND U1.1 R1.2
CLK_24M U1.10
"""


def test_parses_all_sections():
    data = parse_spf(SPF_SAMPLE)
    assert data.drawing_title == "FRDM-IMXRT700 CPU Board"
    assert data.document_meta["revision"] == "B"
    assert ("U1", "MIMXRT798S") in data.components
    assert ("J2", "HDR-2X5") in data.components
    assert set(data.nets) == {"NET_3V3", "GND", "CLK_24M"}
    assert "U1.5" in data.nets["NET_3V3"]


def test_corrupt_file_raises():
    with pytest.raises(SpfParseError):
        parse_spf("random garbage, no sections")


def test_empty_file_raises():
    with pytest.raises(SpfParseError):
        parse_spf("")


def test_cross_check_reports_both_directions():
    spf_nets = {"NET_3V3": [], "SPF_ONLY": []}
    net_nets = {"NET_3V3": [], "NET_ONLY": []}
    warnings = cross_check_nets(spf_nets, net_nets)
    joined = "\n".join(warnings)
    assert "SPF_ONLY" in joined and "NET_ONLY" in joined
    assert "NET_3V3" not in joined
