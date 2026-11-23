# -*- coding: utf-8 -*-
"""M112: serial push confirms command completion with a computed marker
(never with a shell prompt that a previous command printed)."""
from __future__ import annotations

import hashlib
import re

from mtkgui.engine.serial_push import (
    DEFAULT_PROMPT,
    _send_wait,
    push_file,
)

#: the marker suffix ``_send_wait`` appends to every non-empty command
_MARKER = re.compile(r"^(.+); echo \$\(\((\d+)\+(\d+)\)\)$")


class _WireChannel:
    """Serial console double: emulates the WIRE, not the code internals.

    A marker write gets the command's own output, then the computed sum,
    then the prompt.  Delayed responses arrive only after two reads, and
    the echo-ON case replays the literal command line before the sum.
    """

    def __init__(self, md5: str = "") -> None:
        self.md5 = md5
        self.writes: list[str] = []
        self.pending: list[str] = []
        self.stale_prompts_seen = 0
        self._delayed: list[str] = []
        self._delayed_reads = 0

    def write(self, data: str) -> None:
        self.writes.append(data)
        if data == "\n":
            self.pending.append("root@done:~# ")
            return
        if data.endswith("PUSH_EOF\n"):
            # heredoc still in continuation mode: stale prompt + "> >"
            self.pending.extend(["root@stale:~# ", "> > "])
            return
        line = data.rstrip("\n")
        match = _MARKER.fullmatch(line)
        if match:
            self._queue(match.group(1), int(match.group(2)),
                        int(match.group(3)), line)
            return
        # plain command (heredoc open, stty, ...): only the echo returns
        self.pending.append(line)

    def _queue(self, command: str, a: int, b: int, literal: str) -> None:
        marker = str(a + b)
        if "md5sum" in command:
            self.pending.append(f"{self.md5}  /root/remote")
            self.pending.append(marker)
            self.pending.append("root@done:~# ")
        elif command == "true":
            # close: stale prompt / continuation, sum only after two reads
            self._delay(["root@stale:~# ", "> > "], marker)
        elif command == "echo echo-on":
            # tty echo ON: the literal line arrives before the real sum
            self._delay([literal], marker)
        else:
            self.pending.append(marker)
            self.pending.append("root@done:~# ")

    def _delay(self, lines: list[str], marker: str) -> None:
        self.pending.extend(lines)
        self._delayed = [marker, "root@done:~# "]
        self._delayed_reads = 2

    def read_lines(self, max_lines=200, timeout_s=0.0) -> list[str]:
        out, self.pending = self.pending[:max_lines], self.pending[max_lines:]
        self.stale_prompts_seen += sum(
            1 for line in out if line == "root@stale:~# ")
        if self._delayed:
            self._delayed_reads -= 1
            if self._delayed_reads <= 0:
                self.pending.extend(self._delayed)
                self._delayed = []
        return out


def _sum_of_last_write(channel) -> tuple[int, int]:
    match = _MARKER.fullmatch(channel.writes[-1].rstrip("\n"))
    assert match is not None, channel.writes[-1]
    return int(match.group(2)), int(match.group(3))


def test_heredoc_close_waits_for_marker_not_stale_prompt(tmp_path):
    source = tmp_path / "asset.bin"
    data = b"hello serial push\n"
    source.write_bytes(data)
    channel = _WireChannel(hashlib.md5(data).hexdigest())
    result = push_file(channel, str(source), "/root/remote")
    assert result["md5"] == hashlib.md5(data).hexdigest()
    decode = "base64 -d /root/.push.b64 > /root/remote; "
    decode_at = next(i for i, write in enumerate(channel.writes)
                     if write.startswith(decode))
    close_at = next(i for i, write in enumerate(channel.writes)
                    if write.startswith("true; echo $(("))
    assert decode_at > close_at
    # the close wait really saw and ignored the stale prompt / "> >"
    assert channel.stale_prompts_seen >= 1


def test_send_wait_ignores_prompt_buffered_before_command():
    channel = _WireChannel()
    channel.pending.append("root@stale:~# ")     # from a previous command
    text = _send_wait(channel, "echo hi", DEFAULT_PROMPT, 0.5,
                      "pre-buffered prompt")
    a, b = _sum_of_last_write(channel)
    assert "root@stale" not in text
    assert str(a + b) in text
    assert "root@done" in text


def test_tty_echo_of_command_does_not_satisfy_marker():
    channel = _WireChannel()
    text = _send_wait(channel, "echo echo-on", DEFAULT_PROMPT, 0.6,
                      "echo on")
    a, b = _sum_of_last_write(channel)
    literal = f"echo echo-on; echo $(({a}+{b}))"
    assert literal in text          # the tty echoed the command line
    assert str(a + b) in text       # ...but only the sum satisfied the wait
    assert text.index(literal) < text.index(str(a + b))


def test_send_wait_blank_command_still_waits_for_prompt():
    channel = _WireChannel()
    text = _send_wait(channel, "", DEFAULT_PROMPT, 0.5, "blank line")
    assert "root@done" in text
    assert channel.writes == ["\n"]      # no marker suffix on a blank line
