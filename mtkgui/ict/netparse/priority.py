# -*- coding: utf-8 -*-
"""Generic priority ranking (M2 PART B1, headless - no Qt).

Classify -> RANK -> truncate.  This module implements the RANK stage
with project-agnostic, token/keyword rules only:

* **Power**      - pseudo power-tree stage (input rails first ->
                   converter outputs -> load rails), voltage
                   descending, stable input order;
* **Clock**      - frequency band first (LF <= 100 kHz crystal tokens
                   -> 1 totalizer point, HF -> 2 counter points), then
                   a generic importance score;
* **Control IO** - semantic weight RST > EN > CS > MODE.

Every ranked net gets ``record.priority =
{class, score, band, stage, rank}``.  Deterministic: ties keep the
stable input order (Python sort is stable).
"""
from __future__ import annotations

import re

from .confidence import clock_freq_hz
from .device_roles import CONTROL_CHIP, LOAD, role_for_part_number
from .model import (CATEGORY_CLOCK, CATEGORY_CONTROL_IO_LABEL,
                    CATEGORY_GND, CATEGORY_POWER, NET_TYPE_CLOCK_SINGLE,
                    ParseNetsResult)
from .rules import gnd_sub_class, input_rail_tier

# --------------------------------------------------------------- power
#: stage 0 - external input rails
_STAGE0_RE = re.compile(
    r"VBAT|VIN|PWR_IN|DCIN|PP_.*(BAT|IN)", re.IGNORECASE)
#: stage 1 - converter outputs
_STAGE1_RE = re.compile(
    r"(DCDC|BUCK|BOOST|LDO|PMIC).*(OUT|VOUT)", re.IGNORECASE)
#: nominal voltage label in the net name (``3V3`` / ``1V8`` / ``12V``
#: / ``1.8V``) - higher voltage mains first when known
_VOLTAGE_RE = re.compile(
    r"(?<![\d.])([0-9]+)(?:[.]([0-9]+))?V(?![A-Z0-9])"
    r"|_(1V0|1V2|1V5|1V8|2V5|3V3|5V|12V|24V)([0-9A-Z_]*)?$",
    re.IGNORECASE)
_FIXED_VOLTS = {"1V0": 1.0, "1V2": 1.2, "1V5": 1.5, "1V8": 1.8,
                "2V5": 2.5, "3V3": 3.3, "5V": 5.0, "12V": 12.0,
                "24V": 24.0}

# --------------------------------------------------------------- clock
#: band LF: nominal <= 100 kHz (crystal / 32K / SUSCLK / RTC tokens)
_CLOCK_LF_RE = re.compile(
    r"XTAL|EXTAL|OSCI|OSCO|32K|SUSCLK|RTC_CLK", re.IGNORECASE)
#: band HF tokens (everything else with a clock token is HF)
_CLOCK_HF_RE = re.compile(
    r"CLKOUT|CLKIN|MCLK|REFCLK|AUXCLK|[0-9]+M", re.IGNORECASE)
#: importance +3: SoC / main-chip tokens in the net name
_CLOCK_SOC_RE = re.compile(r"SYS_|MAIN_|CPU_|SOC_", re.IGNORECASE)

# ---------------------------------------------------------- control IO
#: semantic weight, descending (RST > EN > CS > MODE)
_CTRL_WEIGHTS = (
    (re.compile(r"RST|RESET|RSTB|RESET_B|POR|POR_B", re.IGNORECASE), 4),
    (re.compile(r"EN|ENABLE|ENB|PWR_EN|PWROK|POK", re.IGNORECASE), 3),
    (re.compile(r"CS[0-9]|CSB|_CS_|_CS$|SS[0-9]|SSEL", re.IGNORECASE), 2),
    (re.compile(r"MODE|BOOT|BOOTMOD|SEL|CONFIG|CFG", re.IGNORECASE), 1),
)


def _refdes_of(token: str) -> str:
    """``U12.14`` -> ``U12`` (tokens without a dot pass through)."""
    return token.split(".", 1)[0] if "." in token else token


def _main_refdes(library: dict | None) -> set[str]:
    """LOAD-role refdes set (the main chips) from the M2 library."""
    if not library:
        return set()
    mains = set()
    for refdes, info in library.items():
        entry = info if isinstance(info, dict) else \
            {"part_number": str(info), "description": ""}
        pn = str(entry.get("part_number") or "")
        desc = str(entry.get("description") or "")
        if role_for_part_number(pn, desc) == LOAD:
            mains.add(refdes)
    return mains


def _control_refdes(library: dict | None) -> set[str]:
    """CONTROL_CHIP-role refdes set (MCU / CPLD / GPIO-expander ...)."""
    if not library:
        return set()
    ctrl = set()
    for refdes, info in library.items():
        entry = info if isinstance(info, dict) else \
            {"part_number": str(info), "description": ""}
        pn = str(entry.get("part_number") or "")
        desc = str(entry.get("description") or "")
        if role_for_part_number(pn, desc) == CONTROL_CHIP:
            ctrl.add(refdes)
    return ctrl


def nominal_volts_of(name: str) -> float:
    """Nominal voltage of a power net name (0.0 when unknown)."""
    return _nominal_volts(name)


def _conf_rank(rec) -> int:
    """Confidence rank of a record (high=0 ... low=2, medium default)."""
    return {"high": 0, "medium": 1, "low": 2}.get(
        getattr(rec, "confidence", "") or "medium", 1)


def _nominal_volts(name: str) -> float:
    """Nominal voltage of a power net name (0.0 when unknown)."""
    match = _VOLTAGE_RE.search(name)
    if not match:
        return 0.0
    fixed = match.group(3)
    if fixed:
        return _FIXED_VOLTS.get(fixed.upper(), 0.0)
    whole = match.group(1)
    if not whole:
        return 0.0
    frac = match.group(2)
    value = float(whole)
    if frac:                       # "1.8V" decimal form
        value = float(f"{whole}.{frac}")
    elif value > 100:              # millivolt form (``1800`` -> 1.8)
        value = value / 1000.0 if value >= 1000 else value / 100.0
    return value


def _power_stage(name: str) -> int:
    """Pseudo power-tree stage (0 = external input rails first)."""
    if _STAGE0_RE.search(name):
        return 0
    if _STAGE1_RE.search(name):
        return 1
    return 2


def _power_key(index: int, rec) -> tuple:
    return (_power_stage(rec.name), -_nominal_volts(rec.name), index)


def _clock_band(name: str) -> str:
    return "LF" if _CLOCK_LF_RE.search(name) else "HF"


def _clock_score(name: str, members: list[str],
                 mains: set[str]) -> int:
    """Generic clock importance: +3 SoC / main chip, +2 audio master
    MCLK (owner decision: tested), +1 plain crystal / CLKOUT."""
    if mains and any(_refdes_of(t) in mains for t in members):
        return 3
    if _CLOCK_SOC_RE.search(name):
        return 3
    if "MCLK" in name.upper():
        return 2
    return 1


def _ctrl_weight(name: str) -> int:
    for pattern, weight in _CTRL_WEIGHTS:
        if pattern.search(name):
            return weight
    return 0


def rank_result(result: ParseNetsResult,
                library: dict | None = None) -> ParseNetsResult:
    """Rank every bucket in place and stamp ``record.priority``.

    Args:
        result:  Parse result (buckets reordered in place).
        library: Optional M2 ``refdes -> part info`` map - LOAD-role
                 refdes count as the project main chip (+3 clock
                 importance).

    Returns:
        The same :class:`ParseNetsResult`, ranked.
    """
    mains = _main_refdes(library)
    for index, rec in enumerate(result.power):
        stage = _power_stage(rec.name)
        tier = input_rail_tier(rec.members, library)
        rec.input_rail = tier >= 0
        rec.priority = {"class": CATEGORY_POWER, "score": 0,
                        "band": "", "stage": stage, "rank": index,
                        "confidence": rec.confidence, "freq_hz": None}
    result.power.sort(key=lambda rec: rec.priority["rank"])
    # capacity fill order: all input rails first (strongest source
    # tier, netlist order within a tier), then the existing
    # high-confidence + tree-flow heuristic for the rest (M3 PART 2.3)
    result.power.sort(key=lambda rec: (
        (0, input_rail_tier(rec.members, library),
         rec.priority["rank"], 0.0) if rec.input_rail
        else (1, 0, _conf_rank(rec),
              _power_key(rec.priority["rank"], rec))))
    for rank, rec in enumerate(result.power):
        rec.priority["rank"] = rank

    ranked_gnd = []
    for index, rec in enumerate(result.gnd):
        sub = rec.sub_class or gnd_sub_class(rec.name)
        rec.sub_class = sub
        # M3 PART 1.2: pcb-plane GND first (default reference), then
        # chassis, then shield; netlist order within a subtype
        order = {"pcb": 0, "chassis": 1, "shield": 2}.get(sub, 3)
        ranked_gnd.append((order, index, rec))
    ranked_gnd.sort(key=lambda item: item[:2])
    result.gnd = [item[2] for item in ranked_gnd]
    for rank, rec in enumerate(result.gnd):
        rec.priority = {"class": CATEGORY_GND, "score": 0, "band": "",
                        "stage": None, "rank": rank,
                        "confidence": rec.confidence, "freq_hz": None}

    ranked_clocks = []
    for index, rec in enumerate(result.clock):
        band = _clock_band(rec.name)
        freq = clock_freq_hz(rec.name)
        score = _clock_score(rec.name, rec.members, mains)
        # owner order: confidence desc, frequency ASCENDING (unknown
        # last), then importance score, then stable input order
        ranked_clocks.append((band != "LF", _conf_rank(rec),
                              (1, 0.0) if not freq else (0, freq),
                              -score, index, rec))
        rec.priority = {"class": CATEGORY_CLOCK, "score": score,
                        "band": band, "stage": None, "rank": index,
                        "confidence": rec.confidence,
                        "freq_hz": freq or None}
    ranked_clocks.sort(key=lambda item: item[:5])
    result.clock = [item[5] for item in ranked_clocks]
    for rank, rec in enumerate(result.clock):
        rec.priority["rank"] = rank

    ctrl_members = _control_refdes(library)
    ranked_ctrl = []
    for index, rec in enumerate(result.control_io):
        weight = _ctrl_weight(rec.name)
        from_ctrl_chip = any(_refdes_of(t) in ctrl_members
                             for t in rec.members)
        ranked_ctrl.append((0 if from_ctrl_chip else 1, -weight,
                            _conf_rank(rec), index, rec))
        rec.priority = {"class": CATEGORY_CONTROL_IO_LABEL,
                        "score": weight, "band": "", "stage": None,
                        "rank": index, "confidence": rec.confidence,
                        "freq_hz": None, "control_chip": from_ctrl_chip}
    ranked_ctrl.sort(key=lambda item: item[:4])
    result.control_io = [item[4] for item in ranked_ctrl]
    for rank, rec in enumerate(result.control_io):
        rec.priority["rank"] = rank
    return result


def clock_points_used(record) -> int:
    """Instrument points a selected clock needs (LF 1, HF 2)."""
    return 1 if record.priority and record.priority.get("band") == "LF" \
        else 2
