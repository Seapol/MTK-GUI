#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the whole User Guide into ONE self-contained HTML file.

    python scripts/build_help_singlefile.py [out.html]

`docs/help/*.md` stays the source of truth; `build_help.py` builds the
per-chapter site used offline, and this script builds the one file you can
mail or open from anywhere: every chapter in reading order, every screenshot
inlined as a data URI, no external asset.

Use it when a reader outside the repository needs the guide (a reviewer, a
station that has no checkout) or when you want to search the whole guide at
once.
"""
from __future__ import annotations

import base64
import mimetypes
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>MTK GUI - User Guide</title>
<style>
:root { --ink:#12212e; --muted:#5b6b7b; --line:#d8e1ea; --accent:#0f6fb5; }
body { margin:0; font:16px/1.62 -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
       color:var(--ink); background:#f6f8fa; }
header { position:sticky; top:0; z-index:2; background:#fff;
         border-bottom:1px solid var(--line); padding:14px 32px; }
header h1 { margin:0; font-size:19px; letter-spacing:.2px; }
header p { margin:4px 0 0; color:var(--muted); font-size:13px; }
main { max-width:1180px; margin:0 auto; padding:28px 32px 80px; background:#fff;
       box-shadow:0 0 0 1px var(--line); }
nav.toc { border:1px solid var(--line); border-radius:8px; padding:14px 18px;
          margin-bottom:28px; background:#fafcfe; }
nav.toc h2 { font-size:14px; text-transform:uppercase; letter-spacing:.6px;
             color:var(--muted); margin:0 0 10px; }
nav.toc a { display:block; color:var(--accent); text-decoration:none; font-size:14px;
            padding:2px 0; }
section.chapter { border-top:1px solid var(--line); padding-top:26px; margin-top:34px; }
section.chapter:first-of-type { border-top:none; }
section.chapter h1 { font-size:24px; margin:0 0 14px; }
h2 { font-size:19px; margin:26px 0 10px; }
h3 { font-size:16px; margin:20px 0 8px; }
p { margin:0 0 12px; }
img { max-width:100%; display:block; margin:14px 0;
      border:1px solid var(--line); border-radius:6px; }
pre { background:#0f1b26; color:#e6edf3; padding:12px 14px; border-radius:6px;
      overflow:auto; font-size:13px; }
code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size:13px; }
table { border-collapse:collapse; width:100%; margin:12px 0 16px; font-size:14px; }
th, td { border:1px solid var(--line); padding:7px 10px; text-align:left;
         vertical-align:top; }
th { background:#f1f5f9; }
ul, ol { margin:0 0 12px 22px; }
</style></head><body>
<header><h1>MTK GUI - User Guide</h1>
<p>All chapters in reading order, screenshots inlined. Generated from
docs/help/*.md - that folder is the source of truth.</p></header>
<main>
"""

TAIL = "</main></body></html>\n"


def _inline_images(html: str) -> str:
    """file:// image URIs -> base64 data URIs, so the page needs no files."""
    def repl(match: re.Match) -> str:
        uri = match.group(1)
        if not uri.startswith("file://"):
            return match.group(0)
        path = Path(uri[len("file://"):].replace("%20", " "))
        if not path.is_file():
            return match.group(0)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'src="data:{mime};base64,{data}"'

    return re.sub(r'src="(file://[^"]+)"', repl, html)


def main() -> int:
    from mtkgui.gui.help_content import CHAPTERS, HELP_ROOT, \
        markdown_to_html, version_history_page_html

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "docs" / "help" / "_build" / "MTK_GUI_User_Guide.html"

    parts = [HEAD, '<nav class="toc"><h2>Chapters</h2>']
    bodies = []
    for index, (_key, label, filename) in enumerate(CHAPTERS):
        source = HELP_ROOT / filename
        if not source.is_file():
            print(f"missing chapter: {filename}", file=sys.stderr)
            return 1
        parts.append(f'<a href="#ch{index}">{label}</a>')
        body = _inline_images(markdown_to_html(source.read_text(
            encoding="utf-8")))
        bodies.append(f'<section class="chapter" id="ch{index}">{body}</section>')
    parts.append("</nav>")
    parts.append("".join(bodies))

    history = _inline_images(version_history_page_html())
    body = re.search(r"<body[^>]*>(.*)</body>", history, re.S)
    parts.append('<section class="chapter" id="ch-history">'
                 + (body.group(1) if body else "") + "</section>")
    parts.append(TAIL)

    html = "".join(parts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    images = html.count('src="data:image')
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, "
          f"{len(CHAPTERS)} chapters, {images} inlined images)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
