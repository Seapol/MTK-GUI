# -*- coding: utf-8 -*-
"""Rail waveform data services (mtkgui.engine.rails)."""
from __future__ import annotations

import csv

from mtkgui.engine.rails import (
    DURATION_S,
    SAMPLE_HZ,
    ai_wave_review,
    capture_samples,
    generate_rails,
    rail_plot_data,
    write_csv,
)

RAILS = [("VDD_3V3", "#c00", 3.3, 0.0),
         ("VDD_1V8", "#0c0", 1.8, 0.05)]


class TestGenerateRails:
    def test_shape_and_length(self):
        samples, n = generate_rails(RAILS, -0.5, 5.5, 200)
        assert len(samples) == len(RAILS)
        assert n == int(6.0 * 200)
        assert all(len(s) == n for s in samples)

    def test_starts_flat_then_rises(self):
        (s,) = generate_rails([RAILS[0]], -0.5, 1.5, 100)[0]
        assert s[0] == 0.0                      # pre-trigger: 0 V
        assert s[-1] > 0.95                     # settled near nominal

    def test_deterministic(self):
        a = generate_rails(RAILS, -0.5, 1.5, 100)[0]
        b = generate_rails(RAILS, -0.5, 1.5, 100)[0]
        assert a == b

    def test_defaults(self):
        assert DURATION_S == 6.0
        assert SAMPLE_HZ == 200


class TestCaptureSamples:
    def test_without_rack_returns_fractions_and_none_volts(self):
        frac, volts = capture_samples(None, RAILS, -0.5, 0.5, 100)
        assert volts is None
        assert len(frac) == 2

    def test_with_rack_returns_volts(self):
        class FakeRack:
            def capture_rails(self, rails, start_s, end_s, rate_hz,
                              force=None):
                assert force is None
                return ([[0.0, 1.0]], [[0.0, 3.3]], None)

        frac, volts = capture_samples(FakeRack(), RAILS, -0.5, 1.5, 2)
        assert volts == [[0.0, 3.3]]
        assert frac == [[0.0, 1.0]]

    def test_no_fault_preview_forces_pass(self):
        class FakeRack:
            def capture_rails(self, rails, start_s, end_s, rate_hz,
                              force=None):
                assert force == "PASS"
                return ([[1.0]], [[3.3]], None)

        capture_samples(FakeRack(), RAILS, 0.0, 1.0, 1,
                        inject_faults=False)


class TestCsvLog:
    def test_write_csv_volts(self, tmp_path):
        samples = [[0.0, 1.0]]
        volts = [[0.0, 3.297]]
        path = write_csv(tmp_path, RAILS[:1], samples, volts, -0.5, 2,
                         virtual_mode=False)
        assert path.parent == tmp_path
        assert path.name.startswith("power_rails_")
        rows = list(csv.reader(open(path)))
        assert rows[0] == ["time_ms", "VDD_3V3"]
        assert rows[1][0] == "-500.0"           # t = start_s * 1000
        assert rows[2][1] == "3.297000"

    def test_write_csv_fractions_and_virtual_tag(self, tmp_path):
        path = write_csv(tmp_path, RAILS[:1], [[0.5]], None, 0.0, 2,
                         virtual_mode=True)
        assert "_virtual" in path.name
        assert list(csv.reader(open(path)))[1][1] == "0.500000"


class TestAiWaveReview:
    def test_no_samples_message(self):
        assert "No waveform captured" in ai_wave_review(
            RAILS, [], 0, 1, 100, False)

    def test_healthy_rails_review(self):
        samples, _n = generate_rails(RAILS, -0.5, 5.5, 200)
        review = ai_wave_review(RAILS, samples, -0.5, 5.5, 200, True)
        assert "2/2 rails pass" in review
        assert "virtual demo data" in review

    def test_real_mode_kind(self):
        samples, _n = generate_rails(RAILS, -0.5, 5.5, 200)
        assert "DAQ capture" in ai_wave_review(
            RAILS, samples, -0.5, 5.5, 200, False)


def test_rail_plot_data():
    samples = [[0.1], [0.2]]
    data = rail_plot_data(RAILS, samples)
    assert data[0] == ("VDD_3V3", "#c00", 3.3, [0.1])
    assert data[1][0] == "VDD_1V8"
