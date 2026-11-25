#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write the frozen build's ``_build_version.txt`` stamp.

A PyInstaller bundle has no git checkout beside the exe, so the GUI
cannot read the commit at runtime.  This script bakes the build facts
into a small JSON marker that ``mtkgui.version_info`` reads beside the
exe, which is what makes the Event Log line show, for a packaged build::

    Build: v1.0.0.0 (develop @ 13908ca) (source: file)

Usage (Windows, after packaging)::

    python scripts/build_stamp.py dist\\MTK_GUI

The PyInstaller spec calls :func:`write_stamp` itself, so a plain
``pyinstaller --noconfirm MTK_GUI_windows.spec`` already stamps the
output; run this script by hand only when restamping an existing
bundle or when the spec was bypassed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MARKER = "_build_version.txt"


def _git(*args: str) -> str:
    """One git query inside the repo; empty string when unavailable."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(REPO), capture_output=True, text=True,
            timeout=5.0, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def collect() -> dict:
    """Build facts of the current checkout as the marker payload."""
    sys.path.insert(0, str(REPO))
    from mtkgui import __version__                    # noqa: PLC0415

    return {
        "version": __version__,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": _git("rev-parse", "--short", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
    }


def write_stamp(dist_dir: Path) -> Path:
    """Write the marker beside the packaged exe.

    Args:
        dist_dir: Folder holding ``MTK_GUI.exe`` (PyInstaller's
            ``dist/MTK_GUI``).

    Returns:
        The written marker path.
    """
    dist_dir = Path(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)
    target = dist_dir / MARKER
    target.write_text(json.dumps(collect(), ensure_ascii=False),
                      encoding="utf-8")
    return target


def main(argv: list[str]) -> int:
    """CLI entry point."""
    target = Path(argv[1]) if len(argv) > 1 else Path("dist") / "MTK_GUI"
    path = write_stamp(target)
    print(f"stamped {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
