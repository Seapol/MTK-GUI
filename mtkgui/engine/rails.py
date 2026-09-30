# -*- coding: utf-8 -*-
"""Power-rails waveform data services for the test flow engine.

Extracted verbatim from mtkgui.test_workflow_page.py (task T2, pure
extraction): simulated rail waveform generation, the Real/Virtual
capture dispatch, the plot data mapping, the CSV log writer and the
rule-based AI waveform review.

Sample data model: ordered samples t -> rail fraction of nominal
(Virtual demo path) or raw volts (virtual U2355A / real U2355A path),
captured between `start_s` (may be negative = pre-trigger) and `end_s`
at `rate_hz`.
"""
from __future__ import annotations

import csv
import random
from datetime import datetime
from pathlib import Path

# legacy defaults; a project YAML overrides them via the capture
# settings (power_rails_up_sequence.duration_s / sample_rate_hz)
DURATION_S = 6.0
SAMPLE_HZ = 200


def generate_rails(rails: list, start_s: float, end_s: float,
                   rate_hz: float) -> tuple[list[list[float]], int]:
    """Generate simulated rail waveforms.

    start_s can be negative — the capture begins before power-on
    (all rails flat at 0 V until t = 0, then ramps begin).
    """
    rng = random.Random(42)
    n = int((end_s - start_s) * rate_hz)
    power_on_idx = int(abs(start_s) * rate_hz)
    samples = []
    for label, color, vnom, ramp_off in rails:
        ramp_pts = max(1, int((0.25 + ramp_off) * rate_hz))
        # realistic converters slightly overshoot (1-4 %) when the
        # ramp completes, then settle within ~20 ms
        overshoot = rng.uniform(0.01, 0.04)
        series = []
        for i in range(n):
            if i < power_on_idx:
                frac = 0.0
            elif i < power_on_idx + ramp_pts:
                local_i = i - power_on_idx
                frac = local_i / ramp_pts
                frac = frac * frac * (3 - 2 * frac)  # smoothstep
            else:
                frac = 1.0
            ripple = 0.004 * (1 - frac) * rng.uniform(-1, 1)
            noise = 0.0015 * rng.uniform(-1, 1) if frac >= 1 else 0
            over = 0.0
            if frac >= 1.0 and overshoot:
                settle = (i - power_on_idx - ramp_pts) / SAMPLE_HZ
                over = overshoot * 2.718 ** (-settle / 0.02)
            series.append(min(1.06, max(
                0.0, frac + ripple + noise + over)))
        samples.append(series)
    return samples, n


def capture_samples(rack, rails: list, start_s: float, end_s: float,
                    rate_hz: float,
                    inject_faults: bool = True) -> tuple:
    """Return (fractions, volts) for one up-sequence capture.

    Virtual mode (rack given): the simulated U2355A produces stochastic
    volts tied to the virtual PSU state (fresh entropy per capture);
    Real mode without a driver keeps the legacy normalized demo
    waveform and returns volts = None.  inject_faults=False gives a
    guaranteed-healthy preview for the properties dialog."""
    if rack is not None:
        force = None if inject_faults else "PASS"
        frac, volts, _anomaly = rack.capture_rails(
            rails, start_s, end_s, rate_hz, force=force)
        return frac, volts
    samples, _n = generate_rails(rails, start_s, end_s, rate_hz)
    return samples, None


def rail_plot_data(rails: list, samples: list) -> list[tuple]:
    """Zip the rail definitions with their sample series for the plot."""
    return [(label, color, vnom, series)
            for (label, color, vnom, _), series
            in zip(rails, samples)]


def write_csv(logs_dir: Path, rails: list, samples: list,
              volts: list | None, start_s: float, rate_hz: float,
              virtual_mode: bool) -> Path:
    """Write one power-rails capture to a timestamped CSV log file.

    A real (or simulated) U2355A logs volts; the legacy demo path has
    only normalized fractions of each rail's nominal.  Returns the CSV
    path (logs_dir / power_rails[_virtual]_YYYYmmdd_HHMMSS.csv)."""
    logs_dir.mkdir(exist_ok=True)
    mid = "_virtual" if virtual_mode else ""
    name = f"power_rails{mid}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    path = Path(logs_dir) / name
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_ms"] + [r[0] for r in rails])
        for i in range(len(samples[0])):
            t_ms = (start_s + i / rate_hz) * 1000
            row = [f"{t_ms:.1f}"]
            for j, series in enumerate(samples):
                if volts is not None:
                    row.append(f"{volts[j][i]:.6f}")
                else:
                    row.append(f"{series[i]:.6f}")
            writer.writerow(row)
    return path


def ai_wave_review(rails: list, rail_samples: list, start_s: float,
                   end_s: float, rate_hz: float,
                   virtual_mode: bool) -> str:
    """Rule-based AI review of the sampled power-rail waveforms.

    Grades every rail's parameters - steady level, start delay, rise
    time, overshoot, settling, ripple and ramp monotonicity - and
    returns a plain-text report page."""
    if not rail_samples:
        return ("AI Waveform Review\n"
                "==================\n"
                "No waveform captured yet - run a sequence first.")
    hz = rate_hz
    kind = ("virtual demo data" if virtual_mode
            else "DAQ capture")
    lines = [
        "AI Waveform Review - Power Rails Up Sequence",
        "=" * 62,
        f"Capture : {start_s:+.2f} s .. {end_s:.2f} s "
        f"@ {hz} Hz, {len(rail_samples)} rails ({kind})",
        "Windows : level +/-3 %, overshoot <=5 %, ripple <=1 % p-p,",
        "          monotonic ramp, settle within 1 %",
        "",
    ]
    grades = []
    for (label, _color, vnom, _off), s in zip(rails, rail_samples):
        # steady level & ripple from the last 20 % of the capture
        tail = s[int(len(s) * 0.8):]
        level = sum(tail) / len(tail)
        dev = (level - 1.0) * 100
        p2p = (max(tail) - min(tail)) * 100
        # timing: first 10 % / 90 % crossings during the ramp
        i10 = next((i for i, v in enumerate(s) if v >= 0.1), None)
        i90 = None
        if i10 is not None:
            i90 = next((i for i in range(i10, len(s))
                        if s[i] >= 0.9), None)
        rise_ms = ((i90 - i10) * 1000 / hz
                   if i10 is not None and i90 is not None else 0.0)
        t10 = (i10 / hz) if i10 is not None else 0.0
        over = (max(s) - 1.0) * 100
        # settling: first moment |v-1| stays within 1 % for 50 ms
        win = max(1, int(hz * 0.05))
        settle_ms = None
        if i10 is not None and i90 is not None:
            for j in range(i90, max(i90 + 1, len(s) - win)):
                if all(abs(v - 1.0) <= 0.01 for v in s[j:j + win]):
                    settle_ms = (j - i10) * 1000 / hz
                    break
        # monotonicity: biggest downward step inside the ramp
        drop = 0.0
        if i10 is not None and i90 is not None and i90 > i10 + 1:
            seg = s[i10:i90 + 1]
            drop = max(a - b for a, b in zip(seg, seg[1:])) * 100
        lvl_ok = abs(dev) <= 3.0
        over_ok = over <= 5.0
        rip_ok = p2p <= 1.0
        mono_ok = drop <= 2.0
        ok_all = lvl_ok and over_ok and rip_ok and mono_ok
        grades.append(ok_all)
        lines += [
            f"{label}  (nominal {vnom:.2f} V)  ->  "
            f"{'Good' if ok_all else 'Check'}",
            f"  steady level    : {level * 100:6.1f} % of nominal "
            f"({dev:+.2f} %)  "
            f"{'ok' if lvl_ok else 'OUT of +/-3 % window'}",
            f"  start (10 %)    : t = {t10:+.3f} s",
            f"  rise 10 -> 90 % : {rise_ms:6.1f} ms",
            f"  overshoot       : {over:+.2f} %  "
            f"{'ok' if over_ok else 'too high (>5 %)'}",
            f"  settle in 1 %   : "
            + (f"{settle_ms:.0f} ms" if settle_ms is not None
               else "not settled"),
            f"  ripple p-p      : {p2p:.2f} %  "
            f"{'ok' if rip_ok else 'noisy (>1 %)'}",
            f"  ramp monotonic  : "
            f"{'ok' if mono_ok else f'dip of {drop:.2f} %'}",
            "",
        ]
    n_good = sum(grades)
    n_all = len(grades)
    if n_good == n_all:
        overall = (f"OVERALL: {n_good}/{n_all} rails pass all windows "
                   f"- waveform is realistic and healthy.")
    else:
        overall = (f"OVERALL: {n_good}/{n_all} rails pass all windows; "
                   f"review the CHECK items above.")
    lines += ["-" * 62, overall]
    return "\n".join(lines)
