# -*- coding: utf-8 -*-
"""M141: Close Yaml also forgets the project's draft state.

The draft store (``config/yamlbuild_state.json``) is restart-safe on
purpose, so closing a project must remove its entry - otherwise the next
launch reloads the project the operator just closed (user report:
an FCT-only YAML came back with the previous 96624 ICT data).
"""

from __future__ import annotations

import pytest

from mtkgui.gui.yamlbuild import store


def test_close_forgets_only_that_project(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_DIR", tmp_path)
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "state.json")
    store.save_project_state("96624", {"plan_version": "1.0.0",
                                       "parsed_nets": {"route": "A"}})
    store.save_project_state("FRDM-IMX93", {"plan_version": "1.0.0"})

    assert store.forget_project_state("96624") is True

    assert store.load_project_state("96624") is None
    kept = store.load_project_state("FRDM-IMX93")
    assert kept is not None and kept["plan_version"] == "1.0.0"
    # the entry is really gone from the file, not only from the return
    assert "96624" not in (tmp_path / "state.json").read_text(encoding="utf-8")


def test_forget_on_a_missing_store_is_harmless(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_DIR", tmp_path)
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "none.json")
    assert store.forget_project_state("anything") is True
