# -*- coding: utf-8 -*-
"""M0 dynamic GUI version label tests: version.json loading, fallback,
CI generator, status-bar rendering (mock, no real GUI render)."""
from __future__ import annotations

import json
import logging

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from mtkgui.gui_version import (  # noqa: E402
    FALLBACK_VERSION,
    generate_version_json,
    load_gui_version,
)
from mtkgui.main_window import MainWindow  # noqa: E402
from mtkgui.permissions import ROLE_SUPERVISOR  # noqa: E402


# ---------------------------------------------------------------- loading
def test_load_valid_full_version(tmp_path):
    f = tmp_path / "version.json"
    f.write_text(json.dumps({
        "major": 4, "branch": 1, "minor": 1, "build": "1287",
        "full_version": "v4.1.1.1287"}), encoding="utf-8")
    version, warning = load_gui_version(f)
    assert version == "v4.1.1.1287" and warning is None


def test_load_rebuilds_from_components(tmp_path):
    f = tmp_path / "version.json"
    f.write_text(json.dumps({
        "major": 4, "branch": 2, "minor": 3, "build": "0042"}),
        encoding="utf-8")
    version, warning = load_gui_version(f)
    assert version == "v4.2.3.0042" and warning is None


def test_missing_file_falls_back_with_warning(tmp_path, caplog):
    version, warning = load_gui_version(tmp_path / "none.json")
    assert version == FALLBACK_VERSION == "v4.1.1.0000"
    assert warning and "missing or unreadable" in warning
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING]
    assert warnings


def test_malformed_json_falls_back_with_warning(tmp_path, caplog):
    f = tmp_path / "version.json"
    f.write_text("{not json", encoding="utf-8")
    version, warning = load_gui_version(f)
    assert version == FALLBACK_VERSION
    assert warning and "static fallback" in warning
    assert any(r.levelno == logging.WARNING
               for r in caplog.records)


def test_malformed_full_version_rebuilt_from_components(tmp_path):
    f = tmp_path / "version.json"
    f.write_text(json.dumps({
        "major": 4, "branch": 1, "minor": 1, "build": "1287",
        "full_version": "oops"}), encoding="utf-8")
    version, warning = load_gui_version(f)
    assert version == "v4.1.1.1287" and warning is None


def test_useless_payload_falls_back(tmp_path):
    f = tmp_path / "version.json"
    f.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    version, warning = load_gui_version(f)
    assert version == FALLBACK_VERSION and warning


# ------------------------------------------------------------- CI helper
def test_generate_version_json_random_build(tmp_path):
    f = tmp_path / "version.json"
    first = generate_version_json(f)
    second = generate_version_json(f)
    assert first["full_version"] == f"v4.1.1.{first['build']}"
    assert 0 <= int(first["build"]) <= 9999
    assert len(str(first["build"])) == 4
    # the build number regenerates (random per build)
    assert first["full_version"] != second["full_version"] \
        or first["build"] != second["build"]
    on_disk = json.loads(f.read_text(encoding="utf-8"))
    assert on_disk == second


# ----------------------------------------------------------- status bar
def test_status_bar_shows_gui_version(qapp, monkeypatch):
    monkeypatch.setattr(
        "mtkgui.gui_version.load_gui_version",
        lambda path=None: ("v4.1.1.1287", None))
    w = MainWindow(role=ROLE_SUPERVISOR)
    try:
        assert isinstance(w.status_version, QLabel)
        assert w.status_version.text() == "GUI version: v4.1.1.1287"
        # display-only: not selectable / not editable
        assert w.status_version.textInteractionFlags() \
            == Qt.TextInteractionFlag.NoTextInteraction
    finally:
        w.close()
        w.deleteLater()


def test_status_bar_fallback_with_warning_log(qapp, monkeypatch):
    monkeypatch.setattr(
        "mtkgui.gui_version.load_gui_version",
        lambda path=None: ("v4.1.1.0000", "version.json missing"))
    w = MainWindow(role=ROLE_SUPERVISOR)
    try:
        assert w.status_version.text() == \
            "GUI version: v4.1.1.0000"
        assert w.gui_version_warning == "version.json missing"
    finally:
        w.close()
        w.deleteLater()


def test_other_status_bar_components_intact(qapp, monkeypatch):
    """No changes to the neighboring status bar components."""
    monkeypatch.setattr(
        "mtkgui.gui_version.load_gui_version",
        lambda path=None: (FALLBACK_VERSION, None))
    w = MainWindow(role=ROLE_SUPERVISOR)
    try:
        for attr in ("status_role", "status_mode", "status_user",
                     "status_progress", "instr_status",
                     "serial_status", "status_date"):
            assert getattr(w, attr) is not None, attr
        assert w.status_date.text().count("-") == 2
    finally:
        w.close()
        w.deleteLater()
