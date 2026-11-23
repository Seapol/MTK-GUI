# -*- coding: utf-8 -*-
"""M107b: ``_fat_summary_outcome`` carries the per-item Summary rows."""
from __future__ import annotations

from mtkgui.engine.fct_exec import (
    VERDICT_FAIL,
    VERDICT_PASS,
    _fat_summary_outcome,
)

SUMMARY = """\
fat.py starting ...
 1      Memory (memtester)                                     PASS          12.34s
 2      USB1_C / USB2_A U-disk read/write speed                 FAIL          99.50s
 3      Wi-Fi scan                                             WARN           1.00s
Summary:
 1      Memory (memtester)                                     PASS          12.34s
 2      USB1_C / USB2_A U-disk read/write speed                 FAIL          99.50s
 3      Wi-Fi scan                                             WARN           1.00s
"""


def test_sub_items_one_entry_per_summary_row():
    outcome = _fat_summary_outcome(SUMMARY)
    assert outcome.verdict == VERDICT_FAIL
    assert outcome.reason == "3 items: FAIL 1, PASS 1, WARN 1"
    assert [item["label"] for item in outcome.sub_items] == [
        "1. Memory (memtester)",
        "2. USB1_C / USB2_A U-disk read/write speed",
        "3. Wi-Fi scan",
    ]
    assert [item["status"] for item in outcome.sub_items] == [
        "PASS", "FAIL", "WARN"]
    assert [item["duration_s"] for item in outcome.sub_items] == [
        12.34, 99.5, 1.0]
    assert all(isinstance(item["duration_s"], float)
               for item in outcome.sub_items)


def test_overall_pass_keeps_every_item():
    outcome = _fat_summary_outcome(
        "Summary:\n 1      Boot                                           "
        "PASS           0.80s\n")
    assert outcome.verdict == VERDICT_PASS
    assert outcome.reason == "1 items: PASS 1"
    assert outcome.sub_items == [{
        "label": "1. Boot", "status": "PASS", "duration_s": 0.8}]


def test_missing_summary_has_no_sub_items():
    outcome = _fat_summary_outcome("no table here")
    assert outcome.verdict == VERDICT_FAIL
    assert outcome.reason == "no fat.py Summary found"
    assert outcome.sub_items == []
