# -*- coding: utf-8 -*-
"""v2-16: Command Snippet Helper tests (catalog + cursor insertion)."""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QTextEdit, QWidget

from mtkgui.gui.yamlbuild.command_snippet_helper import (
    COMMAND_SNIPPETS,
    PAGE_LINUX,
    PAGE_WINDOWS,
    CommandSnippetDialog,
    insert_text_at_cursor,
    snippets_for_page,
    with_snippets,
)


def _find(dialog_tab, title: str) -> int:
    for row in range(dialog_tab.list.count()):
        if dialog_tab.list.item(row).text() == title:
            return row
    raise AssertionError(f"snippet {title!r} not in the list")


# ------------------------------------------------------------- catalog
def test_catalog_has_the_linux_and_windows_blocks():
    linux = [s.title for s in snippets_for_page(PAGE_LINUX)]
    windows = [s.title for s in snippets_for_page(PAGE_WINDOWS)]
    for title in ("Load RF / BT drivers + basic confirmation",
                  "Wi-Fi SSID / password config — wpa_supplicant",
                  "Wi-Fi scan — iw",
                  "Wi-Fi — nmcli",
                  "Wi-Fi — connmanctl",
                  "iperf client (reference / manual Console)",
                  "legacy iperf client",
                  "Bluetooth pair (BT_Pair)",
                  "Bluetooth A2DP sink"):
        assert title in linux
    for title in ("Find AP router (netsh)",
                  "Find AP router (lswifi)",
                  "iperf3 server — start",
                  "iperf server — start (legacy)",
                  "iperf3 server — stop",
                  "iperf server — stop (legacy)",
                  "iperf directory prefix"):
        assert title in windows
    assert all(s.comment.strip() for s in COMMAND_SNIPPETS)
    assert all(s.page in (PAGE_LINUX, PAGE_WINDOWS)
               for s in COMMAND_SNIPPETS)


def test_every_body_uses_one_command_per_line():
    for snippet in COMMAND_SNIPPETS:
        assert "\n\n" not in snippet.body, snippet.title
        assert "\\n" not in snippet.body, snippet.title
        assert not snippet.body.endswith("\\"), snippet.title
        for line in snippet.body.splitlines():
            assert line.strip(), snippet.title
            assert not line.rstrip().endswith("\\"), snippet.title


def test_param_placeholders_are_preserved_verbatim():
    blob = "\n".join(s.body for s in COMMAND_SNIPPETS)
    for placeholder in ("<param:ap_ssid>", "<param:ap_password>",
                        "<param:iface>", "<param:server_ip>",
                        "<param:duration>", "<param:host_addr>",
                        "<param:sink_name>", "<param:iperf_dir>"):
        assert placeholder in blob
    assert "iperf3 -s" in blob
    assert "netsh wlan show networks" in blob


# -------------------------------------------------------------- insertion
def test_insert_text_at_cursor_keeps_existing_text():
    editor = QTextEdit()
    editor.setPlainText("hello")
    cursor = editor.textCursor()
    cursor.setPosition(2)
    editor.setTextCursor(cursor)
    insert_text_at_cursor(editor, "XYZ")
    assert editor.toPlainText() == "heXYZllo"


def test_insert_into_line_edit_at_cursor_index():
    editor = QLineEdit("abcd")
    editor.setCursorPosition(2)
    insert_text_at_cursor(editor, "-mid-")
    assert editor.text() == "ab-mid-cd"


def test_dialog_inserts_selected_snippet_at_the_cursor():
    target = QTextEdit()
    target.setPlainText("before|after")
    cursor = target.textCursor()
    cursor.setPosition(len("before"))
    target.setTextCursor(cursor)
    dialog = CommandSnippetDialog(page=PAGE_LINUX, target=target)
    snippet = next(s for s in COMMAND_SNIPPETS
                   if s.title == "Bluetooth pair (BT_Pair)")
    dialog.tab_linux.list.setCurrentRow(
        _find(dialog.tab_linux, snippet.title))
    dialog._insert_selected()
    text = target.toPlainText()
    assert text.startswith("before# bring the controller up")
    assert text.endswith("after")
    assert snippet.body in text
    assert dialog.inserted_text == snippet.body


def test_dialog_close_does_not_touch_the_target():
    target = QTextEdit()
    target.setPlainText("untouched")
    dialog = CommandSnippetDialog(page=PAGE_WINDOWS, target=target)
    assert dialog.tabs.count() == 3
    dialog.close()
    assert target.toPlainText() == "untouched"


def test_dialog_opens_the_windows_tab_for_host_commands():
    dialog = CommandSnippetDialog(page=PAGE_WINDOWS)
    assert dialog.tabs.currentWidget() is dialog.tab_windows


def test_with_snippets_wraps_the_editor_and_a_button():
    from PySide6.QtWidgets import QPushButton

    editor = QTextEdit()
    box = with_snippets(editor, PAGE_LINUX)
    assert isinstance(box, QWidget)
    buttons = box.findChildren(QPushButton)
    assert [b.text() for b in buttons] == ["Snippets…"]
    assert editor.parent() is box
