# -*- coding: utf-8 -*-
"""Read-only serial console with ANSI colors and an adjustable background.

The default background is black. Received data is parsed for ANSI SGR
sequences (see :mod:`mtkgui.ansi`) and rendered with a
:class:`QTextCursor`; plain SYS / TX messages use the same rendering
path with a single color.
"""

import datetime
import re

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..ansi import AnsiDecoder
from ..theme import DEFAULT_BACKGROUND, THEMES

# keyword highlight rules (P3-B2 log enhancement): case-insensitive,
# matched per output line
_ERROR_RE = re.compile(r"\berror\b", re.IGNORECASE)
_WARN_RE = re.compile(r"\bwarn(?:ing)?\b", re.IGNORECASE)
ERROR_COLOR = "#ff5555"
WARN_COLOR = "#ffb454"


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
        self.filter_text = ""
        # optional per-channel accent color for the SYS tag
        self.tag_color = None
        # Streaming RX state (Tera Term-style): serial data arrives in
        # arbitrary chunks that must be stitched together. A new line is
        # started ONLY on '\n'; a lone '\r' moves the cursor back to the
        # start of the current line and overwrites it (progress bars such
        # as fat.py's "Progress: [###] 51%" then stay on one line instead
        # of being concatenated into a huge line). Chunk boundaries never
        # start new lines, which removes the fragmented/blank-line noise.
        self._rx_own_line = False       # current block is an open RX line
        self._rx_line_empty = True
        self._rx_want_timestamp = False

        layout = QVBoxLayout(self)
        bar = QHBoxLayout()

        self.check_timestamp = QCheckBox("Timestamp")
        self.check_timestamp.setChecked(False)
        self.check_hex = QCheckBox("HEX")
        self.check_autoscroll = QCheckBox("Auto scroll")
        self.check_autoscroll.setChecked(True)

        # log filter (P3-B2): when set, only incoming lines containing
        # the text (case-insensitive) are appended to the log
        self.edit_filter = QLineEdit()
        self.edit_filter.setPlaceholderText("Filter...")
        self.edit_filter.setMaximumWidth(140)
        self.edit_filter.setToolTip(
            "Log filter: only incoming lines containing this text are "
            "applied to the log (empty = show everything)")
        self.edit_filter.textChanged.connect(self._on_filter_changed)

        btn_clear = QPushButton("Clear")
        btn_clear.setObjectName("flat")
        btn_clear.clicked.connect(self.clear_all)
        btn_save = QPushButton("Save")
        btn_save.setObjectName("flat")
        btn_save.clicked.connect(self.save_log)

        bar.addWidget(self.check_timestamp)
        bar.addWidget(self.check_hex)
        bar.addWidget(self.check_autoscroll)
        bar.addWidget(self.edit_filter)
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

    # -------------------------------------------------------------- font
    def set_font(self, font):
        """Apply a QFont to the log view (persisted per channel)."""
        self.view.setFont(font)

    def font(self) -> QFont:
        """Current log view font (for persistence)."""
        return self.view.font()

    # ------------------------------------------------------------- filter
    def _on_filter_changed(self, text):
        """Store the active filter (applies to INCOMING lines; the
        already-rendered history stays untouched)."""
        self.filter_text = text.strip()

    def _line_allowed(self, line: str) -> bool:
        """True when the line passes the active log filter."""
        needle = self.filter_text.lower()
        return not needle or needle in line.lower()

    @staticmethod
    def _line_color(line: str, base: str):
        """Keyword highlight (P3-B2): Error -> red, Warning -> orange;
        other lines keep their base color."""
        if _ERROR_RE.search(line):
            return ERROR_COLOR, True          # bold error
        if _WARN_RE.search(line):
            return WARN_COLOR, False
        return base, False

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
        """Move to a fresh block before a TX/SYS message: insert one only
        when the current block already holds text (a streamed RX line
        ending in '\\n' has already opened an empty block)."""
        if self._current_block_has_text(cursor):
            cursor.insertBlock()

    def _insert_timestamp(self, cursor):
        if self.check_timestamp.isChecked():
            stamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self.palette["timestamp"]))
            cursor.insertText(f"[{stamp}] ", fmt)

    def _insert_prefix(self, cursor, tag):
        """Timestamp (optional) on every line; only SYS keeps a text
        tag. RX and TX are told apart by color alone (Tera Term style),
        so no RX>> / TX>> prefix is drawn."""
        self._insert_timestamp(cursor)
        if tag == "SYS":
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self.tag_color or self.palette["tag"]))
            cursor.insertText("SYS>> ", fmt)

    def _current_block_has_text(self, cursor):
        probe = QTextCursor(cursor)
        probe.movePosition(QTextCursor.StartOfBlock)
        probe.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        return bool(probe.selectedText())

    def _rx_ensure_line(self, cursor):
        """Continue the open RX line, or start a new block when the
        current line belongs to a TX/SYS message (or is freshly ended)."""
        cursor.movePosition(QTextCursor.End)
        if self._rx_own_line:
            return
        if self._current_block_has_text(cursor):
            cursor.insertBlock()
        self._rx_own_line = True
        self._rx_line_empty = True
        self._rx_want_timestamp = self.check_timestamp.isChecked()

    def _rx_overwrite_line(self, cursor):
        """Lone CR: return to the line start and clear it so the next
        text overwrites in place (in-place progress refresh)."""
        cursor.movePosition(QTextCursor.StartOfBlock)
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        self._rx_line_empty = True
        self._rx_own_line = True
        self._rx_want_timestamp = False

    def _insert_plain(self, cursor, text, color, highlight=False):
        """Insert text line-by-line; with highlight=True every line is
        keyword-checked (Error -> red bold, Warning -> orange) and
        lines failing the active filter are dropped."""
        text = text.replace("\r\n", "\n").replace("\r", "") \
                   .replace("\t", "    ")
        parts = text.split("\n")
        for index, part in enumerate(parts):
            if index:
                cursor.insertBlock()
            if not part:
                continue
            if highlight and not self._line_allowed(part):
                continue
            if highlight:
                line_color, bold = ConsoleWidget._line_color(part, color)
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(line_color))
                if bold:
                    fmt.setFontWeight(QFont.Bold)
                cursor.insertText(part, fmt)
            else:
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(color))
                cursor.insertText(part, fmt)

    def append_message(self, tag, text, color=None):
        """Append a plain colored message (SYS / TX / HEX RX).

        TX and RX carry no text prefix (color identifies them); only
        SYS keeps a ``SYS>>`` tag. The log filter drops non-matching
        lines and Error/Warning keywords are highlighted per line."""
        color = color or self.palette["base"]
        if not self._text_allowed(text):
            return
        cursor = self._end_cursor()
        self._start_new_line(cursor)
        self._insert_prefix(cursor, tag)
        self._insert_plain(cursor, text, color, highlight=True)
        self._scroll()
        # the TX/SYS line now owns the block; the next streamed RX byte
        # starts on a fresh line rather than being glued to it
        self._rx_own_line = False
        self._rx_line_empty = True
        self._rx_want_timestamp = self.check_timestamp.isChecked()

    def append_rx(self, tag, data):
        """Append received bytes as a STREAM, honoring ANSI SGR colors.

        Chunk boundaries never start a new line (a shell line can arrive
        in many reads); lines split only on ``\\n``. A lone ``\\r``
        overwrites the current line in place (progress bars), while
        ``\\r\\n`` is treated as one line ending. There is no RX>>
        prefix; keyword highlighting applies to plain (uncolored) text."""
        if not self._text_allowed(data):
            return
        cursor = self._end_cursor()
        base_fg = self.palette["rx"]
        for text, attrs in self.decoder.feed(data):
            # CRLF is one line ending; a lone CR that remains is an
            # in-place progress refresh (handled below as overwrite).
            text = text.replace("\r\n", "\n").replace("\t", "    ")
            tokens = re.split(r"([\r\n])", text)
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                if tok == "\r":
                    self._rx_overwrite_line(cursor)
                elif tok == "\n":
                    cursor.movePosition(QTextCursor.End)
                    cursor.insertBlock()
                    self._rx_own_line = False
                    self._rx_line_empty = True
                    self._rx_want_timestamp = \
                        self.check_timestamp.isChecked()
                elif tok:
                    self._rx_ensure_line(cursor)
                    if self._rx_want_timestamp:
                        self._insert_timestamp(cursor)
                        self._rx_want_timestamp = False
                    if attrs["fg"] is None:
                        line_color, bold = \
                            ConsoleWidget._line_color(tok, base_fg)
                        fmt = QTextCharFormat()
                        fmt.setForeground(QColor(line_color))
                        if bold:
                            fmt.setFontWeight(QFont.Bold)
                    else:
                        fmt = self._char_format(attrs, base_fg)
                    cursor.insertText(tok, fmt)
                    self._rx_line_empty = False
                i += 1
        self._scroll()

    def _text_allowed(self, text: str) -> bool:
        """Filter gate for a whole chunk (fast reject before parsing)."""
        if not self.filter_text:
            return True
        return any(self._line_allowed(ln)
                   for ln in text.splitlines())

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
        self._rx_own_line = False
        self._rx_line_empty = True
        self._rx_want_timestamp = False

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
