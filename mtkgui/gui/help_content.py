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
#: 2026-10-14: chapter 6 (Channel Allocation) merged into the Yaml
#: Build chapter; the Cluster chapter was removed (not user-facing);
#: chapters 3 (Menus Reference), 6 (Instruments), 7 (Station
#: Equipment) and 8 (Hardware BoM) were added - fourteen chapters in
#: total.
CHAPTERS = [
    ("user_guide", "1. Overview", "01_overview.md"),
    ("getting_started", "2. Getting Started", "02_getting_started.md"),
    ("menus", "3. Menus Reference", "03_menus.md"),
    ("test_workflow", "4. Test Work Flow Page", "04_test_workflow.md"),
    ("equipment", "5. Equipment Page", "05_equipment.md"),
    ("instruments", "6. Instruments", "06_instruments.md"),
    ("station_equipment", "7. Station Equipment",
     "07_station_equipment.md"),
    ("hardware_bom", "8. Hardware BoM", "08_hardware_bom.md"),
    ("yaml_build", "9. Yaml Build Page", "09_yaml_build.md"),
    ("console", "10. Console", "10_console.md"),
    ("reports_logs", "11. Reports & Logs", "11_reports_logs.md"),
    ("audit_security", "12. Audit & Security", "12_audit_security.md"),
    ("case_editor_config", "13. Case Editor & Config",
     "13_case_editor_config.md"),
    ("faq", "14. FAQ / Troubleshooting", "14_faq.md"),
]

#: menu key -> section file (kept for direct lookups by key)
HELP_TOPICS = {key: filename for key, _label, filename in CHAPTERS}


def _inline(text: str) -> str:
    """Links + bold + inline code within one line."""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                  r'<a href="\2" target="_blank">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def markdown_to_html(text: str) -> str:
    """Markdown-lite -> HTML with markdown block semantics: consecutive
    text lines merge into ONE paragraph (soft wrap), '- / *' bullets
    become <ul> and '1.' items become <ol> with indented continuation
    lines joining their item, plus pipe tables, headings, images and
    fenced code.  The source files are hard-wrapped at ~72 columns, so
    line merging is what lets the text fill the full content width."""
    out: list = []
    para: list = []                       # pending paragraph lines
    list_items: tuple | None = None       # ("ul"|"ol", [item html...])
    table: list = []
    in_code = False

    def flush_para() -> None:
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            kind, items = list_items
            tag = "ol" if kind == "ol" else "ul"
            out.append(f"<{tag}>" + "".join(
                f"<li>{_inline(t)}</li>" for t in items) + f"</{tag}>")
            list_items = None

    def flush_table() -> None:
        """Emit the collected | pipe rows as an HTML table."""
        if not table:
            return
        rows = []
        for raw in table:
            cells = [c.strip() for c in raw.strip().strip("|").split("|")]
            if cells and all(
                    re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
                continue                      # alignment separator row
            rows.append(cells)
        if rows:
            out.append("<table>")
            out.append("<tr>" + "".join(
                f"<th>{_inline(c)}</th>" for c in rows[0]) + "</tr>")
            for r in rows[1:]:
                out.append("<tr>" + "".join(
                    f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
            out.append("</table>")
        table.clear()

    def flush_blocks() -> None:
        flush_para()
        flush_list()
        flush_table()

    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_blocks()
            out.append("<pre>" if not in_code else "</pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(line)
            continue
        if not stripped:
            flush_blocks()
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_para()
            flush_list()
            table.append(stripped)
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            flush_blocks()
            level = min(len(heading.group(1)) + 1, 5)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        image = re.match(r"^!\[([^\]]*)\]\(([^)\s]+)\)$", stripped)
        if image:
            flush_blocks()
            alt, src = image.group(1), image.group(2)
            path = Path(src)
            if not path.is_absolute():
                path = HELP_ROOT / src          # images live in docs/help
            out.append(f'<img src="{path.as_uri()}" alt="{alt}">')
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            flush_para()
            flush_table()
            if list_items is None or list_items[0] != "ul":
                flush_list()
                list_items = ("ul", [])
            list_items[1].append(bullet.group(1))
            continue
        ordered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if ordered:
            flush_para()
            flush_table()
            if list_items is None or list_items[0] != "ol":
                flush_list()
                list_items = ("ol", [])
            list_items[1].append(ordered.group(1))
            continue
        # plain text: a continuation of the pending list item, or part
        # of the pending paragraph (the source hard-wraps at ~72 cols)
        flush_table()
        if list_items is not None:
            list_items[1][-1] += " " + stripped
        else:
            para.append(stripped)
    flush_blocks()
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def load_topic_html(key: str) -> str:
    """One topic rendered as HTML; a missing file degrades to a clear
    placeholder (no dead links in the UI).

    The chapter heading is prefixed with the chapter number (from the
    CHAPTERS order) so the body headings match the sidebar / pager
    numbering - the number lives in ONE place and survives chapter
    re-ordering without editing the markdown files."""
    filename = HELP_TOPICS.get(key)
    if filename is None:
        return f"<p>Unknown help topic {key!r}.</p>"
    path = HELP_ROOT / filename
    if not path.is_file():
        return (f"<p>Help content file <code>{filename}</code> is not "
                "available in this installation.</p>")
    html = markdown_to_html(path.read_text(encoding="utf-8"))
    index = next((i for i, (_k, _l, f) in enumerate(CHAPTERS)
                  if f == filename), None)
    if index is not None and html.startswith("<h2>"):
        html = f"<h2>{index + 1}. " + html[len("<h2>"):]
    return html


_PAGE_CSS = """
body { font-family: -apple-system, 'Segoe UI', sans-serif; margin: 0;
       color: #1c2733; background: #ffffff; }
header { background: #14375a; color: #fff; padding: 14px 28px; }
header h1 { margin: 0; font-size: 19px; font-weight: 600; }
nav.top { background: #eef3f8; padding: 8px 28px; font-size: 13px; }
nav.top a { color: #1a5c9e; text-decoration: none; margin-right: 14px; }
main { max-width: 1400px; margin: 0 auto; padding: 20px 24px 44px; }
body { line-height: 1.55; }
p { margin: 10px 0; }
ul, ol { margin: 10px 0; padding-left: 30px; }
li { margin: 4px 0; }
h1, h2, h3, h4, h5 { line-height: 1.3; }
h1, h2, h3 { color: #14375a; }
img { max-width: 100%; border: 1px solid #c9d4de; border-radius: 4px;
      margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,.12); }
pre { background: #f4f6f8; border: 1px solid #d7dee5; padding: 10px;
      border-radius: 4px; overflow-x: auto; }
code { background: #f0f2f4; padding: 1px 5px; border-radius: 3px; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; margin: 12px 0; font-size: 14.5px; }
th, td { border: 1px solid #d7dee5; padding: 7px 14px;
         text-align: left; vertical-align: top; }
th { background: #eef3f8; color: #14375a; }
a { color: #1a5c9e; text-decoration: none; }
a:hover { text-decoration: underline; }
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


#: layout + behaviour of the all-in-one User Guide home page
_GUIDE_CSS = _PAGE_CSS + """
layout { display: block; }
aside { position: fixed; top: 0; left: 0; bottom: 0; width: 250px;
        overflow-y: auto; background: #14375a; padding: 18px 14px; }
aside h2 { color: #fff; font-size: 15px; margin: 0 0 12px; }
aside a { display: block; color: #cfe0f1; text-decoration: none;
          font-size: 13.5px; padding: 6px 8px; border-radius: 4px;
          margin: 2px 0; }
aside a:hover { background: #25527e; color: #fff; }
div.guide { margin-left: 250px; }
div.guide > main { max-width: 1340px; }
section.chapter { border-top: 1px solid #d7dee5;
                  padding-top: 8px; margin-top: 26px; }
section.chapter:first-of-type { border-top: none; }
@media (max-width: 900px) { aside { position: static; width: auto; }
  div.guide { margin-left: 0; } }
"""


def guide_page_html() -> str:
    """The all-in-one User Guide home page: a fixed sidebar with the
    chapter table of contents and all fourteen chapters rendered on one
    page (anchor links, screenshots included)."""
    toc = "".join(
        f'<a href="#chapter-{i + 1}">{label}</a>'
        for i, (_k, label, _f) in enumerate(CHAPTERS))
    body = "".join(
        f'<section class="chapter" id="chapter-{i + 1}">'
        f"{load_topic_html(key)}</section>"
        for i, (key, _label, _f) in enumerate(CHAPTERS))
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>MTK GUI User Guide</title>"
            f"<style>{_GUIDE_CSS}</style></head><body>"
            f"<aside><h2>MTK GUI User Guide</h2>{toc}</aside>"
            f"<div class='guide'>"
            f"<header><h1>MTK GUI User Guide &mdash; "
            f"Manufacturing Test Kit</h1></header>"
            f"<main>{body}</main></div>"
            f"</body></html>")


def guide_temp_path() -> Path:
    """Stable temp file of the User Guide home page."""
    import tempfile
    out_dir = Path(tempfile.gettempdir()) / "mtk_gui_help"
    out_dir.mkdir(exist_ok=True)
    return out_dir / "User_Guide.html"


def open_guide() -> None:
    """Render the all-in-one User Guide and open it in the system web
    browser (the sidebar TOC scrolls to each chapter)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    page = guide_page_html()
    # the per-chapter links inside a chapter body (if any) resolve to
    # the sibling single-chapter pages, so also render those
    for k in HELP_TOPICS:
        topic_temp_path(k).write_text(topic_page_html(k), encoding="utf-8")
    path = guide_temp_path()
    path.write_text(page, encoding="utf-8")
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


#: standalone release log (Help > Version History) - NOT a guide
#: chapter; it is rendered by its own menu action.  Releases are
#: recorded here (develop commits are not, user directive 2026-10-14).
VERSION_HISTORY_FILE = "version_history.md"


def version_history_page_html() -> str:
    """Standalone Version History page (same page chrome as a chapter
    page, without the chapter navigation)."""
    path = HELP_ROOT / VERSION_HISTORY_FILE
    if path.is_file():
        body = markdown_to_html(path.read_text(encoding="utf-8"))
    else:
        body = "<p>Version History file is not available.</p>"
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>MTK GUI - Version History</title>"
            f"<style>{_PAGE_CSS}</style></head><body>"
            f"<header><h1>MTK GUI &mdash; Version History</h1></header>"
            f"<main>{body}</main></body></html>")


def open_version_history() -> bool:
    """Render the Version History and open it in the system web
    browser (Help > Version History)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    import tempfile
    out_dir = Path(tempfile.gettempdir()) / "mtk_gui_help"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / "Version_History.html"
    path.write_text(version_history_page_html(), encoding="utf-8")
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
