# -*- coding: utf-8 -*-
"""M86-C3: plan A - reuse the station browser's own session (read-only)."""
from __future__ import annotations

import sqlite3

from mtkgui.engine import browser_session

SECRET_FEDAUTH = "FEDAUTH-SECRET-VALUE"
SECRET_RTFA = "RTFA-SECRET-VALUE"


def _make_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, "
        "path TEXT, is_secure INTEGER, encrypted_value BLOB)")
    conn.executemany(
        "INSERT INTO cookies VALUES (?,?,?,?,?,?)",
        [(".sharepoint.com", "FedAuth", SECRET_FEDAUTH, "/", 1, b""),
         ("corp.sharepoint.com", "rtFa", SECRET_RTFA, "/", 1, b""),
         (".sharepoint.com", "AClient", "not-a-session", "/", 1, b""),
         ("other.example", "FedAuth", "WRONG-HOST", "/", 1, b"")])
    conn.commit()
    conn.close()
    return path


def test_only_fedauth_and_rtfa_for_the_configured_host_are_kept(
        monkeypatch, tmp_path):
    db = _make_db(tmp_path / "Edge" / "Default" / "Network" / "Cookies")
    monkeypatch.setattr(browser_session, "candidate_cookie_dbs", lambda: [db])
    cookies = browser_session.read_session_cookies("corp.sharepoint.com")
    assert cookies, "the synthetic session must be found"
    assert sorted(cookie["name"] for cookie in cookies) == ["FedAuth", "rtFa"]
    values = {cookie["name"]: cookie["value"] for cookie in cookies}
    assert values["FedAuth"] == SECRET_FEDAUTH
    assert values["rtFa"] == SECRET_RTFA
    # a different host only sees its own cookie
    other = browser_session.read_session_cookies("other.example")
    assert [cookie["value"] for cookie in other] == ["WRONG-HOST"]
    assert browser_session.read_session_cookies("") is None


def test_missing_browser_returns_none_instead_of_raising(monkeypatch):
    monkeypatch.setattr(browser_session, "candidate_cookie_dbs", lambda: [])
    assert browser_session.read_session_cookies("corp.sharepoint.com") is None


def test_locked_database_is_copied_to_temp_and_removed(monkeypatch, tmp_path):
    db = _make_db(tmp_path / "Chrome" / "Default" / "Network" / "Cookies")
    copies = []
    real_copy = browser_session._copy_to_temp
    real_connect = browser_session._connect

    def spy_copy(source):
        target = real_copy(source)
        if target is not None:
            copies.append(target.parent)
        return target

    def locked_connect(path, immutable):
        if str(path) == str(db):
            raise sqlite3.OperationalError("database is locked")
        return real_connect(path, immutable)

    monkeypatch.setattr(browser_session, "_copy_to_temp", spy_copy)
    monkeypatch.setattr(browser_session, "_connect", locked_connect)
    rows = browser_session._rows_from_db(db)
    assert rows, "the copy must still yield the cookie rows"
    assert copies, "a locked database must be copied"
    assert not copies[0].exists(), "the copy must not outlive the call"


def test_cookie_values_are_never_written_to_the_log(monkeypatch, tmp_path,
                                                    capsys):
    db = _make_db(tmp_path / "Cookies")
    monkeypatch.setattr(browser_session, "candidate_cookie_dbs", lambda: [db])
    cookies = browser_session.read_session_cookies("corp.sharepoint.com")
    captured = capsys.readouterr()
    assert SECRET_FEDAUTH in {cookie["value"] for cookie in cookies}
    assert SECRET_FEDAUTH not in captured.out
    assert SECRET_FEDAUTH not in captured.err
    assert "FEDAUTH" not in captured.out.upper()
