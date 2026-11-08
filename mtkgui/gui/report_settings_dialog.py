# -*- coding: utf-8 -*-
"""Settings > Report Folders… (M96).

Chooses WHERE the DUT certificates and event logs go (the reports root,
Browse included) and the two sub-folder names.  The per-project level
(``<root>/<PROJECT>/``) is shown read-only: it follows the loaded project
or ``MTKGUI_PROJECT``.  The defaults come from ``report_paths`` - the
program directory plus ``DUT Report`` / ``Event Report`` - so a station
that never opens this dialog keeps the old behaviour.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from .. import report_paths


class ReportFoldersDialog(QDialog):
    """Reports root (+ Browse), DUT name, event name; project is read-only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Report Folders")
        self.resize(620, 260)

        values = report_paths.folder_settings()

        self.root_edit = QLineEdit(values["root"])
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        root_row = QWidget()
        root_layout = QHBoxLayout(root_row)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.root_edit, 1)
        root_layout.addWidget(browse)

        self.dut_edit = QLineEdit(values["dut"])
        self.event_edit = QLineEdit(values["event"])

        self.project_label = QLabel(values["project"])
        self.project_label.setObjectName("strong")

        form = QFormLayout()
        form.addRow("Reports root", root_row)
        form.addRow("Project folder", self.project_label)
        form.addRow("DUT folder name", self.dut_edit)
        form.addRow("Event folder name", self.event_edit)

        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setObjectName("muted")

        hint = QLabel(
            "Blank root or blank names fall back to the defaults "
            f"({report_paths.program_dir()} with "
            f"{report_paths.DEFAULT_DUT} / {report_paths.DEFAULT_EVENT}). "
            "The project folder follows the loaded project "
            f"(MTKGUI_PROJECT overrides it). The settings file is kept in "
            "the work folder, so a package upgrade does not lose it.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.restore_button = buttons.addButton(
            "Restore defaults", QDialogButtonBox.ResetRole)
        self.restore_button.clicked.connect(self._restore)
        self.save_button = buttons.button(QDialogButtonBox.Save)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.preview)
        layout.addWidget(hint)
        layout.addStretch(1)
        layout.addWidget(buttons)

        for edit in (self.root_edit, self.dut_edit, self.event_edit):
            edit.textChanged.connect(self._refresh)
        self._refresh()

    # ---------------------------------------------------------- internals
    def _resolved(self) -> tuple:
        root_text = self.root_edit.text().strip()
        root = (Path(root_text).expanduser() if root_text
                else report_paths.program_dir())
        dut = report_paths.clean_name(self.dut_edit.text(),
                                      report_paths.DEFAULT_DUT)
        event = report_paths.clean_name(self.event_edit.text(),
                                        report_paths.DEFAULT_EVENT)
        return root, dut, event

    def _refresh(self) -> None:
        root, dut, event = self._resolved()
        project = report_paths.project_key()
        self.project_label.setText(project)
        self.preview.setText(
            f"DUT reports:  {root / project / dut}\n"
            f"Event logs:   {root / project / event}")

    def _browse(self) -> None:
        start = self.root_edit.text().strip() or str(
            report_paths.report_root())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the reports root folder", start,
            QFileDialog.ShowDirsOnly)
        if chosen:
            self.root_edit.setText(chosen)

    def _restore(self) -> None:
        self.root_edit.setText(str(report_paths.program_dir()))
        self.dut_edit.setText(report_paths.DEFAULT_DUT)
        self.event_edit.setText(report_paths.DEFAULT_EVENT)

    def _save(self) -> None:
        report_paths.set_folder_settings(root=self.root_edit.text(),
                                         dut=self.dut_edit.text(),
                                         event=self.event_edit.text())
        self.accept()
