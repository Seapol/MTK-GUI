# -*- coding: utf-8 -*-
"""Guard: user-facing GUI strings must be 100% English.

Tokenizes every ``.py`` file under ``mtkgui/gui/`` plus
``mtkgui/permissions.py`` and
``mtkgui/at_commands.py`` and fails on any non-docstring STRING token
that contains CJK characters (U+4E00-U+9FFF).  Docstrings (the first
statement of a module / class / def - identified here as STRING tokens
starting with a triple quote) are allowed to keep Chinese, so the
fixed Excel interchange contract (engine ``_HEADER_CN``) and internal
comments stay untouched.

Parametrized per file so a failure lists every offending file:line.
"""
from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2] / "mtkgui"

# (absolute path, module-relative label) for every guarded file
_TARGETS = sorted(
    [(p, p.relative_to(PKG_ROOT.parent)) for p in
     (PKG_ROOT / "gui").rglob("*.py")]
    + [(PKG_ROOT / "permissions.py", Path("permissions.py")),
       (PKG_ROOT / "at_commands.py", Path("at_commands.py"))]
)

_CJK_RE = re.compile(r"[一-鿿]")


def _cjk_hits(path: Path) -> list[str]:
    """Return 'line:col text' for every non-docstring CJK string."""
    hits: list[str] = []
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type != tokenize.STRING:
                continue
            text = tok.string
            # docstring exemption: triple-quoted token (module/class/
            # def docstrings are the only legal triple-quoted literals
            # in this codebase style)
            if text.startswith('"""') or text.startswith("'''"):
                continue
            if _CJK_RE.search(text):
                hits.append(f"{tok.start[0]}:{tok.start[1]} {text!r}")
    return hits


@pytest.mark.parametrize("path,label", _TARGETS, ids=[str(l) for _, l in _TARGETS])
def test_no_cjk_in_ui_strings(path: Path, label: Path) -> None:
    """Every guarded file must carry zero CJK in string literals."""
    with io.open(path, "r", encoding="utf-8") as fh:  # sanity: decodable
        fh.read()
    hits = _cjk_hits(path)
    assert not hits, (
        f"{label}: Chinese found in non-docstring string literal(s); "
        "translate to factory-floor English:\n" + "\n".join(hits))
