# -*- coding: utf-8 -*-
"""M97 station account tests - the supervisor credential is a station hash.

The autouse ``isolated_work_dir`` fixture in ``tests/conftest.py`` points
``MTKGUI_WORK_DIR`` at a temporary folder, so these tests never touch the
developer's ``<repo>/work``.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from mtkgui import accounts


@pytest.fixture(autouse=True)
def _clean_station_account():
    accounts.clear_password()
    yield
    accounts.clear_password()


# ------------------------------------------------------------------ basics
def test_no_file_means_not_configured_and_verify_false():
    assert accounts.is_configured() is False
    assert accounts.verify("anything") is False
    assert accounts.load_supervisor() is None


def test_set_then_verify_round_trip():
    path = accounts.set_password("Station-2026")
    assert path == accounts.supervisor_path()
    assert accounts.is_configured() is True
    assert accounts.verify("Station-2026") is True
    assert accounts.verify("station-2026") is False   # case matters
    assert accounts.verify("") is False


# ---------------------------------------------------------- no plaintext
def test_record_holds_no_plaintext():
    password = "Station-2026"
    accounts.set_password(password)
    text = accounts.supervisor_path().read_text(encoding="utf-8")
    assert password not in text
    assert '"kdf": "pbkdf2_sha256"' in text
    record = json.loads(text)
    assert isinstance(record["iterations"], int)
    first = accounts.hash_password(password)
    second = accounts.hash_password(password)
    assert first["salt"] != second["salt"]
    assert first["hash"] != second["hash"]


# ------------------------------------------------------------ validation
def test_short_and_retired_values_are_refused():
    with pytest.raises(ValueError):
        accounts.set_password("short")            # 5 characters
    with pytest.raises(ValueError) as retired:
        accounts.set_password("nxp")
    assert str(retired.value) == \
        "that value was the old built-in default - choose a new password"
    with pytest.raises(ValueError) as upper:
        accounts.set_password("NXP")
    assert str(upper.value) == str(retired.value)
    with pytest.raises(ValueError):
        accounts.set_password("        ")         # whitespace only
    assert accounts.is_configured() is False      # nothing partial on disk


# --------------------------------------------------------------- fail closed
def test_tampered_record_fails_closed():
    path = accounts.supervisor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    valid = accounts.hash_password("Station-2026")
    wrong = dict(valid, hash="AAAA")             # valid base64, wrong digest
    path.write_text(json.dumps(wrong), encoding="utf-8")
    assert accounts.verify("Station-2026") is False
    broken = dict(valid, iterations=str(valid["iterations"]))
    path.write_text(json.dumps(broken), encoding="utf-8")
    assert accounts.verify("Station-2026") is False
    assert accounts.load_supervisor() is None
    path.write_text("{not json", encoding="utf-8")
    assert accounts.verify("Station-2026") is False
    assert accounts.load_supervisor() is None


# -------------------------------------------------------------- permissions
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_file_permissions_are_owner_only():
    path = accounts.set_password("Station-2026")
    assert os.stat(path).st_mode & 0o777 == 0o600


# ------------------------------------------------------------------ guard
def test_no_plaintext_default_anywhere_in_the_source():
    """The retired default must not reappear in any shipped source file."""
    root = Path(__file__).resolve().parents[2]
    needles = ('SUPERVISOR_PASSWORD = "nxp"', "'nxp'")
    hits = []
    for sub in ("mtkgui", "main.py"):
        target = root / sub
        paths = [target] if target.is_file() else target.rglob("*.py")
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(n in text for n in needles):
                hits.append(str(path.relative_to(root)))
    assert hits == []
