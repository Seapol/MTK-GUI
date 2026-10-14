# -*- coding: utf-8 -*-
"""GUI version label source - unified to THE single release version.

User directive 2026-10-14: the GUI carries exactly ONE version -
``mtkgui.__version__`` (starting ``v1.0.0.0``).  ``develop`` commits
never change it; only a Release commit bumps the constant (and
records the release in docs/help/version_history.md, Help >
Version History).

The former M0 dynamic scheme (CI-written ``resources/version.json``
with ``vX.Y.Z.xxxx`` and the ``v4.1.1.0000`` static fallback) is
RETIRED - every label (status bar, login, About) renders the release
version.  Build facts (branch / commit / dirty) stay available
separately through :func:`mtkgui.version_info.get_version_info`.
"""

from __future__ import annotations

from pathlib import Path


def load_gui_version(path: Path | None = None) -> tuple[str, str | None]:
    """Return the GUI version label - the single release version.

    Args:
        path: Ignored (kept for call compatibility with the retired
              version.json scheme and its old tests).

    Returns:
        ``(__version__, None)`` - the release version and no warning
        (there is no dynamic source left that could fail).
    """
    from mtkgui import __version__
    return __version__, None
