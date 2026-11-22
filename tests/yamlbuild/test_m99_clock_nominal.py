# -*- coding: utf-8 -*-
"""M99-3: a project clock nominal belongs to the project (Clock
allocation column), never to the algorithm.

M103: the config-workbook round-trip test was removed with the
export-only decision (the workbook import no longer exists).
"""
from __future__ import annotations

from mtkgui.gui.yamlbuild.ict_sequence import auto_fill_limits
from mtkgui.ict.netparse import confidence


def test_auto_fill_limits_prefers_row_nominal():
    """A token-less project clock name uses the stored row nominal; no
    code-side table is consulted."""
    rows = [("test", "Clock Hz - DMIC_CLK", "Hz", "—", "—", "—")]
    testable = {"DMIC_CLK": {"category": "Clock", "nominal_khz": 3072.0}}
    _kind, _name, _unit, expected, low, high = auto_fill_limits(
        rows, testable)[0][:6]
    assert (expected, low, high) == ("3072000", "3071846", "3072154")


def test_project_net_name_not_in_algorithm():
    """DMIC_CLK is a project net - the generic parser must not know it."""
    assert confidence.clock_freq_hz("DMIC_CLK") == 0.0
    assert confidence.clock_freq_hz("CLK_24M") == 24e6
    assert confidence.clock_freq_hz("OSC32K") == 32768.0
    assert not hasattr(confidence, "_NET_NOMINAL_HZ")
