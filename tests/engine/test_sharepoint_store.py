# -*- coding: utf-8 -*-
"""M86: per-project SharePoint config / state store (Qt-free)."""
from __future__ import annotations

import json

import pytest

from mtkgui import sharepoint_store as store
from mtkgui.report_paths import clean_name, work_dir


@pytest.fixture(autouse=True)
def _project(monkeypatch, tmp_path):
    monkeypatch.setenv("MTKGUI_PROJECT", "M86-PROJ")
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    yield


def test_project_dir_is_under_work_sharepoint_and_project_key(tmp_path):
    path = store.project_dir()
    assert path == work_dir() / "sharepoint" / clean_name("M86-PROJ", "x")
    assert path.is_dir()
    assert store.config_path().parent == path
    assert store.state_path().name == "state.json"
    assert store.ledger_path().name == "upload_ledger.json"


def test_config_roundtrips_through_the_store():
    section = {"enabled": True, "site_url": "https://corp.example/ict",
               "upload_mode": "sync", "dest_segments": ["P", "ID"]}
    store.save_config(section)
    assert store.load_config() == section
    assert store.load_config() is not section


def test_state_is_atomic_and_survives_truncated_file():
    store.save_state(light="ok", pending=["a.pdf"], last_result="OK")
    state = store.load_state()
    assert state["light"] == "ok"
    assert state["pending"] == ["a.pdf"]
    assert state["last_result"] == "OK"
    assert not store.state_path().with_suffix(".tmp").exists()

    store.state_path().write_text('{"light": "ok", "pending": [',
                                  encoding="utf-8")
    recovered = store.load_state()
    assert recovered["light"] == "off"
    assert recovered["pending"] == []


def test_identity_folder_is_never_empty(monkeypatch):
    monkeypatch.setattr(store.identity, "identity_prefix", lambda: "")
    monkeypatch.setattr(store.identity, "get_user", lambda: "")
    monkeypatch.setattr(store.identity, "get_station_id", lambda: "")
    assert store.identity_folder() == "operator"

    monkeypatch.setattr(store.identity, "identity_prefix",
                        lambda: "[ST|op]")
    name = store.identity_folder()
    assert name and "/" not in name and "\\" not in name
    assert "|" not in name and "[" not in name


def test_legacy_config_is_migrated_once_and_kept(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy" / "sharepoint_upload.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"sharepoint": {"site_url": "old",
                                                 "enabled": True}}),
                      encoding="utf-8")
    monkeypatch.setattr(store, "LEGACY_CONFIG", legacy)

    assert store.migrate_legacy_config() is True
    assert store.load_config() == {"site_url": "old", "enabled": True}
    assert legacy.is_file(), "the legacy file must stay in place"
    assert store.migrate_legacy_config() is False       # only once
