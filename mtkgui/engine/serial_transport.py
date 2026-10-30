# -*- coding: utf-8 -*-
"""Hardened serial transport helpers (M46, channel layer).

The console channel is shared with the DUT's own printing: a command
sent while the DUT is streaming a boot log gets shattered, and a slow
shell drops characters.  These helpers make every console write
deterministic WITHOUT changing what a command means:

* **quiet window** - wait until the channel has been silent for N ms
  before the first character is written;
* **throttle** - configurable inter-character delay (default ~5 ms);
* **marker framing** - an ``echo <unique marker>`` line delimits the
  command output, so expected text is matched INSIDE the frame and
  interleaved console output cannot fake or break the match;
* **echo verification + retry** - the sent line must come back; on a
  corrupted echo the send is retried (max 3) and then fails EXPLICITLY.

The module is pure: it drives an injected channel (``read_lines`` /
``write``) and takes ``sleep`` as a parameter, so it is headless-testable.
"""
from __future__ import annotations

import re
import time

#: default silence required before a command is written (ms)
DEFAULT_QUIET_MS = 200
#: default inter-character delay (ms) so a slow shell keeps up
DEFAULT_CHAR_DELAY_MS = 5
#: default number of send attempts before an explicit failure
DEFAULT_MAX_RETRIES = 3

#: absolute upper bound for one quiet-window wait (s)
_MAX_QUIET_WAIT_S = 3.0
#: polling granularity of the blocking loops (s)
_POLL_S = 0.02

_WS_RE = re.compile(r"\s+")


class TransportError(RuntimeError):
    """A console write could not be verified (explicitly, never silent)."""


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", str(text or "")).strip()


def frame_marker(seq: int) -> str:
    """Unique marker delimitimg one command's output frame."""
    return f"@@MTK_FRAME_{int(seq)}@@"


def write_throttled(channel, text: str, char_delay_ms: int = 0,
                    sleep=time.sleep) -> None:
    """Write ``text`` with an inter-character delay (0 = one call)."""
    if char_delay_ms and char_delay_ms > 0 and isinstance(text, str):
        delay = float(char_delay_ms) / 1000.0
        for ch in text:
            channel.write(ch)
            if delay:
                sleep(delay)
        return
    channel.write(text)


def wait_quiet(channel, quiet_ms: int = DEFAULT_QUIET_MS,
               max_wait_s: float = _MAX_QUIET_WAIT_S, sleep=time.sleep,
               now=time.monotonic) -> bool:
    """Wait until no line arrived for ``quiet_ms``.

    Returns True when the channel went quiet, False when the bounded
    wait expired (the caller may still send - the DUT is just chatty).
    A channel that never yields lines returns immediately.
    """
    quiet_s = max(quiet_ms, 0) / 1000.0
    deadline = now() + max(max_wait_s, quiet_s)
    quiet_deadline = now() + quiet_s
    while True:
        try:
            got = channel.read_lines(max_lines=200, timeout_s=0.0)
        except Exception:                     # noqa: BLE001 - closed channel
            return True
        t = now()
        if got:
            quiet_deadline = t + quiet_s
        elif t >= quiet_deadline:
            return True
        if t >= deadline:
            return False
        sleep(min(_POLL_S, max(deadline - t, 0.001)))


def read_until(channel, predicate, timeout_s: float = 5.0,
               sleep=time.sleep, now=time.monotonic) -> str:
    """Drain lines until ``predicate(buffer)`` is True; joined text."""
    deadline = now() + max(timeout_s, 0.05)
    buf = ""
    while True:
        try:
            got = channel.read_lines(max_lines=200, timeout_s=0.05)
        except Exception:                     # noqa: BLE001 - closed channel
            got = []
        if got:
            joined = "\n".join(str(x) for x in got)
            buf = (buf + "\n" + joined) if buf else joined
            if predicate(buf):
                return buf
        if now() >= deadline:
            return buf
        sleep(_POLL_S)


class HardenedSerial:
    """Quiet window + throttle + echo verify/retry + marker framing."""

    def __init__(self, channel, quiet_ms: int = DEFAULT_QUIET_MS,
                 char_delay_ms: int = DEFAULT_CHAR_DELAY_MS,
                 max_retries: int = DEFAULT_MAX_RETRIES,
                 sleep=time.sleep, now=time.monotonic, log=None) -> None:
        self._channel = channel
        self._quiet_ms = int(quiet_ms)
        self._char_delay_ms = int(char_delay_ms)
        self._max_retries = max(1, int(max_retries))
        self._sleep = sleep
        self._now = now
        self._seq = 0
        self.attempts = 0
        self._log = log

    def _read(self, timeout_s: float) -> str:
        return read_until(self._channel, lambda _buf: False,
                          timeout_s=timeout_s, sleep=self._sleep,
                          now=self._now)

    def send(self, command: str, timeout_s: float = 5.0) -> str:
        """Send one command; returns the output INSIDE the marker frame.

        Raises :class:`TransportError` when the echo cannot be verified
        after ``max_retries`` attempts (explicit, never silent).
        Injected channel faults (ChannelClosed) count as a failed attempt.
        """
        want = _normalize(command)
        last = ""
        for _attempt in range(self._max_retries):
            self.attempts += 1
            wait_quiet(self._channel, self._quiet_ms, sleep=self._sleep,
                       now=self._now)
            try:
                write_throttled(self._channel, command + "\n",
                                self._char_delay_ms, sleep=self._sleep)
                echo = read_until(
                    self._channel,
                    lambda buf, w=want: _normalize(buf).find(w[:24]) >= 0,
                    timeout_s=timeout_s, sleep=self._sleep, now=self._now)
            except Exception as exc:          # noqa: BLE001 - fault
                last = str(exc)
                continue
            if _normalize(echo).find(want[:24]) >= 0:
                self._seq += 1
                marker = frame_marker(self._seq)
                try:
                    self._channel.write(f"echo {marker}\n")
                except Exception as exc:          # noqa: BLE001 - fault
                    last = str(exc)
                    continue
                body = read_until(
                    self._channel, lambda buf, m=marker: m in buf,
                    timeout_s=timeout_s, sleep=self._sleep, now=self._now)
                if marker in body:
                    head = body.split(marker, 1)[0]
                    if self._log is not None:
                        self._log(f"serial send ok ({_normalize(command)[:40]})")
                    return head
                last = "marker frame missing"
            else:
                last = "echo not verified"
            if self._log is not None:
                self._log(f"serial send retry ({last})")
        raise TransportError(
            f"command echo not verified after {self._max_retries} "
            f"attempts: {command[:48]!r} ({last})")


def apply_send_hardening(channel, text: str,
                         quiet_ms: int = DEFAULT_QUIET_MS,
                         char_delay_ms: int = DEFAULT_CHAR_DELAY_MS,
                         sleep=time.sleep, now=time.monotonic) -> None:
    """Quiet-window + throttle for a plain console write.

    Virtual / in-memory channels are left untouched (they are the unit
    test + Virtual-mode transports and have no timing model)."""
    if getattr(channel, "kind", "") == "virtual":
        channel.write(text)
        return
    wait_quiet(channel, quiet_ms, sleep=sleep, now=now)
    write_throttled(channel, text, char_delay_ms, sleep=sleep)
