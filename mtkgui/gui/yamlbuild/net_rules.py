# -*- coding: utf-8 -*-
"""Net classification rules editor dialog (item 24, Task 1).

The rule core (defaults / validation / classification) lives in the
headless :mod:`mtkgui.ict.netparse.rules` module; this module keeps
only the Qt regex editor dialog.
"""

from __future__ import annotations

import re

from PySide6.QtWidgets import QDialog, QWidget

from mtkgui.ict.netparse.rules import (DEFAULT_RULES, RULE_SLOTS,
                                       validate_rules)


# ------------------------------------------------------------- editor GUI
def _open_editor(parent, rules: dict[str, str]) -> dict | None:
    """Open the regex editor dialog (Qt part split out so the core
    stays importable headless)."""
    dlg = NetRulesEditorDialog(rules, parent)
    if dlg.exec() == NetRulesEditorDialog.DialogCode.Accepted:
        return dlg.rules()
    return None


class NetRulesEditorDialog(QDialog):
    """'Edit Net Classification Rules' dialog (Task 1).

    Four independent regex fields, each with a [Test] box; [Reset to
    Default] restores the factory preset; [Save] pre-validates every
    regex (syntax + catastrophic backtracking) and refuses to close
    on error; [Cancel] discards the changes."""

    def __init__(self, rules: dict[str, str] | None = None,
                 parent=None) -> None:
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
        )
        super().__init__(parent)
        self.setWindowTitle("Edit Net Classification Rules")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        head = QLabel(
            "Priority: manual override > SPF pin attribute > custom "
            "regex > factory default.  An empty regex skips the name "
            "match (SPF pin type only); an empty Exclude regex "
            "disables the exclusion.  Nets matching the Exclude "
            "Parse Nets regex (differential pairs, Reset / Enable / "
            "UART / WAKE / I2C / SPI / JTAG / DBGIF / DATA / ADC, "
            "system random numeric names ...) never become ICT test "
            "objects.  Differential pair detection is kernel-internal.")
        head.setObjectName("muted")
        head.setWordWrap(True)
        lay.addWidget(head)

        self._edits: dict[str, QLineEdit] = {}
        self._samples: dict[str, QLineEdit] = {}
        self._results: dict[str, QLabel] = {}
        form = QFormLayout()
        form.setVerticalSpacing(10)
        for key, label in RULE_SLOTS:
            row = QHBoxLayout()
            edit = QLineEdit((rules or {}).get(key, DEFAULT_RULES[key]))
            edit.setMinimumWidth(280)
            row.addWidget(edit, 1)
            sample = QLineEdit()
            sample.setPlaceholderText("sample net name")
            sample.setMaximumWidth(180)
            row.addWidget(sample)
            test_btn = QPushButton("Test")
            test_btn.setMaximumWidth(56)
            row.addWidget(test_btn)
            result = QLabel("")
            result.setMinimumWidth(80)
            row.addWidget(result)
            wrap = QWidget()
            wrap.setLayout(row)
            form.addRow(f"{label}:", wrap)
            self._edits[key] = edit
            self._samples[key] = sample
            self._results[key] = result
            test_btn.clicked.connect(
                lambda _c=False, k=key: self._run_test(k))
        lay.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b91c1c;")
        self.error_label.setWordWrap(True)
        lay.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Save).setText("Save")
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self._reset_default)
        buttons.addButton(reset_btn,
                          QDialogButtonBox.ActionRole.ResetRole)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # ------------------------------------------------------------ actions
    def _run_test(self, key: str) -> None:
        """[Test]: instantly show Match / No Match for the sample."""
        result = self._results[key]
        pattern = self._edits[key].text()
        sample = self._samples[key].text()
        try:
            hit = bool(re.match(pattern, sample))
            result.setText("Match" if hit else "No Match")
            result.setStyleSheet(
                f"color: {'#16a34a' if hit else '#6b7280'}; "
                "font-weight: bold;")
        except re.error as exc:
            result.setText("Invalid")
            result.setStyleSheet("color: #dc2626; font-weight: bold;")
            result.setToolTip(str(exc))

    def _reset_default(self) -> None:
        """[Reset to Default]: restore all four factory presets."""
        for key, _label in RULE_SLOTS:
            self._edits[key].setText(DEFAULT_RULES[key])
        self.error_label.setText("")

    def _on_save(self) -> None:
        """[Save]: compile + backtracking pre-validation; invalid
        regex forbids saving (error popup text stays in the dialog)."""
        errors = validate_rules(self.rules())
        if errors:
            self.error_label.setText("\n".join(errors))
            return
        self.accept()

    def rules(self) -> dict[str, str]:
        """The current (possibly unsaved) rule patterns."""
        return {key: self._edits[key].text().strip()
                for key, _label in RULE_SLOTS}
