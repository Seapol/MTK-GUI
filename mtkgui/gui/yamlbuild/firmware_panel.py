# -*- coding: utf-8 -*-
"""v2-5 node 03 Firmware Config panel (FAT / OOBE flashing method).

Two slots stacked (FAT top, OOBE below); each slot independently picks a
``CLI command`` (Windows terminal) or a ``3rd-party GUI tool``.  The node
only CONFIGURES — there is no execution state, no output tail, no Abort
control and no timeout anywhere.

Disabled slots grey their fields and collapse to ``{enabled: false}`` in
the YAML; both disabled is legal and the footer explains the FCT run will
flash nothing.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.command_snippet_helper import (
    PAGE_WINDOWS,
    with_snippets,
)
from mtkgui.gui.yamlbuild.firmware_config import (
    FIRMWARE_SLOTS,
    METHODS,
    TERMINALS,
    default_firmware,
)

#: fixed caption for the both-disabled footer (§4.1)
NO_SLOT_FOOTER = "no firmware slot enabled — FCT will run without flashing"


class _Slot(QWidget):
    """One firmware slot (FAT or OOBE): Enable + CLI / GUI branch."""

    changed = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._working_dir = ""
        box = QGroupBox(title)
        lay = QVBoxLayout(box)

        self.chk_enable = QCheckBox("Enable")
        self.chk_enable.setChecked(True)
        lay.addWidget(self.chk_enable)

        # method selection (independent per slot)
        self.radio_cli = QRadioButton("CLI command")
        self.radio_gui = QRadioButton("3rd-party GUI tool")
        self.radio_cli.setChecked(True)
        method_row = QHBoxLayout()
        method_row.addWidget(self.radio_cli)
        method_row.addWidget(self.radio_gui)
        method_row.addStretch(1)
        lay.addLayout(method_row)

        self._cli = self._build_cli()
        self._gui = self._build_gui()
        lay.addWidget(self._cli)
        lay.addWidget(self._gui)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

        self.chk_enable.toggled.connect(self._on_changed)
        self.radio_cli.toggled.connect(self._on_changed)
        self.radio_gui.toggled.connect(self._on_changed)

    def _build_cli(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.combo_terminal = QComboBox()
        self.combo_terminal.setInsertPolicy(QComboBox.NoInsert)
        self.combo_terminal.addItems(list(TERMINALS))
        form.addRow("Terminal:", self.combo_terminal)
        self.chk_admin = QCheckBox("Launch as administrator")
        form.addRow("", self.chk_admin)
        self.chk_show = QCheckBox("Show terminal window during run")
        self.chk_show.setChecked(True)
        form.addRow("", self.chk_show)
        # M130: the working directory duplicated the GUI tool path, so the
        # row is gone; a value loaded from an older YAML is kept as-is and
        # written back untouched (no silent data loss).
        self.edit_command = QLineEdit()
        self.edit_command.setPlaceholderText(
            "fat_flash.bat --port COM4 --image fat_1.2.3.bin")
        form.addRow("Command:", with_snippets(self.edit_command,
                                              PAGE_WINDOWS))
        # M130: one keyword per verdict - three slots plus an and/or
        # combinator was more machinery than a flash message needs.
        self.edit_pass_keyword = QLineEdit()
        self.edit_pass_keyword.setPlaceholderText("Pass keyword (optional)")
        form.addRow("Pass keyword:", self.edit_pass_keyword)
        self.edit_fail_keyword = QLineEdit()
        self.edit_fail_keyword.setPlaceholderText("Fail keyword (optional)")
        form.addRow("Fail keyword:", self.edit_fail_keyword)
        for edit in (self.edit_pass_keyword, self.edit_fail_keyword):
            edit.textChanged.connect(self._on_changed)
        self.combo_terminal.currentTextChanged.connect(self._on_changed)
        self.chk_admin.toggled.connect(self._on_changed)
        self.chk_show.toggled.connect(self._on_changed)
        self.edit_command.textChanged.connect(self._on_changed)
        return widget

    def _build_gui(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.edit_tool_path = QLineEdit()
        self.edit_tool_path.setPlaceholderText(
            r"C:\Tools\OobeFlasher\OobeFlasher.exe")
        form.addRow("Tool path:", self.edit_tool_path)
        self.edit_arguments = QLineEdit()
        form.addRow("Arguments:", self.edit_arguments)
        self.edit_prompt = QLineEdit()
        self.edit_prompt.setPlaceholderText(
            "Flash with the tool, then answer below")
        form.addRow("Prompt:", self.edit_prompt)
        self.edit_tool_path.textChanged.connect(self._on_changed)
        self.edit_arguments.textChanged.connect(self._on_changed)
        self.edit_prompt.textChanged.connect(self._on_changed)
        return widget

    def _on_changed(self, *_args) -> None:
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        enabled = self.chk_enable.isChecked()
        self.radio_cli.setEnabled(enabled)
        self.radio_gui.setEnabled(enabled)
        cli = enabled and self.radio_cli.isChecked()
        gui = enabled and self.radio_gui.isChecked()
        self._cli.setEnabled(cli)
        self._gui.setEnabled(gui)

    def set_values(self, slot: dict) -> None:
        slot = slot or {}
        self.chk_enable.setChecked(bool(slot.get("enabled", True)))
        method = str(slot.get("method") or "cli")
        self.radio_gui.setChecked(method == "gui")
        self.radio_cli.setChecked(method != "gui")
        cli = slot.get("cli") or {}
        self.combo_terminal.setCurrentText(
            str(cli.get("terminal") or "cmd")
            if str(cli.get("terminal") or "cmd") in TERMINALS else "cmd")
        self.chk_admin.setChecked(bool(cli.get("run_as_admin", False)))
        self.chk_show.setChecked(bool(cli.get("show_window", True)))
        self._working_dir = str(cli.get("working_dir") or "")
        self.edit_command.setText(str(cli.get("command") or ""))
        pass_keywords = list(cli.get("pass_keywords") or [])
        self.edit_pass_keyword.setText(
            str(pass_keywords[0]) if pass_keywords else "")
        fail_keywords = list(cli.get("fail_keywords") or [])
        self.edit_fail_keyword.setText(
            str(fail_keywords[0]) if fail_keywords else "")
        gui = slot.get("gui") or {}
        self.edit_tool_path.setText(str(gui.get("tool_path") or ""))
        self.edit_arguments.setText(str(gui.get("arguments") or ""))
        self.edit_prompt.setText(str(gui.get("prompt") or ""))
        self._refresh()

    def values(self) -> dict:
        method = "gui" if self.radio_gui.isChecked() else "cli"
        return {
            "enabled": self.chk_enable.isChecked(),
            "method": method,
            "cli": {
                "terminal": self.combo_terminal.currentText(),
                "run_as_admin": self.chk_admin.isChecked(),
                "show_window": self.chk_show.isChecked(),
                "working_dir": self._working_dir,
                "command": self.edit_command.text().strip(),
                "pass_keywords": _single(self.edit_pass_keyword),
                "pass_logic": "and",
                "fail_keywords": _single(self.edit_fail_keyword),
                "fail_logic": "and",
            },
            "gui": {
                "tool_path": self.edit_tool_path.text().strip(),
                "arguments": self.edit_arguments.text().strip(),
                "prompt": self.edit_prompt.text().strip(),
            },
        }


def _single(edit: QLineEdit) -> list[str]:
    text = edit.text().strip()
    return [text] if text else []


class FirmwareConfigPanel(QWidget):
    """Node 03 panel: FAT + OOBE slots and the no-slot footer."""

    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._slots: dict[str, _Slot] = {}
        for slot in FIRMWARE_SLOTS:
            widget = _Slot(slot.upper())
            widget.changed.connect(self._on_slot_changed)
            self._slots[slot] = widget
            lay.addWidget(widget)
        self.lbl_footer = QLabel("")
        self.lbl_footer.setObjectName("muted")
        self.lbl_footer.setWordWrap(True)
        lay.addWidget(self.lbl_footer)
        lay.addStretch(1)
        self._refresh_footer()

    def _on_slot_changed(self) -> None:
        self._refresh_footer()
        self.content_changed.emit()

    def _refresh_footer(self) -> None:
        if self.any_enabled():
            self.lbl_footer.setText("")
        else:
            self.lbl_footer.setText(NO_SLOT_FOOTER)

    def any_enabled(self) -> bool:
        """True when at least one slot is enabled."""
        return any(slot.chk_enable.isChecked()
                   for slot in self._slots.values())

    def values(self) -> dict:
        """The nested §4.6 config (fat + oobe, both always present)."""
        return {key: slot.values() for key, slot in self._slots.items()}

    def set_values(self, config: dict) -> None:
        """Load a persisted firmware config (factory defaults fill gaps)."""
        config = config or default_firmware()
        for key, slot in self._slots.items():
            slot.set_values(config.get(key) or {})
        self._refresh_footer()
