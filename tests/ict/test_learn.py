# -*- coding: utf-8 -*-
"""M20: Learn-from-Project - additive rule learning + statistics.

Covers the headless learner (NET parsing, bucket statistics, additive
merge, low-confidence conflict demotion) and the dialog integration.
"""
from __future__ import annotations

import pytest

from mtkgui.ict.netparse.learn import (BUCKETS, _bucket, _merge,
                                       count_by_category, learn_rules,
                                       read_net_names)
from mtkgui.ict.netparse.rules import DEFAULT_RULES, validate_rules


# ------------------------------------------------------------ NET reader
def test_read_net_names_splits_refdes(tmp_path):
    net = tmp_path / "board.net"
    net.write_text(
        "# comment\n"
        "( 29420_H\n"
        "VCC_1V8,C30.1 C1.2\n"
        "CLK_32K,U1.5\n"
        "1234.567\n"
        "\n"
        "GND\n", encoding="utf-8")
    names = read_net_names(str(net))
    assert names == ["VCC_1V8", "CLK_32K", "GND"]


def test_read_net_names_missing_file(tmp_path):
    with pytest.raises(ValueError):
        read_net_names(str(tmp_path / "nope.net"))


# -------------------------------------------------------------- buckets
def test_count_by_category_uses_control_io():
    names = ["VDD_3V3", "CLK1", "PCIE_RST_B", "SDA", "VCC_5V"]
    counts = count_by_category(names, None)
    assert counts["Power"] == 2          # VDD_3V3, VCC_5V
    assert counts["Clock"] == 1          # CLK1
    assert counts["Others"] == 2         # PCIE_RST_B (excluded net),
    #                                    # SDA (signal)
    assert counts["Control IO"] == 0
    assert sum(counts.values()) == len(names)


# ------------------------------------------------------------ additive
def test_learn_is_additive_not_replace():
    """The learned rules must MERGE with the current ones; factory
    power matches must survive (regression: a merge bug once dropped
    Power 48 -> 0)."""
    names = ["VDD_3V3", "VCC_5V", "TYPEC_1V8", "PWR_IN_12V",
             "vcc_1v8"]          # lowercase: factory power (case-
    #                             # sensitive) misses it -> Others
    res = learn_rules(names, None)
    # every uppercase power-form net stays Power before AND after
    assert res["before"]["Power"] == 4
    assert res["after"]["Power"] == 5      # lowercase one learned up
    # the learned branch is ADDED (merge), never a replacement
    assert "|" in res["rules"]["power"]
    assert res["rules"]["power"].startswith("(?:") or \
        res["rules"]["power"].startswith("(?i)")
    # learned rules still validate
    assert validate_rules(res["rules"]) == []


def test_learn_suggested_merges_existing_user_rules():
    custom = dict(DEFAULT_RULES, power=r"^PWR_\w+$")
    names = ["PWR_MAIN", "VCC_1V8", "CLK1"]
    res = learn_rules(names, custom)
    # user base preserved + learned branch appended
    assert res["rules"]["power"].startswith(r"(?:^PWR_\w+$)|")
    assert validate_rules(res["rules"]) == []


def test_learn_clock_and_exclude_branches():
    names = ["VDD_3V3", "DMIC_CLK", "RTC_32K", "I2C0_SDA",
             "USB_DM", "ETH_RST_N"]
    res = learn_rules(names, None)
    # CLK / RTC learned into the clock branch
    assert "CLK" in res["rules"]["se_clock"] \
        and "RTC" in res["rules"]["se_clock"]
    # diff members / bus tokens learned into the exclude branch
    assert "_[PN]$" in res["rules"]["exclude"] \
        or "I2C" in res["rules"]["exclude"]
    assert validate_rules(res["rules"]) == []


# -------------------------------------------------------------- conflict
def test_learn_conflict_demoted_to_others():
    """A net the OLD rules place in a definite bucket that the learned
    rules would move elsewhere is low-confidence -> Others."""
    # narrow custom power + a custom clock rule that grabs a power-form
    # name: the learned 1V8 branch would pull it to Power -> conflict
    current = dict(DEFAULT_RULES,
                   power=r"^PWR_\w+$", se_clock=r"^VCC_1V8$")
    names = ["VCC_1V8", "PWR_MAIN", "TYPEC_1V8"]
    res = learn_rules(names, current)
    # VCC_1V8: old=Clock (custom), learned power branch hits it -> demoted
    assert res["before"]["Clock"] == 1
    assert res["after"]["Others"] >= 1
    assert "VCC_1V8" in res["conflicts"]
    # TYPEC_1V8 was Others and gets LEARNED UP (not a conflict)
    assert "TYPEC_1V8" not in res["conflicts"]


def test_learn_conflict_none_without_flip():
    names = ["VDD_3V3", "CLK1"]
    res = learn_rules(names, None)
    assert res["conflicts"] == []


# ------------------------------------------------------------- counting
def test_counts_always_cover_all_nets():
    names = ["VDD_3V3", "CLK1", "PCIE_RST_B", "SDA", "X1"]
    for rules in (None, dict(DEFAULT_RULES)):
        res = learn_rules(names, rules)
        assert sum(res["before"].values()) == len(names)
        assert sum(res["after"].values()) == len(names)
        assert set(res["before"]) == set(BUCKETS)


# ------------------------------------------------------------- helpers
def test_merge_hoists_global_flag():
    merged = _merge("(?i)(DIFF|RESET)", "(?i:NEW)$")
    # the GLOBAL (?i) must stay at the expression start
    assert merged.startswith("(?i)")
    import re
    assert re.compile(merged)          # must compile
    assert not re.match(merged, "RESET") or re.match(merged, "reset")


def test_bucket_unknown_name_is_others():
    assert _bucket("GPIO0", None) == "Others"
