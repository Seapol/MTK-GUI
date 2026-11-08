# -*- coding: utf-8 -*-
"""M80-F: console appendix - ANSI replay, contrast guard, fat.log, dump.

Pure renderer tests (no Qt): the PDF appendix is a terminal replay, every
glyph must be legible on the black appendix background, the run prefers a
pulled fat.log and the full transcript always lands in an ASCII dump file.
"""
from __future__ import annotations

from mtkgui.report_console import (
    DEFAULT_BG,
    DEFAULT_FG,
    render_html,
    sanitize,
    wrapped_lines,
)

#: a small real-shaped transcript: SGR colour, bold, CR progress, DEC box
RAW_LOG = (
    "\x1b[1mFCT boot\x1b[0m\r\n"
    "10%\r50%\r100%\r\n"
    "\x1b(0lqqqqk\x1b(B done\n"
)


# -------------------------------------------------------------------- C1
def test_appendix_renders_ansi_colours_as_spans():
    html = render_html("\x1b[32mOK\x1b[0m plain")
    assert "\x1b" not in html
    assert "<span" in html
    assert "color:#00cd00" in html            # ANSI green survives
    assert "OK" in html and "plain" in html
    assert f"color:{DEFAULT_FG}" in html      # the uncoloured tail


def test_appendix_without_ansi_is_plain_default_grey():
    html = render_html("plain line")
    assert f"color:{DEFAULT_FG}" in html
    assert f"bgcolor='{DEFAULT_BG}'" in html
    assert html.count("color:") == 1          # no inferred colour
    assert "font-weight" not in html
    assert "background-color" not in html


def test_appendix_progress_bar_collapses_to_one_line():
    text = "10%\r20%\r30%\r100%"
    html = render_html(text)
    assert "100%" in html
    assert "10%" not in html
    assert wrapped_lines(text) == 1
    assert sanitize(text) == "100%"


def test_appendix_dec_box_uses_real_line_drawing_chars():
    text = "\x1b(0lqqqqk\x1b(B plain"
    assert sanitize(text) == "\u250c\u2500\u2500\u2500\u2500\u2510 plain"
    assert "\u250c" in render_html(text)


def test_appendix_is_idempotent():
    once = sanitize(RAW_LOG)
    assert sanitize(once) == once
    assert once == "FCT boot\n100%\n\u250c\u2500\u2500\u2500\u2500\u2510 done\n"
