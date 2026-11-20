# -*- coding: utf-8 -*-
"""v2-13 (node 06) Build FCT Test Sequence Qt panel."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from mtkgui.gui.yamlbuild.fct_build import (  # noqa: E402
    FLASH_GUI,
    FctSequence,
    FctStep,
    STEP_MESSAGE_CHECK,
    build_fct_sequence,
)
from mtkgui.gui.yamlbuild.fct_sequence_v2_panel import (  # noqa: E402
    BuildFctSequencePanel)


def test_panel_renders_sequence():
    panel = BuildFctSequencePanel()
    try:
        panel.set_sequence(build_fct_sequence("x", flash_mode=FLASH_GUI))
        # fat flash + default body + oobe flash + power off + reset
        assert panel.table.rowCount() == 5
        types = [panel.table.item(r, 2).text()
                 for r in range(panel.table.rowCount())]
        assert types == ["FLASH (gui)", "MESSAGE_CHECK", "FLASH (gui)",
                         "OPERATION", "OPERATION"]
    finally:
        panel.deleteLater()


def test_panel_edit_emits_changed():
    panel = BuildFctSequencePanel()
    try:
        panel.set_sequence(build_fct_sequence("x", flash_mode=FLASH_GUI))
        panel.table.setCurrentCell(0, 0)
        changed = []
        panel.content_changed.connect(lambda: changed.append(True))
        panel.edit_name.setText("Renamed FAT")
        assert changed
        assert panel.sequence().steps[0].name == "Renamed FAT"
    finally:
        panel.deleteLater()


def test_panel_validate():
    panel = BuildFctSequencePanel()
    try:
        panel.set_sequence(build_fct_sequence("x", flash_mode=FLASH_GUI))
        assert panel.validate() == (True, "")
        dup = FctSequence(name="dup", steps=[
            FctStep(name="a", step_type=STEP_MESSAGE_CHECK),
            FctStep(name="a", step_type=STEP_MESSAGE_CHECK),
        ])
        panel.set_sequence(dup)
        ok, msg = panel.validate()
        assert not ok
        assert "duplicate" in msg
    finally:
        panel.deleteLater()


def test_panel_advanced_signal():
    panel = BuildFctSequencePanel()
    try:
        emitted = []
        panel.advanced_requested.connect(lambda: emitted.append(True))
        panel.btn_advanced.click()
        assert emitted
    finally:
        panel.deleteLater()
