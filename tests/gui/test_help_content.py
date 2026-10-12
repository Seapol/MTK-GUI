# -*- coding: utf-8 -*-
"""Module C help tests: the 12 User Guide chapters exist, the
markdown-lite renderer produces HTML with screenshots, the FAQ covers
the known-issues list, every main-window tab is documented somewhere
(freshness guard), the Help menu mounts a single User Guide entry that
opens the all-in-one guide web page, and the About body carries
version + branch."""
from __future__ import annotations

from mtkgui.gui.help_content import (
    CHAPTERS,
    HELP_ROOT,
    HELP_TOPICS,
    about_html,
    guide_page_html,
    guide_temp_path,
    load_topic_html,
    markdown_to_html,
    topic_page_html,
    topic_temp_path,
)

#: the 12 chapter files (one per Help menu entry)
EXPECTED_FILES = tuple(f for _k, _l, f in CHAPTERS)


def test_all_chapters_exist():
    for name in EXPECTED_FILES:
        assert (HELP_ROOT / name).is_file(), name
    assert len(HELP_TOPICS) == 12
    assert len(CHAPTERS) == 12


def test_markdown_lite_renders_structures():
    html = markdown_to_html(
        "# Title\n\n- item **bold** `code`\n\n```\ncode block\n```\n")
    assert "<h2>Title</h2>" in html
    assert "<li>" in html and "<b>bold</b>" in html
    assert "<code>code</code>" in html
    assert "<pre>" in html and "code block" in html


def test_markdown_lite_renders_images_with_absolute_uri():
    html = markdown_to_html("![Login dialog](images/01_login.png)\n")
    assert html.startswith('<img src="file://')
    assert 'alt="Login dialog"' in html
    assert "01_login.png" in html


def test_load_topic_html_and_unknown_key():
    html = load_topic_html("faq")
    assert "<h" in html
    # unknown keys degrade to a clear placeholder (never a dead link)
    assert "Unknown help topic" in load_topic_html("ghost")


def test_faq_covers_known_issues():
    faq = (HELP_ROOT / "12_faq.md").read_text(encoding="utf-8")
    for issue in ("no nets found", "Address", "CSV log",
                  "keyring", "Run blocked"):
        assert issue in faq, issue


def test_topic_page_html_navigation():
    page = topic_page_html("user_guide")
    assert "MTK GUI User Guide" in page
    assert 'href="mtkgui-help://02_getting_started.html"' in page  # next
    assert "images/" not in page or "file://" in page  # absolute img URIs
    last = topic_page_html("faq")
    assert 'href="mtkgui-help://11_case_editor_config.html"' in last  # prev
    # unknown key -> clear placeholder, never a crash
    assert "Unknown help topic" in topic_page_html("ghost")


# ------------------------------------------------------- freshness guard
def test_every_main_window_tab_is_documented():
    """Docs-freshness rule: whenever a tab is added to the main window,
    at least one User Guide chapter must mention it by name."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mtkgui.main_window import MainWindow
    window = MainWindow()
    all_docs = "\n".join(
        (HELP_ROOT / f).read_text(encoding="utf-8") for f in EXPECTED_FILES)
    for i in range(window.tabs.count()):
        title = window.tabs.tabText(i)
        assert title in all_docs, f"tab {title!r} missing from User Guide"
    window.deleteLater()


# ------------------------------------------------------------- in-app UI
def test_help_menu_mounts_guide_and_opens_browser(qapp, monkeypatch):
    opened = []

    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(
        QDesktopServices, "openUrl",
        staticmethod(lambda url: opened.append(url) or True))

    from mtkgui.main_window import MainWindow
    window = MainWindow()
    texts = [a.text() for a in window.help_menu.actions()
             if not a.isSeparator()]
    # ONE User Guide entry (not chapters flattened into the menu)
    assert texts == ["User Guide", "About"]
    # _open_help renders the all-in-one guide and opens the browser
    window._open_help()
    assert len(opened) == 1
    assert opened[0].toLocalFile() == str(guide_temp_path())
    page = guide_temp_path()
    assert page.is_file()
    html = page.read_text(encoding="utf-8")
    # every chapter is on the page with its sidebar anchor
    for i, (_k, label, _f) in enumerate(CHAPTERS):
        assert f'href="#chapter-{i + 1}">{label}</a>' in html
        assert f'id="chapter-{i + 1}"' in html
    assert '<img src="file://' in html          # screenshots embedded
    window.deleteLater()


def test_about_html_carries_version_and_branch():
    html = about_html()
    assert "Version:" in html and "Branch:" in html
