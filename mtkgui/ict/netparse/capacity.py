# -*- coding: utf-8 -*-
"""Resource-capacity model (M2 PART B2, headless - no Qt).

The ranked nets (see :mod:`.priority`) are truncated to the ICT
instrument capacity; anything beyond capacity falls to ``Others`` with
``sub_class = "capacity"`` while keeping its original class / rank for
audit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ResourceLimits:
    power_pts: int = 80       # R-GND + Voltage (shared 80 DAQ pts)
    rails_up: int = 12        # DAQ AI power-up sequence
    clock_lf: int = 1         # totalizer <= 100 kHz
    clock_hf: int = 2         # counters <= 6 MHz
    ctrl_io: int = 24         # DIO


DEFAULT_LIMITS = ResourceLimits()

#: CLI ``--limits`` key -> :class:`ResourceLimits` field
_LIMIT_KEYS = {"power": "power_pts", "rails": "rails_up",
               "clock_lf": "clock_lf", "clock_hf": "clock_hf",
               "ctrl": "ctrl_io"}


def parse_limits(text: str | None) -> ResourceLimits:
    """Parse ``"power=80,rails=12,clock_lf=1,clock_hf=2,ctrl=24"``.

    Unknown keys / values raise ``ValueError``; ``None`` returns
    :data:`DEFAULT_LIMITS`.
    """
    if not text:
        return DEFAULT_LIMITS
    values: dict[str, int] = {}
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, raw = chunk.partition("=")
        key = key.strip()
        if key not in _LIMIT_KEYS:
            raise ValueError(
                f"unknown limit key: {key!r} "
                f"(valid: {', '.join(sorted(_LIMIT_KEYS))})")
        try:
            values[_LIMIT_KEYS[key]] = int(raw.strip())
        except ValueError as exc:
            raise ValueError(
                f"limit {key!r} needs an integer, got {raw!r}") from exc
    return ResourceLimits(**values)


def truncate(result, limits: ResourceLimits = DEFAULT_LIMITS) -> dict:
    """Split the ranked buckets into selected / capacity overflow.

    Args:
        result: Ranked :class:`ParseNetsResult` (``priority`` stamped
                by :func:`priority.rank_result`).
        limits: Instrument resource limits.

    Returns:
        ``{class: {"limit": int, "selected": [NetRecord],
        "overflow": [NetRecord]}}`` for ``power`` / ``clock`` /
        ``control_io``.  Overflow records keep their original class /
        rank in ``record.priority`` - callers re-label them as
        ``Others`` / ``sub_class = capacity``.
    """
    power_sel = result.power[:limits.power_pts]
    power_over = result.power[limits.power_pts:]
    lf = [r for r in result.clock if r.priority.get("band") == "LF"]
    hf = [r for r in result.clock if r.priority.get("band") != "LF"]
    clock_sel = lf[:limits.clock_lf] + hf[:limits.clock_hf]
    clock_over = [r for r in result.clock
                  if r not in clock_sel]
    ctrl_sel = result.control_io[:limits.ctrl_io]
    ctrl_over = result.control_io[limits.ctrl_io:]
    return {
        "power": {"limit": limits.power_pts,
                  "selected": power_sel, "overflow": power_over},
        "clock": {"limit": limits.clock_lf + limits.clock_hf,
                  "selected": clock_sel, "overflow": clock_over},
        "control_io": {"limit": limits.ctrl_io,
                       "selected": ctrl_sel, "overflow": ctrl_over},
    }


def capacity_reason(class_name: str, limit: int) -> str:
    """Audit reason for an overflow net."""
    return f"capacity_exceeded({class_name}:{limit})"


def limits_dict(limits: ResourceLimits) -> dict:
    """Serialized limits for the JSON export."""
    return asdict(limits)
