# -*- coding: utf-8 -*-
"""SOLO login-dialog styling batch: uniform industrial dark look.

Assertions cover the spec items: fixed size + screen centering,
steady title, uniform input styling (radius / padding / heights),
accent login button, muted hint, and no HTML font tricks in labels.
Logic tests live in test_login_fixture.py (unchanged)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QLineEdit,
)

from mtkgui.permissions import LoginDialog  # noqa: E402
from mtkgui.style import GUI_THEMES, saved_theme  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def dlg(qapp):
    d = LoginDialog()
    yield d
    d.deleteLater()


def _tokens():
    return dict(GUI_THEMES.get(saved_theme(), GUI_THEMES["Dark"]))


# ------------------------------------------------------- size + center
def test_adaptive_size(dlg):
    """Item 12: full adaptive layout - no fixed maximum; Qt layout
    rules drive width / height from the logical-px minimums."""
    assert dlg.minimumWidth() >= 470
    assert dlg.minimumHeight() >= 550
    # resizable: no fixed max clamped to the minimum
    assert dlg.maximumWidth() > dlg.minimumWidth()
    assert dlg.maximumHeight() > dlg.minimumHeight()
    dlg.resize(640, 660)
    assert (dlg.width(), dlg.height()) == (640, 660)


def test_dialog_centers_on_show(qapp, dlg):
    """showEvent centers the dialog on the primary screen."""
    from PySide6.QtWidgets import QApplication
    dlg.show()
    qapp.processEvents()
    avail = QApplication.primaryScreen().availableGeometry()
    center = dlg.geometry().center()
    # small rounding / window-frame tolerance
    assert abs(center.x() - avail.center().x()) <= 3
    assert abs(center.y() - avail.center().y()) <= 3
    dlg.hide()


# ------------------------------------------------------------- styling
def test_inputs_share_uniform_style(dlg):
    """Account combo and password edit: same height, radius 6, thin
    border, uniform padding - one visual language."""
    t = _tokens()
    qss = dlg.styleSheet()
    assert "border-radius: 6px" in qss
    assert f"border: 1px solid {t['border']}" in qss
    assert "padding: 6px 10px" in qss
    # same fixed content height for both inputs
    h_combo = dlg.role_combo.height()
    h_edit = dlg.password_edit.height()
    assert h_combo == h_edit == 34


def test_login_button_accent_styling(dlg):
    """Login button: accent fill, theme text color, 6px radius,
    pressed feedback via accent_press - no gradients."""
    t = _tokens()
    qss = dlg.styleSheet()
    btn = dlg.findChild(type(dlg), "login_btn") or None
    # findChild with QObject works: locate via dialog buttons instead
    from PySide6.QtWidgets import QDialogButtonBox, QPushButton
    box = dlg.findChild(QDialogButtonBox)
    ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
    assert isinstance(ok_btn, QPushButton)
    assert ok_btn.objectName() == "login_btn"
    assert f"background-color: {t['accent']}" in qss
    assert f"background-color: {t['accent_press']}" in qss
    assert "qlineargradient" not in qss          # no gradients
    assert ok_btn.minimumHeight() >= 32


def test_secondary_button_neutral(dlg):
    """The Cancel button stays neutral (card fill, thin border) and
    never competes with the accent login button."""
    from PySide6.QtWidgets import QDialogButtonBox
    box = dlg.findChild(QDialogButtonBox)
    cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
    assert cancel.objectName() == "login_secondary"


def test_title_steady_no_html(dlg):
    """Title is a plain centered bold label - no HTML font spans."""
    from PySide6.QtWidgets import QLabel
    title = dlg.findChild(QLabel, "login_title")
    assert title is not None
    assert "<span" not in title.text()
    assert "Welcome to MTK All-in-One GUI" in title.text()
    assert title.alignment() & Qt.AlignmentFlag.AlignHCenter
    version = dlg.findChild(QLabel, "login_version")
    assert version is not None
    assert version.alignment() & Qt.AlignmentFlag.AlignHCenter


def test_background_matches_theme(dlg):
    """Dialog background uses the theme page color (industrial dark,
    consistent with the main window)."""
    t = _tokens()
    assert f"background-color: {t['page']}" in dlg.styleSheet()


# ------------------------------------------------ item 12 additions
def test_version_bound_to_global_gui_version(dlg):
    """The login version label is bound to the ONE global GUI version
    variable (the status bar source) - no duplicate static version."""
    from mtkgui.gui_version import load_gui_version
    version = dlg.findChild(QLabel, "login_version")
    assert version.text() == f"Version {load_gui_version()[0]}"


def test_title_larger_and_bolder(dlg):
    """Item 12: the main title uses a larger, bolder font (no longer
    tiny / inconspicuous)."""
    title = dlg.findChild(QLabel, "login_title")
    qss = dlg.styleSheet()
    assert "QLabel#login_title" in qss
    block = qss.split("QLabel#login_title")[1].split("}")[0]
    assert "font-size: 21px" in block
    assert "font-weight: 700" in block
    assert title.alignment() & Qt.AlignmentFlag.AlignHCenter


def test_hint_centered_in_middle_area(dlg, qapp):
    """Item 12: the description text sits in the moderate middle area,
    centered - below the form, above the button row (no bottom-biased
    offset indentation)."""
    from PySide6.QtWidgets import QDialogButtonBox
    dlg.show()
    qapp.processEvents()
    hint = dlg.findChild(QLabel, "login_hint")
    assert hint.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert dlg.password_edit.geometry().bottom() < hint.geometry().top()
    box = dlg.findChild(QDialogButtonBox)
    assert hint.geometry().bottom() < box.geometry().top()
    dlg.hide()


def test_bottom_fixed_info_bar(dlg, qapp):
    """Station ID + User + copyright live in the absolute bottom fixed
    area of the login window.  Core standard 5.3: both identity fields
    are the GLOBAL system-derived variables (host name + OS login),
    the same source the Event-Log entries carry - never the selected
    GUI account."""
    import getpass

    from mtkgui.gui.identity import get_station_id, get_user
    from mtkgui.permissions import COPYRIGHT_TEXT
    assert dlg.station_label.text() == \
        f"Station ID: {get_station_id()}"
    assert dlg.user_label.text() == f"User: {get_user()}"
    assert get_user() == getpass.getuser()   # OS login, not the role
    # switching the GUI account does NOT touch the identity footer
    dlg.role_combo.setCurrentText("Operator")
    assert dlg.user_label.text() == f"User: {get_user()}"
    dlg.role_combo.setCurrentText("Supervisor")
    copyr = dlg.findChild(QLabel, "login_copyright")
    assert copyr.text() == COPYRIGHT_TEXT == \
        "\u00a92026 NXP. All Rights Reserved."
    # the footer is the last content block, pinned at the bottom
    dlg.show()
    qapp.processEvents()
    footer = dlg.station_label.parentWidget()
    assert footer.geometry().bottom() >= dlg.height() - 20
    dlg.hide()


def test_nxp_logo_present_and_scaled(dlg):
    """Item 12: the brand mark renders without distortion (aspect
    ratio locked) at the top of the dialog."""
    from PySide6.QtWidgets import QLabel
    logo = dlg.findChild(QLabel, "login_logo")
    assert logo is not None
    pixmap = logo.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    ratio = pixmap.width() / pixmap.height()
    assert 2.5 < ratio < 4.5          # 120x36 viewBox aspect kept
