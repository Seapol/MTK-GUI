# -*- coding: utf-8 -*-
"""P2-3 AI-case GUI visual editor unit tests (headless offscreen)."""
from __future__ import annotations

import pytest
import yaml

from mtkgui.engine.casegen.excel_io import EDITABLE
from mtkgui.gui.case_editor import CaseEditorPage
from mtkgui.gui.case_store import (LockedCaseError, CaseStore,
                                   categorize, coerce_field)

CASES = [
    {"name": "Init Instruments", "kind": "op", "enable": True,
     "wait_ms": 100, "timeout_ms": 5000, "unit": "—",
     "threshold_min": "—", "threshold_max": "—", "test_dim": "op"},
    {"name": "Impedance Shorts (2 pts)", "kind": "test", "enable": True,
     "wait_ms": 100, "timeout_ms": 5000, "unit": "Ω",
     "threshold_min": 1.5, "threshold_max": "—", "test_dim": "impedance",
     "priority": 1, "instrument": "DAQM"},
    {"name": "PWR VDD_3V3 Voltage", "kind": "test", "enable": True,
     "wait_ms": 100, "timeout_ms": 5000, "unit": "V",
     "threshold_min": 3.267, "threshold_max": 3.333,
     "test_dim": "voltage", "priority": 1, "instrument": "DAQM",
     "power_domain": "SOURCE", "upstream": "SOURCE",
     "downstream": "VCORE", "notes": ""},
    {"name": "PWR VCORE Voltage", "kind": "test", "enable": True,
     "wait_ms": 100, "timeout_ms": 5000, "unit": "V",
     "threshold_min": 0.99, "threshold_max": 1.01,
     "test_dim": "voltage", "priority": 2, "instrument": "DAQM",
     "power_domain": "VDD_3V3", "upstream": "VDD_3V3",
     "downstream": "—"},
    {"name": "CLK XCLK_32K Frequency", "kind": "test", "enable": True,
     "wait_ms": 100, "timeout_ms": 5000, "unit": "Hz",
     "threshold_min": 32767.34, "threshold_max": 32768.66,
     "test_dim": "voltage", "priority": 1, "instrument": "DAQ"},
    {"name": "SIG XSIG_GPIO1 Continuity", "kind": "test", "enable": True,
     "wait_ms": 100, "timeout_ms": 5000, "unit": "Ω",
     "threshold_min": 1.5, "threshold_max": "—", "test_dim": "impedance",
     "priority": 3, "instrument": "DAQM"},
]

BASE_CFG = {"project": {"revision": "1.0"},
            "ict_test_cases": [dict(c) for c in CASES],
            "ict_case_audit": {"ai_version": "P1-16.1",
                               "gen_time": "2026-10-04T00:00:00Z",
                               "sources": ["net.txt"], "history": []}}


@pytest.fixture()
def page(tmp_path):
    yaml_path = tmp_path / "project.yaml"
    yaml_path.write_text(yaml.safe_dump(BASE_CFG, sort_keys=False,
                                        allow_unicode=True),
                         encoding="utf-8")
    store = CaseStore(snapshot_dir=str(tmp_path / "snaps"))
    return CaseEditorPage(str(yaml_path), store=store), store, \
        str(yaml_path)


# ------------------------------------------------------- categorize
def test_categorize_groups():
    assert categorize({"name": "PWR X Voltage"}) == "电源网络"
    assert categorize({"name": "CLK X Frequency"}) == "时钟网络"
    assert categorize({"name": "SIG X Continuity"}) == "信号网络"
    assert categorize({"name": "Fixture Lock", "kind": "op"}) == "操作流程"


# ------------------------------------------------------- coercion
def test_coerce_field_semantics_match_excel_importer():
    assert coerce_field("enable", "true") is True
    assert coerce_field("enable", "否") is False
    assert coerce_field("wait_ms", "250") == 250
    assert coerce_field("priority", "") == ""
    assert coerce_field("threshold_min", "3.26") == 3.26
    assert coerce_field("threshold_min", "—") == "—"
    assert coerce_field("notes", None) == ""
    with pytest.raises(ValueError):
        coerce_field("timeout_ms", "abc")
    with pytest.raises(ValueError):
        coerce_field("priority", "high")
    assert coerce_field("retry", "") is None
    assert coerce_field("retry", "2") == 2


def test_gui_editable_superset():
    from mtkgui.gui.case_store import GUI_EDITABLE
    assert set(EDITABLE) <= set(GUI_EDITABLE)
    assert {"retry", "skip_if"} <= set(GUI_EDITABLE)


# ------------------------------------------------------- store edit
def test_apply_case_edit_and_history(page):
    page_, store, yaml_path = page
    cfg = store.load(yaml_path)
    changes = store.apply_case_edit(
        cfg, "PWR VDD_3V3 Voltage",
        {"threshold_min": "3.20", "priority": "4", "retry": "2",
         "skip_if": "fixture_open"})
    assert len(changes) == 4
    case = next(c for c in cfg["ict_test_cases"]
                if c["name"] == "PWR VDD_3V3 Voltage")
    assert case["threshold_min"] == 3.20 and case["priority"] == 4
    assert case["retry"] == 2 and case["skip_if"] == "fixture_open"
    hist = store.history(cfg)
    assert hist[-1]["source"] == "gui-editor"
    assert {c["field"] for c in hist[-1]["changed"]} == \
        {"threshold_min", "priority", "retry", "skip_if"}


def test_apply_case_edit_unknown_and_illegal(page):
    page_, store, yaml_path = page
    cfg = store.load(yaml_path)
    with pytest.raises(KeyError):
        store.apply_case_edit(cfg, "no such case", {"notes": "x"})
    with pytest.raises(KeyError):
        store.apply_case_edit(cfg, "PWR VDD_3V3 Voltage",
                              {"ai_meta": {}})
    with pytest.raises(ValueError):
        store.apply_case_edit(cfg, "PWR VDD_3V3 Voltage",
                              {"wait_ms": "soon"})


def test_retry_empty_inherits_global(page):
    page_, store, yaml_path = page
    cfg = store.load(yaml_path)
    store.apply_case_edit(cfg, "PWR VDD_3V3 Voltage", {"retry": "3"})
    store.apply_case_edit(cfg, "PWR VDD_3V3 Voltage", {"retry": ""})
    case = next(c for c in cfg["ict_test_cases"]
                if c["name"] == "PWR VDD_3V3 Voltage")
    assert "retry" not in case, "empty retry removes the override key"


def test_lock_blocks_edits(page):
    page_, store, yaml_path = page
    cfg = store.load(yaml_path)
    store.set_locked(cfg, "PWR VDD_3V3 Voltage", True)
    assert store.is_locked(cfg, "PWR VDD_3V3 Voltage")
    with pytest.raises(LockedCaseError):
        store.apply_case_edit(cfg, "PWR VDD_3V3 Voltage", {"notes": "x"})
    store.set_locked(cfg, "PWR VDD_3V3 Voltage", False)
    store.apply_case_edit(cfg, "PWR VDD_3V3 Voltage", {"notes": "ok"})
    assert not store.is_locked(cfg, "PWR VDD_3V3 Voltage")


def test_dimension_toggle_skips_locked(page):
    page_, store, yaml_path = page
    cfg = store.load(yaml_path)
    store.set_locked(cfg, "Impedance Shorts (2 pts)", True)
    touched = store.set_dimension_enabled(cfg, "impedance", False)
    assert {c.case for c in touched} == {"SIG XSIG_GPIO1 Continuity"}
    shorts = next(c for c in cfg["ict_test_cases"]
                  if c["name"].startswith("Impedance"))
    assert shorts["enable"] is True, "locked case untouched"
    names = {c["name"] for c in cfg["ict_test_cases"]
             if c.get("test_dim") == "impedance" and not c["enable"]}
    assert names == {"SIG XSIG_GPIO1 Continuity"}


def test_edit_and_save_roundtrip(tmp_path):
    yaml_path = tmp_path / "project.yaml"
    yaml_path.write_text(yaml.safe_dump(BASE_CFG, sort_keys=False,
                                        allow_unicode=True),
                         encoding="utf-8")
    store = CaseStore(snapshot_dir=str(tmp_path / "snaps"))
    cfg = store.load(str(yaml_path))
    new_cfg, changes = store.edit_and_save(
        cfg, "PWR VCORE Voltage", {"threshold_max": "1.05"},
        str(yaml_path))
    assert changes
    reloaded = store.load(str(yaml_path))
    assert reloaded == new_cfg, "save round-trip"
    case = next(c for c in reloaded["ict_test_cases"]
                if c["name"] == "PWR VCORE Voltage")
    assert case["threshold_max"] == 1.05
    assert store.load_snapshot(
        sorted(x for x in __import__("os").listdir(store.snapshot_dir)
               if x.endswith(".yaml"))[-1][:-5]) == cfg, \
        "pre-edit snapshot captured original"


def _find_item(page_, name: str):
    for i in range(page_.tree.topLevelItemCount()):
        group = page_.tree.topLevelItem(i)
        for j in range(group.childCount()):
            if group.child(j).text(0) == name:
                return group.child(j)
    return None


# ------------------------------------------------------- GUI page
def test_page_tree_grouping_and_select(page):
    page_, store, yaml_path = page
    cats = [page_.tree.topLevelItem(i).text(0)
            for i in range(page_.tree.topLevelItemCount())]
    assert cats == ["电源网络", "时钟网络", "信号网络", "操作流程"]
    pw = cats.index("电源网络")
    child_texts = [page_.tree.topLevelItem(pw).child(j).text(0)
                   for j in range(page_.tree.topLevelItem(pw)
                                  .childCount())]
    assert "PWR VDD_3V3 Voltage" in child_texts
    # priority + dimension + status badges present
    item = page_.tree.topLevelItem(pw).child(0)
    assert item.text(2) in ("电压", "阻抗"), "dimension badge"
    assert item.text(3) in ("启用", "停用", "🔒已锁定")


def test_page_visual_edit_save_and_signal(page):
    page_, store, yaml_path = page
    fired = []
    page_.cases_applied.connect(fired.append)
    item = _find_item(page_, "PWR VDD_3V3 Voltage")
    assert item is not None
    page_.tree.setCurrentItem(item)
    assert page_.f_name.text() == "PWR VDD_3V3 Voltage"
    assert page_.f_upstream.text() == "SOURCE", "topology view"
    assert page_.f_downstream.text() == "VCORE"
    page_.f_hi.setText("3.40")
    page_.f_prio.setText("7")
    page_.f_retry.setText("2")
    page_.f_skip.setText("bench_only")
    page_.f_instrument.setCurrentText("DAQ")
    result = page_.on_save()
    assert result is not None
    saved = store.load(yaml_path)
    case = next(c for c in saved["ict_test_cases"]
                if c["name"] == "PWR VDD_3V3 Voltage")
    assert case["threshold_max"] == 3.40
    assert case["priority"] == 7 and case["retry"] == 2
    assert case["skip_if"] == "bench_only"
    assert case["instrument"] == "DAQ"
    assert fired, "cases_applied emitted"
    assert "gui-editor" in page_.trace.toPlainText()


def test_page_save_intercepts_locked(page):
    page_, store, yaml_path = page
    page_.interactive = False
    item = _find_item(page_, "PWR VCORE Voltage")
    assert item is not None
    page_.tree.setCurrentItem(item)
    cfg = store.load(yaml_path)
    store.set_locked(cfg, "PWR VCORE Voltage", True)
    store.save(cfg, yaml_path)
    page_.reload()
    page_.tree.setCurrentItem(_find_item(page_, "PWR VCORE Voltage"))
    page_.f_notes.setPlainText("nope")
    assert page_.on_save() is None, "locked save intercepted"
    reloaded = store.load(yaml_path)
    case = next(c for c in reloaded["ict_test_cases"]
                if c["name"] == "PWR VCORE Voltage")
    assert case.get("notes", "") == "", "locked value unchanged"


def test_page_lock_button_cycle(page):
    page_, store, yaml_path = page
    page_.tree.setCurrentItem(_find_item(page_, "CLK XCLK_32K Frequency"))
    page_.on_lock_toggle()
    assert store.is_locked(store.load(yaml_path),
                           "CLK XCLK_32K Frequency")
    page_.on_lock_toggle()
    assert not store.is_locked(store.load(yaml_path),
                               "CLK XCLK_32K Frequency")


def test_page_dimension_toggle_syncs(page):
    page_, store, yaml_path = page
    box = page_.dim_boxes["impedance"]
    assert box.isChecked(), "both impedance rows enabled -> checked"
    box.setChecked(False)
    reloaded = store.load(yaml_path)
    dims = {c["name"]: c["enable"] for c in reloaded["ict_test_cases"]
            if c.get("test_dim") == "impedance"}
    assert set(dims.values()) == {False}, "batch off applied"
    assert "impedance" in page_.trace.toPlainText() or \
        page_.dim_boxes["impedance"].isChecked() is False


def test_page_trace_shows_ai_provenance(page):
    page_, _store, _yaml_path = page
    text = page_.trace.toPlainText()
    assert "P1-16.1" in text, "AI version shown"
    assert "net.txt" in text, "AI sources shown"
    assert "版本锁定" in text
