# -*- coding: utf-8 -*-
"""Net classification kernel (spec B1-01-01 item 1).

Classification rules (applied in this order):

1. ``gnd_ref``     - GND / AGND / DGND / PGND reference grounds; they
   participate in the measurement loop and are NEVER auto-skipped
   (boundary rule 5);
2. ``diff_pair``   - ``*_P`` / ``*_N`` siblings, excluded from the
   single-ended clock set;
3. ``power``       - supply nets (VDD / VCC / nVn rails / VPRE ...);
4. ``clock_single``- single-ended clock nets (anchored token rules,
   see :func:`classify_clock`; no substring matching);
5. ``signal``      - everything else.
"""
from __future__ import annotations

import re

from .model import (NET_TYPE_CLOCK_SINGLE, NET_TYPE_DIFF_PAIR,
                    NET_TYPE_GND_REF, NET_TYPE_POWER, NET_TYPE_SIGNAL,
                    NetCollection, NetlistData, NetRecord)

_GND_RE = re.compile(
    r"^(GND|AGND|DGND|PGND)([_\W].*)?$", re.IGNORECASE)
_POWER_RE = re.compile(
    r"^(?!.+INTB)(?:"
    r"V(DD|CC|IN|OUT|PRE|SYS|BAT|BUS|AUX|CORE|IO|A|D|DDL|DQL)([0-9_].*)?"
    r"|[0-9]+([.][0-9]+)?V([0-9A-Z_]*)?"
    r"|P[35][V_][0-9A-Z_]*"
    r"|(DCDC|DC)_([0-9]+([.][0-9]+)?V)([0-9A-Z_]*)?"
    r"|[0-9A-Z_]*V(OUT|REF|SW|PWR|FB)[0-9A-Z_]*"
    r"|[0-9A-Z_]+_(1V0|1V2|1V5|1V8|2V5|3V3|5V|12V|24V)([0-9A-Z_]*)?"
    r")$", re.IGNORECASE)
#: anchored system-clock tokens - M1 Fix 4 A: WORD-anchored (start of
#: the mux-stripped name OR after ``_``) so vendor prefixes
#: (``R_`` / ``DUT_`` / ``BB_``) no longer hide real clocks; longer
#: tokens first (AUXCLKIN before CLKIN before CLK, OSCI before OSC,
#: EXTAL next to XTAL).  EXTAL / OSCI / OSCO are crystal-name variants;
#: audio MASTER clocks (CODEC_SYS_MCLK / MCLK_OUT0) are ICT clock test
#: objects (owner decision 2026-10-22) - audio INTERFACE clocks
#: (SAI / ESAI / I2S) stay excluded via the rule-4 exclusion below.
_CLOCK_PREFIX_RE = re.compile(
    r"(^|_)(CLKOUT|CLKIN|CLK_OUT|CLK_IN|AUXCLKIN|AUXCLKOUT|AUXCLK|"
    r"CLK|OSCI|OSCO|OSC|XTAL|EXTAL|MCLK|SCKI|REFCLK|SUSCLK)"
    r"([0-9_].*)?$", re.IGNORECASE)
#: anchored clock token at the END of the mux-stripped net name
_CLOCK_SUFFIX_RE = re.compile(
    r"(_CLK|_XTAL|_OSC)([0-9_]*)$", re.IGNORECASE)
#: frequency form: 24M / 32K / 25MHZ / 25MHZ_2 ... (the ``HZ`` part is
#: optional; the trailing part only allows a bus index - M1 Fix 2 A:
#: ``10G_1_REXT`` / ``16G_REXT`` are SERDES rate labels + calibration
#: resistor nets, NOT "10 GHz" clocks)
_CLOCK_FREQ_RE = re.compile(
    r"^[0-9]+([.][0-9]+)?(M|K|G)(H?Z)?(_[0-9]+)?$", re.IGNORECASE)
#: interface / pin-multiplex clocks are NOT ICT clock targets (M1 Fix 1:
#: I2C / SD / eMMC / UFS / debug-SWD / JTAG interface clocks added to
#: the 5-project spot-check set)
_CLOCK_EXCLUDE_RE = re.compile(
    r"(RGMII|MII|RMII|ETH|SPDIF|TRACE|1588|SERDES|PHY|LINK|GPIO|"
    r"I2C|SD|SDHC|USDHC|MMC|EMMC|UFS|DBGIF|TCK|SWCLK|SWD|JTAG)",
    re.IGNORECASE)
#: M1 Fix 3: SPI / QSPI / audio (ESAI / SAI / I2S) / MLB / SIM
#: interface clocks, as ANCHORED tokens (no bare substrings - same
#: lesson as Clock).  ``QSPI`` is listed explicitly because ``SPI``
#: preceded by ``Q`` is not at a ``^`` / ``_`` boundary.
_CLOCK_IFACE_ANCHOR_RE = re.compile(
    r"(^|_)(SPI|QSPI|ESAI|SAI|I2S|MLB|SIM)([0-9A-Z_]*)?", re.IGNORECASE)
#: M1 Fix 4 B: PSI5 automotive sensor interface clocks
_CLOCK_PSI5_RE = re.compile(
    r"(^|_)(PSI5)([0-9A-Z_]*)?", re.IGNORECASE)
#: M1 close-out FIX 1: ENET / MIPI / PCIe interface clocks and
#: clock-enable / oscillator-power straps
_CLOCK_IFACE2_RE = re.compile(
    r"(^|_)(ENET|MIPI|PCIE)([0-9A-Z_]*)?", re.IGNORECASE)
#: M1 close-out FIX 2: chip-model exclusion table (M2 PLACEHOLDER -
#: replaced by the M2 BOM device knowledge base).  These are
#: chip-supply / power-strap nets of clock chips, not clocks.
_CHIP_MODEL_RE = re.compile(
    r"(^|_)(SI5332|SJA1124|TJA1230|FPGA)([0-9A-Z_]*)?", re.IGNORECASE)
#: parenthesized mux marker: ``SUSCLK_32KHZ(SCU_GPIO0_07)``
_MUX_SUFFIX_RE = re.compile(r"\([^)]*\)")
#: M1 tail fix: crystal-family tokens allow an ALPHABETIC tail too
#: (``XTALI`` / ``XTALO`` / ``RTC_XTALI`` / ``RTC_XTALO`` are crystal
#: IO pins).  The CLK / MCLK / REFCLK / SUSCLK / AUXCLK / SCKI tokens
#: keep their ``[0-9_]``-only tail so ``CLKOUTRUN``-style names stay
#: excluded.  Checked BEFORE _CLOCK_PREFIX_RE (chip-model and
#: interface exclusions still run first).
_CRYSTAL_TOKEN_RE = re.compile(
    r"(^|_)(OSCI|OSCO|OSC|XTAL|EXTAL)([0-9A-Z_]*)?$", re.IGNORECASE)
#: differential-clock markers: ``REFCLK_P`` / ``REFCLK_N``
_DIFF_CLOCK_RE = re.compile(
    r"(_P|_N)([0-9]*)$|_(PLUS|MINUS)$", re.IGNORECASE)
_PIN_TOKEN_RE = re.compile(r"^[\w\.\-\[\]/#]+$")


def classify_clock(name: str) -> bool:
    """True when *name* is a single-ended ICT clock net.

    Anchored token rules only - no substring matching.  The
    parenthesized mux suffix is stripped before matching the clock
    tokens, but the interface / pin-multiplex exclusion inspects the
    ORIGINAL name (so ``SUSCLK_32KHZ(SCU_GPIO0_07)`` falls to signal).
    Differential clock names (``REFCLK_P`` / ``REFCLK_N``) are not
    single-ended clocks.
    """
    if not name:
        return False
    if _CLOCK_EXCLUDE_RE.search(name):
        return False
    if _CLOCK_IFACE_ANCHOR_RE.search(name):
        return False
    if _CLOCK_PSI5_RE.search(name):
        return False
    # chip-model table runs BEFORE the token match (M2 placeholder)
    if _CHIP_MODEL_RE.search(name):
        return False
    if _CLOCK_IFACE2_RE.search(name):
        return False
    if _DIFF_CLOCK_RE.search(name):
        return False
    base = _MUX_SUFFIX_RE.sub("", name).strip()
    if not base:
        return False
    return bool(_CRYSTAL_TOKEN_RE.search(base)
                or _CLOCK_PREFIX_RE.search(base)
                or _CLOCK_SUFFIX_RE.search(base)
                or _CLOCK_FREQ_RE.match(base))


def classify_nets(netlist: NetlistData) -> NetCollection:
    """Classify every netlist net into the fixed type set.

    Args:
        netlist: Parsed Allegro netlist (see ``parse_netlist``).

    Returns:
        :class:`NetCollection` with ``gnd_ref`` / ``diff_pair`` /
        ``power`` / ``clock_single`` / ``signal`` records.
    """
    names = list(netlist.nets)
    pair_map = _diff_pair_map(names)
    collection = NetCollection()
    for name in names:
        members = [t for t in netlist.nets[name] if _PIN_TOKEN_RE.match(t)]
        if _GND_RE.match(name):
            net_type, provenance = NET_TYPE_GND_REF, "rule:gnd_ref"
        elif name in pair_map:
            net_type, provenance = NET_TYPE_DIFF_PAIR, "rule:diff_pair"
        elif _POWER_RE.match(name):
            net_type, provenance = NET_TYPE_POWER, "rule:power"
        elif classify_clock(name):
            net_type, provenance = NET_TYPE_CLOCK_SINGLE, "rule:se_clock"
        else:
            net_type, provenance = NET_TYPE_SIGNAL, "physical:signal"
        collection.nets.append(
            NetRecord(name=name, members=members, net_type=net_type,
                      provenance=provenance))
    collection.diff_pairs = _pair_tuples(pair_map)
    return collection


def _diff_pair_map(names: list[str]) -> dict[str, str]:
    """Map ``*_P`` <-> ``*_N`` sibling names (only when BOTH exist)."""
    name_set = set(names)
    pairs: dict[str, str] = {}
    for name in names:
        if name.endswith(("_P", "_N")):
            base = name[:-2]
            sibling = f"{base}_N" if name.endswith("_P") else f"{base}_P"
            if sibling in name_set:
                pairs[name] = sibling
    return pairs


def _pair_tuples(pairs: dict[str, str]) -> list[tuple[str, str]]:
    """Ordered (positive, negative) tuples, each pair listed once."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pos, neg in pairs.items():
        if pos.endswith("_P") and neg not in seen:
            out.append((pos, neg))
            seen.add(pos)
    return out
