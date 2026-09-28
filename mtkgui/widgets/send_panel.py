# -*- coding: utf-8 -*-
"""Data send panel: input line with history, CR+LF / HEX options."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
)


class CommandLineEdit(QLineEdit):
    """QLineEdit with Up/Down history and Tab completion.

    Completion candidates are drawn from the sent-command history plus an
    externally-supplied list (quick commands, AT commands, ...).  The
    first Tab expands to the longest common prefix of all matches; a
    single match is completed in full.  Repeated Tab presses cycle
    through the matches; Shift+Tab cycles backwards.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []
        self._index = 0
        self._draft = ""
        # tab-completion cycling state
        self._completions = []
        self._completion_index = 0
        self._extra_candidates = []

    # --------------------------------------------------------- candidates
    def set_extra_candidates(self, candidates):
        """Replace the externally supplied completion candidates."""
        self._extra_candidates = [str(c) for c in candidates if c]

    def add_extra_candidate(self, candidate):
        candidate = str(candidate).strip()
        if candidate and candidate not in self._extra_candidates:
            self._extra_candidates.append(candidate)

    def _all_candidates(self):
        seen = set()
        out = []
        for src in (self._history, self._extra_candidates):
            for c in src:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return out

    # ----------------------------------------------------------- history
    def push_history(self, text):
        text = text.strip()
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
            if len(self._history) > 50:
                self._history.pop(0)
        self._index = len(self._history)
        self._draft = ""

    # ------------------------------------------------------- completion
    def _word_at_cursor(self):
        """Return ``(prefix, start_index)`` for the word under the cursor."""
        text = self.text()
        cursor = self.cursorPosition()
        start = text.rfind(" ", 0, cursor) + 1
        return text[start:cursor], start

    def _reset_completion(self):
        self._completions = []
        self._completion_index = 0

    def _do_tab_complete(self, backward=False):
        prefix, start = self._word_at_cursor()
        if not self._completions:
            # first Tab on a fresh prefix: gather matches
            matches = sorted(
                c for c in self._all_candidates()
                if c.startswith(prefix))
            if not matches:
                return
            if len(matches) == 1:
                self._apply_completion(start, matches[0])
                return
            # multiple matches -> expand to common prefix first
            common = os.path.commonprefix(matches)
            if len(common) > len(prefix):
                self._apply_completion(start, common)
                prefix = common  # prefix now equals the expanded text
            # arm cycling for the next Tab
            self._completions = matches
            self._completion_index = 0
            return
        # subsequent Tab: cycle through armed matches
        step = -1 if backward else 1
        self._completion_index = (
            (self._completion_index + step) % len(self._completions))
        self._apply_completion(start, self._completions[self._completion_index])

    def _apply_completion(self, start, replacement):
        text = self.text()
        cursor = self.cursorPosition()
        new_text = text[:start] + replacement + text[cursor:]
        self.setText(new_text)
        self.setCursorPosition(start + len(replacement))

    # ------------------------------------------------------------ keys
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Up and self._history:
            if self._index == len(self._history):
                self._draft = self.text()
            self._index = max(0, self._index - 1)
            self.setText(self._history[self._index])
            self._reset_completion()
            return
        if key == Qt.Key_Down and self._history:
            self._index = min(len(self._history), self._index + 1)
            if self._index == len(self._history):
                self.setText(self._draft)
                self._draft = ""
            else:
                self.setText(self._history[self._index])
            self._reset_completion()
            return
        if key == Qt.Key_Tab:
            self._do_tab_complete(
                backward=bool(event.modifiers() & Qt.ShiftModifier))
            return
        # any other key/modifier breaks the completion cycle
        self._reset_completion()
        super().keyPressEvent(event)


class SendPanel(QGroupBox):
    # text, hex mode, append CR+LF
    send_requested = Signal(str, str, bool, bool)

    def __init__(self, role_key, title, parent=None):
        super().__init__(title, parent)
        self.role_key = role_key

        layout = QHBoxLayout(self)
        self.edit = CommandLineEdit()
        self.edit.setPlaceholderText(
            "Type a command, press Enter; Up/Down for history")
        self.edit.returnPressed.connect(self._emit_send)
        layout.addWidget(self.edit, 1)

        self.check_crlf = QCheckBox("CR+LF")
        self.check_crlf.setChecked(True)
        layout.addWidget(self.check_crlf)

        self.check_hex = QCheckBox("HEX")
        layout.addWidget(self.check_hex)

        btn_send = QPushButton("Send")
        btn_send.clicked.connect(self._emit_send)
        layout.addWidget(btn_send)

    def _emit_send(self):
        text = self.edit.text()
        if text:
            self.send_requested.emit(
                self.role_key, text,
                self.check_hex.isChecked(),
                self.check_crlf.isChecked())

    def set_text(self, text):
        self.edit.setText(text)

    def commit_sent(self, original_text):
        """Remember the command in history and clear the line."""
        self.edit.push_history(original_text)
        self.edit.clear()
