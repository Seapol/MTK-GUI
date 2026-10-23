# -*- coding: utf-8 -*-
"""M10-FIX1 W0 - frozen Help packaging.

The PyInstaller onedir bundle ships ``docs/help`` into
``_internal/docs/help`` (MTK_GUI_windows.spec / MTK_GUI.spec), which is
``sys._MEIPASS`` at runtime.  These tests simulate that layout (no
PyInstaller run needed) and assert the frozen Help pages are not empty,
with the dev tree still used outside a bundle.
"""
from __future__ import annotations

import sys
from pathlib import Path

from mtkgui.gui import help_content

REPO_HELP = Path(help_content.__file__).resolve().parents[2] / "docs" / "help"


def _frozen_layout(root: Path) -> Path:
    """Minimal ``_internal/docs/help`` with one chapter + one image."""
    help_dir = root / "docs" / "help"
    (help_dir / "images").mkdir(parents=True)
    (help_dir / "01_overview.md").write_text(
        "# Overview\n\nThe MTK GUI station overview.\n\n"
        "![station](images/station.png)\n", encoding="utf-8")
    (help_dir / "images" / "station.png").write_bytes(b"\x89PNG\r\n")
    return help_dir


def _unfreeze(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)


def test_frozen_help_root_uses_meipass(monkeypatch, tmp_path):
    expected = _frozen_layout(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert help_content._help_root() == expected

    monkeypatch.setattr(help_content, "HELP_ROOT", help_content._help_root())
    html = help_content.guide_page_html()
    assert "Overview" in html
    assert "The MTK GUI station overview." in html
    # the screenshot resolves inside the bundle, not the dev tree
    assert f'{expected.as_uri()}/images/station.png' in html

    (expected / "version_history.md").write_text(
        "# Version History\n\nV4.0 frozen build\n", encoding="utf-8")
    assert "V4.0 frozen build" in help_content.version_history_page_html()


def test_dev_help_root_is_the_repo_tree(monkeypatch):
    _unfreeze(monkeypatch)
    root = help_content._help_root()
    assert root == REPO_HELP
    assert (root / "01_overview.md").is_file()
    assert "MTK GUI User Guide" in help_content.guide_page_html()


def test_frozen_without_bundled_docs_falls_back_to_dev_tree(monkeypatch,
                                                            tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert help_content._help_root() == REPO_HELP
