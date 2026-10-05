# -*- coding: utf-8 -*-
"""Unit tests for the dynamic build versioning module
(interface_spec.md section 33)."""

from __future__ import annotations

import pytest

from mtkgui import __version__
from mtkgui.version_info import (
    VersionInfo,
    get_version_info,
    resolve,
)


def fake_runner(replies: dict[str, str], fail: set[str] | None = None):
    """Build a git runner that answers from a command->stdout map.

    Args:
        replies: Mapping from the joined git args to stdout.
        fail:    Args joined strings that return rc=1.

    Returns:
        Runner callable ``(list[str]) -> (int, str)``.
    """
    fail = fail or set()

    def run(args: list[str]) -> tuple[int, str]:
        joined = " ".join(args)
        if joined in fail:
            return 1, ""
        return 0, replies.get(joined, "")

    return run


def git_replies(commit="1a2b3c4", branch="develop", tag="v3.0.0",
                status="") -> dict[str, str]:
    """Standard git reply set for the happy path."""
    return {
        "rev-parse --short HEAD": commit,
        "rev-parse --abbrev-ref HEAD": branch,
        "describe --tags --abbrev=0": tag,
        "status --porcelain": status,
    }


# ---------------------------------------------------------------------------
# git source
# ---------------------------------------------------------------------------


def test_resolve_from_git_full():
    """Tag + branch + commit + clean tree resolve from git."""
    info = resolve(runner=fake_runner(git_replies()))
    assert info == VersionInfo(
        tag="v3.0.0", branch="develop", commit="1a2b3c4",
        dirty=False, source="git")


def test_resolve_git_dirty_tree():
    """Uncommitted changes set the dirty flag."""
    info = resolve(runner=fake_runner(git_replies(status=" M x.py")))
    assert info.dirty is True
    assert info.display().endswith("[dirty]")


def test_resolve_git_without_tags():
    """A tree without tags yields an empty tag; display falls back to
    branch @ commit."""
    replies = git_replies()
    runner = fake_runner(replies, fail={"describe --tags --abbrev=0"})
    info = resolve(runner=runner)
    assert info.tag == ""
    assert info.display() == "develop @ 1a2b3c4"


def test_resolve_git_failure_falls_back_to_static():
    """git unavailable -> static mtkgui.__version__ (never raises)."""
    def failing(args):
        return 1, ""

    info = resolve(runner=failing)
    assert info.source == "static"
    assert info.tag == __version__
    assert info.display() == __version__


# ---------------------------------------------------------------------------
# display / suffix formatting
# ---------------------------------------------------------------------------


def test_display_full_form():
    """Spec format: tag (branch @ commit) with optional dirty marker."""
    info = VersionInfo(tag="v3.0.0", branch="develop", commit="1a2b3c4",
                       dirty=False, source="git")
    assert info.display() == "v3.0.0 (develop @ 1a2b3c4)"
    dirty = VersionInfo(tag="v3.0.0", branch="develop", commit="1a2b3c4",
                        dirty=True, source="git")
    assert dirty.display() == "v3.0.0 (develop @ 1a2b3c4) [dirty]"


def test_suffix_is_filename_safe():
    """The suffix keeps letters/digits/dots/dashes only."""
    info = VersionInfo(tag="v3.0.0", branch="develop", commit="1a2b3c4",
                       dirty=True, source="git")
    suffix = info.suffix()
    assert suffix == "v3.0.0-develop-1a2b3c4-dirty"
    for ch in " ()[]@,":
        assert ch not in suffix
    assert " " not in suffix


def test_env_and_file_sources_use_display_directly():
    """env/file versions carry no branch/commit; display is the bare
    version string and the suffix stays filename-safe."""
    info = VersionInfo(tag="v4.0.0", branch="", commit="", dirty=False,
                       source="env")
    assert info.display() == "v4.0.0"
    assert info.suffix() == "v4.0.0"


# ---------------------------------------------------------------------------
# source priority (env > file > git > static)
# ---------------------------------------------------------------------------


def test_resolve_env_override(monkeypatch):
    """MTKGUI_VERSION beats everything (packaged builds)."""
    monkeypatch.setenv("MTKGUI_VERSION", "v4.0.0")
    info = resolve(runner=fake_runner(git_replies()))
    assert info.source == "env"
    assert info.tag == "v4.0.0"


def test_resolve_file_override(tmp_path, monkeypatch):
    """_build_version.txt beside the app root beats git."""
    from mtkgui import version_info as vi
    monkeypatch.setattr(vi, "APP_ROOT", tmp_path)
    (tmp_path / vi.BUILD_VERSION_FILE).write_text(
        "v4.0.0-rc1\n", encoding="utf-8")
    info = vi.resolve(runner=fake_runner(git_replies()))
    assert info.source == "file"
    assert info.tag == "v4.0.0-rc1"


def test_resolve_env_beats_file(tmp_path, monkeypatch):
    """Source priority: env over file over git over static."""
    from mtkgui import version_info as vi
    monkeypatch.setenv("MTKGUI_VERSION", "v4.0.0")
    monkeypatch.setattr(vi, "APP_ROOT", tmp_path)
    (tmp_path / vi.BUILD_VERSION_FILE).write_text(
        "v4.0.0-rc1\n", encoding="utf-8")
    info = vi.resolve(runner=fake_runner(git_replies()))
    assert info.source == "env"


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------


def test_get_version_info_caches_until_forced(monkeypatch):
    """get_version_info resolves once per process; force=True
    re-resolves exactly once."""
    from mtkgui import version_info as vi
    calls = {"n": 0}

    def fake_resolve(runner=None):
        calls["n"] += 1
        return VersionInfo(tag="v9.9.9", branch="", commit="",
                           dirty=False, source="static")

    monkeypatch.setattr(vi, "resolve", fake_resolve)
    info1 = vi.get_version_info(force=True)
    assert info1.tag == "v9.9.9"
    n1 = calls["n"]
    assert vi.get_version_info() is info1   # cached instance reused
    assert vi.get_version_info() is info1
    assert calls["n"] == n1                 # no extra resolution
    vi.get_version_info(force=True)
    assert calls["n"] == n1 + 1
