# -*- coding: utf-8 -*-
"""v2-16: reusable Command Snippet Helper.

A Qt-free catalog of ready-made Linux (DUT shell) and Windows CLI
(Host PC) command blocks plus one small dialog that inserts the
selected block **at the cursor** of any command editor.

Owner rule: one command per line, or a ``|``-joined one-liner; the
engine auto-completes the newline escaping, so the user never types
``\\n``.  ``<param:xxx>`` placeholders are hand-edited after insertion.
"""

from __future__ import annotations

import copy
from typing import Callable, NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

#: tab / page identifiers
PAGE_LINUX = "Linux"
PAGE_WINDOWS = "Windows CLI"
PAGE_CUSTOM = "Custom"

#: group identifiers used inside the catalog and the Custom page
GROUP_LINUX = "linux"
GROUP_WINDOWS = "windows"


class SNIPPET(NamedTuple):
    """One command block: ``(group, page, title, comment, body)``."""

    group: str
    page: str
    title: str
    comment: str
    body: str


#: built-in catalog - Linux tab (DUT shell) then Windows CLI tab
COMMAND_SNIPPETS: list[SNIPPET] = [
    SNIPPET(
        GROUP_LINUX, PAGE_LINUX,
        "Load RF / BT drivers + basic confirmation",
        "Verify the driver is loaded and the interface is up.",
        "# verify the driver is loaded and the interface is up\n"
        "lsmod | grep -E \"mlan|bt|hci\"\n"
        "ip link show"),
    SNIPPET(
        GROUP_LINUX, PAGE_LINUX,
        "Wi-Fi SSID / password config — wpa_supplicant",
        "Write the AP credentials, then connect.",
        "# write the AP credentials, then connect\n"
        "wpa_passphrase \"<param:ap_ssid>\" \"<param:ap_password>\" "
        "> /etc/wpa_supplicant.conf\n"
        "wpa_supplicant -B -i <param:iface> "
        "-c /etc/wpa_supplicant.conf"),
    SNIPPET(
        GROUP_LINUX, PAGE_LINUX,
        "Wi-Fi scan — iw",
        "Scan for the AP and show signal.",
        "# scan for the AP and show signal\n"
        "iw dev <param:iface> scan | grep -E \"SSID|signal\""),
    SNIPPET(
        GROUP_LINUX, PAGE_LINUX,
        "Wi-Fi — nmcli",
        "NetworkManager: list networks and connect.",
        "# NetworkManager: list networks and connect\n"
        "nmcli dev wifi list\n"
        "nmcli dev wifi connect \"<param:ap_ssid>\" "
        "password \"<param:ap_password>\""),
    SNIPPET(
        GROUP_LINUX, PAGE_LINUX,
        "Wi-Fi — connmanctl",
        "ConnMan: scan, then connect to the AP.",
        "# ConnMan: scan, then connect to the AP\n"
        "connmanctl scan wifi\n"
        "connmanctl connect \"<param:service>\""),
    SNIPPET(
        GROUP_LINUX, PAGE_LINUX,
        "iperf client (reference / manual Console)",
        "DUT is the client; server runs on the Host PC.",
        "# DUT is the client; server runs on the Host PC\n"
        "iperf3 -c <param:server_ip> -t <param:duration> -O 1"),
    SNIPPET(
        GROUP_LINUX, PAGE_LINUX,
        "legacy iperf client",
        "Legacy iperf variant of the DUT-side client.",
        "# legacy iperf variant\n"
        "iperf -c <param:server_ip> -t <param:duration> -i 1"),
    SNIPPET(
        GROUP_LINUX, PAGE_LINUX,
        "Bluetooth pair (BT_Pair)",
        "Bring the controller up, then pair / trust / connect to the Host.",
        "# bring the controller up, then pair / trust / connect to the Host\n"
        "power on\n"
        "agent on\n"
        "default-agent\n"
        "scan on\n"
        "pair <param:host_addr>\n"
        "trust <param:host_addr>\n"
        "connect <param:host_addr>\n"
        "info <param:host_addr>"),
    SNIPPET(
        GROUP_LINUX, PAGE_LINUX,
        "Bluetooth A2DP sink",
        "Route the BT audio to the Host sink.",
        "# route the BT audio to the Host sink\n"
        "pactl list sinks short\n"
        "pactl set-default-sink <param:sink_name>"),
    SNIPPET(
        GROUP_WINDOWS, PAGE_WINDOWS,
        "Find AP router (netsh)",
        "List nearby APs and the current interface.",
        "# list nearby APs and the current interface\n"
        "netsh wlan show networks mode=bssid\n"
        "netsh wlan show interfaces"),
    SNIPPET(
        GROUP_WINDOWS, PAGE_WINDOWS,
        "Find AP router (lswifi)",
        "lswifi overview (installed on the Host PC).",
        "# lswifi overview (installed on the Host PC)\n"
        "lswifi"),
    SNIPPET(
        GROUP_WINDOWS, PAGE_WINDOWS,
        "iperf3 server — start",
        "Start the server in a new console.",
        "# start the server in a new console\n"
        "start /b iperf3 -s"),
    SNIPPET(
        GROUP_WINDOWS, PAGE_WINDOWS,
        "iperf server — start (legacy)",
        "Start the legacy iperf server.",
        "# start the legacy iperf server\n"
        "start /b iperf -s"),
    SNIPPET(
        GROUP_WINDOWS, PAGE_WINDOWS,
        "iperf3 server — stop",
        "Stop the iperf3 server.",
        "# stop the server\n"
        "taskkill /F /IM iperf3.exe"),
    SNIPPET(
        GROUP_WINDOWS, PAGE_WINDOWS,
        "iperf server — stop (legacy)",
        "Stop the legacy iperf server.",
        "# stop the legacy iperf server\n"
        "taskkill /F /IM iperf.exe"),
    SNIPPET(
        GROUP_WINDOWS, PAGE_WINDOWS,
        "iperf directory prefix",
        "Run iperf from the configured directory.",
        "# run iperf from the configured directory\n"
        "<param:iperf_dir>\\iperf3 -s"),
]


def snippets_for_page(page: str) -> list[SNIPPET]:
    """Built-in snippets of one page (``Linux`` / ``Windows CLI``)."""
    return [s for s in COMMAND_SNIPPETS if s.page == page]


def insert_text_at_cursor(editor, text: str) -> None:
    """Insert *text* at the editor's cursor, keeping the existing text.

    Works for ``QPlainTextEdit`` / ``QTextEdit`` (via ``textCursor``)
    and ``QLineEdit`` (via ``insert``).  Never replaces the content.
    """
    if not text:
        return
    if hasattr(editor, "textCursor"):
        cursor = editor.textCursor()
        cursor.insertText(text)
        editor.setTextCursor(cursor)
    else:
        editor.insert(text)


class _SnippetTab(QWidget):
    """Search + list + comment + body preview for one snippet set."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snippets: list[SNIPPET] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search snippets...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show_detail)
        lay.addWidget(self.list, 1)
        self.comment = QLabel("")
        self.comment.setWordWrap(True)
        self.comment.setProperty("tone", "muted")
        lay.addWidget(self.comment)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(120)
        lay.addWidget(self.preview)

    def set_snippets(self, snippets: list[SNIPPET]) -> None:
        """Replace the list content and repaint the selection."""
        self._snippets = list(snippets)
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        self.list.clear()
        for snippet in self._snippets:
            haystack = " ".join((snippet.title, snippet.comment,
                                 snippet.body)).lower()
            if needle and needle not in haystack:
                continue
            item = QListWidgetItem(snippet.title)
            item.setData(Qt.UserRole, snippet)
            item.setToolTip(snippet.comment)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.comment.setText("No matching snippet.")
            self.preview.setPlainText("")

    def selected(self) -> SNIPPET | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _show_detail(self, _row: int) -> None:
        snippet = self.selected()
        if snippet is None:
            self.comment.setText("")
            self.preview.setPlainText("")
            return
        self.comment.setText(snippet.comment)
        self.preview.setPlainText(snippet.body)


class CommandSnippetDialog(QDialog):
    """Three-tab snippet picker (Linux / Windows CLI / Custom)."""

    def __init__(self, page: str = PAGE_LINUX, target=None,
                 parent: QWidget | None = None,
                 custom_loader: Callable[[], list] | None = None,
                 custom_saver: Callable[[list], None] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Command Snippets")
        self.setMinimumWidth(640)
        self._target = target
        self._custom_loader = custom_loader
        self._custom_saver = custom_saver
        self.inserted_text: str = ""
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tab_linux = _SnippetTab()
        self.tab_linux.set_snippets(snippets_for_page(PAGE_LINUX))
        self.tab_windows = _SnippetTab()
        self.tab_windows.set_snippets(snippets_for_page(PAGE_WINDOWS))
        self.tab_custom = _SnippetTab()
        self.tabs.addTab(self.tab_linux, PAGE_LINUX)
        self.tabs.addTab(self.tab_windows, PAGE_WINDOWS)
        self.tabs.addTab(self.tab_custom, PAGE_CUSTOM)
        lay.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_insert = QPushButton("Insert")
        self.btn_insert.setDefault(True)
        self.btn_insert.clicked.connect(self._insert_selected)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_insert)
        row.addWidget(self.btn_close)
        lay.addLayout(row)
        self._select_page(page)
        self.reload_custom()

    # ------------------------------------------------------------ custom
    def reload_custom(self) -> None:
        """Load the Custom list from the bound store (default empty)."""
        if self._custom_loader is None:
            self.tab_custom.set_snippets([])
            return
        try:
            raw = self._custom_loader() or []
        except Exception:      # noqa: BLE001 - a broken store never kills the dialog
            raw = []
        snippets: list[SNIPPET] = []
        for entry in raw:
            snippet = custom_to_snippet(entry)
            if snippet is not None:
                snippets.append(snippet)
        self.tab_custom.set_snippets(snippets)

    def _current_tab(self) -> _SnippetTab:
        return self.tabs.currentWidget()

    def _select_page(self, page: str) -> None:
        index = self.tabs.indexOf(
            self.tab_windows if page == PAGE_WINDOWS else self.tab_linux)
        self.tabs.setCurrentIndex(max(0, index))

    def selected_snippet(self) -> SNIPPET | None:
        return self._current_tab().selected()

    # ------------------------------------------------------------ insert
    def _insert_selected(self) -> None:
        snippet = self.selected_snippet()
        if snippet is None:
            return
        self.inserted_text = snippet.body
        if self._target is not None:
            insert_text_at_cursor(self._target, snippet.body)
        self.accept()

    def close(self) -> bool:  # noqa: A003 - Qt API
        """Dismiss without inserting (the target text is untouched)."""
        self.reject()
        return True


def custom_to_snippet(entry) -> SNIPPET | None:
    """Convert one project-YAML entry to a snippet (lenient)."""
    if not isinstance(entry, dict):
        return None
    body = str(entry.get("body") or "")
    if not body.strip():
        return None
    page = PAGE_WINDOWS if str(entry.get("page") or "") == PAGE_WINDOWS \
        else PAGE_LINUX
    return SNIPPET(
        GROUP_WINDOWS if page == PAGE_WINDOWS else GROUP_LINUX,
        page,
        str(entry.get("title") or "Custom command"),
        str(entry.get("comment") or ""),
        body)


# ---------------------------------------------- default (model-bound) store
_LOADER: Callable[[], list] | None = None
_SAVER: Callable[[list], None] | None = None


def bind_model(model) -> None:
    """Route the Custom page to a ``YamlBuildModel`` (project YAML).

    Missing / legacy keys load as an empty list and never raise.
    """
    if model is None:
        return
    global _LOADER, _SAVER
    _LOADER = model.get_command_snippets
    _SAVER = model.set_command_snippets


def custom_snippets() -> list[dict]:
    """The current Custom list (copy), empty when unbound."""
    if _LOADER is None:
        return []
    try:
        return copy.deepcopy(list(_LOADER() or []))
    except Exception:          # noqa: BLE001 - never fatal
        return []


def save_custom_snippets(items: list[dict]) -> None:
    """Persist the Custom list through the bound store (no-op when
    unbound)."""
    if _SAVER is not None:
        _SAVER(copy.deepcopy(list(items or [])))


# ------------------------------------------------------------- attachment
def _resolve_page(page) -> str:
    try:
        return page() if callable(page) else str(page)
    except Exception:          # noqa: BLE001 - fall back to the DUT shell
        return PAGE_LINUX


def make_snippets_button(editor, page=PAGE_LINUX,
                         parent: QWidget | None = None,
                         custom_loader=None, custom_saver=None) -> QPushButton:
    """The small ``Snippets…`` button for one command editor."""
    button = QPushButton("Snippets…")
    button.setObjectName("snippet_button")
    button.setToolTip(
        "Insert a ready-made command block at the cursor "
        "(one command per line)")
    button.setMaximumWidth(110)

    def _open() -> None:
        dialog = CommandSnippetDialog(
            page=_resolve_page(page), target=editor,
            parent=parent if parent is not None else editor.window(),
            custom_loader=custom_loader or _LOADER,
            custom_saver=custom_saver or _SAVER)
        dialog.exec()

    button.clicked.connect(_open)
    return button


def with_snippets(editor, page=PAGE_LINUX,
                  parent: QWidget | None = None,
                  custom_loader=None, custom_saver=None) -> QWidget:
    """Wrap *editor* in a row with the ``Snippets…`` button."""
    box = QWidget(parent)
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(editor, 1)
    lay.addWidget(make_snippets_button(editor, page, box,
                                       custom_loader, custom_saver))
    return box
