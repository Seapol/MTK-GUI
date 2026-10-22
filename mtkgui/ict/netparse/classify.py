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

from .device_roles import (CLOCK_GEN as ROLE_CLOCK_GEN,
                           FPGA as ROLE_FPGA,
                           INTERFACE_CHIP as ROLE_INTERFACE,
                           _NAME_FPGA_RE, role_for_part_number)
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
#: anchored system-clock TOKENS - M1 Fix 4 A: WORD-anchored (start of
#: the mux-stripped name OR after ``_``) so vendor prefixes
#: (``R_`` / ``DUT_`` / ``BB_``) no longer hide real clocks; longer
#: tokens first (AUXCLKIN before CLKIN before CLK, OSCI before OSC,
#: EXTAL next to XTAL).  EXTAL / OSCI / OSCO are crystal-name variants;
#: audio MASTER clocks (CODEC_SYS_MCLK / MCLK_OUT0) are ICT clock test
#: objects (owner decision 2026-10-22) - audio INTERFACE clocks
#: (SAI / ESAI / I2S) stay excluded via the rule-4 exclusion below.
#: (M3: table form so an external rule layer can add/remove tokens.)
_CLOCK_PREFIX_TOKENS = (
    "CLKOUT", "CLKIN", "CLK_OUT", "CLK_IN", "AUXCLKIN", "AUXCLKOUT",
    "AUXCLK", "CLK", "OSCI", "OSCO", "OSC", "XTAL", "EXTAL", "MCLK",
    "SCKI", "REFCLK", "SUSCLK")
#: crystal-family tokens allow an ALPHABETIC tail (``XTALI`` ...)
_CRYSTAL_TOKENS = ("OSCI", "OSCO", "OSC", "XTAL", "EXTAL")
#: anchored clock token at the END of the mux-stripped net name
_CLOCK_SUFFIX_TOKENS = ("CLK", "XTAL", "OSC")
#: M1 Fix 3 / Fix 4 B / close-out FIX 1: interface clock exclusion
#: tokens (SPI / QSPI / audio / MLB / SIM / PSI5 / ENET / MIPI / PCIE)
_CLOCK_IFACE_ANCHOR_TOKENS = ("SPI", "QSPI", "ESAI", "SAI", "I2S",
                              "MLB", "SIM")
_CLOCK_IFACE2_TOKENS = ("ENET", "MIPI", "PCIE")

_CLOCK_PREFIX_RE = re.compile(
    r"(^|_)(" + "|".join(_CLOCK_PREFIX_TOKENS) + r")([0-9_].*)?$",
    re.IGNORECASE)
_CRYSTAL_TOKEN_RE = re.compile(
    r"(^|_)(" + "|".join(_CRYSTAL_TOKENS) + r")([0-9A-Z_]*)?$",
    re.IGNORECASE)
_CLOCK_SUFFIX_RE = re.compile(
    r"(" + "|".join("_" + t for t in _CLOCK_SUFFIX_TOKENS) + r")"
    r"([0-9_]*)$", re.IGNORECASE)
_CLOCK_IFACE_ANCHOR_RE = re.compile(
    r"(^|_)(" + "|".join(_CLOCK_IFACE_ANCHOR_TOKENS) + r")([0-9A-Z_]*)?",
    re.IGNORECASE)
_CLOCK_IFACE2_RE = re.compile(
    r"(^|_)(" + "|".join(_CLOCK_IFACE2_TOKENS) + r")([0-9A-Z_]*)?",
    re.IGNORECASE)
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
#: M1 Fix 4 B: PSI5 automotive sensor interface clocks
_CLOCK_PSI5_RE = re.compile(
    r"(^|_)(PSI5)([0-9A-Z_]*)?", re.IGNORECASE)
#: M1 close-out FIX 2: chip-model exclusion table (M2 PLACEHOLDER -
#: replaced by the M2 BOM device knowledge base).  These are
#: chip-supply / power-strap nets of clock chips, not clocks.
_CHIP_MODEL_RE = re.compile(
    r"(^|_)(SI5332|SJA1124|TJA1230|FPGA)([0-9A-Z_]*)?", re.IGNORECASE)
#: parenthesized mux marker: ``SUSCLK_32KHZ(SCU_GPIO0_07)``
_MUX_SUFFIX_RE = re.compile(r"\([^)]*\)")
#: M2 PART B: a net is a DEVICE-ROLE candidate when its name mentions
#: any clock-ish token (plain substring - the role step refines, the
#: M1 rules stay authoritative without a library)
_CLOCK_HINT_RE = re.compile(
    r"CLK|XTAL|OSC|MCLK|REFCLK|SUSCLK|AUXCLK", re.IGNORECASE)
#: clock-generator power-strap suffixes beat the clock role
#: (``SI5332_CLK_VDDA`` -> Power)
_CLOCK_GEN_POWER_RE = re.compile(
    r"(^|_)(VDDA|VDDDIG|VDDXTAL|VIO|VDD|PWR|AVDD|DVDD|IOVDD)"
    r"([0-9A-Z_.-]*)?$", re.IGNORECASE)
#: differential-clock markers: ``REFCLK_P`` / ``REFCLK_N``
_DIFF_CLOCK_RE = re.compile(
    r"(_P|_N)([0-9]*)$|_(PLUS|MINUS)$", re.IGNORECASE)
_PIN_TOKEN_RE = re.compile(r"^[\w\.\-\[\]/#]+$")


def _clock_excluded(name: str, chip_model: bool = True) -> bool:
    """M1 interface / pin-multiplex / chip-model / diff exclusions.

    Shared by :func:`classify_clock` and the M2 device-role step (the
    role step sits BETWEEN the clock token match and the chip-model
    exclusion, i.e. interface-excluded names never reach it; with
    ``chip_model=False`` the no-library chip-model fallback is left
    out so the role step can re-classify chip-model nets).
    """
    if _CLOCK_EXCLUDE_RE.search(name):
        return True
    if _CLOCK_IFACE_ANCHOR_RE.search(name):
        return True
    if _CLOCK_PSI5_RE.search(name):
        return True
    if chip_model and _CHIP_MODEL_RE.search(name):
        return True
    if _CLOCK_IFACE2_RE.search(name):
        return True
    return bool(_DIFF_CLOCK_RE.search(name))


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
    if _clock_excluded(name):
        return False
    base = _MUX_SUFFIX_RE.sub("", name).strip()
    if not base:
        return False
    return bool(_CRYSTAL_TOKEN_RE.search(base)
                or _CLOCK_PREFIX_RE.search(base)
                or _CLOCK_SUFFIX_RE.search(base)
                or _CLOCK_FREQ_RE.match(base))


def classify_nets(netlist: NetlistData,
                  library: dict[str, str] | None = None) -> NetCollection:
    """Classify every netlist net into the fixed type set.

    Args:
        netlist: Parsed Allegro netlist (see ``parse_netlist``).
        library: Optional ``refdes -> part_number`` map (M2 device
                 knowledge base, built from the BOM).  With a library,
                 clock-ish nets get a DEVICE-ROLE step between the
                 clock token match and the chip-model exclusion;
                 ``None`` keeps the M1 no-library behaviour.

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
        elif library is not None:
            resolved = _device_role_type(name, members, library)
            if resolved is not None:
                net_type, provenance = resolved
            else:
                net_type, provenance = _name_type(name)
        else:
            net_type, provenance = _name_type(name)
        collection.nets.append(
            NetRecord(name=name, members=members, net_type=net_type,
                      provenance=provenance))
    collection.diff_pairs = _pair_tuples(pair_map)
    return collection


def _name_type(name: str) -> tuple[str, str]:
    """M1 name-based classification (no library)."""
    if _POWER_RE.match(name):
        return NET_TYPE_POWER, "rule:power"
    if classify_clock(name):
        return NET_TYPE_CLOCK_SINGLE, "rule:se_clock"
    return NET_TYPE_SIGNAL, "physical:signal"


def _device_role_type(name: str, members: list[str],
                      library: dict) -> tuple[str, str] | None:
    """M2 device-role step for clock-ish nets (None = fall through).

    Clock-generator chips: power straps beat the clock role (``...
    _VDDA`` -> Power), outputs -> Clock.  Interface chips: clock
    inputs stay untested.  FPGA clock inputs from the DUT -> Clock.
    LOAD / unknown roles fall through to the M1 rules unchanged.

    Library entries are ``{"part_number": str, "description": str}``
    (a bare string PN is also accepted).  A net whose NAME carries an
    FPGA marker (``FPGA`` / ``AG25`` / ...) but whose members map to
    no known part (connector + resistor paths) counts as an FPGA
    clock input.
    """
    if not _CLOCK_HINT_RE.search(name) or _clock_excluded(name,
                                                          chip_model=False):
        return None
    roles: set[str] = set()
    for token in members:
        entry = library.get(token.split(".", 1)[0])
        if not entry:
            continue
        if isinstance(entry, dict):
            role = role_for_part_number(
                entry.get("part_number") or "",
                entry.get("description") or "")
        else:
            role = role_for_part_number(str(entry))
        if role:
            roles.add(role)
    if not roles and _NAME_FPGA_RE.search(name):
        roles.add(ROLE_FPGA)
    if not roles:
        return None
    if ROLE_CLOCK_GEN in roles:
        if _CLOCK_GEN_POWER_RE.search(name):
            return NET_TYPE_POWER, "device_role:clock_gen_power"
        return NET_TYPE_CLOCK_SINGLE, "device_role:clock_gen"
    if ROLE_INTERFACE in roles:
        return NET_TYPE_SIGNAL, "device_role:interface"
    if ROLE_FPGA in roles:
        return NET_TYPE_CLOCK_SINGLE, "device_role:fpga"
    return None


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
