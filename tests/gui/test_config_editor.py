# -*- coding: utf-8 -*-
"""P2-2 visual YAML config system unit tests (headless offscreen)."""
from __future__ import annotations

import os

import pytest
import yaml

from mtkgui.gui.config_page import ConfigPage
from mtkgui.gui.config_spec import (FIELDS_BY_PATH, SECTIONS, coerce_value,
                                    get_path, iter_paths, set_path,
                                    validate_config, validate_value)
from mtkgui.gui.config_store import ConfigStore, apply_registered, deep_diff

BASE_CFG = {
    "project": {"software": "mtk-gui v2.0.0", "revision": "1.0",
                "created": "2026-10-04"},
    "product": {"part_number": "FRDM-IMX93", "core_id": "12345",
                "batch": "Dev"},
    "test_workflow": {"stop_if_failure": False, "stop_if_any_short": True,
                      "retry": 0},
    "equipment": {"host": {"fields": {"OS": "Win11", "Test SW": "gui"}}},
}


@pytest.fixture()
def workspace(tmp_path):
    yaml_path = tmp_path / "project.yaml"
    yaml_path.write_text(yaml.safe_dump(BASE_CFG, sort_keys=False,
                                        allow_unicode=True),
                         encoding="utf-8")
    return str(yaml_path), ConfigStore(snapshot_dir=str(tmp_path / "snaps"))


# ------------------------------------------------------- path helpers
def test_get_set_path_roundtrip():
    cfg = {"a": {"b": {"c": 1}}}
    assert get_path(cfg, "a.b.c") == 1
    set_path(cfg, "a.b.d", 2)
    set_path(cfg, "x.y", 9)
    assert cfg["a"]["b"]["d"] == 2 and cfg["x"]["y"] == 9


def test_iter_paths_leaves():
    leaves = dict(iter_paths(BASE_CFG))
    assert leaves["product.part_number"] == "FRDM-IMX93"


# ------------------------------------------------------- validation
def test_validate_baseline_ok():
    assert validate_config(BASE_CFG) == []


@pytest.mark.parametrize("path,value,frag", [
    ("test_workflow.retry", -1, "min"),
    ("test_workflow.retry", 10, "max"),
    ("test_workflow.retry", "abc", "not a number"),
    ("test_workflow.retry", 1.5, "integer"),
    ("test_workflow.global_timeout_s", 0, "min"),
    ("test_workflow.schedule_mode", "wild", "one of"),
    ("sharepoint.site_url", "ftp://x", "URL"),
    ("sharepoint.site_url", "http://ok.com", None),  # legal
    ("project.revision", "bad revision!", "pattern"),
    ("product.part_number", "", "required"),
    ("product.part_number", None, "required"),
    ("test_workflow.stop_if_failure", "maybe", "boolean"),
    ("sharepoint.upload_retry_count", 9, None),  # legal
])
def test_validate_value_matrix(path, value, frag):
    issue = validate_value(FIELDS_BY_PATH[path], value)
    if frag is None:
        assert issue is None
    else:
        assert issue is not None and frag in issue.reason


def test_validate_sharepoint_full_section():
    cfg = {"sharepoint": {"enabled": True,
                          "site_url": "https://sp.company.com/p/ict",
                          "username": "op01", "password": "secret",
                          "token": "tok-123", "upload_retry_count": 5,
                          "resume_on_disconnect": True,
                          "overwrite_policy": "skip",
                          "project_dir": "ICT/2026",
                          "archive_whitelist": "*.pdf\n*.csv"}}
    for path, val in dict(iter_paths(cfg)).items():
        assert validate_value(FIELDS_BY_PATH[path], val) is None, path


def test_coerce_value_types():
    int_f = FIELDS_BY_PATH["test_workflow.retry"]
    bool_f = FIELDS_BY_PATH["test_workflow.stop_if_failure"]
    assert coerce_value(int_f, "3") == 3
    assert coerce_value(int_f, 3.0) == 3
    assert coerce_value(bool_f, "true") is True
    assert coerce_value(bool_f, "no") is False
    assert coerce_value(bool_f, True) is True


def test_validate_path_exists_flag(tmp_path):
    f = tmp_path / "img.bin"
    f.write_bytes(b"x")
    spec = FIELDS_BY_PATH["firmware.fat_image"]  # registry: exists=True
    assert validate_value(spec, str(f)) is None
    issue = validate_value(spec, "/no/such/file")
    assert issue is not None and "does not exist" in issue.reason
    assert "\x00" in str(validate_value(spec, "a\x00b").value) or \
        "NUL" in str(validate_value(spec, "a\x00b").reason)


# ------------------------------------------------------- store
def test_apply_registered_rejects_unknown_path():
    with pytest.raises(KeyError):
        apply_registered(BASE_CFG, {"made.up.path": 1})


def test_apply_and_save_preserves_unregistered(workspace):
    yaml_path, store = workspace
    new_cfg, changes = store.apply_and_save(
        BASE_CFG, {"test_workflow.retry": "2"}, yaml_path)
    assert get_path(new_cfg, "project.created") == "2026-10-04"
    assert get_path(new_cfg, "equipment.host.fields.Test SW") == "gui"
    assert any(ch.path == "test_workflow.retry" for ch in changes)


def test_save_formatted_roundtrip(workspace):
    yaml_path, store = workspace
    new_cfg, _ = store.apply_and_save(
        BASE_CFG, {"sharepoint.enabled": True,
                   "sharepoint.site_url": "https://x.com/a"}, yaml_path)
    reloaded = store.load(yaml_path)
    assert reloaded == new_cfg
    raw = open(yaml_path, encoding="utf-8").read()
    assert raw.index("project:") < raw.index("product:")  # stable order


def test_snapshot_rollback_and_diff(workspace):
    yaml_path, store = workspace
    v2, _ = store.apply_and_save(
        BASE_CFG, {"test_workflow.retry": 2, "product.batch": "MP"},
        yaml_path, snapshot_note="unit")
    snaps = store.list_snapshots()
    assert len(snaps) == 1 and snaps[0].note == "unit"
    restored, diffs = store.rollback(v2, snaps[0].snap_id)
    assert get_path(restored, "test_workflow.retry") == 0
    assert get_path(restored, "product.batch") == "Dev"
    assert {(c.path, c.new) for c in diffs} == {
        ("test_workflow.retry", 0), ("product.batch", "Dev")}


def test_deep_diff_added_removed():
    a = {"x": 1, "y": {"z": 2}}
    b = {"x": 1, "y": {"z": 3}, "w": 4}
    changes = {c.path: c for c in deep_diff(a, b)}
    assert changes["y.z"].old == 2 and changes["y.z"].new == 3
    assert changes["w"].old is None and changes["w"].new == 4


# ------------------------------------------------------- GUI page
def test_page_seed_realtime_validation_and_hot_apply(workspace, qapp):
    yaml_path, store = workspace
    page = ConfigPage(yaml_path, store=store)
    applied = []
    page.config_applied.connect(applied.append)

    retry = page._editors["test_workflow.retry"]
    retry.setText("-3")
    assert page._validate_field(FIELDS_BY_PATH["test_workflow.retry"]) \
        is not None
    retry.setText("1")
    assert page.validate_form() == []

    page._editors["sharepoint.site_url"].setText("https://sp.corp.com/ict")
    page._editors["sharepoint.enabled"].setChecked(True)
    result = page.on_save()
    assert result is not None
    saved, changes = result
    assert get_path(saved, "test_workflow.retry") == 1
    assert get_path(saved, "sharepoint.enabled") is True
    assert applied and applied[-1] == saved  # hot-effect signal fired


def test_page_blocks_illegal_save(workspace, qapp):
    yaml_path, store = workspace
    page = ConfigPage(yaml_path, store=store)
    page.interactive = False  # headless-safe (no modal dialogs)
    page._editors["test_workflow.retry"].setText("999")
    page._editors["product.batch"].setText("")  # required emptied
    assert page.on_save() is None  # intercepted
    assert "拦截" in page.summary.text()  # user-visible status fired
    # nothing written
    assert store.load(yaml_path)["test_workflow"]["retry"] == 0


def test_page_rollback(workspace, qapp):
    yaml_path, store = workspace
    page = ConfigPage(yaml_path, store=store)
    page._editors["test_workflow.retry"].setText("4")
    assert page.on_save() is not None
    page._refresh_snapshots()
    assert page.rollback_combo.count() >= 1
    page.on_rollback()  # rolls back to pre-save snapshot (retry=0)
    assert store.load(yaml_path)["test_workflow"]["retry"] == 0


def test_page_all_registered_sections_rendered(workspace, qapp):
    yaml_path, store = workspace
    page = ConfigPage(yaml_path, store=store)
    expected = {f.path for fields in SECTIONS.values() for f in fields}
    assert set(page._editors) == expected
    assert {"project", "firmware", "equipment", "sharepoint"} == \
        set(SECTIONS)
