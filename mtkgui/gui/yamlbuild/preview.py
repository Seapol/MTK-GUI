# -*- coding: utf-8 -*-
"""YAML live preview pane (right side of the Yaml Build page).

Read-only by default with an Edit toggle: editing is opt-in, and on
edit the text is validated (syntax / sequence / parameters) before it
may enter the model - error lines are highlighted red with a message
bar; invalid edits never reach the model, which keeps the two-way
sync loop-free and the configuration safe.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.sync import sync_model_to_yaml


class YamlPreviewWidget(QWidget):
    """YAML preview with edit toggle, validation errors and red line
    markers."""

    def __init__(self, parent=None) -> None:
        """Create the preview pane."""
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.caption = QLabel("YAML Preview (effective)")
        self.caption.setObjectName("muted")
        bar.addWidget(self.caption)
        bar.addStretch(1)
        self.btn_edit = QPushButton("Edit")
        self.btn_edit.setCheckable(True)
        self.btn_edit.setToolTip(
            "Toggle hand editing; valid edits sync back to the block "
            "diagram, invalid edits are rejected and marked red")
        bar.addWidget(self.btn_edit)
        lay.addLayout(bar)

        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setMinimumWidth(320)
        lay.addWidget(self.editor, 1)

        self.error_bar = QLabel("")
        self.error_bar.setStyleSheet("color: #b91c1c;")
        self.error_bar.setWordWrap(True)
        self.error_bar.setVisible(False)
        lay.addWidget(self.error_bar)

        self.btn_edit.toggled.connect(self._on_edit_toggled)
        self.btn_edit.clicked.connect(lambda: None)
        # re-validate on every keystroke while editing
        self.editor.textChanged.connect(self._on_text_changed)
        self._on_edit_model: YamlBuildModel | None = None
        self._external_set = False
        self._validating = False  # re-entrancy guard: formatting the
        # document emits textChanged again - never re-enter validate

    # ------------------------------------------------------------- state
    def set_model_text(self, model: YamlBuildModel) -> None:
        """Refresh the preview from the model (diagram -> YAML sync).

        While the operator is hand-editing, the incoming model text
        still wins only when the edit toggle is OFF; when editing is
        ON the preview keeps the operator's text (the edit validation
        path drives what enters the model).

        Args:
            model: The data model.
        """
        text = sync_model_to_yaml(model)
        self._external_set = True
        self.editor.setPlainText(text)
        self._external_set = False
        if not self.btn_edit.isChecked():
            self.editor.setReadOnly(True)
            self.error_bar.setVisible(False)
            self._clear_error_marks()
        else:
            self._on_text_changed()

    def _on_edit_toggled(self, on: bool) -> None:
        """Toggle hand editing on / off.

        Args:
            on: True enters edit mode (re-validates current text).
        """
        self.editor.setReadOnly(not on)
        self.btn_edit.setText("Done" if on else "Edit")
        if on:
            self.btn_edit.setText("Apply & Exit Edit")
            self._on_text_changed()
        else:
            # leaving edit mode: the page re-syncs from the model
            self.error_bar.setVisible(False)
            self._clear_error_marks()

    # ------------------------------------------------------- validation
    def bind_model(self, model: YamlBuildModel) -> None:
        """Bind the model used for edit validation.

        Args:
            model: The data model.
        """
        self._on_edit_model = model

    def _on_text_changed(self) -> None:
        """Live validation while editing: mark error lines red and
        show the first message; a clean edit reports nothing."""
        if (self._validating or self._external_set
                or not self.btn_edit.isChecked()
                or self._on_edit_model is None):
            return
        from mtkgui.gui.yamlbuild.sync import validate_yaml_text
        self._validating = True
        try:
            result = validate_yaml_text(self.editor.toPlainText(),
                                        self._on_edit_model)
            if result.ok:
                self.error_bar.setText(
                    "YAML valid - changes applied to the block "
                    "diagram")
                self.error_bar.setStyleSheet("color: #15803d;")
                self.error_bar.setVisible(True)
                self._clear_error_marks()
                if result.data is not None:
                    self._on_edit_model.apply_yaml_dict(result.data)
                return
            messages = "; ".join(msg for msg, _ in result.errors)
            self.error_bar.setText(f"YAML invalid: {messages}")
            self.error_bar.setStyleSheet("color: #b91c1c;")
            self.error_bar.setVisible(True)
            self._mark_error_lines(result.error_lines())
        finally:
            self._validating = False

    # ------------------------------------------------------ red markers
    def _mark_error_lines(self, lines: set[int]) -> None:
        """Highlight the given 1-based lines with a red background.

        Args:
            lines: Line numbers to mark.
        """
        self._clear_error_marks()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#fecaca"))
        doc = self.editor.document()
        for line in lines:
            block = doc.findBlockByNumber(line - 1)
            if block.isValid():
                cursor = QTextCursor(block)
                cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                cursor.mergeCharFormat(fmt)

    def _clear_error_marks(self) -> None:
        """Remove all red line markers."""
        cursor = QTextCursor(self.editor.document())
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("transparent"))
        cursor.mergeCharFormat(fmt)
