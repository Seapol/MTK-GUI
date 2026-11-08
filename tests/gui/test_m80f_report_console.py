# -*- coding: utf-8 -*-
"""M80-F: console appendix - ANSI replay, contrast guard, fat.log, dump.

Pure renderer tests (no Qt): the PDF appendix is a terminal replay, every
glyph must be legible on the black appendix background, the run prefers a
pulled fat.log and the full transcript always lands in an ASCII dump file.
"""
from __future__ import annotations

from types import SimpleNamespace

from mtkgui.report_console import (
    DEFAULT_BG,
    DEFAULT_FG,
    contrast,
    ensure_contrast,
    luminance,
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


# -------------------------------------------------------------------- C2
#: the hostile palette from the directive §0: (fg, bg) as the decoder yields it
_HOSTILE = [
    ("#000000", "#000000"),   # black on black
    ("#0000ee", "#000000"),   # SGR 34 dark blue
    ("#00005f", "#000000"),   # 256-colour index 17
    ("#0c0c0c", "#000000"),   # truecolor 12,12,12
    ("#e5e5e5", "#e5e5e5"),   # 47;37 white on white
    ("#eeeeee", "#ffffff"),   # 48;5;231;38;5;255 pale on light
    ("#7f7f7f", "#7f7f7f"),   # 100;90 grey on grey
    ("#cd0000", "#000000"),   # SGR 31 dark red
]


def test_contrast_guard_meets_4_5_for_eight_hostile_cases():
    assert len(_HOSTILE) == 8
    for foreground, background in _HOSTILE:
        assert contrast(foreground, background) < 4.5, (
            f"{foreground} on {background} was already legible - "
            "the guard would not have acted")
        fixed = ensure_contrast(foreground, background, 4.5)
        assert contrast(fixed, background) >= 4.5, (foreground, background)


def test_dim_text_keeps_3_0_contrast_and_stays_darker_than_normal():
    import re

    html = render_html("\x1b[2mDIM\x1b[0m NORMAL")
    colours = re.findall(r"color:(#[0-9a-f]{6})", html)
    assert len(colours) == 2, colours
    dim, normal = colours
    assert contrast(dim, DEFAULT_BG) >= 3.0
    assert luminance(dim) < luminance(normal)
    assert contrast(normal, DEFAULT_BG) >= 4.5


# -------------------------------------------------------------------- C3
def _page(runner, mc=None):
    """Minimal Test Work Flow stub (empty tables, no console channels)."""
    return SimpleNamespace(
        ict_steps=[], fct_rows=[],
        multi_console=mc or SimpleNamespace(
            channels={}, get_read_buffer=lambda key: b""),
        _runner=runner)


def test_fat_log_is_preferred_when_the_run_pulled_one(tmp_path):
    from mtkgui.engine.report import DutReport

    older = tmp_path / "run1" / "fat.log"
    older.parent.mkdir()
    older.write_text("OLD RUN\n", encoding="utf-8")
    newest = tmp_path / "run2" / "fat.log"
    newest.parent.mkdir()
    newest.write_text("FAT VERDICT PASS\nline2\n", encoding="utf-8")
    other = tmp_path / "notes.txt"
    other.write_text("not a fat log\n", encoding="utf-8")
    runner = SimpleNamespace(run_start_offsets={}, run_pulled_files=[
        str(older), str(other), str(newest)])
    report = DutReport.from_session(_page(runner))
    assert report.console_source == "fat.log"
    assert report.console_log == "FAT VERDICT PASS\nline2\n"


def test_console_dump_is_used_when_no_fat_log(tmp_path):
    from mtkgui.engine.report import DutReport

    pulled = tmp_path / "assets.tar"
    pulled.write_text("", encoding="utf-8")
    mc = SimpleNamespace(
        channels={"console": object()},
        get_read_buffer=lambda key: b"\x1b[32mhello\x1b[0m")
    runner = SimpleNamespace(run_start_offsets={},
                             run_pulled_files=[str(pulled)])
    report = DutReport.from_session(_page(runner, mc))
    assert report.console_source == "console"
    assert report.console_log.startswith("===== console =====")
    assert "hello" in report.console_log
