# -*- coding: utf-8 -*-
"""Data quality pipeline (P1 Task11): invalid rejection, duplicate
collapse, outlier rejection, smoothing, band check, traceability."""
from __future__ import annotations

import math

from mtkgui.engine.data_quality import SampleCleaner


class TestInvalidRejection:
    def test_nan_and_inf_never_enter_result(self):
        r = SampleCleaner().clean([1.0, float("nan"), 1.02,
                                   float("inf"), 0.98])
        assert r.value == 1.0                      # median of survivors
        assert set(r.rejected) == {1, 3}
        assert all("non-finite" in why
                   for why in r.rejected.values())

    def test_all_invalid_falls_back_to_zero(self):
        r = SampleCleaner().clean([float("nan")])
        assert r.value == 0.0 and len(r.rejected) == 1


class TestDuplicateCollapse:
    def test_stuck_repeats_collapsed(self):
        r = SampleCleaner().clean([5.0] * 10)
        assert r.duplicates_collapsed == 7         # 3 kept of 10
        assert r.value == 5.0

    def test_genuine_variation_not_collapsed(self):
        r = SampleCleaner().clean([5.0, 5.01, 4.99, 5.0])
        assert r.duplicates_collapsed == 0


class TestOutlierRejection:
    def test_jump_extreme_dropped(self):
        r = SampleCleaner().clean([3.30, 3.31, 3.29, 3.30, 99.0])
        assert r.value == 3.30
        assert any("outlier" in why for why in r.rejected.values())

    def test_extreme_cluster_dropped_both_sides(self):
        r = SampleCleaner().clean([10.0, 10.1, 9.9, 10.05,
                                   0.001, 500.0])
        assert 9.8 < r.value <= 10.15
        assert len(r.outliers_dropped) == 2

    def test_small_batch_skips_outlier_stage(self):
        r = SampleCleaner().clean([1.0, 2.0])
        assert r.outliers_dropped == [] and r.value == 1.5


class TestSmoothingAndBand:
    def test_median_smoothing_suppresses_jitter(self):
        r = SampleCleaner().clean([3.29, 3.31, 3.30, 3.30, 3.32])
        assert r.smoothed and abs(r.value - 3.30) < 0.01

    def test_band_check_pass_and_fail(self):
        c = SampleCleaner()
        assert c.clean([3.3, 3.31], lo=3.0, hi=3.5).in_band is True
        assert c.clean([3.7, 3.72], lo=3.0, hi=3.5).in_band is False

    def test_no_band_means_no_judgment(self):
        assert SampleCleaner().clean([1.0, 1.1]).in_band is None


class TestTraceability:
    def test_dataq_log_lines_cover_all_stages(self):
        r = SampleCleaner().clean([1.0, float("nan"), 1.02, 99.0],
                                  lo=0.9, hi=1.1)
        text = "\n".join(r.log_lines)
        assert text.count("[DATAQ]") >= 4
        assert "non-finite" in text and "outlier" in text
        assert "band check" in text and "final value" in text

    def test_clean_value_convenience(self):
        assert SampleCleaner().clean_value(
            [2.0, 2.02, float("nan")]) == 2.01     # nan rejected, median
