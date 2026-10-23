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
                    NET_TYPE_SIGNAL, ParseNetsResult, SubClass)
from .rules import (PROTOCOL_TOKENS, _VOLT_TOKEN_RE,
                    conflict_device_class, is_control_conflict_name)

HIGH, MEDIUM, LOW = "high", "medium", "low"
_CONF_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}

#: winner threshold for the B1.5 cross-class scoring (module-level)
CONFLICT_HIGH = 3

# ------------------------------------------------------------ name tokens
#: strong power evidence ALONE -> high: voltage prefix or strong rail
_POWER_STRONG_RE = re.compile(
    r"^\d*\.?\d+\s?V|^VBAT|^VIN|_PWR$|_PSW$|^PP[0-9]*V", re.IGNORECASE)
#: power tokens - medium alone (high only together with a voltage
#: prefix); doubles as the weak evidence (+1) for B1.5.  (M3: table
#: form; ``V[0-9]+`` is a pattern entry, kept verbatim.)
_POWER_WEAK_TOKENS = ("PSW", "PWR", "VBAT", "VIN", "VDDA", "VDDDIG",
                      "VDDXTAL", "VIO", "VDD", "AVDD", "DVDD", "IOVDD",
                      "V[0-9]+")
_POWER_WEAK_RE = re.compile("|".join(_POWER_WEAK_TOKENS), re.IGNORECASE)
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
#: protocol / mux tokens - NEGATIVE evidence on ALL classes (-3).
#: (M3: built from the shared rules.PROTOCOL_TOKENS table so an
#: external tokens.remove layer keeps name-evidence consistent.)
_PROTOCOL_RE = re.compile(
    "|".join(list(PROTOCOL_TOKENS) + ["GPIO"]), re.IGNORECASE)
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
#: explicit per-net nominal frequencies (M9 W2): real net names whose
#: frequency the generic name rules cannot infer.  Highest priority.
_NET_NOMINAL_HZ = {
    "DMIC_CLK": 3.072e6,       # IMXRT DMIC MCLK = 3072 kHz
}


def clock_freq_hz(name: str) -> float:
    """Nominal frequency in Hz extracted from the net name (0 unknown).

    Priority (M9 W2): the explicit per-net table first, then the known
    family table (``SUSCLK`` / ``RTC`` / ``32K`` -> 32768), then the
    numeric forms ``32K`` / ``24M`` / ``12P288M`` / ``32768``.
    """
    key = (name or "").strip().upper()
    if key in _NET_NOMINAL_HZ:
        return _NET_NOMINAL_HZ[key]
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

    M2 Fix 1 semantics: the conflict path ONLY looks at nets M1
    classified into ``power`` / ``clock`` / ``control_io``.  Nets M1
    already excluded (``Others``) are determined not-tested and are
    never re-scored - they only get a truthful sub-class label
    (``interface`` / ``muxed``).

    A candidate hitting a protocol token or a mux indicator leaves
    its candidate class for ``Others`` with the matching sub-class.
    The remaining candidates are scored (name + BOM evidence); a net
    with >=2 class features whose winner reaches
    :data:`CONFLICT_HIGH` moves to that class, otherwise it becomes
    ``Others`` / ``ambiguous``.  Returns the audited net names.
    """
    _audit_candidates(result)
    _label_excluded(result)
    _resolve_power_control_conflicts(result, library)
    audited: list[str] = []
    moved: list = []
    for bucket in ("power", "clock", "control_io"):
        keep = []
        for rec in list(getattr(result, bucket)):
            # a decisive M1 device-role / user-rule or M3 external
            # classification is not a conflict - never re-score it
            if rec.provenance.startswith(("device_role:", "user_rule",
                                          "external")):
                keep.append(rec)
                continue
            scores = _name_evidence(rec.name)
            features = sum(1 for value in scores.values() if value > 0)
            if features < 2:
                keep.append(rec)
                continue
            bom = _bom_evidence(rec.name, rec.members, library)
            for key, value in bom.items():
                scores[key] += value
            audited.append(rec.name)
            best = max(scores, key=lambda k: (scores[k], k))
            ordered = sorted(scores.values(), reverse=True)
            if scores[best] >= CONFLICT_HIGH and ordered[0] > ordered[1]:
                if best != bucket:
                    rec.meta = {"conflict_scores": dict(scores),
                                "original_class": bucket}
                    _move_to_class(result, rec, best, bucket)
                else:
                    keep.append(rec)
                continue
            rec.meta = {"conflict_scores": dict(scores)}
            rec.sub_class = SubClass.AMBIGUOUS
            rec.provenance = "conflict:ambiguous"
            rec.net_type = NET_TYPE_SIGNAL
            moved.append(rec)
        getattr(result, bucket)[:] = keep
    result.others.extend(moved)
    return audited


def _resolve_power_control_conflicts(result: ParseNetsResult,
                                     library: dict) -> None:
    """M3 PART 3: power-name + control-token conflicts never stay power.

    A power record whose name carries an independent control token
    (``CTL`` / ``EN`` / ``RST`` / ``CS`` / ``MODE``) plus an active-low
    suffix (``_B`` / ``_N`` / ``#``) AND a voltage token is resolved by
    device-role evidence from the BOM library: power devices keep the
    power class, logic / buffer / interface devices move to
    ``control_io``, unresolved conflicts move to ``Others`` (never
    power, owner decision 2026-10-22).
    """
    keep = []
    for rec in result.power:
        if rec.provenance.startswith(("device_role:", "user_rule",
                                      "external")):
            keep.append(rec)
            continue
        if not (is_control_conflict_name(rec.name)
                and _VOLT_TOKEN_RE.search(rec.name)):
            keep.append(rec)
            continue
        device = None
        for token in rec.members:
            refdes = token.split(".", 1)[0]
            entry = library.get(refdes)
            if not entry or not refdes.upper().startswith("U"):
                continue
            info = entry if isinstance(entry, dict) else \
                {"part_number": str(entry), "description": ""}
            device = conflict_device_class(
                str(info.get("part_number") or ""),
                str(info.get("description") or ""))
            if device:
                break
        if device == "power":
            keep.append(rec)
            continue
        if device == "logic":
            _move_to_class(result, rec, "control_io", "power")
            continue
        rec.meta = {"conflict": "control_features"}
        rec.sub_class = SubClass.UNCLASSIFIED
        rec.provenance = "conflict:control_features"
        rec.net_type = NET_TYPE_SIGNAL
        result.others.append(rec)
    result.power[:] = keep


def _audit_candidates(result: ParseNetsResult) -> None:
    """Protocol / mux audit of M1 clock + control-IO candidates.

    Power rails are never audited here - ``EMMC_VCC`` / ``USB_5V``
    are legitimate supply nets.
    """
    from .rules import is_muxed, protocol_token

    for bucket in ("clock", "control_io"):
        keep = []
        for rec in getattr(result, bucket):
            token = protocol_token(rec.name)
            if token:
                rec.sub_class = SubClass.INTERFACE
                rec.provenance = f"interface:{token}"
            elif is_muxed(rec.name):
                rec.sub_class = SubClass.MUXED
                rec.provenance = "muxed:reused_io"
            else:
                keep.append(rec)
                continue
            # a determined not-tested verdict is a HIGH-confidence
            # decision (M3 1.4: determined decisions stay visible)
            rec.confidence = HIGH
            rec.net_type = NET_TYPE_SIGNAL
            result.others.append(rec)
        getattr(result, bucket)[:] = keep


def _label_excluded(result: ParseNetsResult) -> None:
    """Label M1-excluded ``Others`` nets (no re-scoring)."""
    from .rules import is_muxed, protocol_token

    for rec in result.others:
        if rec.sub_class != SubClass.UNCLASSIFIED:
            continue
        token = protocol_token(rec.name)
        if token:
            rec.sub_class = SubClass.INTERFACE
            rec.provenance = f"interface:{token}"
            rec.confidence = HIGH
        elif is_muxed(rec.name):
            rec.sub_class = SubClass.MUXED
            rec.provenance = "muxed:reused_io"
            rec.confidence = HIGH


def _move_to_class(result: ParseNetsResult, rec, class_key: str,
                   source: str) -> None:
    getattr(result, source).remove(rec)
    if class_key == "power":
        rec.net_type = NET_TYPE_POWER
        rec.provenance = "conflict:power"
        result.power.append(rec)
    elif class_key == "clock":
        rec.net_type = NET_TYPE_CLOCK_SINGLE
        rec.provenance = "conflict:clock"
        result.clock.append(rec)
    else:
        rec.net_type = NET_TYPE_SIGNAL
        rec.provenance = "conflict:control_io"
        result.control_io.append(rec)
    rec.sub_class = ""
    rec.confidence = HIGH
