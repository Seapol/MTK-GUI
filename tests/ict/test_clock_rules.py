# -*- coding: utf-8 -*-
"""Anchored single-ended clock rules (no substring matching).

The JSONL fixture freezes the five-project victim list plus the
healthy system clocks, so a future rule change cannot silently
re-introduce the pin-multiplex / interface-clock false positives.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mtkgui.ict.netparse import (
    NET_TYPE_CLOCK_SINGLE,
    NET_TYPE_DIFF_PAIR,
    NET_TYPE_SIGNAL,
    NetlistData,
    classify_clock,
    classify_nets,
)

FIXTURE = Path(__file__).parent / "fixtures" / "clock_samples.jsonl"


def _samples() -> list[dict]:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_fixture_physical_types():
    """Every frozen sample classifies to its expected physical type."""
    samples = _samples()
    netlist = NetlistData(
        nets={sample["net"]: ["TP1.1"] for sample in samples})
    collection = classify_nets(netlist)
    for sample in samples:
        record = collection.by_name(sample["net"])
        assert record is not None
        assert record.net_type == sample["expected_net_type"], sample["net"]


def test_fixture_covers_victims_and_healthy_clocks():
    samples = {sample["net"]: sample["expected_net_type"]
               for sample in _samples()}
    # pin-multiplex / interface clocks -> signal
    assert samples["BB_GPIO1(SPDIF0_EXT_CLK)"] == NET_TYPE_SIGNAL
    assert samples["DUT_GPIO7_MAC2_RGMII_TXCLK"] == NET_TYPE_SIGNAL
    assert samples["ETH0_RXCLK"] == NET_TYPE_SIGNAL
    assert samples["CLK_RGMII_A_CLKOUT"] == NET_TYPE_SIGNAL
    assert samples["DUT_1588_CLKIN"] == NET_TYPE_SIGNAL
    # healthy system clocks stay clock_single
    assert samples["CLK_24M"] == NET_TYPE_CLOCK_SINGLE
    assert samples["OSC_125M"] == NET_TYPE_CLOCK_SINGLE
    assert samples["SUSCLK_32KHZ"] == NET_TYPE_CLOCK_SINGLE
    assert samples["OSC32K_XTAL"] == NET_TYPE_CLOCK_SINGLE
    # M1 Fix 1: interface-clock victims never classify as clock
    assert samples["I2C_CTRL_CLK"] == NET_TYPE_SIGNAL
    assert samples["USDHC_CLK"] == NET_TYPE_SIGNAL
    assert samples["DBGIF_TCK_SWCLK"] == NET_TYPE_SIGNAL
    # M1 Fix 2 A: SERDES rate labels never classify as clock
    assert samples["10G_1_REXT"] == NET_TYPE_SIGNAL
    assert samples["16G_REXT"] == NET_TYPE_SIGNAL
    # M1 Fix 2 B: CLKOUT / CLKIN are system clocks again
    assert samples["CLKOUT2"] == NET_TYPE_CLOCK_SINGLE
    assert samples["CLKOUT5"] == NET_TYPE_CLOCK_SINGLE
    assert samples["CLK_IN"] == NET_TYPE_CLOCK_SINGLE
    # M1 Fix 3: SPI / QSPI / audio / MLB / SIM interface clocks
    assert samples["BB_SPI1_CLK(ADC_IN3)"] == NET_TYPE_SIGNAL
    assert samples["QSPI0A_CLK"] == NET_TYPE_SIGNAL
    assert samples["QSPI0B_CLK"] == NET_TYPE_SIGNAL
    assert samples["MCLK_ESAI0"] == NET_TYPE_SIGNAL
    assert samples["BB_MLB_CLK"] == NET_TYPE_SIGNAL
    assert samples["BB_SIM_CLK"] == NET_TYPE_SIGNAL
    # audio MCLK policy pending owner decision -> still clock
    assert samples["MCLK_OUT0"] == NET_TYPE_CLOCK_SINGLE
    # M1 Fix 4 A: word-anchored tokens restore vendor-prefixed clocks
    assert samples["R_CLK_40M"] == NET_TYPE_CLOCK_SINGLE
    assert samples["R_CLK_OSC_125M"] == NET_TYPE_CLOCK_SINGLE
    assert samples["EXTAL"] == NET_TYPE_CLOCK_SINGLE
    assert samples["EXTAL_OPT"] == NET_TYPE_CLOCK_SINGLE
    assert samples["FT1_OSCI"] == NET_TYPE_CLOCK_SINGLE
    assert samples["FT1_OSCO"] == NET_TYPE_CLOCK_SINGLE
    assert samples["DUT_AUXCLKIN"] == NET_TYPE_CLOCK_SINGLE
    assert samples["DUT_AUXCLKOUT1"] == NET_TYPE_CLOCK_SINGLE
    # audio MASTER clocks are tested (owner decision 2026-10-22)
    assert samples["CODEC_SYS_MCLK"] == NET_TYPE_CLOCK_SINGLE
    # M1 Fix 4 B: PSI5 interface clocks stay excluded
    assert samples["PE2_11_PSI5_S_0_TXCLK"] == NET_TYPE_SIGNAL
    # M1 close-out FIX 1: ENET / MIPI / PCIe stay excluded
    assert samples["ENET1_REFCLK"] == NET_TYPE_SIGNAL
    assert samples["MIPI_CSI0_MCLK_OUT"] == NET_TYPE_SIGNAL
    assert samples["PCIE_CLK_OE1"] == NET_TYPE_SIGNAL
    assert samples["PCIE_OSC_PWR"] == NET_TYPE_SIGNAL
    # M1 close-out FIX 2: chip-model table (M2 placeholder)
    assert samples["SI5332_CLK_VDDA"] == NET_TYPE_SIGNAL
    assert samples["SJA1124_CLKIN"] == NET_TYPE_SIGNAL
    assert samples["TJA1230_VDDA_CLK_1"] == NET_TYPE_SIGNAL
    assert samples["DUT_CLK1_FPGA_AG25"] == NET_TYPE_SIGNAL
    # M1 close-out FIX 4: recorded, kept as clock
    assert samples["BB_MCLK_IN(MCLK_IN0)"] == NET_TYPE_CLOCK_SINGLE
    assert samples["FSS_CLKOUT"] == NET_TYPE_CLOCK_SINGLE
    # differential clocks are never single-ended
    assert samples["REFCLK_P"] == NET_TYPE_DIFF_PAIR
    assert samples["REFCLK_N"] == NET_TYPE_DIFF_PAIR


@pytest.mark.parametrize("name,expected", [
    ("CLK_24M", True),
    ("CLK", True),
    ("OSC", True),
    ("OSC_125M", True),
    ("XTAL_26M", True),
    ("MCLK", True),
    ("SCKI0", True),
    ("REFCLK", True),
    ("SUSCLK_32KHZ", True),
    ("CLKOUT2", True),
    ("CLKOUT5", True),
    ("CLKIN", True),
    ("CLK_IN", True),
    ("CLK_OUT", True),
    ("24M", True),
    ("32K", True),
    ("125MHZ", True),
    ("25MHZ_2", True),
    ("10.5M", True),
    ("SYS_CLK", True),
    ("SYS_XTAL", True),
    ("SYS_OSC", True),
    ("", False),
    # interface / pin-multiplex exclusion
    ("BB_GPIO1(SPDIF0_EXT_CLK)", False),
    ("SUSCLK_32KHZ(SCU_GPIO0_07)", False),
    ("DUT_GPIO7_MAC2_RGMII_TXCLK", False),
    ("DUT_GPIO13_TRACE_ETM_CLKOUT_MAC0_MII_COL", False),
    ("ETH0_RXCLK", False),
    ("MII_RGMII_RXCLK_RMII_REFCLK", False),
    ("CLK_RGMII_A_CLKOUT", False),
    ("DUT_1588_CLKIN", False),
    ("GPIO_CLK", False),
    # M1 Fix 1: I2C / SD / debug interface clocks
    ("I2C_CTRL_CLK", False),
    ("USDHC_CLK", False),
    ("SDHC1_CLK", False),
    ("EMMC_CLK", False),
    ("UFS_CLK", False),
    ("DBGIF_TCK_SWCLK", False),
    ("SWD_CLK", False),
    ("JTAG_TCK", False),
    # M1 Fix 2 A: SERDES rate labels + calibration resistor nets
    ("10G_1_REXT", False),
    ("10G_2_REXT", False),
    ("16G_REXT", False),
    ("24M_INDEX", False),
    # M1 Fix 3: SPI / QSPI / audio / MLB / SIM interface clocks
    # (anchored tokens; QSPI listed explicitly - "SPI" after "Q" is
    # not at a ^/_ boundary)
    ("BB_SPI1_CLK(ADC_IN3)", False),
    ("QSPI0A_CLK", False),
    ("QSPI0B_CLK", False),
    ("MCLK_ESAI0", False),
    ("BB_MLB_CLK", False),
    ("BB_SIM_CLK", False),
    ("AUDIO_SAI_CLK", False),
    ("I2S_SCLK", False),
    # M1 Fix 3: audio MCLK policy pending owner decision -> still clock
    ("MCLK_OUT0", True),
    # M1 Fix 4 A: word-anchored tokens (vendor prefixes no longer hide
    # clocks) + crystal variants (EXTAL / OSCI / OSCO) + AUXCLK +
    # audio master clocks (owner decision 2026-10-22)
    ("R_CLK_40M", True),
    ("R_CLK_OSC_125M", True),
    ("EXTAL", True),
    ("EXTAL_OPT", True),
    ("FT1_OSCI", True),
    ("FT1_OSCO", True),
    ("DUT_AUXCLKIN", True),
    ("DUT_AUXCLKOUT1", True),
    ("CODEC_SYS_MCLK", True),
    ("AUDIO_MCLK", True),
    ("CLK_40M", True),
    # M1 Fix 4 B: PSI5 automotive sensor interface clocks
    ("PE2_11_PSI5_S_0_TXCLK", False),
    ("PSI5_CLK", False),
    # M1 close-out FIX 1: ENET / MIPI / PCIe interface clocks + straps
    ("ENET1_REFCLK", False),
    ("MIPI_CSI0_MCLK_OUT", False),
    ("PCIE_CLK_OE1", False),
    ("PCIE_OSC_PWR", False),
    # M1 close-out FIX 2: chip-model exclusion table (M2 placeholder)
    ("SI5332_CLK_VDDA", False),
    ("SJA1124_CLKIN", False),
    ("TJA1230_VDDA_CLK_1", False),
    ("DUT_CLK1_FPGA_AG25", False),
    # M1 close-out FIX 4: recorded, kept as se_clock
    ("BB_MCLK_IN(MCLK_IN0)", True),
    ("FSS_CLKOUT", True),
    # M1 tail fix: crystal IO suffixes allow an alphabetic tail
    ("XTALI", True),
    ("XTALO", True),
    ("RTC_XTALI", True),
    ("RTC_XTALO", True),
    # CLK-family keeps numeric-tail anchoring (no alpha-tail creep)
    ("CLKOUTRUN", False),
    ("MSCLK", False),
    # differential-clock exclusion
    ("REFCLK_P", False),
    ("REFCLK_N", False),
    ("REFCLK_P0", False),
    ("REFCLK_N0", False),
    ("CLK_PLUS", False),
    ("CLK_MINUS", False),
    # substring-only matches never win
    ("NOT_A_CLOCK_LIKE_NAME", False),
    ("TCLK", False),
])
def test_classify_clock_token_rules(name, expected):
    assert classify_clock(name) is expected


def test_classification_provenance():
    netlist = NetlistData(nets={
        "CLK_24M": ["TP1.1"],
        "SIG_A": ["TP2.1"],
        "GND": ["TP3.1"],
        "REFCLK_P": ["TP4.1"],
        "REFCLK_N": ["TP5.1"],
    })
    collection = classify_nets(netlist)
    assert collection.by_name("CLK_24M").provenance == "rule:se_clock"
    assert collection.by_name("SIG_A").provenance == "physical:signal"
    assert collection.by_name("GND").provenance == "rule:gnd_ref"
    assert collection.by_name("REFCLK_P").provenance == "rule:diff_pair"
