# -*- coding: utf-8 -*-
"""Paramiko SSH instrument transport.

Message/response link to instruments reachable through an SSH shell
(e.g. LXI gateways or instruments behind a remote login).  Mirrors the
connection conventions of :mod:`mtkgui.ssh_worker`:

* ``paramiko`` is imported lazily so the package imports even when it
  is not installed,
* ``AutoAddPolicy`` with ``allow_agent=False`` / ``look_for_keys=False``
  (station environment, explicit credentials from YAML),
* one interactive shell channel via ``invoke_shell()``; ``write()``
  sends a command line, ``query()`` reads the reply line framed by the
  configured terminator.

The transport maps every failure to the shared error types of
:mod:`mtkgui.drivers.errors`; no paramiko exception ever leaks to the
drivers.
"""

from __future__ import annotations

import logging
import threading

from mtkgui.drivers.base import Transport
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentIOError,
    InstrumentTimeoutError,
)

_LOG = logging.getLogger("mtkgui.drivers.ssh")

_DEFAULT_PORT = 22
_DEFAULT_TERMINATOR = "\n"
_DEFAULT_TIMEOUT_S = 8.0


def _parse_address(address: str) -> tuple[str, int]:
    """Split an ``host[:port]`` address string.

    Args:
        address: Address from the YAML equipment section, e.g.
                 ``"192.168.1.10"`` or ``"gateway.lan:2222"``.

    Returns:
        ``(host, port)`` tuple with the default port applied.

    Raises:
        InstrumentConfigError: Empty host or non-numeric port.
    """
    address = (address or "").strip()
    if not address:
        raise InstrumentConfigError(
            "SSHTransport.open: empty address")
    host, sep, port_part = address.partition(":")
    host = host.strip()
    if not host:
        raise InstrumentConfigError(
            f"SSHTransport.open: missing host in {address!r}")
    port = _DEFAULT_PORT
    if sep:
        try:
            port = int(port_part.strip())
        except ValueError as exc:
            raise InstrumentConfigError(
                f"SSHTransport.open: bad port in {address!r}") from exc
    return host, port


class SSHTransport(Transport):
    """Interactive-shell SSH transport around a paramiko client.

    Options understood by ``open()``:

    * ``username`` (str, required) - remote login user
    * ``password`` (str, default "") - remote login password
    * ``port`` (int, default 22) - overridden by an address ``host:port``
    * ``terminator`` (str, default "\\n") - line framing
    * ``timeout_s`` (float, default 8.0) - connect AND per-query
      read timeout
    """

    def __init__(self) -> None:
        """Create a closed transport."""
        self._client = None
        self._chan = None
        self._terminator = _DEFAULT_TERMINATOR
        self._timeout_s = _DEFAULT_TIMEOUT_S
        self._write_lock = threading.Lock()
        self._is_open = False

    # -- connection management -------------------------------------------------

    def open(self, address: str, options: dict) -> None:
        """Connect via SSH and open an interactive shell channel.

        Args:
            address: ``host`` or ``host:port`` (from YAML).
            options: See class docstring.  ``username`` is required.

        Raises:
            InstrumentConfigError: Empty address or missing username.
            InstrumentIOError:     paramiko is not installed.
            ConnectionLostError:   Connect or shell setup failed.
        """
        if self._is_open:
            return
        opts = options or {}
        username = str(opts.get("username", "")).strip()
        if not username:
            raise InstrumentConfigError(
                "SSHTransport.open: 'username' option is required "
                "(from config/ YAML)")
        self._timeout_s = float(opts.get("timeout_s", _DEFAULT_TIMEOUT_S))
        self._terminator = str(opts.get("terminator", _DEFAULT_TERMINATOR))
        host, port = _parse_address(address)
        if "port" in opts:
            port = int(opts["port"])
        client, chan = self._connect(
            host, port, username, str(opts.get("password", "")))
        self._client = client
        self._chan = chan
        self._is_open = True
        _LOG.info("SSH transport open: %s@%s:%d", username, host, port)

    def close(self) -> None:
        """Close the shell channel and the SSH client.  Safe to call
        more than once."""
        chan, self._chan = self._chan, None
        client, self._client = self._client, None
        self._is_open = False
        for closer in (chan, client):
            if closer is None:
                continue
            try:
                closer.close()
            except Exception as exc:  # noqa: BLE001 - cleanup must not raise
                _LOG.warning("SSH close warning: %s", exc)

    # -- message exchange ------------------------------------------------------

    def write(self, command: str) -> None:
        """Send one command line to the remote instrument shell.

        Args:
            command: Command string without terminator.

        Raises:
            ConnectionLostError: Transport not open.
            InstrumentIOError:   The shell channel is broken.
        """
        chan = self._require_open()
        payload = (command + self._terminator).encode("utf-8")
        try:
            with self._write_lock:
                chan.sendall(payload)
        except Exception as exc:
            raise InstrumentIOError(
                f"SSHTransport.write failed: {exc}") from exc

    def query(self, command: str) -> str:
        """Send one command and read the reply line.

        Remote shells normally echo the command; the echo line is
        detected and skipped, the first following complete line is
        returned.

        Args:
            command: Command string without terminator.

        Returns:
            The decoded reply line with the terminator stripped.

        Raises:
            ConnectionLostError:    Transport not open.
            InstrumentIOError:      Read failed.
            InstrumentTimeoutError: No reply line within the
                                    configured timeout.
        """
        chan = self._require_open()
        self.write(command)
        line = self._read_line(chan)
        if line.strip() == command.strip():  # shell echo of our command
            line = self._read_line(chan)
        return line

    def identify(self) -> str:
        """Probe helper returning the first shell output line.

        SSH shells have no ``*IDN?`` equivalent at transport level;
        drivers issue their own identification command through
        :meth:`query`.  This convenience reads one pending banner line
        if the remote printed any.

        Returns:
            First pending output line, or "" when none arrived.

        Raises:
            ConnectionLostError: Transport not open.
        """
        chan = self._require_open()
        try:
            return self._read_line(chan)
        except InstrumentTimeoutError:
            return ""

    # -- helpers -----------------------------------------------------------------

    @staticmethod
    def _import_paramiko():
        """Import paramiko lazily (station convention of ssh_worker).

        Returns:
            The ``paramiko`` module.

        Raises:
            InstrumentIOError: paramiko is not installed.
        """
        try:
            import paramiko
        except ImportError as exc:
            raise InstrumentIOError(
                "SSH support unavailable: paramiko is not installed "
                "(pip install paramiko)") from exc
        return paramiko

    def _connect(self, host: str, port: int, username: str,
                 password: str):
        """Connect the SSH client and open the shell channel.

        The paramiko import happens here (deepest lazy point), so a
        mocked ``_connect`` runs without paramiko installed.

        Args:
            host:     Remote host.
            port:     Remote port.
            username: Login user.
            password: Login password.

        Returns:
            ``(client, channel)`` tuple.

        Raises:
            InstrumentIOError:     paramiko is not installed.
            ConnectionLostError:   Connect or shell setup failed.
        """
        paramiko = self._import_paramiko()
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=self._timeout_s,
                allow_agent=False,
                look_for_keys=False,
            )
            chan = client.invoke_shell()
            chan.settimeout(self._timeout_s)
            return client, chan
        except Exception as exc:
            try:
                client.close()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001 - cleanup must not mask the error
                pass
            raise ConnectionLostError(
                f"SSH connect failed to {host}:{port}: {exc}") from exc

    def _read_line(self, chan) -> str:
        """Read one terminator-framed line from the shell channel.

        Args:
            chan: The paramiko shell channel.

        Returns:
            The decoded line without trailing CR/LF.

        Raises:
            InstrumentIOError:      The channel closed unexpectedly.
            InstrumentTimeoutError: No complete line within the
                                    timeout.
        """
        buffer = bytearray()
        terminator = self._terminator.encode("utf-8")
        while not buffer.endswith(terminator):
            try:
                chunk = chan.recv(4096)
            except Exception as exc:
                if isinstance(exc, TimeoutError) or "timed out" in str(exc):
                    raise InstrumentTimeoutError(
                        "SSHTransport.query: no reply within "
                        f"{self._timeout_s}s") from exc
                raise InstrumentIOError(
                    f"SSHTransport read failed: {exc}") from exc
            if not chunk:
                raise InstrumentIOError(
                    "SSHTransport: remote shell closed the connection")
            buffer.extend(chunk)
        return buffer.decode("utf-8", errors="replace").rstrip("\r\n")

    def _require_open(self):
        """Return the open shell channel or raise ConnectionLostError.

        Returns:
            The paramiko shell channel.

        Raises:
            ConnectionLostError: The transport is not open.
        """
        if not self._is_open or self._chan is None:
            raise ConnectionLostError("SSHTransport: not open")
        return self._chan
