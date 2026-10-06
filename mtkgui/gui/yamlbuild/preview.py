# -*- coding: utf-8 -*-
"""YAML preview pane (right side of the Yaml Build page).

Single fixed-position toggle button with two mutually exclusive
states (M0 UI requirement):

* READ_ONLY (default): the YAML editor is disabled, the button label
  is ``Edit``; clicking activates edit mode;
* EDIT mode: the editor is enabled, the label is ``Apply``; clicking
  runs the YAML validation - on PASS the changes persist, the block
  diagram refreshes and the widget returns to READ_ONLY; on FAIL the
  error hint is shown, edit mode is kept and the label stays
  ``Apply``.

The button never moves - only its label text changes (auto width).
Invalid edits never reach the model, which keeps the two-way sync
loop-free and the configuration safe.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
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

EDIT_LABEL = "Edit"
APPLY_LABEL = "Apply"


class YamlPreviewWidget(QWidget):
    """YAML preview with the Edit/Apply toggle and red error marks."""

    #: emitted after a valid hand edit entered the model - the page
    #: uses it to refresh the block cards (YAML -> diagram direction)
    edits_applied = Signal()
    #: emitted whenever the toggle label changes (Edit <-> Apply) -
    #: the page top toolbar re-syncs the uniform button width (item 16)
    label_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        """Create the preview pane (READ_ONLY by default)."""
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.caption = QLabel("YAML Preview (effective)")
        self.caption.setObjectName("muted")
        bar.addWidget(self.caption)
        bar.addStretch(1)
        # item 16: the Edit/Apply toggle moved to the page top toolbar
        # (placed to the right of the Excel buttons).  The widget is
        # created here - state, permission gate and toggle logic stay
        # owned by the preview - but is NOT added to this header any
        # more; the page reparents it into the unified top button row.
        self.btn_edit = QPushButton(EDIT_LABEL)
        self.btn_edit.setCheckable(False)
        self.btn_edit.setToolTip(
            "Edit: activate hand editing. Apply: validate and persist; "
            "invalid edits keep edit mode and are marked red")
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

        self.btn_edit.clicked.connect(self._on_button_clicked)
        self._on_edit_model: YamlBuildModel | None = None
        self._editing = False

    # ------------------------------------------------------------- state
    def is_editing(self) -> bool:
        """True while the widget is in EDIT mode."""
        return self._editing

    def set_model_text(self, model: YamlBuildModel) -> None:
        """Refresh the preview from the model (diagram -> YAML sync).

        While the operator is in EDIT mode the preview keeps the
        operator's text (the Apply path drives what enters the model).

        Args:
            model: The data model.
        """
        if self._editing:
            return                    # operator text wins while editing
        text = sync_model_to_yaml(model)
        self.editor.setPlainText(text)
        self.editor.setReadOnly(True)
        self.error_bar.setVisible(False)
        self._clear_error_marks()

    # ------------------------------------------------------ button toggle
    def set_edit_allowed(self, allowed: bool) -> None:
        """Permission gate (T5): without the edit right the Edit/Apply
        button is disabled and a pending edit session is rolled back
        to READ_ONLY (the preview stays viewable)."""
        self.btn_edit.setEnabled(bool(allowed))
        if not allowed and self._editing:
            self._exit_edit()

    def _on_button_clicked(self) -> None:
        """Dispatch the single button: Edit -> enter edit mode,
        Apply -> validate and (on pass) persist + return to Edit."""
        if not self._editing:
            self._enter_edit()
        else:
            self._apply_edits()

    def _enter_edit(self) -> None:
        """EDIT mode: editor enabled, label switches to Apply."""
        self._editing = True
        self.editor.setReadOnly(False)
        self.btn_edit.setText(APPLY_LABEL)
        self.label_changed.emit(APPLY_LABEL)

    def _apply_edits(self) -> None:
        """Apply clicked: validate; PASS persists + returns to
        READ_ONLY, FAIL shows the error hint and stays in EDIT."""
        if self._on_edit_model is None:
            return
        from mtkgui.gui.yamlbuild.sync import validate_yaml_text
        result = validate_yaml_text(self.editor.toPlainText(),
                                    self._on_edit_model)
        if result.ok:
            if result.data is not None:
                self._on_edit_model.apply_yaml_dict(result.data)
            self._exit_edit()
            # re-sync the (now read-only) text from the updated model
            self.set_model_text(self._on_edit_model)
            self.edits_applied.emit()
            return
        # FAIL: error hint, stay in EDIT, label keeps Apply
        messages = "; ".join(msg for msg, _ in result.errors)
        self.error_bar.setText(f"YAML invalid: {messages}")
        self.error_bar.setStyleSheet("color: #b91c1c;")
        self.error_bar.setVisible(True)
        self._mark_error_lines(result.error_lines())

    def _exit_edit(self) -> None:
        """READ_ONLY mode: editor disabled, label back to Edit."""
        self._editing = False
        self.editor.setReadOnly(True)
        self.btn_edit.setText(EDIT_LABEL)
        self.label_changed.emit(EDIT_LABEL)
        self.error_bar.setVisible(False)
        self._clear_error_marks()

    # ------------------------------------------------------- model bind
    def bind_model(self, model: YamlBuildModel) -> None:
        """Bind the model used for edit validation.

        Args:
            model: The data model.
        """
        self._on_edit_model = model

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
