# -*- coding: utf-8 -*-
"""M2 Fix 1/2: ambiguous semantics + protocol-IO removal.

``ambiguous`` is reserved for nets that genuinely cannot be decided
(>=2 class features, no protocol/mux evidence, no class reaching the
threshold).  Protocol nets and reused/muxed IO are DETERMINED
not-tested (``interface`` / ``muxed``), and M1-excluded nets are never
re-scored by the conflict path.
"""
from __future__ import annotations

from mtkgui.ict.netparse import parse_testable_nets

#: main chip + one muxed clock candidate + one protocol net
_TEXT = """*SIGNAL* CLK_EN
U9.1 TP1.1
*SIGNAL* CLK_MUX0
U9.2 TP2.1
*SIGNAL* PCIE_CLK_OE1
U9.3 TP3.1
*SIGNAL* DDR0_CS0
U9.4 TP4.1
*SIGNAL* MIPI_CSI0_RST_B
U9.5 TP5.1
*SIGNAL* EMMC_RST_B
U9.6 TP6.1
*SIGNAL* PCIE_RST_B
U9.7 TP7.1
*SIGNAL* SDA_RST_BUFF
U9.8 TP8.1
*SIGNAL* SPI0_CS
U9.9 TP9.1
*SIGNAL* ETH0_RST
U9.10 TP10.1
*SIGNAL* SDIO_EN
U9.11 TP11.1
*SIGNAL* WIFI_EN0
U9.12 TP12.1
"""

_LIBRARY = {"U9": {"part_number": "IMX93DQ"}}


def _parse():
    return parse_testable_nets(_TEXT, library=_LIBRARY)


def test_ambiguous_only_for_genuine_conflict():
    result = _parse()
    others = {r.name: r for r in result.others}
    rec = others["CLK_EN"]
    assert rec.sub_class == "ambiguous"
    assert rec.meta["conflict_scores"]  # the competing scores are kept


def test_protocol_nets_are_interface_not_ambiguous():
    result = _parse()
    others = {r.name: r for r in result.others}
    for net, token in (("PCIE_CLK_OE1", "PCIE"),
                       ("MIPI_CSI0_RST_B", "MIPI"),
                       ("EMMC_RST_B", "EMMC"), ("SDA_RST_BUFF", "SDA"),
                       ("ETH0_RST", "ETH")):
        assert others[net].sub_class == "interface", net
        assert others[net].provenance == f"interface:{token}"
        assert others[net].meta is None     # never re-scored


def test_muxed_candidate_leaves_clock_class():
    result = _parse()
    others = {r.name: r for r in result.others}
    assert others["CLK_MUX0"].sub_class == "muxed"
    assert not any(r.name == "CLK_MUX0" for r in result.clock)


def test_protocol_names_never_in_control_io():
    result = _parse()
    ctrl = {r.name for r in result.control_io}
    for net in ("SPI0_CS", "ETH0_RST", "SDIO_EN", "MIPI_CSI0_RST_B",
                "EMMC_RST_B", "PCIE_RST_B", "SDA_RST_BUFF"):
        assert net not in ctrl
    # owner-confirmed memory chip-select stays control IO
    assert "DDR0_CS0" in ctrl
    assert "WIFI_EN0" in ctrl


def test_labeling_is_library_mode_only():
    result = parse_testable_nets(_TEXT)
    assert result.others
    assert all(r.sub_class == "unclassified" for r in result.others)
