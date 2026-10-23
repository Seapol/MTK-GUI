# -*- coding: utf-8 -*-
"""M10-FIX4 F1: statistics data model + dialog (offscreen)."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem  # noqa: E402

from mtkgui.gui import statistics_store as store  # noqa: E402
from mtkgui.gui.statistics_dialog import StatisticsDialog  # noqa: E402


class _Page:
    """Minimal Test Work Flow page stub (only what statistics read)."""

    def __init__(self):
        self.products_passed = 2
        self.products_failed = 1
        self.cycle_times = [10.0, 11.0, 9.0]
        self.ict = QTableWidget(3, 8)
        self.fct = QTableWidget(1, 5)
        self.ict_steps = [
            ("test", "VDD_CORE Test", "—", "V", "1.20", "1.10", "1.30"),
            ("test", "VIO Test", "—", "V", "1.80", "1.70", "1.90"),
            ("op", "Power On DUT", "—", "—", "—", "—", "—"),
        ]
        self._verdict = "FAIL"
        self._fill()

    def _fill(self) -> None:
        rows = [
            ("#1", "VDD_CORE Test", "", "V", "1.20", "1.10", "1.30", "FAIL"),
            ("#2", "VIO Test", "", "V", "1.80", "1.70", "1.90", "PASS"),
            ("#3", "Power On DUT", "", "", "", "", "", "PASS"),
        ]
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                self.ict.setItem(r, c, QTableWidgetItem(text))
        for c, text in enumerate(("#1", "Delay: 500ms", "", "0.5", "PASS")):
            self.fct.setItem(0, c, QTableWidgetItem(text))

    def product_info(self):
        return {"part": "P", "core_id": "C", "batch": "B",
                "serial": "SN-0001"}

    def _judge_verdict(self):
        return self._verdict


@pytest.fixture
def page():
    return _Page()


# -------------------------------------------------------------------------
# data model
# -------------------------------------------------------------------------


def test_run_record_round_trip():
    """dict -> RunRecord -> dict keeps every field and arrays."""
    record = store.RunRecord(
        timestamp="2026-10-23T09:30:00", serial="SN-1", verdict="FAIL",
        cycle_time_s=12.5, passed=0, failed=1,
        failed_steps=["VDD_CORE Test"],
        measurements={"VDD_CORE Test": (1.2, 1.1, 1.3)})
    data = record.to_dict()
    assert data["measurements"]["VDD_CORE Test"] == [1.2, 1.1, 1.3]
    restored = store.RunRecord.from_dict(json.loads(json.dumps(data)))
    assert restored == record


def test_append_and_load_history(tmp_path):
    path = tmp_path / "runs.json"
    assert store.load_runs(path) == ([], "")
    record = store.RunRecord("2026-10-23T09:30:00", "SN-1", "PASS",
                             10.0, 1, 0)
    assert store.append_run(record, path) == path
    store.append_run(store.RunRecord("2026-10-23T09:31:00", "SN-2",
                                     "FAIL", 11.0, 0, 1), path)
    records, warning = store.load_runs(path)
    assert warning == ""
    assert [r.serial for r in records] == ["SN-1", "SN-2"]


def test_corrupt_history_starts_fresh(tmp_path):
    path = tmp_path / "runs.json"
    path.write_text("{not an array", encoding="utf-8")
    records, warning = store.load_runs(path)
    assert records == []
    assert "corrupt" in warning
    # appending replaces the broken file with a valid array
    store.append_run(store.RunRecord("t", "SN-9", "PASS", 5.0, 1, 0), path)
    records, warning = store.load_runs(path)
    assert warning == ""
    assert len(records) == 1


def test_non_array_history_is_corrupt(tmp_path):
    path = tmp_path / "runs.json"
    path.write_text('{"runs": []}', encoding="utf-8")
    records, warning = store.load_runs(path)
    assert records == [] and "not an array" in warning


def test_cpk_math_known_values():
    """Values 4 / 5 / 6 -> mean 5, sample sigma 1; LSL 2, USL 8 ->
    Cp = 6/(6*1) = 1.0, CpK = min(3/3, 3/3) = 1.0."""
    records = [
        store.RunRecord("t", "s1", "PASS", 1.0, 1, 0,
                        measurements={"T": (4.0, 2.0, 8.0)}),
        store.RunRecord("t", "s2", "PASS", 1.0, 1, 0,
                        measurements={"T": (5.0, 2.0, 8.0)}),
        store.RunRecord("t", "s3", "PASS", 1.0, 1, 0,
                        measurements={"T": (6.0, 2.0, 8.0)}),
    ]
    rows = store.cpk_rows(records)
    assert len(rows) == 1
    row = rows[0]
    assert row["samples"] == 3
    assert row["mean"] == pytest.approx(5.0)
    assert row["sigma"] == pytest.approx(1.0)
    assert row["cp"] == pytest.approx(1.0)
    assert row["cpk"] == pytest.approx(1.0)
    assert row["indicative"] is True


def test_cpk_single_sample_is_na():
    rows = store.cpk_rows([store.RunRecord(
        "t", "s1", "PASS", 1.0, 1, 0,
        measurements={"T": (4.0, 2.0, 8.0)})])
    assert rows[0]["cp"] is None and rows[0]["cpk"] is None
    assert rows[0]["indicative"] is False


def test_record_from_page(page):
    record = store.record_from_page(page, timestamp="2026-10-23T10:00:00")
    assert record.serial == "SN-0001"
    assert record.verdict == store.VERDICT_FAIL
    assert record.cycle_time_s == 9.0
    assert record.passed == 0 and record.failed == 1
    assert record.failed_steps == ["VDD_CORE Test"]
    assert record.measurements["VDD_CORE Test"] == (1.2, 1.1, 1.3)
    assert record.measurements["VIO Test"] == (1.8, 1.7, 1.9)
    # op rows never carry a measurement
    assert "Power On DUT" not in record.measurements


def test_session_records_from_counters(page):
    records = store.session_records(page)
    assert len(records) == 3                     # 2 passed + 1 failed
    assert sum(1 for r in records
               if r.verdict == store.VERDICT_PASS) == 2
    assert records[-1].verdict == store.VERDICT_FAIL
    assert records[-1].measurements                # newest carries detail
    assert [r.cycle_time_s for r in records] == [10.0, 11.0, 9.0]


def test_session_records_empty_page_is_empty():
    class Empty:
        products_passed = 0
        products_failed = 0
        cycle_times = []
        ict = None
        fct = None
        ict_steps = []

        def product_info(self):
            return {}

        def _judge_verdict(self):
            return None

    assert store.session_records(Empty()) == []


# -------------------------------------------------------------------------
# dialog
# -------------------------------------------------------------------------


def test_dialog_opens_with_empty_history(qapp, tmp_path):
    dlg = StatisticsDialog(None, runs_path=tmp_path / "runs.json")
    dlg.show()
    qapp.processEvents()
    try:
        assert dlg.isModal()
        assert [dlg.cards[k].value.text() for k in
                ("total", "yield_pct", "uph")] == ["—", "—", "—"]
        assert dlg.history_table.rowCount() == 0
        assert dlg.cpk_table.rowCount() == 0
        assert dlg.bar_chart.bar_count() == 0
        assert dlg.pie_chart.slice_count() == 0
        assert not dlg.warning_label.isVisible()
    finally:
        dlg.close()


def test_dialog_history_view_and_refresh(qapp, page, tmp_path):
    path = tmp_path / "runs.json"
    page.products_passed = 4
    page.products_failed = 1
    page.cycle_times = [10.0, 12.0, 14.0, 16.0, 18.0]
    for i in range(5):
        store.append_run(
            store.RunRecord(f"t{i}", f"SN-{i}",
                            "FAIL" if i == 4 else "PASS",
                            10.0 + 2 * i, 0 if i == 4 else 1,
                            1 if i == 4 else 0,
                            ["VDD_CORE Test"] if i == 4 else [],
                            {"VDD_CORE Test": (1.2 + 0.01 * i, 1.1, 1.3)},
                            ), path)
    dlg = StatisticsDialog(page, runs_path=path)
    dlg.source_combo.setCurrentIndex(1)
    dlg.show()
    qapp.processEvents()
    try:
        assert dlg.cards["total"].value.text() == "5"
        assert dlg.cards["passed"].value.text() == "4"
        assert dlg.cards["failed"].value.text() == "1"
        assert dlg.cards["yield_pct"].value.text() == "80.0"
        assert dlg.cards["avg_cycle_s"].value.text() == "14.00"
        assert dlg.cards["uph"].value.text() == "257.1"
        assert dlg.history_table.rowCount() == 5
        assert dlg.cpk_table.rowCount() == 1
        assert dlg.pie_chart.slice_count() == 1
        assert dlg.line_chart.point_count("Yield %") == 5
        assert dlg.bar_chart.bar_count() == 5
        # another run -> Refresh updates every number
        store.append_run(
            store.RunRecord("t5", "SN-5", "FAIL", 20.0, 0, 1,
                            ["VIO Test"],
                            {"VDD_CORE Test": (1.3, 1.1, 1.3)}), path)
        dlg.refresh()
        assert dlg.cards["total"].value.text() == "6"
        assert dlg.history_table.rowCount() == 6
        assert dlg.pie_chart.slice_count() == 2
    finally:
        dlg.close()


def test_dialog_session_view(qapp, page):
    dlg = StatisticsDialog(page, runs_path=None)
    dlg.show()
    qapp.processEvents()
    try:
        assert dlg.cards["total"].value.text() == "3"
        assert dlg.cards["passed"].value.text() == "2"
        assert dlg.cards["failed"].value.text() == "1"
        assert dlg.cards["yield_pct"].value.text() == "66.7"
        assert dlg.history_table.rowCount() == 3
        assert dlg.cpk_table.rowCount() == 2
    finally:
        dlg.close()


def test_dialog_survives_corrupt_history(qapp, tmp_path):
    path = tmp_path / "runs.json"
    path.write_text("<<<broken>>>", encoding="utf-8")
    dlg = StatisticsDialog(None, runs_path=path)
    dlg.source_combo.setCurrentIndex(1)
    dlg.show()
    qapp.processEvents()
    try:
        assert dlg.cards["total"].value.text() == "—"
        assert dlg.warning_label.isVisible()
        assert "corrupt" in dlg.warning_label.text()
        assert dlg.history_table.rowCount() == 0
    finally:
        dlg.close()
