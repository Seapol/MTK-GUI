# -*- coding: utf-8 -*-
"""M11 — Event Log: timestamp dedup + Simplified / Detailed levels.

Covers the level model (pure functions), the role defaults, the
QSettings persistence, the UI filter vs. the always-full auto-save
file, and the Settings menu state per role.
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.event_log_levels import (  # noqa: E402
    DETAILED,
    IMPORTANT,
    SIMPLIFIED,
    TEST,
    normalize_level,
    resolve_level,
    should_display,
    strip_leading_stamp,
)
from mtkgui.main_window import (  # noqa: E402
    EVENT_LOG_LEVEL_KEY,
    OPERATOR_EVENT_LOG_TIP,
    MainWindow,
    load_event_log_level,
    save_event_log_level,
)
from mtkgui.permissions import ROLE_OPERATOR, ROLE_SUPERVISOR  # noqa: E402

MainWindow.__test__ = False

STAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tmp_settings(tmp_path):
    """Isolated QSettings file (never the developer's preferences)."""
    return QSettings(str(tmp_path / "settings.ini"),
                     QSettings.Format.IniFormat)


# ---------------------------------------------------------------------------
# F1 — leading timestamp dedup
# ---------------------------------------------------------------------------


def test_strip_leading_full_datetime_stamp():
    """workflow-page lines carry '[YYYY-MM-DD HH:MM:SS] ' in front."""
    assert strip_leading_stamp(
        "[2026-10-23 22:07:38] DAQ AI: 10 rails captured") == \
        "DAQ AI: 10 rails captured"


def test_strip_leading_time_only_stamp():
    """the old call-site format '[HH:MM:SS] ' is stripped too."""
    assert strip_leading_stamp("[22:07:38] Logged in: Supervisor") == \
        "Logged in: Supervisor"


def test_strip_tolerates_one_space_and_repeats():
    """A single space after the bracket is part of the stamp, and a
    doubly stamped line keeps only the caller's text."""
    assert strip_leading_stamp(
        "[2026-10-23 22:07:38] [22:07:38] Yaml saved: a.yaml") == \
        "Yaml saved: a.yaml"


def test_strip_keeps_mid_text_timestamp():
    """A stamp that is NOT leading belongs to the message."""
    text = "Retry after [22:07:38] timeout"
    assert strip_leading_stamp(text) == text


def test_strip_ignores_level_tags():
    """Producer level tags are NOT timestamps - they stay in the text."""
    assert strip_leading_stamp("[INFO] Excel import done") == \
        "[INFO] Excel import done"


# ---------------------------------------------------------------------------
# F2 — level model
# ---------------------------------------------------------------------------


def test_normalize_level():
    assert normalize_level("WARN") == "WARNING"
    assert normalize_level("warn") == "WARNING"
    assert normalize_level("error") == "ERROR"
    assert normalize_level("DEBUG") == "DEBUG"
    assert normalize_level(None) == "INFO"
    assert normalize_level("bogus") == "INFO"
    assert normalize_level(TEST) == TEST
    assert normalize_level(IMPORTANT) == IMPORTANT


def test_resolve_level_consumes_producer_tag():
    """'[INFO]/[WARN]/[ERROR]' signal lines map onto the level model;
    the tag text itself is kept."""
    assert resolve_level("[WARN] pump slow", "INFO") == "WARNING"
    assert resolve_level("[ERROR] rack lost", "INFO") == "ERROR"
    assert resolve_level("[DEBUG] tick", "INFO") == "DEBUG"


@pytest.mark.parametrize("text", [
    "VDD_1V8 impedance -> PASS",
    "Clock 32.768 kHz -> FAIL",
    "Rail capture done",
    "U2355A AI acquisition error",
])
def test_resolve_level_auto_classifies_test_results(text):
    """Verdict lines (PASS / FAIL / Done / Error) are TEST lines."""
    assert resolve_level(text, "INFO") == TEST


@pytest.mark.parametrize("text,expected", [
    ("WARNING: statistics record not saved", "WARNING"),
    ("ERROR: rack connection lost", "ERROR"),
    ("DEBUG: internal tick", "DEBUG"),
    ("Warning: something", "WARNING"),
])
def test_resolve_level_plain_text_prefix(text, expected):
    """A plain 'WARNING:' / 'ERROR:' message prefix maps onto the level
    model, so such lines survive the Simplified filter."""
    assert resolve_level(text, "INFO") == expected


def test_resolve_level_explicit_marks_win():
    assert resolve_level("plain note", IMPORTANT) == IMPORTANT
    assert resolve_level("PASS", IMPORTANT) == IMPORTANT
    assert resolve_level("[INFO] plain", "TEST") == TEST
    assert resolve_level("plain note", "INFO") == "INFO"


@pytest.mark.parametrize("level,detailed,shown", [
    ("DEBUG", False, False),
    ("INFO", False, False),
    (TEST, False, True),
    ("WARNING", False, True),
    ("ERROR", False, True),
    (IMPORTANT, False, True),
    ("DEBUG", True, True),
    ("INFO", True, True),
    (TEST, True, True),
    ("ERROR", True, True),
])
def test_should_display_matrix(level, detailed, shown):
    """Simplified hides DEBUG / plain INFO only - WARNING, ERROR and
    TEST are never hidden; Detailed shows everything."""
    assert should_display(level, detailed) is shown


# ---------------------------------------------------------------------------
# F3 — role defaults + persistence
# ---------------------------------------------------------------------------


def test_role_defaults(tmp_settings):
    """Operator -> simplified, Supervisor -> detailed (no saved value)."""
    assert load_event_log_level(ROLE_OPERATOR, tmp_settings) == SIMPLIFIED
    assert load_event_log_level(ROLE_SUPERVISOR, tmp_settings) == DETAILED


def test_persistence_round_trip(tmp_settings):
    """A supervisor choice is written to event_log/level and read back;
    an Operator is clamped to simplified even when detailed is saved."""
    save_event_log_level(SIMPLIFIED, tmp_settings)
    assert tmp_settings.value(EVENT_LOG_LEVEL_KEY) == SIMPLIFIED
    assert load_event_log_level(ROLE_SUPERVISOR, tmp_settings) == SIMPLIFIED
    save_event_log_level(DETAILED, tmp_settings)
    assert load_event_log_level(ROLE_SUPERVISOR, tmp_settings) == DETAILED
    assert load_event_log_level(ROLE_OPERATOR, tmp_settings) == SIMPLIFIED


def test_invalid_saved_value_falls_back_to_detailed(tmp_settings):
    tmp_settings.setValue(EVENT_LOG_LEVEL_KEY, "verbose")
    assert load_event_log_level(ROLE_SUPERVISOR, tmp_settings) == DETAILED


def test_operator_menu_entries_disabled(qapp):
    """Operator: both actions stay VISIBLE but disabled, simplified is
    checked, and the tooltip explains why."""
    w = MainWindow(role=ROLE_OPERATOR, mode="Real")
    try:
        assert w.act_event_log_simplified.isVisible()
        assert w.act_event_log_detailed.isVisible()
        assert not w.act_event_log_simplified.isEnabled()
        assert not w.act_event_log_detailed.isEnabled()
        assert w.act_event_log_detailed.toolTip() == OPERATOR_EVENT_LOG_TIP
        assert w.act_event_log_simplified.isChecked()
        assert not w.act_event_log_detailed.isChecked()
        # the operator default is the simplified log
        assert w._event_log_level == SIMPLIFIED
    finally:
        w.close()
        w.deleteLater()


def test_supervisor_menu_defaults_and_switch(qapp):
    """Supervisor: detailed by default, both entries enabled; the menu
    switch persists the choice for the next login."""
    w = MainWindow(role=ROLE_SUPERVISOR, mode="Real")
    try:
        assert w.act_event_log_detailed.isChecked()
        assert w.act_event_log_simplified.isEnabled()
        assert w.act_event_log_detailed.isEnabled()
        assert w.act_event_log_detailed.toolTip() != OPERATOR_EVENT_LOG_TIP
        w.act_event_log_simplified.trigger()
        assert w._event_log_level == SIMPLIFIED
        assert w.act_event_log_simplified.isChecked()
        assert not w.act_event_log_detailed.isChecked()
        assert QSettings(_org(), _app()).value(EVENT_LOG_LEVEL_KEY) == \
            SIMPLIFIED
    finally:
        w.close()
        w.deleteLater()
    # next login keeps the saved choice
    w2 = MainWindow(role=ROLE_SUPERVISOR, mode="Real")
    try:
        assert w2._event_log_level == SIMPLIFIED
        assert w2.act_event_log_simplified.isChecked()
    finally:
        w2.close()
        w2.deleteLater()


def _org():
    from mtkgui.style import APP_ORG
    return APP_ORG


def _app():
    from mtkgui.style import APP_NAME
    return APP_NAME


# ---------------------------------------------------------------------------
# F1/F2 in the window: one stamp per line, UI filter, full auto-save
# ---------------------------------------------------------------------------


def test_single_stamp_per_line(qapp):
    """A caller-embedded stamp never doubles the rendered stamp."""
    w = MainWindow(role=ROLE_SUPERVISOR, mode="Real")
    try:
        w._append_event_log(
            "[2026-10-23 22:07:38] DAQ AI: 10 rails captured")
        last = w.event_log.toPlainText().strip().splitlines()[-1]
        assert STAMP_RE.findall(last) and len(STAMP_RE.findall(last)) == 1
        assert last.endswith("DAQ AI: 10 rails captured")
        assert "[" not in last
    finally:
        w.close()
        w.deleteLater()


def test_simplified_filter_hides_info_and_keeps_test(qapp):
    """Operator UI shows TEST / WARNING / ERROR / IMPORTANT only."""
    w = MainWindow(role=ROLE_OPERATOR, mode="Real")
    try:
        w._append_event_log("[DEBUG] internal tick")
        w._append_event_log("plain informational note")
        w._append_event_log("[ERROR] rack connection lost")
        w._append_event_log("VDD_1V8 impedance -> PASS")
        w._append_event_log("Sensitive business event", level=IMPORTANT)
        log = w.event_log.toPlainText()
        assert "internal tick" not in log
        assert "plain informational note" not in log
        assert "rack connection lost" in log
        assert "-> PASS" in log
        assert "Sensitive business event" in log
        # startup LOGIN line is an important event in both modes
        assert "Logged in: Operator" in log
    finally:
        w.close()
        w.deleteLater()


def test_detailed_shows_everything(qapp):
    w = MainWindow(role=ROLE_SUPERVISOR, mode="Real")
    try:
        w._append_event_log("[DEBUG] internal tick")
        w._append_event_log("plain informational note")
        log = w.event_log.toPlainText()
        assert "internal tick" in log
        assert "plain informational note" in log
    finally:
        w.close()
        w.deleteLater()


def test_autosave_file_keeps_full_detail_in_simplified_mode(qapp, tmp_path):
    """The audit file always records every line, even when the UI runs
    the simplified filter."""
    w = MainWindow(role=ROLE_OPERATOR, mode="Real")
    try:
        log_path = tmp_path / "event.log"
        w._event_log_file.close()
        w._event_log_file = open(log_path, "w", encoding="utf-8")
        w._append_event_log("[DEBUG] internal tick")
        w._append_event_log("plain informational note")
        w._append_event_log("VDD_1V8 impedance -> PASS")
        w._event_log_file.close()
        w._event_log_file = None
        text = log_path.read_text(encoding="utf-8")
        assert "internal tick" in text
        assert "plain informational note" in text
        assert "-> PASS" in text
        for line in text.strip().splitlines():
            assert line.startswith(STAMP_RE.match(line).group(0))
            assert len(STAMP_RE.findall(line)) == 1
    finally:
        w.close()
        w.deleteLater()
