# -*- coding: utf-8 -*-
"""Virtual power-rails capture realism (user direction): the rails
come up staggered with per-rail rise times / overshoot / ripple and
load-step sag - NOT a single ideal simultaneous ramp."""
from __future__ import annotations

import pytest

from mtkgui.virtual_hardware import VirtualRack

RAILS = [(f"VDD_RAIL_{k}", "#c00", 3.3, 0.0) for k in range(4)]


def _capture():
    rack = VirtualRack(0.0, 0.0)
    rack.psu.output_on = True                # the DUT is powered
    frac, volts, anomaly = rack.capture_rails(
        RAILS, -0.5, 3.0, 200, force="PASS")
    return frac, volts, anomaly


def _crossing(s, level):
    return next((i for i, v in enumerate(s) if v >= level), None)


def test_capture_is_healthy_and_settles():
    frac, volts, anomaly = _capture()
    assert anomaly is None
    for s in frac:
        assert abs(s[-1] - 1.0) <= 0.01      # settles at nominal
        assert max(s) <= 1.18


def test_rails_start_staggered():
    """The rails do NOT ramp simultaneously: their 10 % crossings are
    spread over tens of milliseconds (sequenced power-up with jitter -
    adjacent rails may swap, that is the realistic part)."""
    frac, _volts, _anomaly = _capture()
    t10 = [_crossing(s, 0.1) for s in frac]
    assert all(t is not None for t in t10)
    assert len(set(t10)) >= 3                # staggered, not one ramp
    assert max(t10) - min(t10) >= 2          # spread >= 10 ms


def test_rise_times_and_overshoot_differ_per_rail():
    frac, _volts, _anomaly = _capture()
    rises = []
    for s in frac:
        i10 = _crossing(s, 0.1)
        i90 = _crossing(s, 0.9)
        rises.append(i90 - i10)
    assert len(set(rises)) >= 2              # different rise times
    assert any(max(s) > 1.004 for s in frac)  # visible overshoot
    assert all(max(s) <= 1.05 for s in frac)  # but within spec


def test_load_step_sag_on_earlier_rails():
    """A later rail turning on dips the already-up rails slightly."""
    frac, _volts, _anomaly = _capture()
    first = frac[0]
    after = first[_crossing(frac[1], 0.9):]
    assert min(after) < 0.999                # decaying dip present
