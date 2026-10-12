# -*- coding: utf-8 -*-
"""Tera Term-style console rendering (P3-B7 console readability).

Covers streamed RX stitching (no forced newlines on chunk boundaries),
lone-CR in-place progress refresh, CRLF handling, ANSI color passthrough,
no RX>>/TX>> text prefix (SYS keeps one), Timestamp off by default, and
TX rendered in cyan.
"""

from mtkgui.theme import THEMES
from mtkgui.widgets.console_widget import ConsoleWidget


def _block_texts(console):
    """Non-empty block texts in display order."""
    doc = console.view.document()
    out = []
    for b in range(doc.blockCount()):
        t = doc.findBlockByNumber(b).text()
        if t:
            out.append(t)
    return out


def _colors(console):
    doc = console.view.document()
    colors = set()
    for b in range(doc.blockCount()):
        block = doc.findBlockByNumber(b)
        it = block.begin()
        while it != block.end():
            colors.add(it.fragment().charFormat().foreground().color().name())
            it += 1
    return colors


def test_timestamp_default_off(qapp):
    c = ConsoleWidget("k", "T", "f")
    try:
        assert not c.check_timestamp.isChecked()
        c.append_rx("RX", b"hello\n")
        assert not _block_texts(c)[0].startswith("[")
    finally:
        c.deleteLater()


def test_rx_has_no_prefix(qapp):
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_rx("RX", b"imx93frdm login:\n")
        assert "RX>>" not in c.view.toPlainText()
        assert _block_texts(c)[0] == "imx93frdm login:"
    finally:
        c.deleteLater()


def test_tx_no_prefix_and_cyan(qapp):
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_message("TX", "ls -la", color=THEMES["dark"]["tx"])
        text = c.view.toPlainText()
        assert "TX>>" not in text
        assert "ls -la" in text
        assert THEMES["dark"]["tx"] in _colors(c)
    finally:
        c.deleteLater()


def test_sys_keeps_tag(qapp):
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_message("SYS", "connected", color=THEMES["dark"]["sys"])
        assert "SYS>>" in c.view.toPlainText()
    finally:
        c.deleteLater()


def test_fragmented_chunks_stitch_into_one_line(qapp):
    c = ConsoleWidget("k", "T", "f")
    try:
        # one shell line arriving in three reads must not be split
        c.append_rx("RX", b"imx93fr")
        c.append_rx("RX", b"dm login: ")
        c.append_rx("RX", b"root\n")
        assert _block_texts(c) == ["imx93frdm login: root"]
    finally:
        c.deleteLater()


def test_lone_cr_overwrites_progress_line(qapp):
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_rx("RX", b"Progress: [###-------] 30%\r")
        c.append_rx("RX", b"Progress: [######----] 60%\r")
        c.append_rx("RX", b"Progress: [##########] 100%\n")
        c.append_rx("RX", b"[PASS] board ok\n")
        texts = _block_texts(c)
        assert texts == ["Progress: [##########] 100%", "[PASS] board ok"]
    finally:
        c.deleteLater()


def test_crlf_is_one_line_end_no_blank(qapp):
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_rx("RX", b"line one\r\nline two\r\n")
        assert _block_texts(c) == ["line one", "line two"]
    finally:
        c.deleteLater()


def test_systemd_crlf_status_lines_keep_text(qapp):
    # systemd ends every status line with '\r\r\n'; the lone CR must
    # NOT blank the line that just ended (boot log was flooded with
    # empty lines where the [ OK ] lines should be)
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_rx("RX",
                    b"[\x1b[0;32m  OK  \x1b[0m] Mounted /var/volatile."
                    b"\r\r\n")
        c.append_rx("RX",
                    b"         Starting Load/Save OS Random Seed...\r\r\n")
        c.append_rx("RX", b"[    5.603174] audit: prog-id=9 op=LOAD\r\n")
        assert _block_texts(c) == [
            "[  OK  ] Mounted /var/volatile.",
            "         Starting Load/Save OS Random Seed...",
            "[    5.603174] audit: prog-id=9 op=LOAD",
        ]
        # two text blocks + the document's final empty block only:
        # no blank lines in between
        assert c.view.document().blockCount() == 4
    finally:
        c.deleteLater()


def test_lone_cr_across_chunks_line_end_keeps_text(qapp):
    # a CR at the end of one chunk with the '\r\n' split off into the
    # next chunk must not blank the line either (USB CDC chunk split)
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_rx("RX", b"Stopping Network Time Synchronization...\r")
        c.append_rx("RX", b"\r\n")
        assert _block_texts(c) == [
            "Stopping Network Time Synchronization..."]
    finally:
        c.deleteLater()


def test_chunked_cr_progress_still_overwrites(qapp):
    # the deferred overwrite must still clear the line when fresh text
    # actually arrives on it (chunk-boundary progress refresh)
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_rx("RX", b"Progress: 30%\r")
        c.append_rx("RX", b"Progress: 60%\r")
        c.append_rx("RX", b"Progress: 100%\n")
        assert _block_texts(c) == ["Progress: 100%"]
    finally:
        c.deleteLater()


def test_ansi_red_preserved(qapp):
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_rx("RX", b"\x1b[31mFATAL boom\x1b[0m\n")
        texts = _block_texts(c)
        assert texts == ["FATAL boom"]
        assert "#cd0000" in _colors(c)
    finally:
        c.deleteLater()


def test_tx_after_rx_newline_has_no_blank_line(qapp):
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_rx("RX", b"root@imx93frdm:~# \n")
        c.append_message("TX", "uname -a", color=THEMES["dark"]["tx"])
        assert _block_texts(c) == ["root@imx93frdm:~# ", "uname -a"]
    finally:
        c.deleteLater()


def test_clear_resets_stream_state(qapp):
    c = ConsoleWidget("k", "T", "f")
    try:
        c.append_rx("RX", b"partial-no-newline")
        c.clear_all()
        c.append_rx("RX", b"fresh line\n")
        assert _block_texts(c) == ["fresh line"]
    finally:
        c.deleteLater()
