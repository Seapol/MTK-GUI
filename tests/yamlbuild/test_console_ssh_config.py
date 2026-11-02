# -*- coding: utf-8 -*-
"""M29 SSH channel engine tests.

M50 removed the Console page (SSH credentials now live in the Equipment
DUT group ``SSH Login``); the SSH transfer engine (``get_dir`` remote
tree pull + the pull-dir console fields) keeps its coverage here.

All tests run offscreen; paramiko is replaced with in-memory fakes.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")

from mtkgui.engine.fct_test_config import ConsoleCfg, FctTestConfig
from mtkgui.engine.fct_channels import SshFctChannel


# ------------------------------------------------- console pull fields
def test_console_cfg_pull_fields_round_trip():
    """The pull fields survive to_dict -> from_dict."""
    cfg = ConsoleCfg(pull_remote_dir="/tmp/results",
                     pull_local_dir="logs/results")
    d = cfg.to_dict()
    assert d["pull_remote_dir"] == "/tmp/results"
    assert d["pull_local_dir"] == "logs/results"
    back = FctTestConfig.from_dict(
        {"console": d}).console
    assert back.pull_remote_dir == "/tmp/results"
    assert back.pull_local_dir == "logs/results"


# -------------------------------------------------------------- get_dir
class _SftpAttr:
    def __init__(self, name: str, size: int, is_dir: bool):
        self.filename = name
        self.st_size = size
        self.st_mode = 0o040755 if is_dir else 0o100644


class _FakeDirSftp:
    """In-memory remote tree: {remote_path: bytes}; directories are
    implied by the key structure."""

    tree: dict = {}

    def listdir_attr(self, path):
        prefix = path.rstrip("/") + "/"
        seen: dict = {}
        for p in self.tree:
            if p.startswith(prefix):
                rest = p[len(prefix):]
                name = rest.split("/", 1)[0]
                seen[name] = "/" in rest
        return [_SftpAttr(n, len(self.tree.get(f"{prefix}{n}", b"")), d)
                for n, d in sorted(seen.items())]

    def get(self, remote_path, local_path):
        with open(local_path, "wb") as f:
            f.write(self.tree.get(remote_path, b""))

    def stat(self, path):
        raise IOError("unused")


def _install_fake_dir_paramiko(monkeypatch):
    mod = types.ModuleType("paramiko")

    class _Client:
        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, **kw):
            pass

        def open_sftp(self):
            return _FakeDirSftp()

        def close(self):
            pass

    mod.AutoAddPolicy = object
    mod.SSHClient = _Client
    monkeypatch.setitem(sys.modules, "paramiko", mod)


def _fake_cred_channel(monkeypatch):
    import mtkgui.engine.credentials as credentials
    monkeypatch.setattr(credentials, "get_credential",
                        lambda ref: ("pw", ""))


def test_get_dir_pulls_two_level_tree(monkeypatch, tmp_path):
    """M29: get_dir mirrors a 2-level remote tree into the local
    folder (relative paths preserved) and reports the pulled files."""
    _FakeDirSftp.tree = {
        "/data/a.txt": b"A",
        "/data/sub/b.txt": b"B",
        "/data/sub/deep/c.txt": b"C",
    }
    _install_fake_dir_paramiko(monkeypatch)
    _fake_cred_channel(monkeypatch)
    ch = SshFctChannel(host="h", username="u", credential_ref="ref")
    out = tmp_path / "out"
    pulled = ch.get_dir("/data", str(out))
    names = sorted(str(p) for _r, p, _s in pulled)
    assert names == sorted([
        str(out / "a.txt"),
        str(out / "sub" / "b.txt"),
        str(out / "sub" / "deep" / "c.txt")])
    assert (out / "sub" / "deep" / "c.txt").read_bytes() == b"C"
    assert len(pulled) == 3
    assert "get_dir /data" in ch.read_lines()[0]
    ch.close()


def test_get_dir_requires_remote_source(monkeypatch):
    _install_fake_dir_paramiko(monkeypatch)
    _fake_cred_channel(monkeypatch)
    ch = SshFctChannel(host="h", username="u", credential_ref="ref")
    from mtkgui.engine.fct_channels import ChannelClosed
    with pytest.raises(ChannelClosed):
        ch.get_dir("", "/tmp/x")
    ch.close()
