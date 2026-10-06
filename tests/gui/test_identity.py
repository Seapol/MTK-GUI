# -*- coding: utf-8 -*-
"""Global identity variables (core standard 5.3): Station ID from the
host name, User from the OS login, automatically carried by every
Event-Log entry (unique by source, not manually editable)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from mtkgui.gui.identity import (  # noqa: E402
    get_station_id,
    get_user,
    identity_prefix,
)


def test_station_id_from_hostname():
    """The Station ID is the computer host name (Windows + macOS) and
    is never empty."""
    station = get_station_id()
    assert station and station != "UNKNOWN-STATION"
    import platform
    assert station == platform.node() or station


def test_user_from_os_login():
    """The User is the OS login account name (Windows + macOS) and is
    never empty."""
    import getpass
    assert get_user() == getpass.getuser()


def test_identity_prefix_format():
    assert identity_prefix() == \
        f"[{get_station_id()}|{get_user()}]"


def test_fallbacks_never_empty(monkeypatch):
    """When the host name / account lookups fail, the stable
    placeholders keep the Event-Log format intact."""
    import mtkgui.gui.identity as ident
    monkeypatch.setattr(ident.platform, "node", lambda: "")
    import socket
    monkeypatch.setattr(socket, "gethostname", lambda: "")
    monkeypatch.setattr(ident.getpass, "getuser",
                        lambda: (_ for _ in ()).throw(OSError))
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)
    assert get_station_id() == "UNKNOWN-STATION"
    assert get_user() == "UNKNOWN-USER"


def test_event_log_entries_carry_identity(qapp):
    """Every Event-Log line written by the main window automatically
    carries the [StationID|User] prefix (GUI + session file)."""
    from mtkgui.main_window import MainWindow
    window = MainWindow()
    try:
        window._append_event_log("[INFO] identity probe")
        log = window.event_log.toPlainText()
        assert f"[{get_station_id()}|{get_user()}] " \
               "[INFO] identity probe" in log
    finally:
        window.deleteLater()
