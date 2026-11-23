# -*- coding: utf-8 -*-
"""M111: serial push confirms the heredoc close via the PUSH_DONE
sentinel and ignores prompts buffered before a command."""
from __future__ import annotations

import hashlib

from mtkgui.engine.serial_push import (
    DEFAULT_PROMPT,
    _send_wait,
    push_file,
)


class _ScriptedChannel:
    """Serial console double: queues DUT output for read_lines()."""

    def __init__(self, md5: str = "") -> None:
        self.md5 = md5
        self.writes: list[str] = []
        self.pending: list[str] = []
        self.decode_before_sentinel = False
        self.stale_prompts_seen = 0
        self._sentinel_written = False
        self._sentinel_reads: int | None = None
        self._prompt_reads: int | None = None

    def write(self, data: str) -> None:
        self.writes.append(data)
        if data == "echo PUSH_DONE\n":
            self._sentinel_written = True
            # still in continuation mode: these arrive BEFORE the sentinel
            self.pending.extend(["root@stale:~# ", "> > "])
            self._sentinel_reads = 2
        elif data.endswith("PUSH_EOF\n"):
            # the heredoc closed, but a stale prompt is still on screen
            self.pending.extend(["root@stale:~# ", "> > "])
        elif data.startswith("base64 -d"):
            if not self._sentinel_written:
                self.decode_before_sentinel = True
            self.pending.append("root@done:~# ")
        elif data.startswith("md5sum"):
            self.pending.append(f"{self.md5}  /root/remote")
            self.pending.append("root@done:~# ")
        elif data.startswith("echo prompt-test"):
            self._prompt_reads = 2       # the new prompt appears later
        else:
            self.pending.append("root@done:~# ")

    def read_lines(self, max_lines=200, timeout_s=0.0) -> list[str]:
        out, self.pending = self.pending[:max_lines], self.pending[max_lines:]
        self.stale_prompts_seen += sum(
            1 for line in out if line == "root@stale:~# ")
        if self._sentinel_reads is not None:
            self._sentinel_reads -= 1
            if self._sentinel_reads == 0:
                self.pending.append("PUSH_DONE")
                self._sentinel_reads = None
        if self._prompt_reads is not None:
            self._prompt_reads -= 1
            if self._prompt_reads == 0:
                self.pending.append("root@new:~# ")
                self._prompt_reads = None
        return out


def test_heredoc_close_waits_for_sentinel_not_stale_prompt(tmp_path):
    source = tmp_path / "asset.bin"
    source.write_bytes(b"hello serial push\n")
    channel = _ScriptedChannel(hashlib.md5(source.read_bytes()).hexdigest())
    result = push_file(channel, str(source), "/root/remote")
    assert result["md5"] == hashlib.md5(source.read_bytes()).hexdigest()
    decode = "base64 -d /root/.push.b64 > /root/remote\n"
    assert decode in channel.writes
    sentinel_at = channel.writes.index("echo PUSH_DONE\n")
    assert channel.writes.index(decode) > sentinel_at
    assert channel.decode_before_sentinel is False
    # the close wait really saw and ignored the stale prompt / "> >"
    assert channel.stale_prompts_seen >= 1


def test_send_wait_ignores_prompt_buffered_before_command():
    channel = _ScriptedChannel()
    channel.pending.append("root@stale:~# ")     # from a previous command
    text = _send_wait(channel, "echo prompt-test", DEFAULT_PROMPT, 0.5,
                      "prompt test")
    assert "root@new:~#" in text
    assert "root@stale" not in text
