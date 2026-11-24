# -*- coding: utf-8 -*-
"""M112: serial push confirms command completion with a computed marker
(never with a shell prompt that a previous command printed)."""
from __future__ import annotations

import base64
import hashlib
import re

import pytest

from mtkgui.engine.serial_push import (
    DEFAULT_PROMPT,
    STREAM_DELAY_S,
    PushError,
    _send_wait,
    _stream_delay_s,
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

    def __init__(self, md5: str = "", replies: dict | None = None,
                 size_replies: list | None = None) -> None:
        self.md5 = md5
        #: command prefix -> stderr lines emitted before the marker
        self.replies = dict(replies or {})
        #: scripted `wc -c` answers (consumed first, then the real size)
        self.size_replies = list(size_replies or [])
        self.writes: list[str] = []
        self.pending: list[str] = []
        self.stale_prompts_seen = 0
        self._in_heredoc = False
        self.staged_size = 0
        self._delayed: list[str] = []
        self._delayed_reads = 0

    def write(self, data: str) -> None:
        self.writes.append(data)
        if data == "\n":
            self.pending.append("root@done:~# ")
            return
        if data.startswith("cat > "):
            self._in_heredoc = True
            self.staged_size = 0
            self.pending.append(data.rstrip("\n"))
            return
        if self._in_heredoc:
            if data.endswith("PUSH_EOF\n"):
                self._in_heredoc = False
                self.staged_size += 1        # newline before the tag
                # heredoc still in continuation mode: stale prompt + "> >"
                self.pending.extend(["root@stale:~# ", "> > "])
            else:
                self.staged_size += len(data)
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
        if command.startswith("wc -c"):
            size = (self.size_replies.pop(0) if self.size_replies
                    else self.staged_size)
            self.pending.append(str(size))
            self.pending.append(marker)
            self.pending.append("root@done:~# ")
            return
        for prefix, lines in self.replies.items():
            if command.startswith(prefix):
                self.pending.extend(lines)
                self.pending.append(marker)
                self.pending.append("root@done:~# ")
                return
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


# --------------------------------------- m113: remote parent dir + decode errors
def _source(tmp_path, name: str = "load_rf_drivers.sh"):
    source = tmp_path / name
    data = b"#!/bin/sh\necho ok\n"
    source.write_bytes(data)
    return source, data


def test_push_file_creates_remote_parent_dir(tmp_path):
    source, data = _source(tmp_path)
    channel = _WireChannel(hashlib.md5(data).hexdigest())
    push_file(channel, str(source),
              "/root/fct_assets/drivers/load_rf_drivers.sh")
    mkdir_at = next(i for i, write in enumerate(channel.writes)
                    if write.startswith("mkdir -p /root/fct_assets/drivers"))
    decode_at = next(i for i, write in enumerate(channel.writes)
                     if write.startswith("base64 -d"))
    assert mkdir_at < decode_at


def test_push_file_skips_mkdir_for_flat_remote(tmp_path):
    source, data = _source(tmp_path, "fat.log")
    channel = _WireChannel(hashlib.md5(data).hexdigest())
    # parent is "/" -> no `mkdir -p /`
    push_file(channel, str(source), "/fat.log")
    assert not any("mkdir -p" in write for write in channel.writes)


def test_push_file_reports_decode_error_not_md5_parse(tmp_path):
    source, data = _source(tmp_path)
    channel = _WireChannel(hashlib.md5(data).hexdigest(), replies={
        "base64 -d": ["-sh: /root/fct_assets/drivers/load_rf_drivers.sh: "
                      "No such file or directory"]})
    with pytest.raises(PushError,
                       match="decode failed for load_rf_drivers.sh") as exc:
        push_file(channel, str(source),
                  "/root/fct_assets/drivers/load_rf_drivers.sh")
    assert "cannot parse md5sum" not in str(exc.value)


def test_push_file_reports_mkdir_error(tmp_path):
    source, data = _source(tmp_path)
    channel = _WireChannel(hashlib.md5(data).hexdigest(), replies={
        "mkdir -p /root/fct_assets": [
            "mkdir: cannot create directory '/root/fct_assets': "
            "Read-only file system"]})
    with pytest.raises(PushError, match="remote mkdir failed"):
        push_file(channel, str(source),
                  "/root/fct_assets/drivers/load_rf_drivers.sh")


# ------------------------ m115-B: staging size verify + restream escalation
def test_stream_delay_scales_with_attempt():
    assert STREAM_DELAY_S == 0.05
    assert _stream_delay_s() == STREAM_DELAY_S
    assert _stream_delay_s(2.0) == pytest.approx(0.1)
    assert _stream_delay_s(4.0) == pytest.approx(0.2)
    assert _stream_delay_s(0.5) == STREAM_DELAY_S      # clamped to 1x


def test_push_file_checks_staging_size_before_decode(tmp_path):
    source, data = _source(tmp_path)
    channel = _WireChannel(hashlib.md5(data).hexdigest())
    push_file(channel, str(source), "/fat.log")
    wc_at = next(i for i, write in enumerate(channel.writes)
                 if write.startswith("wc -c < /root/.push.b64"))
    decode_at = next(i for i, write in enumerate(channel.writes)
                     if write.startswith("base64 -d"))
    assert wc_at < decode_at


def test_push_file_restreams_when_staging_size_short(tmp_path):
    source, data = _source(tmp_path)
    expected = len(base64.b64encode(data)) + 1
    channel = _WireChannel(hashlib.md5(data).hexdigest(),
                           size_replies=[expected - 3])
    result = push_file(channel, str(source), "/fat.log")
    assert result["md5"] == hashlib.md5(data).hexdigest()
    assert sum(1 for w in channel.writes if w.startswith("cat > ")) == 2
    assert sum(1 for w in channel.writes if w.startswith("wc -c")) == 2


def test_push_file_raises_when_staging_size_never_matches(tmp_path):
    source, data = _source(tmp_path)
    channel = _WireChannel(hashlib.md5(data).hexdigest(),
                           size_replies=[1, 2, 3])
    with pytest.raises(PushError, match="staging size mismatch for"):
        push_file(channel, str(source), "/fat.log")
    assert sum(1 for w in channel.writes if w.startswith("wc -c")) == 3
    assert not any(w.startswith("base64 -d") for w in channel.writes)


def test_push_file_single_mismatch_still_verifies_md5(tmp_path):
    source, data = _source(tmp_path)
    channel = _WireChannel("0" * 32, size_replies=[1])
    with pytest.raises(PushError, match="checksum mismatch"):
        push_file(channel, str(source), "/fat.log")
    assert any(w.startswith("md5sum") for w in channel.writes)
