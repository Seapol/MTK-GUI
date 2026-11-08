# -*- coding: utf-8 -*-
"""Plan A authentication: reuse the station's own browser session (M86).

The NXP owner signs in once in Edge / Chrome; this module reads the resulting
``FedAuth`` / ``rtFa`` cookies for the configured host straight from the
browser's cookie database, hands them to
:func:`mtkgui.engine.sharepoint_site.session_cookies` for the shaping, and the
caller drops them after the uploader is configured.

Rules, deliberately: never touch the browser's file lock (SQLite
``immutable=1`` first, a temp copy second, deleted in ``finally``); never log,
persist or echo a cookie value; every failure - other platform, missing
browser, locked DB, undecryptable value - answers ``None`` instead of raising.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from .sharepoint_site import SESSION_COOKIE_NAMES, session_cookies

#: browser profiles that carry a usable session (Default + numbered ones)
PROFILES = ("Default",) + tuple(f"Profile {index}" for index in range(1, 9))

_COLUMNS = ("host_key", "name", "value", "path", "is_secure",
            "encrypted_value")


# ---------------------------------------------------------------- discovery
def candidate_cookie_dbs() -> list[Path]:
    """Cookie databases of the station's Edge / Chrome installs (Windows)."""
    if sys.platform != "win32":
        return []
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    roots = (Path(local) / "Microsoft" / "Edge" / "User Data",
             Path(local) / "Google" / "Chrome" / "User Data")
    found: list[Path] = []
    for root in roots:
        for profile in PROFILES:
            path = root / profile / "Network" / "Cookies"
            if path.is_file():
                found.append(path)
    return found


# -------------------------------------------------------------- sqlite read
def _connect(path: Path, immutable: bool) -> sqlite3.Connection:
    uri = f"file:{Path(path).as_posix()}?mode=ro"
    if immutable:
        uri += "&immutable=1"
    return sqlite3.connect(uri, uri=True, timeout=1.0)


def _select_cookies(conn: sqlite3.Connection) -> list[dict]:
    """Raw cookie rows of one open database (tolerant of older schemas)."""
    try:
        cursor = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM cookies")
    except sqlite3.Error:
        return []
    rows = []
    for row in cursor.fetchall():
        values = list(row) + [None] * len(_COLUMNS)
        host, name, value, path, secure, encrypted = values[:len(_COLUMNS)]
        text = "" if value is None else str(value)
        if not text and encrypted is not None:
            text = _decrypt_value(encrypted)
            if text is None:            # encrypted and unusable - skip it
                continue
        rows.append({"name": str(name or ""), "value": text,
                     "domain": str(host or ""), "path": str(path or "/"),
                     "secure": bool(secure)})
    return rows


def _copy_to_temp(db: Path) -> Path | None:
    """A private copy of a locked database (caller deletes its folder)."""
    try:
        folder = Path(tempfile.mkdtemp(prefix="mtk_cookies_"))
        target = folder / "Cookies"
        shutil.copy2(db, target)
        return target
    except OSError:
        return None


def _rows_from_db(db: Path) -> list[dict]:
    """Rows of one cookie DB: direct read first, temp copy when locked."""
    for immutable in (True, False):
        try:
            conn = _connect(db, immutable)
        except sqlite3.Error:
            continue
        try:
            return _select_cookies(conn)
        finally:
            conn.close()
    copy = _copy_to_temp(db)
    if copy is None:
        return []
    try:
        conn = _connect(copy, True)
        try:
            return _select_cookies(conn)
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)


# ------------------------------------------------------------ chromed cookies
def _cookie_key() -> bytes | None:
    """Chrome/Edge master key from ``Local State`` (DPAPI-unwrapped)."""
    if sys.platform != "win32":
        return None
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    states = (Path(local) / "Microsoft" / "Edge" / "User Data" / "Local State",
              Path(local) / "Google" / "Chrome" / "User Data" / "Local State")
    for state in states:
        try:
            blob = base64.b64decode(
                json.loads(state.read_text(encoding="utf-8"))
                ["os_crypt"]["encrypted_key"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not blob.startswith(b"DPAPI"):
            continue
        key = _dpapi_unwrap(blob[5:])
        if key:
            return key
    return None


def _dpapi_unwrap(blob: bytes) -> bytes | None:
    """Windows DPAPI unwrap (``cryptography`` + ``ctypes`` both required)."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:                       # noqa: BLE001 - non-Windows
        return None

    class _Blob(ctypes.Structure):
        _fields_ = (("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char)))

    try:
        buffer = ctypes.create_string_buffer(blob, len(blob))
        source = _Blob(len(blob), ctypes.cast(buffer,
                                              ctypes.POINTER(ctypes.c_char)))
        result = _Blob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None,
                                          None, None, 0,
                                          ctypes.byref(result)):
            return None
        try:
            return bytes(ctypes.string_at(result.pbData, result.cbData))
        finally:
            kernel32.LocalFree(result.pbData)
    except Exception:                       # noqa: BLE001 - never raise
        return None


def _decrypt_value(raw) -> str | None:
    """A cookie value: plain text, or ``v10``/``v11`` AES-GCM (None = unusable)."""
    if isinstance(raw, (bytes, bytearray)):
        data = bytes(raw)
    else:
        data = str(raw or "").encode("utf-8", "replace")
    if not data:
        return ""
    if not data.startswith((b"v10", b"v11")):
        return data.decode("utf-8", "replace")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception:                       # noqa: BLE001 - optional dependency
        return None
    key = _cookie_key()
    if not key:
        return None
    body = data[3:]
    if len(body) < 28:
        return None
    try:
        plain = AESGCM(key).decrypt(body[:12], body[12:], None)
    except Exception:                       # noqa: BLE001 - bad blob / key
        return None
    return plain.decode("utf-8", "replace")


# ------------------------------------------------------------------ public
def read_session_cookies(host: str) -> list[dict] | None:
    """Usable FedAuth / rtFa cookies for ``host``, or None.

    The returned list lives in memory only; the caller drops it after the
    uploader is configured.  Never raises, never logs a value.
    """
    host = str(host or "").strip().lower()
    if not host:
        return None
    rows: list[dict] = []
    for db in candidate_cookie_dbs():
        rows.extend(_rows_from_db(db))
    kept = session_cookies(rows, host)      # host / name shaping, one place
    return kept or None


__all__ = ["PROFILES", "candidate_cookie_dbs", "read_session_cookies"]
