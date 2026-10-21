# -*- coding: utf-8 -*-
"""Confidence scoring + cross-class conflict resolution (M2 B1/B1.5).

Headless, no Qt.  EVERY classified net carries a confidence
(``high`` / ``medium`` / ``low``) from generic, project-agnostic
token rules (B1).  When a net name carries features of MORE THAN ONE
class at once (B1.5), the classes are SCORED with name + BOM evidence
and the winner must reach :data:`_CONFLICT_HIGH` - otherwise the net
falls to ``Others`` / ``sub_class = "ambiguous"``.

No-library mode: M1 expectations stay unchanged - the conflict path
only takes library mode.
"""
from __future__ import annotations

import re

from .device_roles import (CLOCK_GEN as ROLE_CLOCK_GEN,
                           CONTROL_CHIP as ROLE_CONTROL,
                           FPGA as ROLE_FPGA,
                           INTERFACE_CHIP as ROLE_INTERFACE,
                           LOAD as ROLE_LOAD, role_for_part_number)
from .model import (NET_TYPE_CLOCK_SINGLE, NET_TYPE_POWER,
                    ParseNetsResult, SubClass)

HIGH, MEDIUM, LOW = "high", "medium", "low"
_CONF_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}

#: winner threshold for the B1.5 cross-class scoring (module-level)
CONFLICT_HIGH = 3

# ------------------------------------------------------------ name tokens
#: strong power evidence ALONE -> high: voltage prefix or strong rail
_POWER_STRONG_RE = re.compile(
    r"^\d*\.?\d+\s?V|^VBAT|^VIN|_PWR$|_PSW$|^PP[0-9]*V", re.IGNORECASE)
#: power tokens - medium alone (high only together with a voltage
#: prefix); doubles as the weak evidence (+1) for B1.5
_POWER_WEAK_RE = re.compile(
    r"PSW|PWR|VBAT|VIN|VDDA|VDDDIG|VDDXTAL|VIO|VDD|AVDD|DVDD|IOVDD|"
    r"V[0-9]+", re.IGNORECASE)
#: strong clock tokens (anchored, same families as B1) - +2
_CLOCK_STRONG_RE = re.compile(
    r"(^|_)(CLKOUT|CLKIN|CLK_OUT|CLK_IN|CLK|OSCI|OSCO|OSC|XTAL|EXTAL|"
    r"MCLK|REFCLK|SUSCLK|AUXCLK|SCKI|32K)([0-9A-Z_]*)?$"
    r"|^[0-9]+([.][0-9]+)?(M|K|G)(H?Z)?", re.IGNORECASE)
#: weak clock evidence - +1
_CLOCK_WEAK_RE = re.compile(r"CLK|XTAL|OSC", re.IGNORECASE)
#: strong control tokens (anchored) - +2
_CONTROL_STRONG_RE = re.compile(
    r"(^|_)(RST|RESET|RSTB|POR|EN|ENB|PWR_EN|PWROK|CS[0-9]|CSB|MODE|"
    r"BOOTMOD|SEL|CFG)([0-9A-Z_]*)?$", re.IGNORECASE)
#: weak control evidence - +1
_CONTROL_WEAK_RE = re.compile(r"RST|ENB|CS|MODE|SEL|CFG|RESET", re.IGNORECASE)
#: protocol / mux tokens - NEGATIVE evidence on ALL classes (-3)
_PROTOCOL_RE = re.compile(
    r"I2C|SCL|SDA|SPI|QSPI|UART|TX|RX|CAN|USB|SD|SDHC|USDHC|EMMC|UFS|"
    r"PCIE|ETH|ENET|RGMII|MII|SGMII|SAI|ESAI|I2S|PSI5|MIPI|DBGIF|JTAG|"
    r"SWD|SWCLK|TCK|1588|TRACE|PHY|SERDES|LINK|SPDIF|MLB|SIM|GPIO",
    re.IGNORECASE)
#: clock-gen power-strap name form (B4 rule reused by the scoring)
_CLOCK_GEN_POWER_RE = re.compile(
    r"(^|_)(VDDA|VDDDIG|VDDXTAL|VIO|VDD|PWR|AVDD|DVDD|IOVDD)"
    r"([0-9A-Z_.-]*)?$", re.IGNORECASE)
#: clock tokens for the LOAD-member bom evidence check
_CLOCK_HINT_RE = re.compile(r"CLK|XTAL|OSC|MCLK|REFCLK|SUSCLK", re.IGNORECASE)
_CONTROL_HINT_RE = re.compile(r"RST|EN|CS|MODE|SEL|CFG|POR", re.IGNORECASE)
#: passive bridge member prefixes (rail evidence)
_BRIDGE_REFDES_RE = re.compile(r"^(FB|SJ|JP|[RCLBJ])[0-9]+$", re.IGNORECASE)

# ---------------------------------------------------------- clock classes
#: audio master clock stays medium (owner decision, M1 close-out)
_AUDIO_MCLK_RE = re.compile(r"CODEC_SYS_MCLK|_MCLK", re.IGNORECASE)
#: weak / interface-adjacent clock signals -> low
_CLOCK_WEAK_SIG_RE = re.compile(
    r"BCLK|LRCLK|EECLK|EEPROM_CLK", re.IGNORECASE)
#: numeric / frequency tail: 32K, 24M, 12P288M, CLKOUT0 ...
_FREQ_TAIL_RE = re.compile(
    r"([0-9]+([.][0-9]+)?(P[0-9.]+)?[KMG](H?Z)?)"
    r"|((^|_)(CLKOUT|CLKIN|CLK_OUT|CLK_IN|CLK|AUXCLK|REFCLK)"
    r"([0-9_]+)$)", re.IGNORECASE)
#: known clock-family nominal frequencies (extendable, module-level)
_NOMINAL_HZ = ((re.compile(r"OSC32K|SUSCLK|RTC|32K", re.IGNORECASE), 32768.0),)


def clock_freq_hz(name: str) -> float:
    """Nominal frequency in Hz extracted from the net name (0 unknown).

    Generic: the known-family nominal table first (``SUSCLK`` / ``RTC``
    / ``32K`` -> 32768), then the numeric forms ``32K`` / ``24M`` /
    ``12P288M`` / ``32768``.
    """
    for pattern, hz in _NOMINAL_HZ:
        if pattern.search(name):
            return hz
    match = re.search(
        r"(\d+(?:\.[0-9]+)?)(?:P(\d+(?:\.[0-9]+)?))?([KMG])H?Z?"
        r"(?![A-Z0-9])", name, re.IGNORECASE)
    if match:
        value = float(match.group(1))
        if match.group(2):
            value = float(f"{match.group(1)}.{match.group(2)}")
        unit = {"K": 1e3, "M": 1e6, "G": 1e9}[match.group(3).upper()]
        return value * unit
    plain = re.search(r"(?<![\d.])(32768|24576|19200)(?![\d.])", name)
    if plain:
        return float(plain.group(1))
    return 0.0


def _power_confidence(name: str) -> str:
    if _POWER_STRONG_RE.search(name):
        return HIGH
    if _POWER_WEAK_RE.search(name):
        return MEDIUM
    return LOW


def _clock_confidence(name: str) -> str:
    if _CLOCK_WEAK_SIG_RE.search(name):
        return LOW
    if _FREQ_TAIL_RE.search(name):
        return HIGH
    if _AUDIO_MCLK_RE.search(name):
        return MEDIUM
    if _CLOCK_STRONG_RE.search(name):
        return MEDIUM
    return LOW


def _control_confidence(name: str) -> str:
    if _CONTROL_STRONG_RE.search(name):
        return HIGH
    if _CONTROL_WEAK_RE.search(name):
        return MEDIUM
    return LOW


def confidence_for(rec) -> str:
    """B1 confidence of one classified record (bucket-agnostic)."""
    if rec.net_type == NET_TYPE_POWER:
        return _power_confidence(rec.name)
    if rec.net_type == NET_TYPE_CLOCK_SINGLE:
        return _clock_confidence(rec.name)
    if rec.provenance.startswith("control_io:"):
        return _control_confidence(rec.name)
    return LOW


def stamp_confidence(result: ParseNetsResult,
                     library: dict | None = None) -> None:
    """Stamp :attr:`NetRecord.confidence` on every classified net.

    Library mode (B4): a clock candidate with a LOAD / main-chip or
    FPGA member is ``high`` confidence.
    """
    mains: set[str] = set()
    if library:
        for refdes, info in library.items():
            entry = info if isinstance(info, dict) else \
                {"part_number": str(info), "description": ""}
            role = role_for_part_number(
                str(entry.get("part_number") or ""),
                str(entry.get("description") or ""))
            if role in (ROLE_LOAD, ROLE_FPGA):
                mains.add(refdes)
    for rec in (result.power + result.clock + result.control_io
                + result.others):
        rec.confidence = confidence_for(rec)
    if mains:
        for rec in result.clock:
            if any(token.split(".", 1)[0] in mains
                   for token in rec.members):
                rec.confidence = HIGH


# ------------------------------------------------- B1.5 conflict scoring
def _name_evidence(name: str) -> dict[str, int]:
    """Per-class name evidence (+2 strong, +1 weak; protocol -3 all)."""
    scores = {"power": 0, "clock": 0, "control_io": 0}
    if _POWER_STRONG_RE.search(name):
        scores["power"] += 2
    elif _POWER_WEAK_RE.search(name):
        scores["power"] += 1
    if _CLOCK_STRONG_RE.search(name):
        scores["clock"] += 2
    elif _CLOCK_WEAK_RE.search(name):
        scores["clock"] += 1
    if _CONTROL_STRONG_RE.search(name):
        scores["control_io"] += 2
    elif _CONTROL_WEAK_RE.search(name):
        scores["control_io"] += 1
    if _PROTOCOL_RE.search(name):
        scores = {k: v - 3 for k, v in scores.items()}
    return scores


def _role_of(entry) -> str | None:
    if not entry:
        return None
    if isinstance(entry, dict):
        return role_for_part_number(entry.get("part_number") or "",
                                    entry.get("description") or "")
    return role_for_part_number(str(entry))


def _bom_evidence(name: str, members: list[str],
                  library: dict) -> dict[str, int]:
    """B1.5 per-class BOM evidence from member device roles."""
    scores = {"power": 0, "clock": 0, "control_io": 0}
    for token in members:
        refdes = token.split(".", 1)[0]
        role = _role_of(library.get(refdes))
        if not role:
            continue
        if role == ROLE_CLOCK_GEN:
            scores["clock"] += 2
            if _CLOCK_GEN_POWER_RE.search(name):
                scores["power"] += 2
        elif role == ROLE_INTERFACE:
            scores["clock"] -= 3
            scores["control_io"] -= 3
        elif role == ROLE_CONTROL:
            scores["control_io"] += 2
        elif role in (ROLE_LOAD, ROLE_FPGA):
            if _CLOCK_HINT_RE.search(name):
                scores["clock"] += 1
            if _CONTROL_HINT_RE.search(name):
                scores["control_io"] += 1
        elif _BRIDGE_REFDES_RE.match(refdes):
            scores["power"] += 1
    return scores


def resolve_conflicts(result: ParseNetsResult, library: dict) -> list[str]:
    """B1.5 cross-class conflict resolution (library mode only).

    Scans the unclassified ``Others`` nets; a winner scoring
    ``>= CONFLICT_HIGH`` is re-classified into its class with
    confidence ``high``; otherwise the net becomes
    ``Others`` / ``ambiguous`` with the competing scores kept in
    ``members_meta``.  Returns the audited net names.
    """
    audited: list[str] = []
    keep: list = []
    for rec in result.others:
        if rec.sub_class != SubClass.UNCLASSIFIED:
            keep.append(rec)
            continue
        scores = _name_evidence(rec.name)
        bom = _bom_evidence(rec.name, rec.members, library)
        for key, value in bom.items():
            scores[key] += value
        audited.append(rec.name)
        best = max(scores, key=lambda k: (scores[k], k))
        ordered = sorted(scores.values(), reverse=True)
        if scores[best] >= CONFLICT_HIGH and ordered[0] > ordered[1]:
            rec.meta = {"conflict_scores": dict(scores),
                        "original_class": "others"}
            _move_to_class(result, rec, best)
            continue
        rec.sub_class = SubClass.AMBIGUOUS
        rec.provenance = "conflict:ambiguous"
        rec.meta = {"conflict_scores": dict(scores)}
        keep.append(rec)
    result.others[:] = keep
    return audited


def _move_to_class(result: ParseNetsResult, rec, class_key: str) -> None:
    if class_key == "power":
        rec.net_type = NET_TYPE_POWER
        rec.provenance = "conflict:power"
        rec.confidence = HIGH
        result.power.append(rec)
    elif class_key == "clock":
        rec.net_type = NET_TYPE_CLOCK_SINGLE
        rec.provenance = "conflict:clock"
        rec.confidence = HIGH
        result.clock.append(rec)
    else:
        rec.net_type = "signal"
        rec.provenance = f"control_io:conflict:{class_key}"
        rec.confidence = HIGH
        result.control_io.append(rec)
