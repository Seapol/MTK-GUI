# -*- coding: utf-8 -*-
"""Net classification rules editor dialog (item 24, Task 1).

The rule core (defaults / validation / classification) lives in the
headless :mod:`mtkgui.ict.netparse.rules` module; this module keeps
only the Qt regex editor dialog plus the "Learn from Project" panel
(scan a new project's NET file, review Power / Clock / Control IO /
Others before vs after a learned ADDITIVE suggestion, then Apply).
"""

from __future__ import annotations

import re

from PySide6.QtWidgets import QDialog, QWidget

from mtkgui.ict.netparse.learn import BUCKETS, learn_rules, read_net_names
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

        self._learn_panel = self._build_learn_panel()
        lay.addWidget(self._learn_panel)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Save).setText("Save")
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self._reset_default)
        buttons.addButton(reset_btn,
                          QDialogButtonBox.ActionRole.ResetRole)
        learn_btn = QPushButton("Learn from Project...")
        learn_btn.clicked.connect(self._learn_from_project)
        buttons.addButton(learn_btn,
                          QDialogButtonBox.ActionRole.ActionRole)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # ------------------------------------------------------ learn panel
    def _build_learn_panel(self) -> QWidget:
        """Collapsible 'Learn from Project' result panel (hidden until
        a NET file has been scanned)."""
        from PySide6.QtWidgets import (
            QAbstractItemView,
            QFormLayout,
            QGroupBox,
            QHBoxLayout,
            QHeaderView,
            QLabel,
            QLineEdit,
            QPushButton,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
        )
        box = QGroupBox("Learn from Project")
        v = QVBoxLayout(box)

        self._learn_note = QLabel("")
        self._learn_note.setWordWrap(True)
        self._learn_note.setObjectName("muted")
        v.addWidget(self._learn_note)

        self._learn_table = QTableWidget(4, 4)
        self._learn_table.setHorizontalHeaderLabels(
            ["Category", "Before", "After", "Change"])
        self._learn_table.verticalHeader().setVisible(False)
        self._learn_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._learn_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        hh = self._learn_table.horizontalHeader()
        hh.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self._learn_table)

        self._learn_conflicts = QLabel("")
        self._learn_conflicts.setWordWrap(True)
        self._learn_conflicts.setStyleSheet("color: #b45309;")
        v.addWidget(self._learn_conflicts)

        form = QFormLayout()
        form.setVerticalSpacing(6)
        self._learn_sugs: dict[str, QLineEdit] = {}
        for key, label in RULE_SLOTS:
            edit = QLineEdit()
            edit.setReadOnly(True)
            form.addRow(f"Suggested {label}:", edit)
            self._learn_sugs[key] = edit
        v.addLayout(form)

        hint = QLabel(
            "Learned patterns are ADDITIVE (merged with the current "
            "rules, nothing removed); low-confidence re-classifications "
            "fall back to Others for manual adjustment.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        v.addWidget(hint)

        row = QHBoxLayout()
        self._apply_btn = QPushButton("Apply Learned Rules")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._apply_learned)
        row.addWidget(self._apply_btn)
        row.addStretch(1)
        v.addLayout(row)

        box.setVisible(False)
        return box

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

    # -------------------------------------------------- learn actions
    def _learn_from_project(self) -> None:
        """[Learn from Project...]: pick a NET file, run the headless
        learner and fill the comparison panel."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _f = QFileDialog.getOpenFileName(
            self, "Select Project NET File", "",
            "Allegro NET (*.net *.NET);;All Files (*)")
        if not path:
            return
        try:
            names = read_net_names(path)
            if not names:
                raise ValueError("no net names found in the file")
            result = learn_rules(names, self.rules())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Learn from Project",
                                f"Cannot learn from {path}:\n{exc}")
            return
        self._learn_result = result
        self._fill_learn_table(result, path, len(names))
        self._learn_panel.setVisible(True)
        self.adjustSize()

    def _fill_learn_table(self, result: dict, path: str,
                          n_nets: int) -> None:
        """Fill the before/after comparison table + suggested regexes."""
        import os
        from PySide6.QtGui import QBrush, QColor
        from PySide6.QtWidgets import QTableWidgetItem
        before, after = result["before"], result["after"]
        self._learn_note.setText(
            f"File: {os.path.basename(path)}  ({n_nets} nets)")
        for i, bucket in enumerate(BUCKETS):
            b = before.get(bucket, 0)
            a = after.get(bucket, 0)
            change = a - b
            self._learn_table.setItem(
                i, 0, QTableWidgetItem(bucket))
            self._learn_table.setItem(
                i, 1, QTableWidgetItem(str(b)))
            self._learn_table.setItem(
                i, 2, QTableWidgetItem(str(a)))
            cell = QTableWidgetItem(
                "" if not change else f"{'+' if change > 0 else ''}{change}")
            if change:
                cell.setForeground(
                    change > 0 and QBrush(QColor("#16a34a"))
                    or QBrush(QColor("#b91c1c")))
            self._learn_table.setItem(i, 3, cell)
        conflicts = result.get("conflicts", [])
        if conflicts:
            shown = ", ".join(conflicts[:8])
            more = f" (+{len(conflicts) - 8} more)" if len(conflicts) > 8 else ""
            self._learn_conflicts.setText(
                f"Low-confidence re-classifications (moved to Others, "
                f"adjust manually): {shown}{more}")
        else:
            self._learn_conflicts.setText("")
        for key, _label in RULE_SLOTS:
            self._learn_sugs[key].setText(result["rules"].get(key, ""))
        self._apply_btn.setEnabled(True)

    def _apply_learned(self) -> None:
        """[Apply Learned Rules]: copy the suggested (additive) regexes
        into the editable fields above."""
        for key, _label in RULE_SLOTS:
            self._edits[key].setText(self._learn_sugs[key].text())
        self.error_label.setText("")
        self.adjustSize()

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
