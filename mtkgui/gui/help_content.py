# -*- coding: utf-8 -*-
"""Help content provider (Module C): the built-in User Guide / FAQ /
About render the markdown-lite files in docs/help/ in-app.

markdown-lite -> HTML (stdlib re only): headings, bullet lists, code
spans / fenced code, bold, tables are rendered as preformatted text.
"""
from __future__ import annotations

import re
from pathlib import Path

HELP_ROOT = Path(__file__).resolve().parents[2] / "docs" / "help"

#: menu key -> section file (Module C content list, directive C1)
HELP_TOPICS = {
    "user_guide": "01_overview.md",
    "getting_started": "02_getting_started.md",
    "page_guide": "03_page_guide.md",
    "instruments": "04_instruments.md",
    "test_items": "05_test_items.md",
    "reports_logs": "06_reports_logs.md",
    "faq": "07_faq.md",
    "security_roles": "08_security_roles.md",
    "overview": "01_overview.md",
}


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
