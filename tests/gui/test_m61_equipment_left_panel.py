# -*- coding: utf-8 -*-
"""M61: Equipment page left-panel layout fixes (user-reported).

* the row Config button was clipped by the app QSS padding
  (7px 16px) at a fixed 72 px - now 92 px, name minimum 130 px so
  label + button stay inside the ~226 px content width;
* collapsing the left column only hid the list, so the
  "Hardware Configuration" caption kept dictating the splitter's
  left width - now the caption is hidden too and the splitter shrinks
  to a 28 px arrow strip / restores the ~25 % share.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from mtkgui.equipment_page import (  # noqa: E402
    EquipmentPage,
    LEFT_ENTRIES,
)

#: left column = 240 px; its content width minus the body margins
#: (6 + 6) and the frame/border leaves ~226 px for one entry row
LEFT_COLUMN_PX = 240
ROW_CONTENT_PX = 226


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    p = EquipmentPage()
    p.resize(1600, 900)
    p.show()
    qapp.processEvents()
    yield p
    p.close()
    p.deleteLater()


def _name_label(page, key, label):
    """The name QLabel of an entry row (shares the button's parent)."""
    btn = page.entry_buttons[key]["config"]
    return next(w for w in btn.parentWidget().findChildren(QLabel)
                if w.text() == label)


# ---------------------------------------------------------- §1 button fit
def test_config_button_is_92_px_and_fits_its_label(page, qapp):
    btn = page.entry_buttons["daq973a"]["config"]
    assert btn.minimumWidth() == 92
    assert btn.maximumWidth() == 92
    qapp.processEvents()
    assert btn.width() == 92
    assert btn.width() >= btn.sizeHint().width()


def test_name_label_plus_button_fit_the_column(page):
    checked = 0
    for _group, entries in LEFT_ENTRIES:
        for key, label, _kind, _source in entries:
            name = _name_label(page, key, label)
            btn = page.entry_buttons[key]["config"]
            # M80-1: no elision at the computed default width; the
            # tooltip carries the full text on a narrow drag
            assert name.toolTip() == label, key
            assert name.sizeHint().width() + btn.width() \
                + 2 * 6 <= page.computed_left_width, key
            checked += 1
    assert checked


def test_no_horizontal_scrollbar_at_the_expanded_share(page, qapp):
    """The left column's normal width is the expanded share - there the
    row content fits and the list needs no horizontal scrollbar."""
    page.btn_collapse.click()
    qapp.processEvents()
    page.btn_collapse.click()
    qapp.processEvents()
    body = page.left_list.widget()
    assert body.width() <= page.left_list.viewport().width() + 2
    assert not page.left_list.horizontalScrollBar().isVisible()


# --------------------------------------------------- §2 collapse the width
def test_collapse_hides_the_caption_and_the_list(page, qapp):
    page.btn_collapse.click()
    qapp.processEvents()
    assert page.cap_label.isHidden()
    assert page.left_list.isHidden()


def test_collapse_shrinks_the_splitter_and_frees_the_right_side(page, qapp):
    before = page.splitter.sizes()
    page.btn_collapse.click()
    qapp.processEvents()
    left, right = page.splitter.sizes()
    assert left <= 30
    assert left + right == sum(before)
    assert right >= before[1]


def test_expand_restores_the_quarter_share(page, qapp):
    page.btn_collapse.click()
    qapp.processEvents()
    page.btn_collapse.click()
    qapp.processEvents()
    assert not page.cap_label.isHidden()
    assert not page.left_list.isHidden()
    left, right = page.splitter.sizes()
    total = left + right
    assert abs(left - total // 4) <= 1


# ------------------------------------------------ §3 arrow / tooltip state
def test_arrow_and_tooltip_follow_the_state(page, qapp):
    assert page.btn_collapse.arrowType() == Qt.ArrowType.LeftArrow
    assert page.btn_collapse.toolTip() == "Collapse Hardware Configuration"
    page.btn_collapse.click()
    qapp.processEvents()
    assert page.btn_collapse.arrowType() == Qt.ArrowType.RightArrow
    assert page.btn_collapse.toolTip() == "Show Hardware Configuration"
    page.btn_collapse.click()
    qapp.processEvents()
    assert page.btn_collapse.arrowType() == Qt.ArrowType.LeftArrow
    assert page.btn_collapse.toolTip() == "Collapse Hardware Configuration"


def test_every_config_button_has_the_same_width(page):
    widths = {b["config"].width() for b in page.entry_buttons.values()}
    assert widths == {92}
