# -*- coding: utf-8 -*-
"""FCT channel abstraction (B4 design §1.1): one protocol, four
adapters.  A step never knows which transport it uses.

Adapters:

* :class:`VirtualFctChannel` - in-memory queue with INJECTABLE output
  and faults (Virtual mode + all unit tests);
* :class:`SubprocessFctChannel` - one-shot host CLI command (stdout /
  stderr captured line-wise, exit code exposed);
* :class:`BoundConsoleChannel` - wraps an EXISTING console channel
  worker (serial via pyserial / SSH via paramiko) by its multi-console
  key — no new transport code.

RED LINE note: no adapter here performs message JUDGING (that is
`fct_exec.judge_keywords`) and none opens hardware on import.
"""
from __future__ import annotations

import subprocess
import time


class ChannelClosed(RuntimeError):
    """The channel cannot deliver / capture anymore."""


class VirtualFctChannel:
    """In-memory channel: tests / Virtual mode inject scripted lines
    and faults; `read_lines` drains what arrived so far."""

    kind = "virtual"

    def __init__(self) -> None:
        self._lines: list = []
        self._fault: str = ""          # "" | "no_response" | "error"
        self._closed = False
        self.written: list = []        # test evidence

    # -- test/Virtual injection hooks --------------------------------
    def inject_output(self, lines) -> None:
        """Queue scripted output lines (str or list[str])."""
        if isinstance(lines, str):
            lines = [lines]
        self._lines.extend(str(line) for line in lines)

    def inject_fault(self, fault: str) -> None:
        """Simulate a channel fault: no_response / error."""
        self._fault = fault

    # -- FctChannel protocol ------------------------------------------
    def read_lines(self, max_lines: int = 100,
                   timeout_s: float = 0.0) -> list:
        if self._closed:
            raise ChannelClosed("virtual channel closed")
        if self._fault == "error":
            self._fault = ""
            raise ChannelClosed("virtual channel error (injected)")
        if self._fault == "no_response":
            return []                   # silence: nothing arrives
        got = self._lines[:max(1, max_lines)]
        del self._lines[:len(got)]
        return got

    def write(self, data: str) -> None:
        if self._closed:
            raise ChannelClosed("virtual channel closed")
        self.written.append(data)

    def close(self) -> None:
        self._closed = True


class SubprocessResult:
    """Outcome of one host CLI command (CLI_RUN joint judgement)."""

    def __init__(self, exit_code: int, lines: list) -> None:
        self.exit_code = exit_code
        self.lines = lines


def run_subprocess(command: str, timeout_s: float,
                   cwd: str = "") -> SubprocessResult:
    """One-shot host CLI command (B4 §4): stdout+stderr merged,
    line-split; never raises on non-zero exit - the exit code is part
    of the result (joint judgement in fct_exec)."""
    proc = subprocess.Popen(
        command, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace",
        cwd=cwd or None)
    lines: list = []
    deadline = time.monotonic() + max(timeout_s, 0.1)
    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        if line:
            lines.append(line.rstrip("\r\n"))
        elif proc.poll() is not None:
            break
        elif time.monotonic() > deadline:
            proc.kill()
            lines.append("[fct] subprocess timeout")
            break
    if proc.poll() is None:             # drain after natural exit
        for line in proc.stdout:
            lines.append(line.rstrip("\r\n"))
    proc.wait()
    return SubprocessResult(proc.returncode if proc.returncode is not None
                            else -1, lines)


class SubprocessFctChannel:
    """Host CLI channel: `write` runs the command, `read_lines` yields
    its captured output (one-shot per command)."""

    kind = "subprocess"

    def __init__(self, timeout_s: float = 30.0, cwd: str = "") -> None:
        self._timeout = timeout_s
        self._cwd = cwd
        self._result: SubprocessResult | None = None

    def write(self, data: str) -> None:
        """`data` is the command; runs it synchronously."""
        self._result = run_subprocess(data, self._timeout, self._cwd)

    def read_lines(self, max_lines: int = 100,
                   timeout_s: float = 0.0) -> list:
        if self._result is None:
            return []
        got = self._result.lines[:max(1, max_lines)]
        del self._result.lines[:len(got)]
        return got

    @property
    def exit_code(self) -> int:
        return self._result.exit_code if self._result else -1

    def close(self) -> None:
        self._result = None


class BoundConsoleChannel:
    """Binds an EXISTING multi-console channel worker (serial pyserial
    or SSH paramiko) by key - no new transport code (B4 §1.1)."""

    kind = "console"

    def __init__(self, worker) -> None:
        """`worker` = the console channel worker exposing the B2
        console interface: `send(data)`, `pop_lines()` (or read buffer)
        and `connected`."""
        self._worker = worker

    def read_lines(self, max_lines: int = 100,
                   timeout_s: float = 0.0) -> list:
        pop = getattr(self._worker, "pop_lines", None)
        if callable(pop):
            return [str(x) for x in pop(max_lines)]
        buf = getattr(self._worker, "read_buffer_snapshot", None)
        if callable(buf):
            return [str(x) for x in buf(max_lines)]
        return []

    def write(self, data: str) -> None:
        self._worker.send(data)

    def close(self) -> None:
        pass                            # the console owns the transport


# ---------------------------------------------------------------------------
# P3-B4 Module A / B: first-class serial + SSH adapters
# ---------------------------------------------------------------------------
class SerialFctChannel:
    """pyserial transport (P3-B4 Module A) with auto-reconnect.

    Config comes from the product YAML (port / baudrate / bytesize /
    parity / stopbits / timeout + reconnect_interval_s).  Reading is
    line-buffered; a dropped device surfaces on the NEXT operation and
    transparently reconnects (`reconnect=True`) or raises
    ChannelClosed (`reconnect=False`).
    """

    kind = "serial"

    def __init__(self, port: str, baudrate: int = 115200,
                 bytesize: int = 8, parity: str = "N",
                 stopbits: int = 1, timeout: float = 1.0,
                 reconnect: bool = True,
                 reconnect_interval_s: float = 2.0) -> None:
        import serial as pyserial                     # baseline dep
        self._serial_module = pyserial
        self._cfg = dict(port=port, baudrate=int(baudrate),
                         bytesize=int(bytesize), parity=parity,
                         stopbits=int(stopbits), timeout=float(timeout))
        self._reconnect = bool(reconnect)
        self._reconnect_interval = float(reconnect_interval_s)
        self._buf = ""                                # partial line
        self._ser = None
        self._open()

    # ---------------------------------------------------------- internal
    def _open(self) -> None:
        self._ser = self._serial_module.Serial(**self._cfg)

    def _ensure_open(self) -> None:
        if self._ser is not None and self._ser.is_open:
            return
        if not self._reconnect:
            raise ChannelClosed(f"serial {self._cfg['port']} closed")
        deadline = time.monotonic() + max(self._reconnect_interval, 0.5)
        while time.monotonic() < deadline:
            time.sleep(0.1)
            try:
                self._open()
                return
            except Exception:                         # noqa: BLE001
                pass
        raise ChannelClosed(f"serial {self._cfg['port']} reconnect "
                            "timeout")

    # ---------------------------------------------------------- protocol
    def read_lines(self, max_lines: int = 100,
                   timeout_s: float = 0.0) -> list:
        """Drain available bytes, return COMPLETE lines (the trailing
        partial line stays buffered)."""
        self._ensure_open()
        deadline = time.monotonic() + max(timeout_s, 0.0)
        try:
            chunk = self._ser.read(4096)
            if not chunk and timeout_s and time.monotonic() < deadline:
                time.sleep(0.05)
                chunk = self._ser.read(4096)
        except Exception as exc:          # noqa: BLE001 - device gone
            self._ser = None
            raise ChannelClosed(f"serial read failed: {exc}") from exc
        text = chunk.decode(errors="replace")
        self._buf += text
        if "\n" not in self._buf and self._buf:
            return []                     # partial line only
        parts = self._buf.split("\n")
        self._buf = parts.pop()           # trailing partial stays
        lines = [p.rstrip("\r") for p in parts if p.strip()]
        return lines[:max(1, max_lines)]

    def write(self, data: str) -> None:
        self._ensure_open()
        try:
            self._ser.write((data if data.endswith("\n")
                             else data + "\n").encode())
            self._ser.flush()
        except Exception as exc:          # noqa: BLE001 - device gone
            self._ser = None
            raise ChannelClosed(f"serial write failed: {exc}") from exc

    def close(self) -> None:
        if self._ser is not None and self._ser.is_open:
            self._ser.close()
        self._ser = None


class SshFctChannel:
    """paramiko transport (P3-B4 Module B): exec commands with stdout
    / stderr separated and the exit code captured; the password comes
    from the credential layer (D4-A keyring, env fallback) - NEVER
    from the YAML."""

    kind = "ssh"

    def __init__(self, host: str, username: str, credential_ref: str,
                 port: int = 22, timeout: float = 10.0,
                 connect_timeout: float = 10.0,
                 remote_dir: str = "") -> None:
        import paramiko                                # baseline dep
        self._paramiko = paramiko
        self._host, self._port = host, int(port)
        self._username = username
        self._timeout = float(timeout)
        self._connect_timeout = float(connect_timeout)
        # default DUT target directory for SFTP uploads (P3-B4 addendum:
        # e.g. "/tmp/" or "/home/root/"); empty = cwd of the login user
        self._remote_dir = remote_dir.rstrip("/") if remote_dir else ""
        self._client = None
        self._sftp = None
        self._pending = None
        self._auth(credential_ref)

    def _auth(self, credential_ref: str) -> None:
        from .credentials import CredentialUnavailable, get_credential
        self._client = self._paramiko.SSHClient()
        self._client.set_missing_host_key_policy(
            self._paramiko.AutoAddPolicy())   # lab station, known host
        password, warning = "", ""
        try:
            password, warning = get_credential(credential_ref)
        except CredentialUnavailable:
            pass                              # fall through to agent/key
        kwargs: dict = dict(hostname=self._host, port=self._port,
                            username=self._username,
                            timeout=self._connect_timeout,
                            allow_agent=True, look_for_keys=True)
        if password:
            kwargs["password"] = password
        try:
            self._client.connect(**kwargs)
        except Exception as exc:              # noqa: BLE001 - auth/net
            self._client = None
            raise ChannelClosed(f"ssh connect {self._host} failed: "
                                f"{exc}"
                                + (f" [{warning}]" if warning else "")
                                ) from exc

    def _ensure_open(self) -> None:
        if self._client is None:
            raise ChannelClosed("ssh client closed")

    def read_lines(self, max_lines: int = 100,
                   timeout_s: float = 0.0) -> list:
        """SSH is command/response: `write` stores the result, this
        drains the stored output."""
        self._ensure_open()
        if self._pending is None:
            return []
        got = self._pending[:max(1, max_lines)]
        del self._pending[:len(got)]
        return got

    def write(self, data: str) -> None:
        """Execute one command; captures stdout+stderr (stderr lines
        are prefixed '[stderr]') and the exit code ('[exit] N')."""
        self._ensure_open()
        _stdin, stdout, stderr = self._client.exec_command(
            data, timeout=self._timeout)
        out = [line.rstrip("\r\n") for line in stdout]
        err = [f"[stderr] {line.rstrip(chr(13) + chr(10))}"
               for line in stderr]
        code = stdout.channel.recv_exit_status()
        self._pending = out + err + [f"[exit] {code}"]

    # ------------------------------------------------ SFTP file transfer
    # P3-B4 addendum: file DEPLOYMENT on top of the console channel.
    # Typical flow: connect -> put_file(script/bin) -> write("sh
    # /tmp/load_drivers.sh") -> read_lines() polls for the result.
    # Credentials stay in the credential layer - SFTP reuses the
    # authenticated SSH transport, nothing extra is stored.
    def _ensure_sftp(self):
        self._ensure_open()
        if self._sftp is None:
            self._sftp = self._client.open_sftp()
        return self._sftp

    def put_file(self, local_path: str, remote_path: str = "") -> str:
        """SFTP upload of one Host PC local file (shell script / bin /
        app package) to the DUT.

        `remote_path` empty -> ``remote_dir``/basename(local_path);
        `remote_dir` also empty -> the login user's cwd.  Returns the
        remote path used; an event line lands in the read buffer so
        the FCT judge / EventLog can see the transfer."""
        import os
        target = remote_path or (
            f"{self._remote_dir}/{os.path.basename(local_path)}"
            if self._remote_dir else os.path.basename(local_path))
        if (os.path.exists(local_path)
                and os.path.realpath(local_path) == os.path.realpath(target)):
            # guard: paramiko opens the local file for reading, then the
            # remote handle for writing - on the same file (loopback sshd,
            # same-path collision) the remote open truncates the source
            raise ChannelClosed(
                f"sftp put: local and remote path are the same file "
                f"({target}); choose a different remote_path")
        sftp = self._ensure_sftp()
        sftp.put(local_path, target)
        size = os.path.getsize(local_path)
        self._pending = [f"[sftp] put {local_path} -> {target} "
                         f"({size} bytes)"]
        return target

    def get_file(self, remote_path: str, local_path: str) -> str:
        """SFTP download from the DUT (read-back verification)."""
        self._ensure_sftp().get(remote_path, local_path)
        return local_path

    def close(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:                 # noqa: BLE001 - best effort
                pass
            self._sftp = None
        if self._client is not None:
            self._client.close()
        self._client = None
        self._pending = None
