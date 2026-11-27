# -*- coding: utf-8 -*-
"""M160c: node 06 six-column table + category/type editor stack."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.step_types import (  # noqa: E402
    CATEGORY_CONSOLE,
    CATEGORY_EXTERNAL_GUI,
    STEP_CATEGORIES,
)
from mtkgui.gui.yamlbuild.fct_build import (  # noqa: E402
    FctSequence,
    FctStep,
)
from mtkgui.gui.yamlbuild.fct_sequence_v2_panel import (  # noqa: E402
    COLUMNS,
    BuildFctSequencePanel,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel():
    widget = BuildFctSequencePanel()
    widget.show()
    yield widget
    widget.hide()
    widget.deleteLater()


def _sequence() -> FctSequence:
    return FctSequence(name="FCT", steps=[
        FctStep(name="Burn image", category=CATEGORY_CONSOLE, type="cli",
                channel="ser1", command="uuu.exe -b emmc image.bin"),
        FctStep(name="Flash FAT", category=CATEGORY_EXTERNAL_GUI,
                type="flash", params={"slot": "fat"}),
    ])


def test_columns_are_the_six_tuple():
    assert COLUMNS == ("#", "Name", "Type", "Channel", "Timeout (s)",
                       "Retries")


def test_selecting_a_step_syncs_category_and_type(panel):
    panel.set_sequence(_sequence())
    panel.table.setCurrentCell(0, 0)
    assert panel.edit_category.currentText() == CATEGORY_CONSOLE
    assert panel.edit_type.currentText() == "cli"
    # the left Type cell renders the SAME source as the right combo
    assert panel.table.item(0, 2).text() == panel.edit_type.currentText()
    assert panel.stack.currentWidget() is panel._pages[CATEGORY_CONSOLE]


def test_switching_category_repopulates_type_and_swaps_page(panel):
    panel.set_sequence(_sequence())
    panel.table.setCurrentCell(0, 0)
    panel.edit_category.setCurrentText(CATEGORY_EXTERNAL_GUI)
    assert panel.edit_type.currentText() == "flash"
    assert list(STEP_CATEGORIES[CATEGORY_EXTERNAL_GUI]) == [
        panel.edit_type.itemText(i)
        for i in range(panel.edit_type.count())]
    assert panel.stack.currentWidget() is \
        panel._pages[CATEGORY_EXTERNAL_GUI]
    assert panel.sequence().steps[0].category == CATEGORY_EXTERNAL_GUI
    assert panel.table.item(0, 2).text() == "flash"


def test_cli_and_flash_fields_do_not_leak(panel):
    panel.set_sequence(_sequence())
    panel.table.setCurrentCell(0, 0)
    assert panel.edit_command.isVisibleTo(panel)
    assert panel._command_box.isVisibleTo(panel)
    assert panel.edit_slot.isVisibleTo(panel) is False

    panel.table.setCurrentCell(1, 0)
    assert panel.edit_slot.isVisibleTo(panel)
    # the command box lives on the Console page and is not shown now
    assert panel.edit_command.isVisibleTo(panel) is False
    assert panel._command_box.isVisibleTo(panel) is False

    # switching the same step to ExternalGui.test hides the flash slot
    panel.edit_type.setCurrentText("test")
    assert panel.edit_slot.isVisibleTo(panel) is False
