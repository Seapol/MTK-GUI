# -*- coding: utf-8 -*-
"""GUI version label tests - unified to the single release version
(user directive 2026-10-14): every label renders mtkgui.__version__
(starting v1.0.0.0); the retired M0 version.json scheme is ignored."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from mtkgui import __version__  # noqa: E402
from mtkgui.gui_version import load_gui_version  # noqa: E402
from mtkgui.main_window import MainWindow  # noqa: E402

MainWindow.__test__ = False


# ---------------------------------------------------------------- loading
def test_load_returns_release_version(tmp_path):
    """The release version is THE version - a leftover version.json
    from the retired M0 scheme is ignored entirely (no warning: there
    is no dynamic source left that could fail)."""
    stale = tmp_path / "version.json"
    stale.write_text('{"full_version": "v4.1.1.1287"}', encoding="utf-8")
    version, warning = load_gui_version(stale)
    assert version == __version__ == "v1.0.0.0"
    assert warning is None


def test_load_without_any_source():
    """No path, no version.json anywhere - still the release version."""
    version, warning = load_gui_version()
    assert version == __version__ and warning is None


# ------------------------------------------------------------- status bar
def test_status_bar_shows_release_version(qapp):
    """The status bar label renders `GUI version: v1.0.0.0` - never a
    git tag or a random CI build number."""
    window = MainWindow(role="Supervisor", mode="Virtual")
    try:
        assert window.status_version.text() == f"GUI version: {__version__}"
        assert window.gui_version_warning is None
    finally:
        window.deleteLater()
