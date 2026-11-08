# -*- coding: utf-8 -*-
"""Console appendix renderer for the DUT certificate (M80-F).

The PDF appendix is a faithful terminal replay: ANSI SGR colours, DEC
box-drawing characters, carriage-return progress frames, hard-wrapped into one
black monospace cell.  The module is Qt-free so the pipeline is unit-testable.

``mtkgui/engine/fct_test_runner.strip_ansi`` is deliberately NOT reused: it
rewrites ``\\r`` to ``\\n`` for the message matcher and must stay untouched
(the renderer therefore has its own pipeline).

No ANSI => no colour: plain text renders the default grey on black.
"""
from __future__ import annotations

import html as _html
import re

from .ansi import AnsiDecoder

#: default appendix colours (console look on white paper)
DEFAULT_FG = "#e6e6e6"
DEFAULT_BG = "#000000"

#: measured A4 appendix capacity (see the M80-F directive §0)
APPENDIX_MAX_PAGES = 10
APPENDIX_LINES_PER_PAGE = 80
APPENDIX_MAX_LINES = APPENDIX_MAX_PAGES * APPENDIX_LINES_PER_PAGE

#: DEC special-graphics (``ESC ( 0``) -> real box-drawing characters
_DEC_GRAPHICS = {
    "l": "\u250c", "q": "\u2500", "k": "\u2510", "x": "\u2502",
    "m": "\u2514", "j": "\u2518", "t": "\u251c", "u": "\u2524",
    "v": "\u2534", "w": "\u252c", "n": "\u253c", "a": "\u2592",
    "~": "\u00b7", "`": "\u25c6", "f": "\u00b0", "g": "\u00b1",
}

#: OSC (window title ...) with a bounded body; BEL or ST terminated
_OSC_RE = re.compile("\x1b\\][^\x07\x1b]{0,4096}(?:\x07|\x1b\\\\)")
#: every CSI sequence (SGR included - the sanitized form is plain text)
_CSI_RE = re.compile("\x1b\\[[0-?]*[ -/]*[@-~]")
#: C0 controls worth keeping
_KEEP_C0 = "\n\t\r"
_C0_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: tab stop used when replaying the transcript
_TAB = 8


# ------------------------------------------------------------- sanitize
def _translate_dec(text: str) -> str:
    """Map DEC special-graphics characters to real box-drawing glyphs."""
    out: list[str] = []
    dec = False
    index = 0
    while index < len(text):
        if text.startswith("\x1b(0", index):
            dec = True
            index += 3
            continue
        if text.startswith("\x1b(B", index):
            dec = False
            index += 3
            continue
        char = text[index]
        out.append(_DEC_GRAPHICS.get(char, char) if dec else char)
        index += 1
    return "".join(out)


def _replay_cr(text: str) -> str:
    """``\\r`` overwrites the current line, ``\\n`` starts a new one.

    A ``\\r\\n`` pair is one newline (Windows-style line endings), so a
    progress report ``10%\\r20%\\r30%\\n`` collapses to ``30%``.
    """
    text = text.replace("\r\n", "\n")
    lines: list[str] = []
    current: list[str] = []
    for char in text:
        if char == "\r":
            current = []
        elif char == "\n":
            lines.append("".join(current))
            current = []
        else:
            current.append(char)
    lines.append("".join(current))
    return "\n".join(lines)


def sanitize(text: str) -> str:
    """ANSI/DEC/OSC/C0 removal with CR replay - the plain ASCII form."""
    text = re.sub("\ufffd+", "\ufffd", str(text or ""))
    text = _translate_dec(text)
    text = _OSC_RE.sub("", text)
    text = _CSI_RE.sub("", text)
    text = text.replace("\x1b=", "").replace("\x1b>", "")
    text = _C0_RE.sub("", text)
    return _replay_cr(text)


# ------------------------------------------------------------- rendering
def _blend(color_a: str, color_b: str, ratio: float) -> str:
    """Blend two hex colours (weight of *color_b*), the console rule."""
    a = color_a.lstrip("#")
    b = color_b.lstrip("#")
    out = []
    for index in (0, 2, 4):
        va = int(a[index:index + 2], 16)
        vb = int(b[index:index + 2], 16)
        out.append(int(va * (1 - ratio) + vb * ratio))
    return f"#{out[0]:02x}{out[1]:02x}{out[2]:02x}"


def _colours(attrs: dict) -> tuple[str, str]:
    """``(fg, bg)`` after reverse and dim, before the contrast guard."""
    fg = attrs.get("fg") or DEFAULT_FG
    bg = attrs.get("bg") or DEFAULT_BG
    if attrs.get("reverse"):
        fg, bg = bg, fg
    if attrs.get("dim"):
        fg = _blend(fg, bg, 0.5)
    return fg, bg


def _css(attrs: dict) -> str:
    """Inline CSS for one attribute run (palette fixed by the theme)."""
    fg, bg = _colours(attrs)
    fg = ensure_contrast(fg, bg, 3.0 if attrs.get("dim") else 4.5)
    rules = [f"color:{fg}"]
    if bg != DEFAULT_BG:
        rules.append(f"background-color:{bg}")
    if attrs.get("bold"):
        rules.append("font-weight:700")
    if attrs.get("underline"):
        rules.append("text-decoration:underline")
    return "; ".join(rules)


# ------------------------------------------------------- contrast guard
def _linear(channel: str) -> float:
    value = int(channel, 16) / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def luminance(hex_colour) -> float:
    """WCAG relative luminance of ``#rrggbb``."""
    colour = str(hex_colour or "").lstrip("#")
    if len(colour) != 6:
        return 0.0
    return (0.2126 * _linear(colour[0:2])
            + 0.7152 * _linear(colour[2:4])
            + 0.0722 * _linear(colour[4:6]))


def contrast(a, b) -> float:
    """WCAG contrast ratio between two ``#rrggbb`` colours."""
    first, second = luminance(a), luminance(b)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


def ensure_contrast(fg, bg, target=4.5) -> str:
    """Blend *fg* toward white (dark bg) / black (light bg) until *target*.

    The hue direction is preserved - the glyph gets lighter (or darker) on
    its own background instead of being replaced by a fixed colour.
    """
    if contrast(fg, bg) >= target:
        return fg
    # blend toward whichever extreme this background can actually reach:
    # mid-grey backgrounds (luminance 0.21) cannot reach 4.5 toward white
    toward = ("#ffffff" if contrast("#ffffff", bg) >= contrast("#000000", bg)
              else "#000000")
    low, high = 0.0, 1.0
    for _ in range(12):
        mid = (low + high) / 2.0
        if contrast(_blend(fg, toward, mid), bg) >= target:
            high = mid
        else:
            low = mid
    candidate = _blend(fg, toward, high)
    # 8-bit rounding can drop a hair below the target - the extreme end is
    # the maximum this background allows, so use it only then
    return candidate if contrast(candidate, bg) >= target else toward


def _cells(text: str) -> list[list[tuple[str, dict]]]:
    """Decode the transcript into replayed lines of ``(char, attrs)``."""
    text = _translate_dec(str(text or "")).replace("\r\n", "\n")
    decoder = AnsiDecoder()
    lines: list[list[tuple[str, dict]]] = [[]]
    for chunk, attrs in decoder.feed(text.encode("utf-8", "replace")):
        for char in chunk:
            if char == "\r":
                lines[-1] = []
            elif char == "\n":
                lines.append([])
            elif char == "\t":
                lines[-1].extend([(" ", dict(attrs))] * _TAB)
            else:
                lines[-1].append((char, dict(attrs)))
    return lines


def render_html(text: str, wrap: int = 110) -> str:
    """One black monospace table cell replaying the transcript."""
    out: list[str] = []
    for line in _cells(text):
        run_css: str | None = None
        run_text: list[str] = []
        column = 0

        def flush():
            nonlocal run_css, run_text
            if run_text:
                out.append(f"<span style=\"{run_css}\">"
                           + "".join(run_text) + "</span>")
                run_text = []

        for char, attrs in line:
            css = _css(attrs)
            if css != run_css:
                flush()
                run_css = css
            if column >= wrap:
                flush()
                out.append("<br>")
                column = 0
            run_text.append("&nbsp;" if char == " " else _html.escape(char))
            column += 1
        flush()
        out.append("<br>")
    return ("<table width='100%' cellspacing='0' cellpadding='4'>"
            "<tr><td bgcolor='#000000' style=\""
            "font-family:Menlo,Consolas,monospace; font-size:8px\">"
            + "".join(out) + "</td></tr></table>")


def wrapped_lines(text: str, wrap: int = 110) -> int:
    """Number of A4 appendix lines this transcript needs."""
    total = 0
    for line in _cells(text):
        total += max(1, -(-len(line) // max(1, wrap)))
    return total


def omitted_pointer(dump_name: str, lines: int) -> str:
    """The single paragraph that replaces an over-long appendix."""
    return ("<p>Full console log: "
            f"{_html.escape(dump_name or 'console_log.txt')} "
            f"(ASCII, {int(lines)} lines) \u2014 omitted from this PDF "
            f"(limit {APPENDIX_MAX_PAGES} pages).</p>")


__all__ = [
    "APPENDIX_LINES_PER_PAGE",
    "APPENDIX_MAX_LINES",
    "APPENDIX_MAX_PAGES",
    "DEFAULT_BG",
    "DEFAULT_FG",
    "contrast",
    "ensure_contrast",
    "luminance",
    "omitted_pointer",
    "render_html",
    "sanitize",
    "wrapped_lines",
]
