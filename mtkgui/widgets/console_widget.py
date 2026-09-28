# -*- coding: utf-8 -*-
"""Read-only serial console with ANSI colors and an adjustable background.

The default background is black. Received data is parsed for ANSI SGR
sequences (see :mod:`mtkgui.ansi`) and rendered with a
:class:`QTextCursor`; plain SYS / TX messages use the same rendering
path with a single color.
"""

import datetime

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..ansi import AnsiDecoder
from ..theme import DEFAULT_BACKGROUND, THEMES


def _blend(color_a, color_b, ratio):
    """Blend two hex colors; ratio is the weight of color_b."""
    a = color_a.lstrip("#")
    b = color_b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        va = int(a[i:i + 2], 16)
        vb = int(b[i:i + 2], 16)
        out.append(int(va * (1 - ratio) + vb * ratio))
    return f"#{out[0]:02x}{out[1]:02x}{out[2]:02x}"


class _ConsoleOutput(QTextEdit):
    """Read-only output area that reports double-clicks."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class ConsoleWidget(QGroupBox):
    # emitted on a double-click inside the receive window (used to open
    # the per-channel connection configuration dialog)
    doubleClicked = Signal()

    def __init__(self, role_key, title, default_filename, parent=None):
        super().__init__(title, parent)
        self.role_key = role_key
        self.default_filename = default_filename

        self.bg_color = DEFAULT_BACKGROUND
        self.palette = THEMES["dark"]
        self.decoder = AnsiDecoder()
        # optional per-channel accent color for the RX/TX/SYS tag
        self.tag_color = None

        layout = QVBoxLayout(self)
        bar = QHBoxLayout()

        self.check_timestamp = QCheckBox("Timestamp")
        self.check_timestamp.setChecked(True)
        self.check_hex = QCheckBox("HEX")
        self.check_autoscroll = QCheckBox("Auto scroll")
        self.check_autoscroll.setChecked(True)

        btn_clear = QPushButton("Clear")
        btn_clear.setObjectName("flat")
        btn_clear.clicked.connect(self.clear_all)
        btn_save = QPushButton("Save")
        btn_save.setObjectName("flat")
        btn_save.clicked.connect(self.save_log)

        bar.addWidget(self.check_timestamp)
        bar.addWidget(self.check_hex)
        bar.addWidget(self.check_autoscroll)
        bar.addStretch(1)
        bar.addWidget(btn_clear)
        bar.addWidget(btn_save)
        layout.addLayout(bar)

        self.view = _ConsoleOutput()
        self.view.setObjectName("console")
        self.view.setReadOnly(True)
        self.view.setMinimumHeight(50)
        self.view.double_clicked.connect(self.doubleClicked)
        layout.addWidget(self.view, 1)

        self.set_background(self.bg_color)

    def set_accent(self, color):
        """Set the per-channel tag color (RX>> / TX>> / SYS>> prefix)."""
        self.tag_color = color

    # ---------------------------------------------------------- background
    def set_background(self, color):
        """Set the console background (QColor or hex) and its palette."""
        if isinstance(color, QColor):
            color = color.name()
        self.bg_color = color
        from ..theme import theme_for
        self.palette = THEMES[theme_for(color)]
        border = self.palette["border"]
        self.view.setStyleSheet(
            f'QTextEdit#console {{'
            f' background-color: {color};'
            f' border: 1px solid {border};'
            f' border-radius: 4px;'
            f'}}')

    # ------------------------------------------------------------ output
    def _end_cursor(self):
        cursor = QTextCursor(self.view.document())
        cursor.movePosition(QTextCursor.End)
        return cursor

    def _start_new_line(self, cursor):
        doc_empty = (self.view.document().blockCount() <= 1
                     and not self.view.toPlainText())
        if not doc_empty:
            cursor.insertBlock()

    def _insert_prefix(self, cursor, tag):
        if self.check_timestamp.isChecked():
            stamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self.palette["timestamp"]))
            cursor.insertText(f"[{stamp}] ", fmt)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self.tag_color or self.palette["tag"]))
        cursor.insertText(f"{tag}>> ", fmt)

    @staticmethod
    def _insert_plain(cursor, text, color):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        text = text.replace("\r\n", "\n").replace("\r", "") \
                   .replace("\t", "    ")
        parts = text.split("\n")
        for index, part in enumerate(parts):
            if index:
                cursor.insertBlock()
            if part:
                cursor.insertText(part, fmt)

    def append_message(self, tag, text, color=None):
        """Append a plain colored message (SYS / TX / HEX RX)."""
        color = color or self.palette["base"]
        cursor = self._end_cursor()
        self._start_new_line(cursor)
        self._insert_prefix(cursor, tag)
        self._insert_plain(cursor, text, color)
        self._scroll()

    def append_rx(self, tag, data):
        """Append received bytes, honoring ANSI SGR sequences."""
        cursor = self._end_cursor()
        self._start_new_line(cursor)
        self._insert_prefix(cursor, tag)

        base_fg = self.palette["rx"]
        for text, attrs in self.decoder.feed(data):
            fmt = self._char_format(attrs, base_fg)
            text = text.replace("\r\n", "\n").replace("\r", "") \
                       .replace("\t", "    ")
            parts = text.split("\n")
            for index, part in enumerate(parts):
                if index:
                    cursor.insertBlock()
                if part:
                    cursor.insertText(part, fmt)
        self._scroll()

    def _char_format(self, attrs, base_fg):
        fg = attrs["fg"] or base_fg
        bg = attrs["bg"]
        if attrs["reverse"]:
            fg, bg = bg or self.bg_color, attrs["fg"] or base_fg
        if attrs["dim"]:
            fg = _blend(fg, self.bg_color, 0.55)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(fg))
        if bg:
            fmt.setBackground(QColor(bg))
        if attrs["bold"]:
            fmt.setFontWeight(QFont.Bold)
        fmt.setFontItalic(attrs["italic"])
        fmt.setFontUnderline(attrs["underline"])
        return fmt

    def _scroll(self):
        if self.check_autoscroll.isChecked():
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    # ------------------------------------------------------------ actions
    def clear_all(self):
        self.view.clear()
        self.decoder.reset()

    def save_log(self):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        suggested = f"{self.default_filename}_{stamp}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save console log", suggested,
            "Text files (*.txt);;All files (*)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.view.toPlainText())
            self.append_message(
                "SYS", f"Log saved: {path}", color=self.palette["sys"])
