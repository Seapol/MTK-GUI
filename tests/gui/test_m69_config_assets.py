# -*- coding: utf-8 -*-
"""M69: project-bound assets folder (M85: the GUI panel is gone).

Built-in assets stay READ-ONLY; each project owns
``projects/<Project>/assets_<Project>``.  Assets belong to the project:
an engineer prepares the folder by hand from the read-only template, so
the application never creates, edits or syncs it.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.fct_test_config import default_assets_dir  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------- menu entry
def test_tools_menu_has_no_config_assets_entry(qapp):
    """Assets belong to the project: engineers prepare `assets_<PROJECT>`
    by hand from the template, so Tools carries no assets panel any more
    (2026-11-08 user direction - the entry was confusing)."""
    from mtkgui.main_window import MainWindow
    w = MainWindow(role="SUPERVISOR", mode="Virtual")
    try:
        tools_action = [a for a in w.menuBar().actions()
                        if a.text() == "Tools"][0]
        tools = tools_action.menu()
        labels = [a.text() for a in tools.actions() if not a.isSeparator()]
        assert "Config assets for projects…" not in labels
        assert not hasattr(w, "act_assets_config")
        assert not hasattr(w, "_assets_dialog")
    finally:
        w.close()
        w.deleteLater()


# ------------------------------------------------- default_assets_dir priority
def test_default_assets_dir_priority(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    (base / "P1").mkdir(parents=True)
    (base / "P1" / "assets_P1").mkdir()
    (base / "P2").mkdir()
    (base / "P2" / "assets").mkdir()
    (base / "P3").mkdir()
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.chdir(tmp_path.parent)
    path, hint = default_assets_dir("P1", str(base), str(bundled))
    assert os.path.basename(path) == "assets_P1" and hint == ""
    path, hint = default_assets_dir("P2", str(base), str(bundled))
    assert os.path.basename(path) == "assets" and hint == ""
    path, hint = default_assets_dir("P3", str(base), str(bundled))
    assert path == os.path.normpath(str(bundled)) and hint
    # no project name -> bundled template
    path, hint = default_assets_dir("", str(base), str(bundled))
    assert path == os.path.normpath(str(bundled)) and hint == ""
