# -*- coding: utf-8 -*-
"""Module C help tests: the 16 User Guide chapters exist, the
markdown-lite renderer produces HTML with screenshots, the FAQ covers
the known-issues list, every main-window tab is documented somewhere
(freshness guard), the Help menu mounts a single User Guide entry that
opens the all-in-one guide web page, and the About body carries
version + branch."""
from __future__ import annotations

from pathlib import Path

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

#: the 16 chapter files (one per Help menu entry)
EXPECTED_FILES = tuple(f for _k, _l, f in CHAPTERS)


def test_all_chapters_exist():
    for name in EXPECTED_FILES:
        assert (HELP_ROOT / name).is_file(), name
    # 2026-10-14: Channel Allocation merged into the Yaml Build
    # chapter, Cluster removed, Instruments + Station Equipment added
    # 2026-10-27: chapters 15 (Example ICT) and 16 (Example FCT) added
    assert len(HELP_TOPICS) == 16
    assert len(CHAPTERS) == 16


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
    # the body heading carries the chapter number (matches the sidebar)
    assert html.startswith("<h2>14. ")
    assert "<h" in html
    # unknown keys degrade to a clear placeholder (never a dead link)
    assert "Unknown help topic" in load_topic_html("ghost")


def test_faq_covers_known_issues():
    faq = (HELP_ROOT / "14_faq.md").read_text(encoding="utf-8")
    for issue in ("no nets found", "Address", "CSV log",
                  "keyring", "Run blocked"):
        assert issue in faq, issue


def test_topic_page_html_navigation():
    page = topic_page_html("user_guide")
    assert "MTK GUI User Guide" in page
    assert 'href="mtkgui-help://02_getting_started.html"' in page  # next
    assert "images/" not in page or "file://" in page  # absolute img URIs
    last = topic_page_html("faq")
    assert 'href="mtkgui-help://13_case_editor_config.html"' in last  # prev
    # unknown key -> clear placeholder, never a crash
    assert "Unknown help topic" in topic_page_html("ghost")


# ------------------------------------------------------- version history
def test_version_history_page_renders_release_log():
    """Help > Version History renders the standalone release log with
    the versioning rule and the v1.0.0.0 baseline entry (releases
    only - develop commits are never recorded)."""
    from mtkgui import __version__
    from mtkgui.gui.help_content import version_history_page_html
    page = version_history_page_html()
    assert "MTK GUI &mdash; Version History" in page
    assert "Versioning rule" in page or "Versioning rule" in page.lower()
    assert f"{__version__} - 2026-10-14" in page
    assert "develop</code> commits are NOT recorded" in page


def test_version_history_menu_opens_browser(qapp, monkeypatch):
    """Help > Version History writes the temp page and opens it."""
    opened = []

    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(
        QDesktopServices, "openUrl",
        staticmethod(lambda url: opened.append(url) or True))

    from mtkgui.main_window import MainWindow
    window = MainWindow()
    window._open_version_history()
    assert len(opened) == 1
    page = opened[0].toLocalFile()
    assert page.endswith("Version_History.html")
    assert "v1.0.0.0" in open(page, encoding="utf-8").read()
    window.deleteLater()


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
    # ONE User Guide entry + the standalone Version History release log
    assert texts == ["User Guide", "Version History", "About"]
    # _open_help renders the all-in-one guide and opens the browser
    window._open_help()
    assert len(opened) == 1
    assert Path(opened[0].toLocalFile()) == guide_temp_path()
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
