# -*- coding: utf-8 -*-
"""YAML preview pane (right side of the Yaml Build page).

Single fixed ``Apply`` button (user direction: no Edit mode any
more - the YAML editor is DIRECTLY editable):

* the editor is always writable (permission-gated for operator
  accounts); hand edits mark the document as modified so a concurrent
  diagram refresh never wipes the operator's text;
* clicking ``Apply`` runs the YAML validation - on PASS the changes
  persist, the block diagram refreshes and the modified flag clears;
  on FAIL the error hint is shown and the invalid lines are marked
  red.

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

APPLY_LABEL = "Apply"


class YamlPreviewWidget(QWidget):
    """YAML preview with the fixed Apply button and red error marks."""

    #: emitted after a valid hand edit entered the model - the page
    #: uses it to refresh the block cards (YAML -> diagram direction)
    #: and the main window offers the file save
    edits_applied = Signal()

    def __init__(self, parent=None) -> None:
        """Create the preview pane (editor directly editable)."""
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.caption = QLabel("YAML Preview (effective)")
        self.caption.setObjectName("muted")
        bar.addWidget(self.caption)
        bar.addStretch(1)
        lay.addLayout(bar)

        self.editor = QPlainTextEdit()
        self.editor.setMinimumWidth(320)
        lay.addWidget(self.editor, 1)

        self.error_bar = QLabel("")
        self.error_bar.setStyleSheet("color: #b91c1c;")
        self.error_bar.setWordWrap(True)
        self.error_bar.setVisible(False)
        lay.addWidget(self.error_bar)

        self.btn_apply = QPushButton(APPLY_LABEL)
        self.btn_apply.setCheckable(False)
        self.btn_apply.setToolTip(
            "Apply: validate the YAML text; on success the config "
            "enters the model and saving to a file is offered; "
            "invalid edits are kept and marked red")
        self.btn_apply.clicked.connect(self._apply_edits)
        self._on_edit_model: YamlBuildModel | None = None

    # ------------------------------------------------------------- state
    def set_model_text(self, model: YamlBuildModel) -> None:
        """Refresh the preview from the model (diagram -> YAML sync).

        While the operator has UNAPPLIED hand edits (document modified)
        the preview keeps the operator's text - the Apply path drives
        what enters the model.

        Args:
            model: The data model.
        """
        if self.editor.document().isModified():
            return                    # operator text wins until Apply
        text = sync_model_to_yaml(model)
        self.editor.setPlainText(text)
        self.error_bar.setVisible(False)
        # NOTE: the char-format cleanup marks the document modified
        # (Qt internals) - the operator-edit flag is cleared LAST so a
        # plain diagram refresh never blocks the next sync
        self._clear_error_marks()
        self.editor.document().setModified(False)

    # ------------------------------------------------------ permission
    def set_edit_allowed(self, allowed: bool) -> None:
        """Permission gate (T5): without the edit right the Apply
        button is disabled and the editor stays read-only (the
        preview stays viewable)."""
        self.btn_apply.setEnabled(bool(allowed))
        self.editor.setReadOnly(not allowed)

    def _apply_edits(self) -> None:
        """Apply clicked: validate; PASS persists into the model and
        re-syncs the text, FAIL shows the error hint and marks the
        invalid lines red (the operator's text stays)."""
        if self._on_edit_model is None:
            return
        from mtkgui.gui.yamlbuild.sync import validate_yaml_text
        result = validate_yaml_text(self.editor.toPlainText(),
                                    self._on_edit_model)
        if result.ok:
            if result.data is not None:
                self._on_edit_model.apply_yaml_dict(result.data)
            # re-sync the text from the updated model (clears the
            # operator-edit flag as its last step)
            self.set_model_text(self._on_edit_model)
            self.edits_applied.emit()
            return
        # FAIL: error hint, the operator's text stays for correction
        messages = "; ".join(msg for msg, _ in result.errors)
        self.error_bar.setText(f"YAML invalid: {messages}")
        self.error_bar.setStyleSheet("color: #b91c1c;")
        self.error_bar.setVisible(True)
        self._mark_error_lines(result.error_lines())

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
