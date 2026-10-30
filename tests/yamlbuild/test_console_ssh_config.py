# -*- coding: utf-8 -*-
"""M29 Console tab SSH config tests.

Covers: the password NEVER reaches the YAML (credential layer only,
ref ``fct_ssh_<host>``), the bare-metal gating of the whole SSH area,
the Test Connection button's three outcomes (mock paramiko), the new
``SshFctChannel.get_dir`` recursive pull (2-level tree) and the
pre-front transfer progress bar (mock channel, signal driven).

All Qt tests run offscreen; paramiko is replaced with in-memory fakes.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

import yaml as pyyaml

from mtkgui.engine.fct_test_config import ConsoleCfg, FctTestConfig
from mtkgui.engine.fct_channels import SshFctChannel
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (
    FCTTestConfigPanel,
    _SshProbeWorker,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cred(monkeypatch):
    """In-memory credential layer (the panel calls it lazily)."""
    import mtkgui.engine.credentials as credentials
    store: dict = {}
    events: list = []

    def _set(ref, value):
        events.append(("set", ref, value))
        store[ref] = value
        return True, ""

    def _delete(ref):
        events.append(("delete", ref))
        store.pop(ref, None)
        return True

    def _get(ref):
        if ref in store:
            return store[ref], ""
        raise credentials.CredentialUnavailable(f"no credential for {ref}")

    monkeypatch.setattr(credentials, "set_credential", _set)
    monkeypatch.setattr(credentials, "delete_credential", _delete)
    monkeypatch.setattr(credentials, "get_credential", _get)
    credentials._STORE = store
    credentials._EVENTS = events
    return credentials


SSH_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/ttyFAKE"
    ssh_host: 192.168.1.20
    ssh_username: root
    scripts_local_dir: assets/dut
    scripts_remote_dir: /root
    pull_remote_dir: /tmp/results
    pull_local_dir: logs/results
    test_commands:
      - {name: Kernel check, send: "uname -a", expect_pass: Linux}
"""


def _panel_with_yaml(qapp, cred, text=SSH_YAML):
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": text})
    return panel


# ------------------------------------------------- password never in YAML
def test_console_cfg_pull_fields_round_trip():
    """The new pull fields survive to_dict -> from_dict and the dict
    NEVER carries a password key."""
    cfg = ConsoleCfg(pull_remote_dir="/tmp/results",
                     pull_local_dir="logs/results")
    d = cfg.to_dict()
    assert d["pull_remote_dir"] == "/tmp/results"
    assert d["pull_local_dir"] == "logs/results"
    assert "ssh_password" not in d and "password" not in d
    back = FctTestConfig.from_dict(
        {"console": d}).console
    assert back.pull_remote_dir == "/tmp/results"
    assert back.pull_local_dir == "logs/results"


def test_password_goes_to_credential_layer_never_yaml(qapp, cred):
    """Typing a password + values() stores it under ref
    fct_ssh_<host> (same ref as fct_exec.bind_sftp_channel) and the
    emitted YAML contains no password; an EMPTY field clears the
    credential; an empty host never touches the credential layer."""
    panel = _panel_with_yaml(qapp, cred)
    # load prefills from the credential layer (empty store -> empty)
    assert panel.console_ssh_password.text() == ""

    panel.console_ssh_password.setText("s3cret-pw")
    out = panel.values()
    assert ("set", "fct_ssh_192.168.1.20", "s3cret-pw") in cred._EVENTS
    assert "s3cret-pw" not in out["fct_test_config_yaml"]
    data = pyyaml.safe_load(out["fct_test_config_yaml"])
    console = data["fct_test_config"]["console"]
    assert "ssh_password" not in console
    assert console["pull_remote_dir"] == "/tmp/results"
    assert console["pull_local_dir"] == "logs/results"

    # empty field = clear the credential
    events_before = len(cred._EVENTS)
    panel.console_ssh_password.setText("")
    panel.values()
    assert ("delete", "fct_ssh_192.168.1.20") in cred._EVENTS[events_before:]

    # empty host -> the credential layer is never touched
    events_before = len(cred._EVENTS)
    panel.console_ssh_host.setText("")
    panel.console_ssh_password.setText("x")
    panel.values()
    assert len(cred._EVENTS) == events_before


def test_password_prefilled_from_credential_layer(qapp, cred):
    """Loading a YAML prefills the password field from the credential
    layer (ref fct_ssh_<host>), not from the YAML."""
    cred._STORE["fct_ssh_192.168.1.20"] = "loaded-pw"
    panel = _panel_with_yaml(qapp, cred)
    assert panel.console_ssh_password.text() == "loaded-pw"


# ---------------------------------------------------------- bare metal
def test_bare_metal_disables_the_whole_ssh_area(qapp, cred):
    panel = _panel_with_yaml(qapp, cred)
    ssh_widgets = (panel.console_ssh_host, panel.console_ssh_user,
                   panel.console_ssh_password, panel.ssh_test_btn,
                   panel.console_ssh_box, panel.sftp_put_box,
                   panel.sftp_pull_box)
    assert all(w.isEnabled() for w in ssh_widgets)

    panel.dut_type.setCurrentText("bare_metal")
    assert all(not w.isEnabled() for w in ssh_widgets)
    assert panel.ssh_bare_hint.isVisibleTo(panel)

    panel.dut_type.setCurrentText("linux")
    assert all(w.isEnabled() for w in ssh_widgets)
    assert not panel.ssh_bare_hint.isVisibleTo(panel)


def test_test_connection_disabled_without_host(qapp, cred):
    panel = _panel_with_yaml(qapp, cred)
    panel.console_ssh_host.setText("")
    assert not panel.ssh_test_btn.isEnabled()
    panel.console_ssh_host.setText("10.0.0.9")
    assert panel.ssh_test_btn.isEnabled()


# ----------------------------------------------------- test connection
class _FakeSSHClient:
    def __init__(self):
        self.kw: dict = {}

    def set_missing_host_key_policy(self, policy):
        pass

    def connect(self, **kw):
        self.kw = kw
        mode = _FakeSSHClient.mode
        if mode == "auth":
            raise RuntimeError("Authentication failed.")
        if mode == "timeout":
            raise RuntimeError("timed out")
        if mode == "refused":
            raise RuntimeError("Connection refused")

    def exec_command(self, command, timeout=None):
        out = types.SimpleNamespace(
            read=lambda: b"Linux 6.1.55\n", channel=None)
        return None, out, None

    def close(self):
        pass


_FakeSSHClient.mode = "ok"


def _install_fake_paramiko(monkeypatch):
    mod = types.ModuleType("paramiko")
    mod.AutoAddPolicy = object
    mod.SSHClient = _FakeSSHClient
    monkeypatch.setitem(sys.modules, "paramiko", mod)


@pytest.fixture
def net_ok(monkeypatch):
    """M41: the Test Connection runs ping -> TCP 22 -> auth; here the
    two network layers pass so the paramiko layer is exercised."""
    from mtkgui.engine import host_platform
    monkeypatch.setattr(host_platform, "ping_host", lambda *a, **k: True)
    monkeypatch.setattr(host_platform, "tcp_port_open",
                        lambda *a, **k: True)


def _wait_probe(qapp, panel):
    probe = panel._ssh_probe
    assert probe is not None
    assert probe.wait(5000), "probe thread did not finish"
    qapp.processEvents()


def test_test_connection_success_shows_green_ok(qapp, cred, monkeypatch,
                                                net_ok):
    panel = _panel_with_yaml(qapp, cred)
    _install_fake_paramiko(monkeypatch)
    panel._on_ssh_test()
    _wait_probe(qapp, panel)
    assert panel.ssh_test_status.text().startswith("SSH OK: root@192.168.1.20")
    assert "Linux 6.1.55" in panel.ssh_test_status.text()
    assert "#15803d" in panel.ssh_test_status.styleSheet()   # green


@pytest.mark.parametrize("mode,fragment", [
    ("auth", "Authentication failed"),
    ("timeout", "timed out"),
    ("refused", "Connection refused"),
])
def test_test_connection_failure_shows_real_error(
        qapp, cred, monkeypatch, net_ok, mode, fragment):
    panel = _panel_with_yaml(qapp, cred)
    _FakeSSHClient.mode = mode
    try:
        _install_fake_paramiko(monkeypatch)
        panel._on_ssh_test()
        _wait_probe(qapp, panel)
        assert panel.ssh_test_status.text().startswith("SSH FAILED:")
        assert fragment in panel.ssh_test_status.text()
        assert "#b91c1c" in panel.ssh_test_status.styleSheet()  # red
    finally:
        _FakeSSHClient.mode = "ok"


def test_test_connection_paramiko_missing(qapp, cred, monkeypatch, net_ok):
    panel = _panel_with_yaml(qapp, cred)
    monkeypatch.setitem(sys.modules, "paramiko", None)   # import raises
    panel._on_ssh_test()
    _wait_probe(qapp, panel)
    assert "paramiko is not installed" in panel.ssh_test_status.text()


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


# ------------------------------------------------------------ transfer
class _FakeTransferChannel:
    """put_dir/get_dir replacement driven through the SAME public
    surface (constructor kwargs + progress callback)."""

    last = None

    def __init__(self, host, username, credential_ref):
        self.host = host
        self.credential_ref = credential_ref
        _FakeTransferChannel.last = self

    def put_dir(self, local_dir, remote_dir="", progress=None):
        files = ["f1", "f2", "f3"]
        for i, f in enumerate(files, 1):
            if progress is not None:
                progress(i, len(files), f, f"{remote_dir}/{f}")
        return [(f, f"{remote_dir}/{f}", 1) for f in files]

    def close(self):
        pass


def test_transfer_progress_bar_pre_front_and_completes(
        qapp, cred, monkeypatch, tmp_path):
    """M29: the progress bar is visible with "Connecting..." BEFORE the
    transfer runs, then advances with the per-file signals and ends at
    100% / "Done: N files"."""
    import mtkgui.engine.fct_channels as fct_channels
    monkeypatch.setattr(fct_channels, "SshFctChannel",
                        _FakeTransferChannel)
    panel = _panel_with_yaml(qapp, cred)
    local = tmp_path / "assets"
    local.mkdir()
    panel.console_scripts_local.setText(str(local))
    panel.console_scripts_remote.setText("/root")

    panel._on_ssh_transfer()
    # PRE-FRONT: bar visible, 0%, "Connecting...", button disabled -
    # BEFORE any file signal arrived
    assert panel.ssh_transfer_bar.isVisibleTo(panel)
    assert panel.ssh_transfer_bar.value() == 0
    assert panel.ssh_transfer_status.text() == "Connecting..."
    assert not panel.ssh_transfer_btn.isEnabled()

    worker = panel._ssh_transfer
    assert worker.wait(5000), "transfer thread did not finish"
    qapp.processEvents()
    assert _FakeTransferChannel.last.credential_ref == \
        "fct_ssh_192.168.1.20"
    assert panel.ssh_transfer_bar.value() == 100
    assert panel.ssh_transfer_status.text() == "Done: 3 files"
    assert panel.ssh_transfer_btn.isEnabled()


def test_transfer_pull_uses_get_dir(qapp, cred, monkeypatch, tmp_path):
    import mtkgui.engine.fct_channels as fct_channels
    calls: list = []

    class _Pull(_FakeTransferChannel):
        def get_dir(self, remote_dir, local_dir="", progress=None):
            calls.append(("get_dir", remote_dir, local_dir))
            if progress is not None:
                progress(1, 1, remote_dir, "r.txt")
            return [("/tmp/results/r.txt", "r.txt", 1)]

    monkeypatch.setattr(fct_channels, "SshFctChannel", _Pull)
    panel = _panel_with_yaml(qapp, cred)
    panel.ssh_transfer_direction.setCurrentIndex(1)   # Pull
    panel._on_ssh_transfer()
    worker = panel._ssh_transfer
    assert worker.wait(5000)
    qapp.processEvents()
    assert calls == [("get_dir", "/tmp/results",
                      panel.console_pull_local.text())]
    assert panel.ssh_transfer_status.text() == "Done: 1 files"
