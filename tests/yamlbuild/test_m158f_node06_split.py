# -*- coding: utf-8 -*-
"""M158f: node 06 splits into a step table (left) and a step editor
(right), with the sequence-level keyword tables collapsed by default.

The old single vertical column squeezed the table, blew up the editor
and hid the keywords under the detail they do not belong to.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (QApplication, QGroupBox,  # noqa: E402
                               QSplitter)

from mtkgui.engine.step_types import CATEGORY_CONSOLE  # noqa: E402
from mtkgui.gui.yamlbuild.fct_build import (  # noqa: E402
    FctSequence,
    FctStep,
)
from mtkgui.gui.yamlbuild.fct_sequence_v2_panel import (  # noqa: E402
    BuildFctSequencePanel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _sequence() -> FctSequence:
    return FctSequence(name="FCT", steps=[
        FctStep(name="first", category=CATEGORY_CONSOLE, type="serial",
                channel="ser1"),
        FctStep(name="second", category=CATEGORY_CONSOLE, type="serial",
                channel="ser1"),
    ])


def _group(panel: BuildFctSequencePanel, title: str) -> QGroupBox:
    return next(box for box in panel.findChildren(QGroupBox)
                if box.title() == title)


def _panel(qapp) -> BuildFctSequencePanel:
    panel = BuildFctSequencePanel()
    panel.set_sequence(_sequence())
    return panel


def test_master_detail_split_puts_the_table_left_and_editor_right(qapp):
    panel = _panel(qapp)
    try:
        split = panel.findChildren(QSplitter)[0]
        assert split.orientation() == Qt.Orientation.Horizontal
        assert split.widget(0) is panel.table
        right = split.widget(1)
        editor = _group(panel, "Selected step")
        assert editor.parent() is right
        keywords = _group(panel, "Keyword tables (sequence-level)")
        assert keywords.parent() is right
    finally:
        panel.deleteLater()


def test_keyword_tables_start_collapsed(qapp):
    panel = _panel(qapp)
    try:
        assert panel.keyword_group.isChecked() is False
        panel.keyword_group.setChecked(True)
        assert panel.keyword_group.isChecked() is True
    finally:
        panel.deleteLater()


def test_read_only_panel_disables_every_row_action(qapp):
    panel = _panel(qapp)
    try:
        panel.setEnabled(False)
        for button in (panel.btn_add, panel.btn_delete, panel.btn_move_up,
                       panel.btn_move_down, panel.btn_advanced):
            assert not button.isEnabled(), button.text()
    finally:
        panel.deleteLater()
