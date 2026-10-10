# -*- coding: utf-8 -*-
"""Help content provider (Module C): the built-in User Guide renders
the chapter files in docs/help/ as HTML pages opened in the system web
browser (chapter-based, with screenshots and prev/next navigation).

markdown-lite -> HTML (stdlib re only): headings, bullet lists, code
spans / fenced code, bold, images, everything else as paragraphs.
"""
from __future__ import annotations

import re
from pathlib import Path

HELP_ROOT = Path(__file__).resolve().parents[2] / "docs" / "help"

#: ordered chapter list (key, menu label, section file). The Help menu
#: mounts one action per chapter so a click opens that web page.
CHAPTERS = [
    ("user_guide", "1. Overview", "01_overview.md"),
    ("getting_started", "2. Getting Started", "02_getting_started.md"),
    ("test_workflow", "3. Test Work Flow Page", "03_test_workflow.md"),
    ("equipment", "4. Equipment Page", "04_equipment.md"),
    ("yaml_build", "5. Yaml Build Page", "05_yaml_build.md"),
    ("channel_allocation", "6. Channel Allocation Page",
     "06_channel_allocation.md"),
    ("console", "7. Console", "07_console.md"),
    ("reports_logs", "8. Reports & Logs", "08_reports_logs.md"),
    ("cluster", "9. Cluster", "09_cluster.md"),
    ("audit_security", "10. Audit & Security", "10_audit_security.md"),
    ("case_editor_config", "11. Case Editor & Config",
     "11_case_editor_config.md"),
    ("faq", "12. FAQ / Troubleshooting", "12_faq.md"),
]

#: menu key -> section file (kept for direct lookups by key)
HELP_TOPICS = {key: filename for key, _label, filename in CHAPTERS}


def _inline(text: str) -> str:
    """Bold + inline code within one line."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def markdown_to_html(text: str) -> str:
    """Tiny markdown-lite -> HTML (headings, bullets, fenced code,
    bold, inline code; everything else as paragraphs)."""
    out: list = []
    in_code = False
    in_list = False
    for line in (text or "").splitlines():
        if line.strip().startswith("```"):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<pre>" if not in_code else "</pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(line)
            continue
        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            if in_list:
                out.append("</ul>")
                in_list = False
            level = min(len(heading.group(1)) + 1, 5)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        image = re.match(r"^!\[([^\]]*)\]\(([^)\s]+)\)$", stripped)
        if image:
            if in_list:
                out.append("</ul>")
                in_list = False
            alt, src = image.group(1), image.group(2)
            path = Path(src)
            if not path.is_absolute():
                path = HELP_ROOT / src          # images live in docs/help
            out.append(f'<img src="{path.as_uri()}" alt="{alt}">')
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{_inline(stripped)}</p>")
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def load_topic_html(key: str) -> str:
    """One topic rendered as HTML; a missing file degrades to a clear
    placeholder (no dead links in the UI)."""
    filename = HELP_TOPICS.get(key)
    if filename is None:
        return f"<p>Unknown help topic {key!r}.</p>"
    path = HELP_ROOT / filename
    if not path.is_file():
        return (f"<p>Help content file <code>{filename}</code> is not "
                "available in this installation.</p>")
    return markdown_to_html(path.read_text(encoding="utf-8"))


_PAGE_CSS = """
body { font-family: -apple-system, 'Segoe UI', sans-serif; margin: 0;
       color: #1c2733; background: #ffffff; }
header { background: #14375a; color: #fff; padding: 14px 28px; }
header h1 { margin: 0; font-size: 19px; font-weight: 600; }
nav.top { background: #eef3f8; padding: 8px 28px; font-size: 13px; }
nav.top a { color: #1a5c9e; text-decoration: none; margin-right: 14px; }
main { max-width: 980px; margin: 0 auto; padding: 20px 28px 40px; }
h1, h2, h3 { color: #14375a; }
img { max-width: 100%; border: 1px solid #c9d4de; border-radius: 4px;
      margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,.12); }
pre { background: #f4f6f8; border: 1px solid #d7dee5; padding: 10px;
      border-radius: 4px; overflow-x: auto; }
code { background: #f0f2f4; padding: 1px 5px; border-radius: 3px; }
pre code { background: none; padding: 0; }
nav.pager { display: flex; justify-content: space-between;
            margin-top: 36px; padding-top: 14px;
            border-top: 1px solid #d7dee5; }
nav.pager a { color: #1a5c9e; text-decoration: none; font-weight: 600; }
"""


def _chapter_title(label: str) -> str:
    return label.replace("Page", "").strip()


def topic_page_html(key: str) -> str:
    """A full standalone HTML page (styles + top chapter nav + prev /
    next pager) for one help topic; images use absolute file:// URIs so
    the page works from any location in the system browser."""
    try:
        idx = [k for k, _l, _f in CHAPTERS].index(key)
    except ValueError:
        return f"<html><body><p>Unknown help topic {key!r}.</p></body></html>"
    _, label, _file = CHAPTERS[idx]
    body = load_topic_html(key)

    def link(i: int) -> str:
        from pathlib import Path as _P
        return f"mtkgui-help://{_P(CHAPTERS[i][2]).stem}.html"

    chapters = "".join(
        f'<a href="{link(i)}">{c}</a>'
        for i, (_k, c, _f) in enumerate(CHAPTERS) if i != idx)
    prev_next = ""
    if idx > 0:
        prev_next += (f'<a href="{link(idx - 1)}">'
                      f"&larr; {_chapter_title(CHAPTERS[idx - 1][1])}</a>")
    if idx < len(CHAPTERS) - 1:
        prev_next += (f'<a href="{link(idx + 1)}">'
                      f"{_chapter_title(CHAPTERS[idx + 1][1])} &rarr;</a>")
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>MTK GUI User Guide - {label}</title>"
            f"<style>{_PAGE_CSS}</style></head><body>"
            f"<header><h1>MTK GUI User Guide &mdash; {label}</h1></header>"
            f"<nav class='top'>{chapters}</nav>"
            f"<main>{body}"
            f"<nav class='pager'>{prev_next}</nav></main>"
            f"</body></html>")


def topic_temp_path(key: str) -> Path:
    """Stable temp file for a rendered chapter (the browser can cache
    and the file can be re-opened after the app exits)."""
    import tempfile
    out_dir = Path(tempfile.gettempdir()) / "mtk_gui_help"
    out_dir.mkdir(exist_ok=True)
    filename = HELP_TOPICS.get(key, "unknown")
    return out_dir / (Path(filename).stem + ".html")


def open_topic(key: str) -> bool:
    """Render one chapter to HTML and open it in the system web
    browser; returns False for an unknown topic (never a dead link).
    All chapter pages are written so the prev / next / top-nav links
    always point at existing sibling files."""
    if key not in HELP_TOPICS:
        return False
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    page = topic_page_html(key)
    # rewrite the self-referencing chapter links to sibling temp files
    page = page.replace(
        'href="mtkgui-help://',
        f'href="file://{topic_temp_path(key).parent}/')
    for k in HELP_TOPICS:
        topic_temp_path(k).write_text(topic_page_html(k), encoding="utf-8")
    path = topic_temp_path(key)
    path.write_text(page, encoding="utf-8")
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    return True


def about_html() -> str:
    """About dialog body: version + branch + build info."""
    from ..gui_version import load_gui_version
    version, _warning = load_gui_version()
    branch = ""
    try:                                    # best effort (frozen builds)
        from pathlib import Path as _P
        head = (_P(__file__).resolve().parents[2] / ".git" / "HEAD")
        if head.is_file():
            ref = head.read_text().strip()
            if ref.startswith("ref:"):
                ref_path = head.parent / ref.split(" ", 1)[1]
                branch = ref_path.name if ref_path.is_file() else \
                    ref.split("/", 2)[-1]
            else:
                branch = ref[:8]
    except Exception:                       # noqa: BLE001 - cosmetic
        pass
    return (f"<h2>MTK GUI</h2>"
            f"<p>Manufacturing Test Kit — ICT / Flash / FCT / Flash</p>"
            f"<p>Version: <b>{version}</b></p>"
            + (f"<p>Branch: <b>{branch}</b></p>" if branch else "")
            + "<p>© NXP — internal manufacturing test tool.</p>")
