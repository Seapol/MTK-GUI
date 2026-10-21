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

from .device_roles import LOAD, role_for_part_number
from .model import (CATEGORY_CLOCK, CATEGORY_CONTROL_IO_LABEL,
                    CATEGORY_POWER, NET_TYPE_CLOCK_SINGLE,
                    ParseNetsResult)

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
        rec.priority = {"class": CATEGORY_POWER, "score": 0,
                        "band": "", "stage": stage, "rank": index}
    result.power.sort(key=lambda rec: rec.priority["rank"])
    result.power.sort(key=lambda rec: _power_key(
        rec.priority["rank"], rec))
    for rank, rec in enumerate(result.power):
        rec.priority["rank"] = rank

    ranked_clocks = []
    for index, rec in enumerate(result.clock):
        band = _clock_band(rec.name)
        score = _clock_score(rec.name, rec.members, mains)
        ranked_clocks.append((band != "LF", -score, index, rec))
        rec.priority = {"class": CATEGORY_CLOCK, "score": score,
                        "band": band, "stage": None, "rank": index}
    ranked_clocks.sort(key=lambda item: item[:3])
    result.clock = [item[3] for item in ranked_clocks]
    for rank, rec in enumerate(result.clock):
        rec.priority["rank"] = rank

    ranked_ctrl = []
    for index, rec in enumerate(result.control_io):
        weight = _ctrl_weight(rec.name)
        ranked_ctrl.append((-weight, index, rec))
        rec.priority = {"class": CATEGORY_CONTROL_IO_LABEL,
                        "score": weight, "band": "", "stage": None,
                        "rank": index}
    ranked_ctrl.sort(key=lambda item: item[:2])
    result.control_io = [item[2] for item in ranked_ctrl]
    for rank, rec in enumerate(result.control_io):
        rec.priority["rank"] = rank
    return result


def clock_points_used(record) -> int:
    """Instrument points a selected clock needs (LF 1, HF 2)."""
    return 1 if record.priority and record.priority.get("band") == "LF" \
        else 2
