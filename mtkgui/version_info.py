# -*- coding: utf-8 -*-
"""Dynamic build versioning (interface_spec.md section 33).

THE VERSION NUMBER is the release version ``mtkgui.__version__``
(starting ``v1.0.0.0``, user directive 2026-10-14): the GUI carries
exactly ONE version at any time.  ``develop`` commits never change
it - only a Release commit bumps the constant (and records the
release in the Version History).  Build facts resolve ONCE per
process from, in order:

1. the ``MTKGUI_VERSION`` environment variable (packaged builds),
2. a ``_build_version.txt`` file beside the app root (frozen builds),
3. live git metadata of the working tree (branch, short commit,
   dirty flag) combined with the release version,
4. the bare release version (last resort).

The resolution never raises into the UI: every failure falls back
silently to the next source and the returned :class:`VersionInfo`
records which source produced it (``source`` field) so the running
build stays auditable.  Consumers:

* status bar / home page version label (``display()``),
* About / Version History dialogs,
* every exported-file version suffix (``suffix()`` - filename safe).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _exe_dir() -> Path:
    """Folder containing the running executable (frozen onedir/onefile).

    The packaging step writes ``_build_version.txt`` BESIDE the exe
    (``MTK_GUI.exe``), not into PyInstaller's ``_internal/`` bundle -
    so a frozen build must look here, never at the module path.
    """
    return Path(sys.executable).resolve().parent


#: app root: beside the exe when frozen, the dev checkout otherwise
APP_ROOT = _exe_dir() if _frozen() else Path(__file__).resolve().parent.parent
BUILD_VERSION_FILE = "_build_version.txt"
ENV_VERSION = "MTKGUI_VERSION"
_GIT_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class VersionInfo:
    """Resolved build version facts.

    Attributes:
        tag:    Nearest git tag ("" when the tree has no tags).
        branch: Current branch name ("" when detached / unknown).
        commit: Short commit hash ("" when unknown).
        dirty:  True when the working tree has uncommitted changes.
        source: Which source produced this info:
                "env" | "file" | "git" | "static".
    """

    tag: str
    branch: str
    commit: str
    dirty: bool
    source: str

    def display(self) -> str:
        """Human readable version line for the UI.

        Returns:
            e.g. ``"v3.0.0 (develop @ 1a2b3c4) [dirty]"``; without a
            tag ``"develop @ 1a2b3c4"``; the bare version string when
            only the static source is available.
        """
        if self.source == "static":
            return self.tag
        if self.tag:
            if self.branch and self.commit:
                base = f"{self.tag} ({self.branch} @ {self.commit})"
            elif self.branch:
                base = f"{self.tag} ({self.branch})"
            elif self.commit:
                base = f"{self.tag} (@ {self.commit})"
            else:
                base = self.tag
        else:
            base = " @ ".join(
                part for part in (self.branch, self.commit) if part)
        if self.dirty:
            base = f"{base} [dirty]"
        return base or "unknown"

    def suffix(self) -> str:
        """Filename-safe version suffix for exported files.

        Returns:
            e.g. ``"v3.0.0-develop-1a2b3c4"``; punctuation and any
            character illegal in file names is dropped or converted
            to dashes (branch names may contain ``/``).
        """
        text = self.display()
        for ch in "()[],@":
            text = text.replace(ch, "")
        for ch in '/\\:*?"<>|':
            text = text.replace(ch, "-")
        return "-".join(text.split())


# module-level cache: resolve once per process (spec section 33)
_CACHE: VersionInfo | None = None


def _default_runner(args: list[str]) -> tuple[int, str]:
    """Run one git command inside the app working tree.

    Args:
        args: Git argument list (without the ``git`` binary).

    Returns:
        ``(returncode, stdout)`` tuple; stdout is stripped.
    """
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(APP_ROOT), capture_output=True,
            text=True, timeout=_GIT_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, (proc.stdout or "").strip()


def _from_git(runner) -> VersionInfo | None:
    """Collect the version facts from live git metadata.

    The version NUMBER itself is the release version
    (``mtkgui.__version__`` - git tags no longer influence it);
    git only contributes the branch / commit / dirty build facts.

    Args:
        runner: Callable executing one git command.

    Returns:
        :class:`VersionInfo` with ``source="git"``, or ``None`` when
        git is unavailable / the tree has no commit.
    """
    from mtkgui import __version__
    rc, commit = runner(["rev-parse", "--short", "HEAD"])
    if rc != 0 or not commit:
        return None
    rc, branch = runner(["rev-parse", "--abbrev-ref", "HEAD"])
    rc, status = runner(["status", "--porcelain"])
    return VersionInfo(
        tag=__version__, branch=branch, commit=commit, dirty=bool(status),
        source="git")


def resolve(runner=None) -> VersionInfo:
    """Resolve the build version (uncached; see :func:`get_version_info`).

    Args:
        runner: Optional git runner override (tests); defaults to the
                real subprocess runner.

    Returns:
        :class:`VersionInfo` from the first available source.
    """
    from mtkgui import __version__

    runner = runner or _default_runner
    # 1. packaged-build environment override
    env_version = os.environ.get(ENV_VERSION, "").strip()
    if env_version:
        return VersionInfo(tag=env_version, branch="", commit="",
                           dirty=False, source="env")
    # 2. frozen-build version file beside the app root (beside the exe
    #    in a frozen build, the dev checkout root otherwise)
    root = _exe_dir() if _frozen() else APP_ROOT
    marker = root / BUILD_VERSION_FILE
    try:
        if marker.is_file():
            file_version = marker.read_text(
                encoding="utf-8").strip()
            if file_version:
                return VersionInfo(tag=file_version, branch="", commit="",
                                   dirty=False, source="file")
    except OSError:
        pass
    # 3. live git metadata (dev checkouts only; a frozen build has no
    #    repo beside the exe and spawning git.exe flashes console
    #    windows on Windows)
    if not getattr(sys, "frozen", False):
        info = _from_git(runner)
        if info is not None:
            return info
    # 4. static last resort
    return VersionInfo(tag=__version__, branch="", commit="",
                       dirty=False, source="static")


def get_version_info(force: bool = False) -> VersionInfo:
    """Return the cached build version (resolved once per process).

    Args:
        force: True re-resolves (tests / explicit refresh).

    Returns:
        The cached :class:`VersionInfo`.
    """
    global _CACHE
    if _CACHE is None or force:
        _CACHE = resolve()
    return _CACHE
