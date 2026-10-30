# -*- coding: utf-8 -*-
"""Serial (console) file transfer: Push to / Pull from the DUT (M46).

Two standard FCT steps use this engine over the SAME serial console the
tests already use (a freshly flashed DUT has no network):

* ``Serial: Push file to DUT``  - Host PC file -> DUT;
* ``Serial: Pull file from DUT`` - DUT file -> Host PC.

Protocol (base64 chunks with marker ACKs - immune to console output
interleaving):

    push:  PUT_CHUNK <seq> <b64>  -> DUT ``ACK <seq>``
           PUT_DONE               -> DUT ``PUT_OK <bytes>``
    pull:  PULL_START <bytes>     -> ``PULL_CHUNK <seq> <b64>``
           ... host ``ACK <seq>`` per chunk ...
           PULL_OK <bytes>

The DUT side is busybox-compatible (``base64 -d`` / ``base64`` / ``cat``
/ ``wc``).  Baud negotiation raises both ends for speed, then BOTH ends
MUST be restored to the console rate; any restore failure raises an
EXPLICIT error (never a silent half-restored console).

The module is pure (injected channel + ``sleep`` / ``now``) so it is
headless-testable.
"""
from __future__ import annotations

import base64
import os

from .serial_transport import read_until

#: baud rates offered by the editor (Tera Term table)
BAUD_CHOICES = (110, 300, 600, 1200, 2400, 4800, 9600, 14400, 19200,
                38400, 57600, 115200, 230400, 460800, 921600)
#: console rate assumed when the row leaves the baud field blank
DEFAULT_CONSOLE_BAUD = 115200
#: base64 characters per protocol chunk (one console line)
CHUNK_B64 = 512
#: staging file on the DUT
STAGING = "/root/.mtk_xfer.b64"
#: per-chunk ACK timeout (s) and overall transfer timeout (s)
_CHUNK_TIMEOUT_S = 10.0
_TRANSFER_TIMEOUT_S = 600.0


class SerialTransferError(RuntimeError):
    """A serial transfer failed (protocol, timeout, baud restore)."""


# ---------------------------------------------------------------------------
# estimate (read-only hint in the editor)
# ---------------------------------------------------------------------------
def estimate_seconds(size_bytes: int, baud: int) -> float:
    """Rough transfer time: size * 10 bits (base64 overhead) / baud,
    plus ~30 % protocol overhead."""
    size = max(0, int(size_bytes or 0))
    rate = max(1, int(baud or 0))
    return (size * 10.0 / rate) * 1.3


def format_duration(seconds: float) -> str:
    """Human readable duration ("<1 s", "12 s", "5 min 20 s")."""
    secs = max(0.0, float(seconds or 0.0))
    if secs < 1.0:
        return "<1 s"
    if secs < 60.0:
        return f"{secs:.0f} s"
    minutes = int(secs // 60)
    rest = int(round(secs - minutes * 60))
    if rest == 60:
        minutes, rest = minutes + 1, 0
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours} h {minutes} min"
    return f"{minutes} min {rest} s" if rest else f"{minutes} min"


def estimate_text(size_bytes: int, baud: int) -> str:
    """The READ-ONLY estimate shown next to the Baudrate field."""
    return format_duration(estimate_seconds(size_bytes, baud))


def dir_size(path: str) -> int:
    """Total bytes of a file or a directory tree (0 when missing)."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            fp = os.path.join(root, name)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _drain(channel, sleep, now, timeout_s: float = 0.4) -> str:
    return read_until(channel, lambda _b: False, timeout_s=timeout_s,
                      sleep=sleep, now=now)


def _wait_token(channel, pattern, timeout_s: float, sleep, now) -> str:
    """Drain until ``pattern`` matches; raise on timeout."""
    out = read_until(channel, lambda buf: pattern.search(buf) is not None,
                     timeout_s=timeout_s, sleep=sleep, now=now)
    if pattern.search(out) is None:
        raise SerialTransferError(
            f"timeout waiting for {pattern.pattern!r}: {out[-160:]!r}")
    return out


def _set_host_baud(channel, baud: int) -> bool:
    setter = getattr(channel, "set_baudrate", None)
    if not callable(setter):
        return False
    return bool(setter(int(baud)))


def _switch_up(channel, baud: int, console_baud: int, log, sleep, now) -> None:
    """Raise BOTH ends to ``baud`` (DUT stty first, then the host port)."""
    if baud <= 0 or baud == console_baud:
        return
    if not callable(getattr(channel, "set_baudrate", None)):
        raise SerialTransferError(
            f"cannot switch to {baud}: the channel does not support "
            "baud control")
    channel.write(f"stty {baud}\n")
    sleep(0.3)
    _drain(channel, sleep, now)
    if not _set_host_baud(channel, baud):
        raise SerialTransferError(
            f"baud switch to {baud} failed on the Host PC port")
    _drain(channel, sleep, now)
    channel.write(f"echo BAUD_OK {baud}\n")
    import re
    _wait_token(channel, re.compile(rf"BAUD_OK {baud}\b"), _CHUNK_TIMEOUT_S,
                sleep, now)
    if log is not None:
        log(f"transfer link raised to {baud}")


def _switch_back(channel, console_baud: int, log, sleep, now) -> None:
    """Restore BOTH ends to the console rate; NEVER fail silently."""
    try:
        channel.write(f"stty {console_baud}\n")
    except Exception as exc:                  # noqa: BLE001 - explicit
        raise SerialTransferError(
            f"baud restore to {console_baud} failed on the DUT: {exc}") \
            from exc
    sleep(0.3)
    _drain(channel, sleep, now)
    if not _set_host_baud(channel, console_baud):
        raise SerialTransferError(
            f"baud restore to {console_baud} failed on the Host PC port")
    _drain(channel, sleep, now)
    import re
    channel.write(f"echo BAUD_OK {console_baud}\n")
    try:
        _wait_token(channel, re.compile(rf"BAUD_OK {console_baud}\b"),
                    _CHUNK_TIMEOUT_S, sleep, now)
    except SerialTransferError as exc:
        raise SerialTransferError(
            f"baud restore to {console_baud} not confirmed: {exc}") from exc
    if log is not None:
        log(f"transfer link restored to {console_baud}")


def _split_b64(data: bytes) -> list:
    b64 = base64.b64encode(data).decode()
    return [b64[i:i + CHUNK_B64] for i in range(0, len(b64), CHUNK_B64)]


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------
def push_file(channel, local_path: str, remote_path: str, *,
              baud: int = 0, console_baud: int = DEFAULT_CONSOLE_BAUD,
              log=None, progress=None, sleep=None, now=None) -> dict:
    """Push ONE local file to the DUT over the serial console."""
    import re
    import time
    sleep = sleep or time.sleep
    now = now or time.monotonic
    if not os.path.isfile(local_path):
        raise SerialTransferError(f"local file not found: {local_path}")
    data = open(local_path, "rb").read()
    chunks = _split_b64(data)
    remote = str(remote_path or "").strip()
    if not remote:
        raise SerialTransferError("push: no remote target configured")
    raised = baud > 0 and baud != console_baud
    if raised:
        _switch_up(channel, baud, console_baud, log, sleep, now)
    try:
        if log is not None:
            log(f"serial push {os.path.basename(local_path)}: "
                f"{os.path.getsize(local_path)} bytes -> {remote}")
        receiver = (
            f"rm -f {STAGING}; while read -r tag seq dat; do case \"$tag\" in "
            f"PUT_CHUNK) printf '%s' \"$dat\" >> {STAGING}; echo \"ACK $seq\";; "
            f"PUT_DONE) base64 -d {STAGING} > {remote}; "
            f"echo \"PUT_OK $(wc -c < {remote})\"; break;; esac; done")
        channel.write(receiver + "\n")
        _drain(channel, sleep, now)
        for i, chunk in enumerate(chunks, 1):
            channel.write(f"PUT_CHUNK {i} {chunk}\n")
            _wait_token(channel, re.compile(rf"\bACK {i}\b"), _CHUNK_TIMEOUT_S,
                        sleep, now)
            if progress is not None and chunks:
                progress(min(len(data), int(len(data) * i / len(chunks))),
                         len(data), os.path.basename(local_path))
        channel.write("PUT_DONE\n")
        out = _wait_token(channel, re.compile(r"PUT_OK (\d+)"),
                          _TRANSFER_TIMEOUT_S, sleep, now)
        m = re.search(r"PUT_OK (\d+)", out)
        got = int(m.group(1)) if m else -1
        if got != len(data):
            raise SerialTransferError(
                f"push size mismatch: local {len(data)} bytes, DUT {got}")
    finally:
        if raised:
            _switch_back(channel, console_baud, log, sleep, now)
    if log is not None:
        log(f"serial push OK ({len(data)} bytes)")
    return {"remote": remote, "bytes": len(data)}


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------
def pull_file(channel, remote_path: str, local_path: str, *,
              baud: int = 0, console_baud: int = DEFAULT_CONSOLE_BAUD,
              log=None, progress=None, sleep=None, now=None) -> dict:
    """Pull ONE DUT file back to the Host PC over the serial console."""
    import re
    import time
    sleep = sleep or time.sleep
    now = now or time.monotonic
    remote = str(remote_path or "").strip()
    if not remote:
        raise SerialTransferError("pull: no remote source configured")
    local = str(local_path or "").strip()
    if not local:
        raise SerialTransferError("pull: no local destination configured")
    raised = baud > 0 and baud != console_baud
    if raised:
        _switch_up(channel, baud, console_baud, log, sleep, now)
    try:
        if log is not None:
            log(f"serial pull {remote} -> {local}")
        script = (
            f"S=$(wc -c < {remote}); echo \"PULL_START $S\"; i=0; "
            f"base64 {remote} | fold -w {CHUNK_B64} | while read -r l; do "
            f"i=$((i+1)); echo \"PULL_CHUNK $i $l\"; read -r ack; done; "
            f"echo \"PULL_OK $S\"")
        channel.write(script + "\n")
        collected: list = []
        total = -1
        deadline = now() + _TRANSFER_TIMEOUT_S
        buf = ""
        while True:
            got = channel.read_lines(max_lines=200, timeout_s=0.05)
            if got:
                joined = "\n".join(str(x) for x in got)
                buf = (buf + "\n" + joined) if buf else joined
            progressed = True
            while progressed:
                progressed = False
                m_start = re.search(r"PULL_START (\d+)", buf)
                if m_start and total < 0:
                    total = int(m_start.group(1))
                    buf = buf[m_start.end():]
                    progressed = True
                m_chunk = re.search(r"PULL_CHUNK (\d+) ([A-Za-z0-9+/=]+)", buf)
                if m_chunk:
                    seq = int(m_chunk.group(1))
                    collected.append(m_chunk.group(2))
                    buf = buf[m_chunk.end():]
                    channel.write(f"ACK {seq}\n")
                    if progress is not None and total > 0:
                        done = min(total, len("".join(collected)) * 6 // 8)
                        progress(done, total, os.path.basename(remote))
                    progressed = True
                m_ok = re.search(r"PULL_OK (\d+)", buf)
                if m_ok:
                    got_total = int(m_ok.group(1))
                    if total < 0:
                        total = got_total
                    data = base64.b64decode("".join(collected) or "")
                    parent = os.path.dirname(os.path.abspath(local))
                    os.makedirs(parent, exist_ok=True)
                    with open(local, "wb") as fh:
                        fh.write(data)
                    if len(data) != total:
                        raise SerialTransferError(
                            f"pull size mismatch: DUT {total} bytes, "
                            f"received {len(data)}")
                    if log is not None:
                        log(f"serial pull OK ({len(data)} bytes -> {local})")
                    return {"remote": remote, "local": local,
                            "bytes": len(data)}
            if now() >= deadline:
                raise SerialTransferError(
                    f"pull timeout: {remote} (received {len(collected)} "
                    "chunk(s))")
            sleep(0.02)
    finally:
        if raised:
            _switch_back(channel, console_baud, log, sleep, now)


# ---------------------------------------------------------------------------
# step-level entry (direction-aware)
# ---------------------------------------------------------------------------
def transfer(channel, direction: str, local_path: str, remote_path: str,
             **kwargs) -> dict:
    """``direction`` = "push" | "pull"."""
    if str(direction).lower() == "push":
        return push_file(channel, local_path, remote_path, **kwargs)
    if str(direction).lower() == "pull":
        return pull_file(channel, remote_path, local_path, **kwargs)
    raise SerialTransferError(f"unknown transfer direction {direction!r}")
