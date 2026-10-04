# -*- coding: utf-8 -*-
"""Measurement data quality pipeline (P1 Task11).

Anti-jitter, outlier-rejection and repeatability treatment for raw
instrument samples.  Purely additive: device management, protocol
layer, scheduling, retry, state machine and the failure taxonomy are
untouched - callers feed raw sample arrays, the pipeline returns one
stable, traced, in-band verdict value.

  pipeline per reading batch:
    1. invalid rejection  - NaN / inf samples are dropped and marked
                            (they never enter the result set)
    2. duplicate collapse - stuck-sample repeats (collection stall)
                            collapse to one contribution
    3. outlier rejection  - robust MAD-based z-score vs the batch
                            median; jump extremes are dropped
    4. smoothing          - median of the surviving window (robust
                            against short-term jitter)
    5. band check         - final value judged against the YAML band
                            with the raw trace kept for forensics
  every stage leaves [DATAQ] lines: counts, dropped indexes, reasons
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field


@dataclass
class CleanResult:
    """One cleaned batch with full forensic trace."""
    value: float                  # final smoothed value
    raw_count: int
    rejected: dict[int, str]      # index -> rejection reason
    duplicates_collapsed: int
    outliers_dropped: list[int]
    smoothed: bool
    in_band: bool | None          # None when no band given
    log_lines: list[str] = field(default_factory=list)


class SampleCleaner:
    """Configurable robust cleaning pipeline for one reading batch."""

    def __init__(self, min_samples: int = 3,
                 mad_z_limit: float = 3.5,
                 max_identical_repeats: int = 3):
        self.min_samples = min_samples
        self.mad_z_limit = mad_z_limit
        self.max_identical_repeats = max_identical_repeats

    def _dq(self, lines: list[str], msg: str) -> None:
        lines.append(f"[DATAQ] {msg}")

    def clean(self, samples: list[float],
              lo: float | None = None,
              hi: float | None = None) -> CleanResult:
        lines: list[str] = []
        rejected: dict[int, str] = {}
        self._dq(lines, f"batch of {len(samples)} sample(s) received")

        # 1. invalid rejection (NaN / inf never enter the result set)
        valid: list[tuple[int, float]] = []
        for i, s in enumerate(samples):
            f = float(s)
            if math.isnan(f) or math.isinf(f):
                rejected[i] = "non-finite sample (NaN/inf)"
            else:
                valid.append((i, f))
        if rejected:
            self._dq(lines, f"rejected {len(rejected)} non-finite "
                            f"sample(s) at {sorted(rejected)}")

        # 2. duplicate collapse (collection stall repeats)
        values: list[float] = [v for _, v in valid]
        collapsed = 0
        if values:
            uniq_mode = all(v == values[0] for v in values)
            if uniq_mode and len(values) > 1:
                # every sample identical: could be a real constant OR
                # a stalled collection; cap the influence of repeats
                repeats = len(values) - 1
                collapsed = max(0, repeats - (self.max_identical_repeats
                                              - 1))
                if collapsed:
                    self._dq(lines, f"stuck-sample pattern: collapsed "
                                    f"{collapsed} identical repeat(s)")
        kept = valid[:len(valid) - collapsed]

        # 3. robust outlier rejection (MAD z-score vs median)
        nums = [v for _, v in kept]
        outliers: list[int] = []
        if len(nums) >= self.min_samples:
            med = statistics.median(nums)
            mad = statistics.median([abs(v - med) for v in nums]) \
                or (abs(nums[0] - med) or 1.0)
            for i, v in kept:
                z = 0.6745 * (v - med) / mad
                if abs(z) > self.mad_z_limit:
                    outliers.append(i)
                    rejected[i] = f"outlier (robust z={z:.1f})"
            if outliers:
                self._dq(lines, f"dropped {len(outliers)} outlier(s) "
                                f"at {outliers}")
        survivors = [(i, v) for i, v in kept if i not in outliers]

        # 4. median smoothing over the surviving window
        final_vals = [v for _, v in survivors]
        if not final_vals:
            final_vals = [v for _, v in valid] or [0.0]
        smoothed = len(final_vals) > 1
        value = statistics.median(final_vals)
        if smoothed:
            self._dq(lines, f"smoothed value {value:.6g} over "
                            f"{len(final_vals)} surviving sample(s)")

        # 5. band check
        in_band: bool | None = None
        if lo is not None and hi is not None:
            in_band = lo <= value <= hi
            self._dq(lines, f"band check [{lo}, {hi}] -> "
                            f"{'in band' if in_band else 'OUT OF BAND'}")
        self._dq(lines, f"final value {value:.6g} "
                        f"(raw {len(samples)}, rejected "
                        f"{len(rejected)})")
        return CleanResult(value=value, raw_count=len(samples),
                           rejected=rejected,
                           duplicates_collapsed=collapsed,
                           outliers_dropped=outliers,
                           smoothed=smoothed, in_band=in_band,
                           log_lines=lines)

    def clean_value(self, samples: list[float],
                    lo: float | None = None,
                    hi: float | None = None) -> float:
        """Convenience one-liner for the measure pipeline."""
        return self.clean(samples, lo, hi).value
