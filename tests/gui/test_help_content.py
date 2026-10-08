# -*- coding: utf-8 -*-
"""Module C help tests: the 8 sections exist, the markdown-lite
renderer produces HTML, the FAQ covers the known-issues list, the page
guide covers every page, the menu mounts the topics and the About
body carries version + branch."""
from __future__ import annotations

import pytest

from mtkgui.gui.help_content import (
    HELP_ROOT,
    HELP_TOPICS,
    about_html,
    load_topic_html,
    markdown_to_html,
)

#: the 8 directive sections (C1)
EXPECTED_FILES = (
    "01_overview.md",
    "02_getting_started.md",
    "03_page_guide.md",
    "04_instruments.md",
    "05_test_items.md",
    "06_reports_logs.md",
    "07_faq.md",
    "08_security_roles.md",
)

#: every app page must appear in the page guide (C3 coverage rule)
PAGES = ("Test Work Flow", "Equipment", "Yaml Build",
         "Channel Allocation", "Design Input", "Parse nets",
         "Instruments", "Validate", "Publish", "Console")


def test_all_sections_exist():
    for name in EXPECTED_FILES:
        assert (HELP_ROOT / name).is_file(), name
    assert len(HELP_TOPICS) >= 8


def test_markdown_lite_renders_structures():
    html = markdown_to_html(
        "# Title\n\n- item **bold** `code`\n\n```\ncode block\n```\n")
    assert "<h2>Title</h2>" in html
    assert "<li>" in html and "<b>bold</b>" in html
    assert "<code>code</code>" in html
    assert "<pre>" in html and "code block" in html


def test_load_topic_html_and_unknown_key():
    html = load_topic_html("faq")
    assert "FAQ" in html and "<h" in html
    # unknown keys degrade to a clear placeholder (never a dead link)
    assert "Unknown help topic" in load_topic_html("ghost")


def test_faq_covers_known_issues():
    faq = (HELP_ROOT / "07_faq.md").read_text(encoding="utf-8")
    for issue in ("no nets found", "Address", "CSV log",
                  "keyring", "Run blocked"):
        assert issue in faq, issue


def test_page_guide_covers_all_pages():
    guide = (HELP_ROOT / "03_page_guide.md").read_text(
        encoding="utf-8")
    for page in PAGES:
        assert page in guide, page


def test_about_html_carries_version_and_branch():
    html = about_html()
    assert "Version:" in html and "Branch:" in html


# ------------------------------------------------------------- in-app UI
def test_help_menu_mounts_topics_and_dialogs_render(qapp):
    from PySide6.QtWidgets import QDialog, QApplication
    from mtkgui.main_window import MainWindow
    window = MainWindow()
    texts = [a.text() for a in window.help_menu.actions()]
    assert texts[0] == "User Guide"
    assert "FAQ / Troubleshooting" in texts
    assert texts[-1] == "About"
    # _open_help creates a non-blocking dialog we can close headlessly
    from PySide6.QtCore import QTimer

    def close_it():
        top = QApplication.activeModalWidget()
        if top is not None:
            top.close()

    QTimer.singleShot(120, close_it)
    window._open_help("overview")           # must not raise
    window.deleteLater()
