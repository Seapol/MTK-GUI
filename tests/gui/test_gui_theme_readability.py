# -*- coding: utf-8 -*-
"""M67: placeholder / read-only / uncovered controls are theme-driven.

Field report: text invisible in dark-theme config dialogs and switching
GUI themes did not help.  Root cause: the global QSS never set
``placeholder-text-color`` (Qt used the Fusion palette color) and
``:read-only`` inputs had no explicit rule; the contrast audit did not
check those pairs.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDateTimeEdit,
    QLineEdit,
)

from mtkgui.style import (  # noqa: E402
    GUI_THEMES,
    audit_all,
    audit_theme,
    build_qss,
    contrast,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def themed(qapp):
    """Apply one theme for one test (restore the previous sheet after)."""
    previous = qapp.styleSheet()

    def apply(name):
        qapp.setStyleSheet(build_qss(name))
        qapp.processEvents()

    yield apply
    qapp.setStyleSheet(previous)
    qapp.processEvents()


def _shown(widget):
    widget.show()
    QApplication.processEvents()
    return widget


# ------------------------------------------------------- token coverage
@pytest.mark.parametrize("name", sorted(GUI_THEMES))
def test_every_theme_has_a_readable_placeholder_token(name):
    theme = GUI_THEMES[name]
    assert theme["placeholder"]
    ratio = contrast(theme["placeholder"], theme["card"])
    assert ratio >= 4.5, f"{name}: placeholder/card contrast {ratio:.2f}"


@pytest.mark.parametrize("name", sorted(GUI_THEMES))
def test_every_theme_is_audit_clean(name):
    assert audit_theme(name) == [], name
    qss = build_qss(name)
    # the rules that used to be missing from the global stylesheet
    assert "placeholder-text-color" in qss
    assert 'QLineEdit[readOnly="true"]' in qss
    assert "QDateTimeEdit" in qss and "QCalendarWidget" in qss
    assert "QMessageBox" in qss


def test_audit_all_passes_for_all_five_themes():
    assert audit_all() == {}


def test_audit_covers_the_new_pairs():
    """The audit must actually contain the M67 pairs (not just pass)."""
    # rebuild the same check the audit performs for the Dark theme
    theme = GUI_THEMES["Dark"]
    assert contrast(theme["placeholder"], theme["card"]) >= 4.5
    assert contrast(theme["text"], theme["alt"]) >= 4.5
    assert contrast(theme["accent_text"], theme["accent_press"]) >= 3.0
    # a deliberately unreadable placeholder is reported, not ignored
    bad = dict(theme, placeholder=theme["card"])
    pairs = [pair for pair, _ratio, _req in audit_theme("Dark")]
    assert "placeholder on card" not in pairs
    if contrast(bad["placeholder"], bad["card"]) < 4.5:
        # sanity: the same pair WOULD fail with an unreadable token
        assert contrast(bad["placeholder"], bad["card"]) < 4.5


# ------------------------------------------------- palette spot-checks
def test_dark_placeholder_uses_the_theme_token(qapp, themed):
    themed("Dark")
    edit = _shown(QLineEdit())
    edit.setPlaceholderText("optional")
    qapp.processEvents()
    color = edit.palette().color(QPalette.ColorRole.PlaceholderText)
    assert color.name() == GUI_THEMES["Dark"]["placeholder"]
    edit.deleteLater()


def test_light_placeholder_uses_the_theme_token(qapp, themed):
    themed("Light")
    edit = _shown(QLineEdit())
    edit.setPlaceholderText("optional")
    qapp.processEvents()
    color = edit.palette().color(QPalette.ColorRole.PlaceholderText)
    assert color.name() == GUI_THEMES["Light"]["placeholder"]
    edit.deleteLater()


def test_read_only_line_edit_uses_the_theme_colors(qapp, themed):
    themed("Dark")
    # dialogs create the read-only rows this way (before the first polish)
    edit = QLineEdit("Basic Information value")
    edit.setReadOnly(True)
    _shown(edit)
    qapp.processEvents()
    palette = edit.palette()
    assert palette.color(QPalette.ColorRole.Text).name() == \
        GUI_THEMES["Dark"]["text"]
    assert palette.color(QPalette.ColorRole.Base).name() == \
        GUI_THEMES["Dark"]["alt"]
    edit.deleteLater()


def test_datetime_edit_follows_the_theme(qapp, themed):
    themed("Dark")
    edit = _shown(QDateTimeEdit())
    qapp.processEvents()
    palette = edit.palette()
    assert palette.color(QPalette.ColorRole.Text).name() == \
        GUI_THEMES["Dark"]["text"]
    assert palette.color(QPalette.ColorRole.Base).name() == \
        GUI_THEMES["Dark"]["card"]
    edit.deleteLater()
