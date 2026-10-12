# -*- coding: utf-8 -*-
"""P3-B4 Modules A/B: SerialFctChannel / SshFctChannel unit tests.

Transport backends (pyserial / paramiko) are replaced with in-memory
fakes via sys.modules injection - the REAL transport verification
runs in the integration layer (socat pty pair / local sshd), these
tests cover the adapter logic: line buffering, reconnect, credential
handling, stderr/exit-code framing.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from mtkgui.engine.fct_channels import (
    ChannelClosed,
    SerialFctChannel,
    SshFctChannel,
)


# ---------------------------------------------------------------- fakes
class FakeSerial:
    is_open = True
    _NEXT_RX = b""                         # rx for the NEXT instance

    def __init__(self, **cfg):
        self.cfg = cfg
        self.tx: list = []
        self.rx: bytes = FakeSerial._NEXT_RX
        FakeSerial._NEXT_RX = b""
        self.closed = False
        FakeSerial._LAST = self                # test handle

    def write(self, data: bytes):
        self.tx.append(data)
        return len(data)

    def flush(self):
        pass

    def read(self, n):
        data, self.rx = self.rx[:n], self.rx[n:]
        return data

    def close(self):
        self.is_open = False
        self.closed = True


class FakeSSHChannel:
    def __init__(self, code):
        self._code = code

    def recv_exit_status(self):
        return self._code


class FakeSSHStdout(list):
    channel = None


class FakeSFTPClient:
    """In-memory SFTP: put stores content, get writes it back."""

    store: dict = {}                       # remote_path -> bytes
    calls: list = []                       # ("put"/"get", local, remote)
    dirs: set = set()                      # created remote directories

    def put(self, local_path, remote_path):
        with open(local_path, "rb") as f:
            FakeSFTPClient.store[remote_path] = f.read()
        FakeSFTPClient.calls.append(("put", local_path, remote_path))

    def get(self, remote_path, local_path):
        with open(local_path, "wb") as f:
            f.write(FakeSFTPClient.store.get(remote_path, b""))
        FakeSFTPClient.calls.append(("get", local_path, remote_path))

    def stat(self, path):
        if path in self.dirs or path in self.store:
            return object()
        raise IOError("no such file")

    def mkdir(self, path):
        self.dirs.add(path)

    def close(self):
        pass


def make_fake_paramiko(script: dict, fail_auth: bool = False):
    """`script`: command -> (stdout_lines, stderr_lines, exit_code)."""
    mod = types.ModuleType("paramiko")

    class AutoAddPolicy:
        pass

    class SSHClient:
        def __init__(self):
            self.connected = False
            self.commands: list = []
            self.sftp = None
            SSHClient._LAST = self

        def open_sftp(self):
            self.sftp = FakeSFTPClient()
            return self.sftp

        def set_missing_host_key_policy(self, policy):
            self.policy = policy

        def connect(self, **kw):
            if fail_auth:
                raise RuntimeError("Authentication failed")
            self.connected = True
            self.kw = kw

        def exec_command(self, command, timeout=None):
            self.commands.append(command)
            out, err, code = script.get(command, ([], [], 0))
            stdout = FakeSSHStdout(out)
            stdout.channel = FakeSSHChannel(code)
            stderr = FakeSSHStdout(err)
            return None, stdout, stderr

        def close(self):
            self.connected = False

    mod.AutoAddPolicy = AutoAddPolicy
    mod.SSHClient = SSHClient
    return mod


@pytest.fixture
def fake_serial(monkeypatch):
    monkeypatch.setitem(sys.modules, "serial",
                        types.SimpleNamespace(Serial=FakeSerial))


@pytest.fixture
def fake_cred(monkeypatch):
    import mtkgui.engine.credentials as cred
    monkeypatch.setattr(cred, "get_credential",
                        lambda ref: ("secret-pw", "env fallback"))
    return cred


# --------------------------------------------------------- Module A: serial
def test_serial_roundtrip(fake_serial):
    ch = SerialFctChannel(port="/dev/ttyFAKE", reconnect=False)
    FakeSerial._LAST.rx = b"Success\n"
    ch.write("AT")
    assert FakeSerial._LAST.tx[-1] == b"AT\n"
    assert ch.read_lines() == ["Success"]
    ch.close()


def test_serial_partial_line_buffered(fake_serial):
    ch = SerialFctChannel(port="/dev/ttyFAKE", reconnect=False)
    FakeSerial._LAST.rx = b"hello wor"
    assert ch.read_lines() == []          # partial stays buffered
    FakeSerial._LAST.rx = b"ld\nnext\n"
    assert ch.read_lines() == ["hello world", "next"]
    ch.close()


def test_serial_write_failure_raises_channelclosed(fake_serial):
    ch = SerialFctChannel(port="/dev/ttyFAKE", reconnect=False)
    FakeSerial._LAST.is_open = False       # simulate device gone
    with pytest.raises(ChannelClosed):
        ch.write("x")
    ch.close()


def test_serial_reconnect_off_raises(fake_serial):
    ch = SerialFctChannel(port="/dev/ttyFAKE", reconnect=False)
    FakeSerial._LAST.is_open = False
    with pytest.raises(ChannelClosed):
        ch.read_lines()
    ch.close()


def test_serial_reconnect_on_recovers(fake_serial, monkeypatch):
    ch = SerialFctChannel(port="/dev/ttyFAKE", reconnect=True,
                          reconnect_interval_s=0.6)
    FakeSerial._LAST.is_open = False       # drop
    monkeypatch.setattr("time.sleep", lambda _s: None)
    FakeSerial._NEXT_RX = b"Success\n"     # reconnected instance serves it
    assert ch.read_lines() == ["Success"]
    ch.close()


# ----------------------------------------------------------- Module B: ssh
def test_ssh_write_captures_stdout_stderr_exit(fake_cred, monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({
        "uname -a": (["Darwin host"], ["warning line"], 0)}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref")
    ch.write("uname -a")
    lines = ch.read_lines()
    assert lines[0] == "Darwin host"
    assert "[stderr] warning line" in lines
    assert lines[-1] == "[exit] 0"
    ch.close()


def test_ssh_password_from_credentials_not_yaml(fake_cred, monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref")
    client = type(ch._client)._LAST
    assert client.kw["password"] == "secret-pw"
    ch.close()


def test_ssh_auth_failure_raises(fake_cred, monkeypatch):
    monkeypatch.setitem(
        sys.modules, "paramiko", make_fake_paramiko({}, fail_auth=True))
    with pytest.raises(ChannelClosed):
        SshFctChannel(host="h", username="u", credential_ref="ref")


def test_ssh_negative_exit_code_line(fake_cred, monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({
        "false": ([], [], 1)}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref")
    ch.write("false")
    assert "[exit] 1" in ch.read_lines()
    ch.close()


def test_ssh_close_clears_state(fake_cred, monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref")
    ch.close()
    with pytest.raises(ChannelClosed):
        ch.write("x")


# -------------------------------------------------- SFTP file deployment
@pytest.fixture
def local_file(tmp_path):
    p = tmp_path / "load_drivers.sh"
    p.write_text("#!/bin/sh\necho drivers-ok\n")
    return p


def test_sftp_put_uses_remote_dir_default(local_file, fake_cred,
                                          monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref",
                       remote_dir="/home/root/")
    target = ch.put_file(str(local_file))
    assert target == "/home/root/load_drivers.sh"
    assert FakeSFTPClient.calls[-1] == ("put", str(local_file), target)
    assert "[sftp] put" in ch.read_lines()[0]     # event in read buffer
    ch.close()


def test_sftp_put_explicit_remote_path(local_file, fake_cred,
                                       monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref")
    target = ch.put_file(str(local_file), remote_path="/tmp/x.sh")
    assert target == "/tmp/x.sh"
    ch.close()


def test_sftp_put_then_exec_flow(local_file, fake_cred, monkeypatch):
    """Typical deployment flow: put -> console send -> read result."""
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({
        "sh /tmp/load_drivers.sh": (["drivers-ok"], [], 0)}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref",
                       remote_dir="/tmp")
    ch.put_file(str(local_file))
    ch.read_lines()                               # drain sftp event
    ch.write("sh /tmp/load_drivers.sh")
    lines = ch.read_lines()
    assert "drivers-ok" in lines and lines[-1] == "[exit] 0"
    ch.close()


def test_sftp_get_roundtrip(tmp_path, local_file, fake_cred,
                            monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref",
                       remote_dir="/tmp")
    target = ch.put_file(str(local_file))
    back = tmp_path / "readback.sh"
    ch.get_file(target, str(back))
    assert back.read_text() == local_file.read_text()
    ch.close()


def test_sftp_close_closes_sftp(local_file, fake_cred, monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref")
    ch.put_file(str(local_file))
    client = type(ch._client)._LAST
    sftp = client.sftp
    ch.close()
    assert ch._sftp is None                       # dropped with the client


def test_sftp_put_dir_recursive(tmp_path, fake_cred, monkeypatch):
    """Whole asset folder is mirrored: subdirectories created and every
    file uploaded under the remote target."""
    FakeSFTPClient.dirs.clear()
    root = tmp_path / "linux"
    (root / "sub").mkdir(parents=True)
    (root / "load_rf_drivers.sh").write_text("#!/bin/sh\necho ok\n")
    (root / "connect_wifi.sh").write_text("#!/bin/sh\necho wifi\n")
    (root / "sub" / "start_bt_audio.sh").write_text("#!/bin/sh\necho bt\n")
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref")
    uploaded = ch.put_dir(str(root), "/root")
    remotes = {rp for _lp, rp, _n in uploaded}
    assert remotes == {"/root/load_rf_drivers.sh",
                       "/root/connect_wifi.sh",
                       "/root/sub/start_bt_audio.sh"}
    assert "/root" in FakeSFTPClient.dirs and "/root/sub" in \
        FakeSFTPClient.dirs
    event = "\n".join(ch.read_lines())
    assert "put_dir" in event and "3 files" in event
    ch.close()


def test_sftp_put_dir_missing_raises(fake_cred, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "paramiko", make_fake_paramiko({}))
    ch = SshFctChannel(host="h", username="u", credential_ref="ref")
    with pytest.raises(ChannelClosed):
        ch.put_dir(str(tmp_path / "does_not_exist"), "/root")
    ch.close()
