"""M130: node 03 keeps one keyword per verdict and no duplicate cwd row."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from mtkgui.gui.yamlbuild.firmware_config import default_firmware
from mtkgui.gui.yamlbuild.firmware_panel import FirmwareConfigPanel


def test_one_keyword_per_verdict_and_no_working_directory_row(qapp=None):
    panel = FirmwareConfigPanel()
    try:
        slot = panel._slots["fat"]
        labels = [lb.text() for lb in slot.findChildren(QLabel)
                  if isinstance(lb, QLabel)]
        # form rows are labels too; the widget row text is what we assert on
        assert not hasattr(slot, "combo_pass_logic")
        assert not hasattr(slot, "edit_working_dir")
        assert slot.edit_pass_keyword.placeholderText().startswith(
            "Pass keyword")
        assert slot.edit_fail_keyword.placeholderText().startswith(
            "Fail keyword")
        assert labels  # sanity: the slot still renders its rows
    finally:
        panel.deleteLater()


def test_single_keyword_round_trips_through_the_values_dict():
    panel = FirmwareConfigPanel()
    try:
        slot = panel._slots["fat"]
        slot.edit_pass_keyword.setText("FAT image flashed")
        slot.edit_fail_keyword.setText("Flash failed")
        values = panel.values()["fat"]["cli"]
        assert values["pass_keywords"] == ["FAT image flashed"]
        assert values["fail_keywords"] == ["Flash failed"]
        assert values["pass_logic"] == "and"
        assert values["fail_logic"] == "and"
    finally:
        panel.deleteLater()


def test_legacy_keyword_list_keeps_the_first_entry():
    panel = FirmwareConfigPanel()
    try:
        config = default_firmware()
        config["fat"]["cli"]["pass_keywords"] = ["first", "second", "third"]
        config["fat"]["cli"]["working_dir"] = r"C:\FW\imx93\fat"
        panel.set_values(config)
        slot = panel._slots["fat"]
        assert slot.edit_pass_keyword.text() == "first"
        # the hidden cwd survives a load -> save round trip untouched
        assert panel.values()["fat"]["cli"]["working_dir"] == r"C:\FW\imx93\fat"
    finally:
        panel.deleteLater()


def test_disabling_a_slot_greys_out_its_whole_branch():
    panel = FirmwareConfigPanel()
    try:
        slot = panel._slots["oobe"]
        slot.chk_enable.setChecked(False)
        assert not slot._cli.isEnabled()
        assert not slot._gui.isEnabled()
        assert not slot.radio_cli.isEnabled()
        slot.chk_enable.setChecked(True)
        assert slot._cli.isEnabled()
    finally:
        panel.deleteLater()
