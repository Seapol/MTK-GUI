# -*- coding: utf-8 -*-
"""Unit tests for the Paramiko SSH instrument transport.

paramiko is mocked at the seam where SSHTransport._connect() returns
``(client, channel)``, so the tests run without paramiko installed and
without a network.  The lazy-import failure path is covered by putting
``None`` into ``sys.modules['paramiko']`` (Python then raises
ImportError on ``import paramiko``).
"""

from __future__ import annotations

import socket
import sys

import pytest

from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentIOError,
    InstrumentTimeoutError,
)
from mtkgui.drivers.transport_ssh import SSHTransport, _parse_address


class FakeChannel:
    """In-memory stand-in for a paramiko interactive shell channel."""

    def __init__(self, replies: list[bytes] | None = None) -> None:
        self.sent: list[bytes] = []
        self.replies = list(replies or [])
        self.closed = False
        self.timeout: float | None = None

    def sendall(self, payload: bytes) -> None:
        """Record one write."""
        self.sent.append(payload)

    def settimeout(self, timeout: float) -> None:
        """Record the channel timeout (paramiko API)."""
        self.timeout = timeout

    def recv(self, size: int) -> bytes:
        """Return queued reply bytes; raise socket.timeout when empty."""
        if self.replies:
            return self.replies.pop(0)
        raise socket.timeout("timed out")

    def close(self) -> None:
        """Mark the channel closed."""
        self.closed = True


class FakeClient:
    """In-memory stand-in for a paramiko SSHClient."""

    def __init__(self) -> None:
        self.closed = False
        self.connect_kwargs: dict | None = None
        self.channel = FakeChannel()

    def set_missing_host_key_policy(self, policy) -> None:
        """Accept any policy (paramiko API)."""

    def connect(self, **kwargs) -> None:
        """Record the connection parameters."""
        self.connect_kwargs = kwargs

    def invoke_shell(self):
        """Return the shared fake channel."""
        return self.channel

    def close(self) -> None:
        """Mark the client closed."""
        self.closed = True


def make_transport(replies: list[bytes]) -> tuple[SSHTransport, FakeClient]:
    """Return an open SSHTransport wired to fake paramiko objects."""
    transport = SSHTransport()
    client = FakeClient()
    client.channel.replies = list(replies)
    transport._connect = (  # type: ignore[method-assign]
        lambda *args, **kwargs: (client, client.channel))
    transport.open("192.168.1.50", {"username": "admin", "password": "s3cret"})
    return transport, client


# ---------------------------------------------------------------------------
# address parsing
# ---------------------------------------------------------------------------


def test_parse_address_defaults_port():
    """A bare host gets the default port 22."""
    assert _parse_address("192.168.1.50") == ("192.168.1.50", 22)


def test_parse_address_explicit_port():
    """``host:port`` splits into host and integer port."""
    assert _parse_address("gateway.lan:2222") == ("gateway.lan", 2222)


@pytest.mark.parametrize("bad", ["", "   ", ":2222", "host:abc"])
def test_parse_address_rejects_bad_input(bad):
    """Empty hosts and non-numeric ports are config errors."""
    with pytest.raises(InstrumentConfigError):
        _parse_address(bad)


# ---------------------------------------------------------------------------
# connection handling
# ---------------------------------------------------------------------------


def test_open_forwards_connection_parameters():
    """open() validates options and forwards host/port/user/password
    to the connect step."""
    transport = SSHTransport()
    client = FakeClient()
    captured: dict = {}

    def fake_connect(host, port, username, password):
        captured.update(host=host, port=port, username=username,
                        password=password)
        return client, client.channel

    transport._connect = fake_connect  # type: ignore[method-assign]
    transport.open("192.168.1.50:2222", {
        "username": "admin", "password": "pw",
    })
    assert captured == {"host": "192.168.1.50", "port": 2222,
                        "username": "admin", "password": "pw"}
    assert transport._is_open


def test_real_connect_uses_station_conventions(monkeypatch):
    """The real _connect() applies the ssh_worker conventions: explicit
    credentials, agent/keys disabled, AutoAddPolicy, timeout applied to
    client and channel."""
    import types

    fake_paramiko = types.ModuleType("paramiko")
    fake_paramiko.SSHClient = FakeClient
    fake_paramiko.AutoAddPolicy = lambda: "AUTOADD"
    monkeypatch.setitem(sys.modules, "paramiko", fake_paramiko)

    transport = SSHTransport()
    transport._timeout_s = 3.0
    client, chan = transport._connect("192.168.1.50", 2222, "admin", "pw")
    kwargs = client.connect_kwargs
    assert kwargs["hostname"] == "192.168.1.50"
    assert kwargs["port"] == 2222
    assert kwargs["username"] == "admin"
    assert kwargs["password"] == "pw"
    assert kwargs["allow_agent"] is False
    assert kwargs["look_for_keys"] is False
    assert kwargs["timeout"] == 3.0
    assert chan.timeout == 3.0


def test_open_requires_username():
    """open() without a username is a config error."""
    transport = SSHTransport()
    with pytest.raises(InstrumentConfigError):
        transport.open("192.168.1.50", {})


def test_open_maps_connect_failure_to_connection_lost():
    """A connect failure maps to ConnectionLostError (no leak)."""
    transport = SSHTransport()

    def failing_connect(*args, **kwargs):
        raise ConnectionLostError("refused")

    transport._connect = failing_connect  # type: ignore[method-assign]
    with pytest.raises(ConnectionLostError):
        transport.open("192.168.1.50", {"username": "admin"})


def test_lazy_import_failure_maps_to_io_error(monkeypatch):
    """A missing paramiko maps to InstrumentIOError with a clear
    message (station convention: GUI must still import)."""
    monkeypatch.setitem(sys.modules, "paramiko", None)
    transport = SSHTransport()
    with pytest.raises(InstrumentIOError, match="paramiko is not installed"):
        transport.open("192.168.1.50", {"username": "admin"})


# ---------------------------------------------------------------------------
# message exchange
# ---------------------------------------------------------------------------


def test_write_appends_terminator():
    """write() appends the terminator and records the payload."""
    transport, client = make_transport([])
    transport.write("*RST")
    assert client.channel.sent == [b"*RST\n"]


def test_query_skips_shell_echo():
    """query() skips the echoed command line and returns the reply."""
    transport, _ = make_transport(
        [b"MEAS:VOLT:DC? AUTO,DEF,(@101)\n", b"+3.30000000E+00\n"])
    reply = transport.query("MEAS:VOLT:DC? AUTO,DEF,(@101)")
    assert reply == "+3.30000000E+00"


def test_query_without_echo():
    """query() returns the first line when the remote does not echo."""
    transport, _ = make_transport([b"+3.30000000E+00\n"])
    reply = transport.query("*IDN?")
    assert reply == "+3.30000000E+00"


def test_query_timeout_maps_to_instrument_timeout():
    """A silent shell raises InstrumentTimeoutError (no paramiko leak)."""
    transport, _ = make_transport([])  # recv() will raise socket.timeout
    with pytest.raises(InstrumentTimeoutError):
        transport.query("*IDN?")


def test_query_channel_closed_maps_to_io_error():
    """An EOF (empty recv chunk) maps to InstrumentIOError."""
    transport = SSHTransport()
    client = FakeClient()
    client.channel.recv = lambda size: b""  # remote closed
    transport._connect = (  # type: ignore[method-assign]
        lambda *args, **kwargs: (client, client.channel))
    transport.open("192.168.1.50", {"username": "admin"})
    with pytest.raises(InstrumentIOError):
        transport.query("*IDN?")


def test_write_before_open_raises():
    """write()/query() before open() raise ConnectionLostError."""
    transport = SSHTransport()
    with pytest.raises(ConnectionLostError):
        transport.write("*RST")
    with pytest.raises(ConnectionLostError):
        transport.query("*IDN?")


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


def test_close_closes_channel_and_client():
    """close() closes both channel and client exactly once each."""
    transport, client = make_transport([])
    transport.close()
    assert client.channel.closed is True
    assert client.closed is True
    assert not transport._is_open
    transport.close()  # idempotent
