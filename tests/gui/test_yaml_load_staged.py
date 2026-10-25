# -*- coding: utf-8 -*-
"""Staged yaml load + factory reset (user direction 2026-10-15).

1. the big ICT plans load through a QTimer stage chain with the
   status-bar progress bar; Run Control + double-click editing are
   disabled while loading and restored afterwards;
2. loading a different project auto-closes the previous one first
   (two test projects must never blend in the tables);
3. Close Yaml / initialization clear the ICT/FCT tables COMPLETELY -
   no empty placeholder row (the former single op / MessageOK row)."""
from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.main_window import MainWindow  # noqa: E402

MainWindow.__test__ = False


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _sandbox_cwd(tmp_path, monkeypatch):
    """Auto-saves redirect out of the repository."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def window(qapp):
    w = MainWindow(role="Supervisor", mode="Virtual")
    yield w
    w.close()
    w.deleteLater()


def _wait_load_done(window, qapp):
    while getattr(window, "_yaml_loading", False):
        qapp.processEvents()


def test_clear_tables_zero_rows(window):
    """Close Yaml / init: ICT AND FCT tables are EMPTY - zero rows,
    zero step data (the former empty op / MessageOK placeholder row is
    user-direction-retired 2026-10-15)."""
    page = window.workflow_page
    # consistent fabricated state (steps + enables, like a live page)
    page.ict_steps = [("op", "Leftover", "—", "—", "—", "—")]
    page.ict_enables = [True]
    page.fct_rows = ["Leftover"]
    page.fct_enables = [True]
    page.fct_kinds = ["MessageOK"]
    window.close_yaml()
    assert page.ict.rowCount() == 0
    assert page.fct.rowCount() == 0
    assert page.ict_steps == []
    assert page.fct_rows == []
    assert page.fct_kinds == []
    # run gates still count (0, 0) test items
    assert page.test_item_counts() == (0, 0)


def test_staged_load_restores_controls(window, tmp_path, qapp,
                                       monkeypatch):
    """A staged load disables Run Control while it runs and restores
    everything after; the progress bar returns to Idle."""
    import yaml as _yaml
    plan = {
        "product": {"part_number": "MTK12345", "core_id": "29420",
                    "batch": "EVT (Proto-1)"},
        "test_workflow": {"ict_test_cases": [], "fct_test_cases": []},
    }
    path = tmp_path / "proj.yaml"
    path.write_text(_yaml.safe_dump(plan), encoding="utf-8")

    page = window.workflow_page
    seen_disabled = []
    orig_parse = MainWindow._yaml_parse

    def _spy_parse(self, p):
        # mid-load: the controls must be disabled
        seen_disabled.append((not page.btn_run.isEnabled(),
                              not page.longrun_spin.isEnabled(),
                              getattr(page, "_yaml_loading", False)))
        orig_parse(self, p)

    monkeypatch.setattr(MainWindow, "_yaml_parse", _spy_parse)
    window._begin_yaml_load(str(path))
    _wait_load_done(window, qapp)

    assert seen_disabled == [(True, True, True)]
    assert page.btn_run.isEnabled()
    assert page.longrun_spin.isEnabled()
    assert not getattr(page, "_yaml_loading", False)
    assert window.status_progress.format() == "Idle"
    assert window.status_progress.value() == 0
    assert page.part_edit.text() == "MTK12345"
    assert "Yaml loaded" in window.event_log.toPlainText()


def test_project_switch_autocloses_previous(window, tmp_path, qapp):
    """Loading project B while project A is loaded auto-closes A
    first: the tables carry ONLY B's rows and the log records the
    auto-close (no blend of two test projects)."""
    import yaml as _yaml

    def _project(part, ict_names, fct_names):
        return {
            "product": {"part_number": part, "core_id": "1"},
            "test_workflow": {
                "ict_test_cases": [
                    {"kind": "test", "name": n, "unit": "V"}
                    for n in ict_names],
                "fct_test_cases": [
                    {"kind": "MessageOK", "name": n}
                    for n in fct_names],
            },
        }

    a = tmp_path / "a.yaml"
    a.write_text(_yaml.safe_dump(_project(
        "PROJ-A", ["A_Impedance"], ["A_Fct"])), encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text(_yaml.safe_dump(_project(
        "PROJ-B", ["B_Impedance"], ["B_Fct"])), encoding="utf-8")

    window._begin_yaml_load(str(a))
    _wait_load_done(window, qapp)
    page = window.workflow_page
    assert page.part_edit.text() == "PROJ-A"
    assert [page.ict.item(r, 1).text()
            for r in range(page.ict.rowCount())] == ["A_Impedance"]
    assert [page.fct.item(r, 1).text()
            for r in range(page.fct.rowCount())] == ["A_Fct"]

    window._begin_yaml_load(str(b))
    _wait_load_done(window, qapp)
    assert page.part_edit.text() == "PROJ-B"
    ict = [page.ict.item(r, 1).text()
           for r in range(page.ict.rowCount())]
    fct = [page.fct.item(r, 1).text()
           for r in range(page.fct.rowCount())]
    assert ict == ["B_Impedance"]          # A's rows are GONE
    assert fct == ["B_Fct"]
    log = window.event_log.toPlainText()
    assert "Previous project auto-closed" in log
    assert "Yaml loaded" in log


def test_load_failed_keeps_gui_usable(window, tmp_path, qapp,
                                      monkeypatch):
    """A broken YAML file fails the stage chain with the Load Failed
    box - the controls are restored and the GUI is not wedged."""
    import yaml as _yaml
    bad = tmp_path / "bad.yaml"
    bad.write_text("product: [unclosed", encoding="utf-8")
    errors = []
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.critical",
        lambda *a, **k: errors.append(k[1] if len(k) > 1 else a[1]))
    window._begin_yaml_load(str(bad))
    _wait_load_done(window, qapp)
    assert len(errors) == 1
    page = window.workflow_page
    assert page.btn_run.isEnabled()
    assert not getattr(page, "_yaml_loading", False)
    assert window.status_progress.format() == "Idle"


def test_lazy_render_collect_matches_data(window, tmp_path, qapp):
    """The viewport-lazy combo rendering (652-row GPIO tables cost
    ~12 s of widget polish) must keep collect() identical to the row
    DATA for every row - rendered or not."""
    from mtkgui.gui.yamlbuild.channel_allocation import (
        AllocatedRow, merge_rows, rows_from_testable)
    page = window.yaml_build_page.channel_alloc
    model = window.yaml_build_page.model
    model.imported["testable_nets"] = {
        f"GPIO_{i:03d}": {"category": "GPIO", "members": [f"U1.{i}"]}
        for i in range(120)
    }
    saved = {"gpio": [{"net": f"GPIO_{i:03d}",
                       "dio_channel": f"U2355A DIO{i % 24 + 1:02d}"}
                      for i in range(0, 120, 10)]}
    model.set_channel_allocation({"power": [], "clock": [], **saved})
    page.refresh_from_model()
    table = page.table_gpio
    assert table.table.rowCount() == 120
    # collect reads the ROW OBJECTS: identical to the saved config
    collected = {r["net"]: r for r in table.collect()}
    for i in range(0, 120, 10):
        row = collected[f"GPIO_{i:03d}"]
        assert row["dio_channel"] == f"U2355A DIO{i % 24 + 1:02d}"
    # widget count stays below the FULL render count (120 rows x 4
    # dropdown columns = 480 combos - M19b added the Drive level cell;
    # the lazy window only covers the visible rows +- the margin - the
    # 652-row 96624 plan measured 148 widgets vs 1956 at full render)
    widgets = sum(table.table.cellWidget(r, c) is not None
                  for r in range(table.table.rowCount())
                  for c in range(table.table.columnCount()))
    assert 0 < widgets < 120 * 4
