# -*- coding: utf-8 -*-
"""v2/C3: config / settings / event-log path plumbing.

Four contracts:
  * ``settings.json`` is written once with the factory defaults, unknown
    keys are ignored, known keys round-trip;
  * the event log lives OUTSIDE the work dir (``<station>/logs/event``);
  * the shipped ``permissions.json`` carries exactly the 13 keys of
    ``PERMISSION_LABELS``;
  * the performance timing log is named
    ``_performance_timing_<YYYYMMDDTHHMMSS>.log``.
"""
from __future__ import annotations

import json
import re

from mtkgui import app_paths, startup_timing
from mtkgui.permissions import PERMISSION_LABELS


def test_settings_json_roundtrip(tmp_path, monkeypatch):
    """Defaults written once; unknown key ignored; known key round-trips."""
    monkeypatch.setenv("MTKGUI_CONFIG_DIR", str(tmp_path / "config"))
    cfg = app_paths.ensure_config()
    path = cfg / "settings.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == \
        app_paths.SETTINGS_DEFAULTS

    # a second seed never overwrites the local copy
    app_paths.set_setting("theme", "Dark")
    app_paths.ensure_config()
    assert app_paths.get_setting("theme") == "Dark"

    # unknown keys are ignored (schema is closed)
    payload = dict(app_paths.SETTINGS_DEFAULTS)
    payload["not_a_key"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert "not_a_key" not in app_paths.load_settings()
    assert app_paths.get_setting("not_a_key", "absent") == "absent"

    app_paths.set_setting("slow_span_threshold_s", 0.5)
    assert app_paths.get_setting("slow_span_threshold_s") == 0.5


def test_event_log_outside_project(tmp_path, monkeypatch):
    """The event path is not under the work dir and carries project + stamp."""
    from mtkgui import report_paths

    work = tmp_path / "work"
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(work))
    path = report_paths.event_log_path("P-96317")
    assert work not in path.parents
    assert path.parent == app_paths.event_log_dir()
    assert re.fullmatch(r"event_P-96317_\d{8}T\d{6}\.log", path.name), path


def test_permissions_has_all_keys():
    """The shipped factory JSON carries exactly the 13 permission keys."""
    path = app_paths.factory_config_dir() / "permissions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == set(PERMISSION_LABELS)
    assert len(data) == 13


def test_timing_log_name():
    """One name per launch: _performance_timing_<YYYYMMDDTHHMMSS>.log."""
    name = startup_timing.log_file_name()
    assert re.fullmatch(r"_performance_timing_\d{8}T\d{6}\.log", name), name
