# -*- coding: utf-8 -*-
"""M69: Tools > Config assets for projects...

Project-bound custom assets folder ``projects/<Project>/assets_<Project>``
created from the READ-ONLY built-in ``assets/`` template.  The binding
(``assets_dir`` in the project's shared FCT params) is configuration
data only - the app never injects or reorders FCT steps here.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mtkgui.engine import assets_config as assets
from mtkgui.gui.dialog_sizing import fit_dialog

EXPLANATION = ("Each project owns a customizable assets folder "
               "(assets_<Project>) copied from the built-in template. "
               "The built-in assets are read-only and never modified.")


class AssetsConfigDialog(QDialog):
    """Modal assets manager (one instance per MainWindow, reused)."""

    def __init__(self, parent=None, *, tenant_base: str | None = None,
                 bind_callback=None, builtin_source: str | None = None,
                 folder_opener=None):
        super().__init__(parent)
        self.setWindowTitle("Config assets for projects")
        self.setModal(True)
        self._bind_callback = bind_callback
        self._builtin_source = builtin_source
        self._folder_opener = folder_opener or self._open_in_file_manager
        if tenant_base is None:
            from mtkgui.gui.shell import resolve_tenant_base
            tenant_base = resolve_tenant_base()
        self.tenant_base = str(tenant_base)
        fit_dialog(self, 940, 660)

        root = QVBoxLayout(self)
        note = QLabel(EXPLANATION)
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Projects:"))
        self.list_widget = QListWidget()
        self.list_widget.setMinimumWidth(250)
        self.list_widget.setMaximumWidth(300)
        self.list_widget.currentRowChanged.connect(self._on_project_changed)
        left.addWidget(self.list_widget, 1)
        body.addLayout(left)

        right = QVBoxLayout()
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self.path_label)
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        right.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.btn_create = QPushButton("Create from built-in")
        self.btn_open = QPushButton("Open Folder")
        self.btn_edit = QPushButton("Edit File…")
        self.btn_recreate = QPushButton("Re-create from built-in")
        self.btn_delete = QPushButton("Delete customized assets")
        for button in (self.btn_create, self.btn_open, self.btn_edit,
                       self.btn_recreate, self.btn_delete):
            buttons.addWidget(button)
        buttons.addStretch(1)
        right.addLayout(buttons)
        right.addStretch(1)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        # ----------------------------------------------- inline editor
        self.editor_box = QGroupBox("Edit file")
        editor = QVBoxLayout(self.editor_box)
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(120)
        self.file_list.currentTextChanged.connect(self._load_file)
        editor.addWidget(self.file_list)
        self.editor_hint = QLabel("")
        self.editor_hint.setObjectName("muted")
        self.editor_hint.setWordWrap(True)
        editor.addWidget(self.editor_hint)
        self.editor = QPlainTextEdit()
        self.editor.setMinimumHeight(160)
        editor.addWidget(self.editor)
        save_row = QHBoxLayout()
        self.btn_save = QPushButton("Save")
        self.btn_cancel_edit = QPushButton("Cancel")
        save_row.addWidget(self.btn_save)
        save_row.addWidget(self.btn_cancel_edit)
        save_row.addStretch(1)
        editor.addLayout(save_row)
        self.editor_box.setVisible(False)
        root.addWidget(self.editor_box)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        bottom.addWidget(close)
        root.addLayout(bottom)

        self.btn_create.clicked.connect(self._create)
        self.btn_recreate.clicked.connect(self._recreate)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_open.clicked.connect(self._open_folder)
        self.btn_edit.clicked.connect(self._toggle_editor)
        self.btn_save.clicked.connect(self._save_file)
        self.btn_cancel_edit.clicked.connect(self._close_editor)
        self.refresh()

    # ------------------------------------------------------------ state
    def project(self) -> str:
        item = self.list_widget.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) \
            if item is not None else ""

    def custom_path(self) -> str:
        project = self.project()
        return assets.custom_assets_dir(project, self.tenant_base) \
            if project else ""

    def refresh(self) -> None:
        """Rescan ``projects/`` (selection preserved when possible)."""
        current = self.project()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        projects = assets.list_projects(self.tenant_base)
        for name in projects:
            state = assets.assets_state(name, self.tenant_base)
            item = QListWidgetItem(
                f"{name}  {assets.status_suffix(state)}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        if projects:
            row = projects.index(current) if current in projects else 0
            self.list_widget.setCurrentRow(row)
        else:
            self._on_project_changed(-1)

    def _on_project_changed(self, _row=None):
        project = self.project()
        self.editor_box.setVisible(False)
        if not project:
            self.path_label.setText("No project folder under "
                                    f"{self.tenant_base}")
            self.status_label.setText("")
            self._set_buttons(custom=False)
            return
        path = assets.custom_assets_dir(project, self.tenant_base)
        self.path_label.setText(f"Target assets folder: {path}")
        state = assets.assets_state(project, self.tenant_base)
        if state == "custom":
            self.status_label.setText(
                "Custom assets ready - the project uses this folder.")
        elif state == "legacy":
            self.status_label.setText(
                "Legacy assets/ folder found - create a custom "
                "assets_<Project> folder to take ownership.")
        else:
            self.status_label.setText(
                "No custom assets yet - Create from built-in copies the "
                "read-only template.")
        self._set_buttons(custom=state == "custom")

    def _set_buttons(self, custom: bool):
        # Create is available whenever there is no CUSTOM folder (a
        # legacy assets/ folder does not block it)
        self.btn_create.setEnabled(not custom)
        self.btn_open.setEnabled(custom)
        self.btn_edit.setEnabled(custom)
        self.btn_recreate.setEnabled(custom)
        self.btn_delete.setEnabled(custom)

    # ------------------------------------------------------ operations
    def _bind(self, project: str, path: str) -> None:
        if callable(self._bind_callback):
            self._bind_callback(project, path)

    def _copy(self, overwrite: bool) -> bool:
        project = self.project()
        try:
            path = assets.create_custom_assets(
                project, self.tenant_base, self._builtin_source,
                overwrite=overwrite)
        except (OSError, FileExistsError) as exc:
            QMessageBox.critical(self, "Custom assets failed", str(exc))
            return False
        self._bind(project, path)
        self.refresh()
        return True

    def _create(self):
        if self.project():
            self._copy(overwrite=False)

    def _recreate(self):
        if not self.project():
            return
        answer = QMessageBox.question(
            self, "Re-create customized assets",
            "This wipes the custom folder and copies the built-in "
            "template again.\n\nAny custom edits are lost. Continue?")
        if answer == QMessageBox.StandardButton.Yes:
            self._copy(overwrite=True)

    def _delete(self):
        project = self.project()
        if not project:
            return
        answer = QMessageBox.question(
            self, "Delete customized assets",
            f"Remove only the custom folder assets_{project}?\n\n"
            "The project folder and its other files are kept. The "
            "project falls back to the built-in template.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            assets.remove_custom_assets(project, self.tenant_base)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self._bind(project, "")            # fall back to the bundled tree
        self.refresh()

    def _open_folder(self):
        path = self.custom_path()
        if path and os.path.isdir(path):
            self._folder_opener(path)

    def _open_in_file_manager(self, path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # --------------------------------------------------------- editor
    def _toggle_editor(self):
        if self.editor_box.isVisible():
            self._close_editor()
            return
        path = self.custom_path()
        if not os.path.isdir(path):
            return
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for rel in assets.list_asset_files(path):
            self.file_list.addItem(rel)
        self.file_list.blockSignals(False)
        self.editor_box.setVisible(True)
        if self.file_list.count():
            self.file_list.setCurrentRow(0)
        else:
            self.editor.setPlainText("")
            self.editor.setReadOnly(True)
            self.editor_hint.setText("The custom folder has no files.")

    def _close_editor(self):
        self.editor_box.setVisible(False)
        self.editor.setReadOnly(False)
        self.editor_hint.setText("")

    def _load_file(self, rel: str):
        rel = str(rel or "")
        path = self.custom_path()
        if not rel or not path:
            return
        text, is_text = assets.read_asset_text(os.path.join(path, rel))
        self.editor.setReadOnly(not is_text)
        self.btn_save.setEnabled(is_text)
        if is_text:
            self.editor.setPlainText(text)
            self.editor_hint.setText(f"Editing {rel} (UTF-8)")
        else:
            self.editor.setPlainText("")
            self.editor_hint.setText(
                f"{rel} is a binary file - open it in an external editor.")

    def _save_file(self):
        rel = self.file_list.currentItem()
        rel_text = rel.text() if rel is not None else ""
        path = self.custom_path()
        if not rel_text or not path or self.editor.isReadOnly():
            return
        target = os.path.join(path, rel_text)
        try:
            assets.write_asset_text(target, self.editor.toPlainText())
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.editor_hint.setText(f"Saved {rel_text} (UTF-8)")
