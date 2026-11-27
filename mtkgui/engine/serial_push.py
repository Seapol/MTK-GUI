# -*- coding: utf-8 -*-
"""Serial-console file deployment engine (no network, no DUT-side assets).

Production reality: a freshly flashed DUT has NONE of the test assets
(setup shell scripts, the ``frdm_imx93_board_test`` package).  Before the
FCT body can run, the station must provision them over the ONLY channel
guaranteed to exist at that point - the serial console.

Fast protocol (verified on the FRDM-IMX93, console ttyLP0):

1. raise the link to a high baud on BOTH ends (``stty 921600`` on the DUT,
   reconfigure the host serial), then ``stty -echo``;
2. ``cat > /root/.push.b64 <<'PUSH_EOF'``, stream the base64 in paced
   blocks (the host sends slightly slower than the DUT reads, so the tty
   input queue never fills), close with ``PUSH_EOF``;
3. ``base64 -d /root/.push.b64 > <remote>``;
4. ``md5sum`` the remote, compare with the local MD5;
5. for an archive: ``unzip -o -q``;
6. restore the production baud (115200) on both ends.

Measured on FRDM-IMX93: a 1.2 MB zip deploys + verifies + unzips in ~42 s
at 921600 (vs ~10 min at 115200 with per-chunk shell acks).  If the channel
cannot change baud (virtual / an adapter capped at 115200), the engine
falls back to the same heredoc stream at the current baud - slower, but
still correct (MD5-verified).

The engine is pure: it drives an injected channel (read_lines / write /
optional set_baudrate) and reports progress via a callback, so it is
headless-testable and the GUI shows a foreground progress dialog.
"""
from __future__ import annotations

import base64
import hashlib
import os
import random
import re
import time

#: shell prompt (root ``#`` or user ``$``) at end of the buffer (tolerates
#: trailing ANSI color codes)
DEFAULT_PROMPT = re.compile(r"[#\$](\x1b\[[0-9;]*[A-Za-z])*\s*$")
#: high-speed link used for the asset transfer
HIGH_BAUD = 921600
#: production console rate (restored after the transfer)
DEFAULT_BAUD = 115200
#: base64 bytes per streamed block.  Halved from 2048: at 921600 the tty
#: input queue is still overrun when the GUI thread is busy, and a smaller
#: block bounds the damage of a single lost write.
STREAM_BLOCK = 1024
#: inter-block delay (s) for the FIRST attempt.  Measured on the bench: the
#: GUI stream averaged ~36 KB/s with a fixed 0.03 s and still dropped
#: characters, so the first attempt starts slower and the caller escalates.
STREAM_DELAY_S = 0.05
#: escalation ladder: the same file is re-streamed at DELAY * scale while the
#: staging byte count does not match.  Never a fixed retry count of one.
STREAM_SCALE_STEPS = (1.0, 2.0, 4.0)
#: heredoc terminator (must not appear in base64 - it does not)
HEREDOC_TAG = "PUSH_EOF"
STAGING = "/root/.push.b64"


def _stream_delay_s(scale: float = 1.0) -> float:
    """Inter-block delay for one streaming attempt."""
    return STREAM_DELAY_S * max(1.0, float(scale))


class PushError(RuntimeError):
    """A deployment step failed (transport / checksum / missing file)."""


# ---------------------------------------------------------------------------
# low-level tty helpers
# ---------------------------------------------------------------------------
def _pump_read(channel, timeout_s: float) -> str:
    """Drain available lines for ``timeout_s`` (each read pumps the GUI
    when a pump is injected); return the joined text."""
    deadline = time.monotonic() + max(timeout_s, 0.05)
    chunks: list = []
    while time.monotonic() < deadline:
        got = channel.read_lines(max_lines=200, timeout_s=0.1)
        if got:
            chunks.append("\n".join(got))
    return "\n".join(chunks)


def _send_wait(channel, command: str, prompt_re, timeout_s: float,
               tag: str = "") -> str:
    """Write one command, drain until its completion marker appears.

    M112: a prompt printed by command N must never satisfy command N+1,
    with tty echo ON or OFF.  Every non-empty command is suffixed with
    ``; echo $((a+b))`` and the wait stops only at the computed sum: an
    echoed command prints the literal ``$((a+b))``, never the sum.
    """
    # M111: drop bytes already pending - a prompt echoed by a PREVIOUS
    # command must never satisfy THIS command's wait.
    channel.read_lines(max_lines=1000, timeout_s=0.0)
    if not command:
        # a blank line confirms a live prompt (baud switch)
        channel.write("\n")
        deadline = time.monotonic() + max(timeout_s, 0.1)
        seen = ""
        while time.monotonic() < deadline:
            got = channel.read_lines(max_lines=200, timeout_s=0.1)
            if got:
                seen = (seen + "\n" + "\n".join(got)) if seen \
                    else "\n".join(got)
                if prompt_re.search(seen):
                    return seen
        raise PushError(f"timeout waiting for {tag or command[:32]}: "
                        f"{seen[-160:]!r}")
    a = random.randint(10000, 99999)
    b = random.randint(10000, 99999)
    marker = str(a + b)
    # semicolon: the marker prints even when the command itself fails.
    # The wait only accepts the evaluated `echo $((a+b))` sum.
    channel.write(f"{command}; echo $(({a}+{b}))\n")
    deadline = time.monotonic() + max(timeout_s, 0.1)
    seen = ""
    while time.monotonic() < deadline:
        got = channel.read_lines(max_lines=200, timeout_s=0.1)
        if got:
            seen = (seen + "\n" + "\n".join(got)) if seen else "\n".join(got)
            if marker in seen:
                # consume the trailing prompt HERE so the next command
                # cannot match it
                drain_deadline = time.monotonic() + 0.1
                while time.monotonic() < drain_deadline:
                    tail = channel.read_lines(max_lines=200,
                                              timeout_s=0.05)
                    if tail:
                        seen = (seen + "\n" + "\n".join(tail)) if seen \
                            else "\n".join(tail)
                return seen
    raise PushError(f"timeout waiting for {tag or command[:32]}: "
                    f"{seen[-160:]!r}")


#: command stderr markers that mean the remote parent could not be made
MKDIR_ERROR_MARKERS = ("Permission denied", "Read-only file system",
                       "No such file or directory")
#: command stderr markers that mean the decode redirect did not land
DECODE_ERROR_MARKERS = ("No such file or directory", "Permission denied",
                        "Read-only file system", "Is a directory")


def _ensure_remote_parent(channel, remote_path: str, prompt_re,
                          timeout_s: float, tag: str = "") -> None:
    """mkdir -p the remote parent so the decode redirect can land."""
    parent = os.path.dirname(remote_path)
    if not parent or parent == "/":
        return
    out = _send_wait(channel, f"mkdir -p {parent}", prompt_re, timeout_s,
                     tag or "mkdir parent")
    for line in out.splitlines():
        if any(marker in line for marker in MKDIR_ERROR_MARKERS):
            raise PushError(f"remote mkdir failed: {line.strip()!r}")


def _switch_baud(channel, target: int, prompt_re, log) -> bool:
    """Raise/lower the link on the DUT (``stty``) and then on the host.
    Returns True when both ends are confirmed at ``target``."""
    setter = getattr(channel, "set_baudrate", None)
    if not callable(setter):
        return False
    channel.write(f"stty {target}\n")
    time.sleep(0.6)                      # let the DUT settle at the new rate
    _pump_read(channel, 0.2)            # discard transition garbage
    if not setter(target):
        return False
    # confirm the link at the new rate: a blank line yields a prompt
    channel.write("\n")
    try:
        _send_wait(channel, "", prompt_re, 8.0, f"prompt@{target}")
        return True
    except PushError:
        return False


# ---------------------------------------------------------------------------
# one file
# ---------------------------------------------------------------------------
def _stream_heredoc(channel, b64: str, prompt_re, progress, total_bytes: int,
                    name: str, delay_s: float = STREAM_DELAY_S) -> None:
    """Open a quoted heredoc, stream the base64 in paced blocks, close it."""
    channel.write(f"cat > {STAGING} <<'{HEREDOC_TAG}'\n")
    time.sleep(0.4)
    _pump_read(channel, 0.2)
    blocks = [b64[i:i + STREAM_BLOCK]
              for i in range(0, len(b64), STREAM_BLOCK)]
    for i, block in enumerate(blocks):
        channel.write(block)
        time.sleep(delay_s)
        if progress is not None:
            sent_b64 = min(len(b64), (i + 1) * STREAM_BLOCK)
            progress(int(sent_b64 * total_bytes / len(b64)), total_bytes,
                     name)
        # read_lines also pumps the GUI loop (RX must reach the buffer)
        channel.read_lines(max_lines=200, timeout_s=0.0)
    channel.write(f"\n{HEREDOC_TAG}\n")
    # M112: the close is confirmed by a computed marker. If the shell is
    # still in heredoc continuation this line is swallowed as content, no
    # marker appears, and the call raises PushError instead of skipping
    # the file.
    _send_wait(channel, "true", prompt_re, 12.0, "heredoc close")


def push_file(channel, local_path: str, remote_path: str, *,
              log=None, progress=None, prompt_re=DEFAULT_PROMPT,
              command_timeout_s: float = 20.0,
              stream_scale_steps: tuple | None = None) -> dict:
    """Deploy ONE local file over the serial console at the CURRENT baud
    (heredoc streaming, MD5-verified).  Use :func:`push_bundle` for the
    full high-speed multi-file flow.

    Returns {"remote", "bytes", "md5", "elapsed_s"}; raises PushError on a
    missing file, transport timeout or checksum mismatch.
    """
    def _log(m):
        if log is not None:
            log(m)

    if not os.path.isfile(local_path):
        raise PushError(f"local file not found: {local_path}")
    data = open(local_path, "rb").read()
    b64 = base64.b64encode(data).decode()
    name = os.path.basename(local_path)
    _log(f"deploy {name}: {len(data)} bytes -> {remote_path}")
    t0 = time.monotonic()
    _send_wait(channel, f"rm -f {STAGING}", prompt_re, command_timeout_s,
               "rm staging")
    # the asset dir step only creates /root/fct_assets: subdirectories
    # (drivers/…) must exist before the decode redirect can land
    _ensure_remote_parent(channel, remote_path, prompt_re, command_timeout_s)
    # verify the staging bytes after the close marker, before any decode:
    # a dropped character would otherwise only surface as a remote MD5
    # mismatch after a wasted base64 -d (m115-B)
    expected = len(b64) + 1          # the b64 body plus its newline
    got = -1
    for scale in tuple(stream_scale_steps or STREAM_SCALE_STEPS):
        _stream_heredoc(channel, b64, prompt_re, progress, len(data), name,
                        delay_s=_stream_delay_s(scale))
        size_out = _send_wait(channel, f"wc -c < {STAGING}", prompt_re,
                              command_timeout_s, "staging size")
        # m118-fix: with `stty -echo` the shell prompt is still printed and
        # it has no trailing newline, so `wc -c` output lands glued to the
        # prompt (e.g. "root@imx93frdm:~# 3005").  A bare `line.isdigit()`
        # rejects that line and the parser would then pick the computed
        # marker as the size.  Extract the LAST number on each line instead.
        sizes = []
        for line in size_out.splitlines():
            m = re.search(r"(\d+)\s*$", line)
            if m:
                sizes.append(int(m.group(1)))
        got = sizes[0] if sizes else -1
        if got == expected:
            break
        _log(f"staging size mismatch {name}: sent {expected} bytes, DUT kept "
             f"{got} -> restream slower (scale {scale})")
    else:
        raise PushError(f"staging size mismatch for {name}: expected "
                        f"{expected} bytes, DUT kept {got}")
    decode_out = _send_wait(
        channel, f"base64 -d {STAGING} > {remote_path}", prompt_re,
        command_timeout_s, "decode")
    for line in decode_out.splitlines():
        if any(marker in line for marker in DECODE_ERROR_MARKERS):
            raise PushError(f"decode failed for {name}: {line.strip()!r}")
    out = _send_wait(channel, f"md5sum {remote_path}", prompt_re,
                     command_timeout_s, "md5")
    m = re.search(r"([0-9a-f]{32})", out)
    if not m:
        raise PushError(f"cannot parse md5sum output: {out[-160:]!r}")
    remote_md5, local_md5 = m.group(1), hashlib.md5(data).hexdigest()
    if remote_md5 != local_md5:
        raise PushError(f"checksum mismatch {name}: local {local_md5} "
                        f"remote {remote_md5}")
    _send_wait(channel, f"rm -f {STAGING}", prompt_re, command_timeout_s,
               "cleanup")
    _log(f"deploy {name}: OK (md5 {local_md5})")
    return {"remote": remote_path, "bytes": len(data), "md5": local_md5,
            "elapsed_s": round(time.monotonic() - t0, 1)}


# ---------------------------------------------------------------------------
# bundle (high-speed, multi-file)
# ---------------------------------------------------------------------------
def push_bundle(channel, files: list, *, log=None, progress=None,
                prompt_re=DEFAULT_PROMPT, high_baud: int = HIGH_BAUD,
                default_baud: int = DEFAULT_BAUD,
                deadline: float = 0.0) -> list:
    """Deploy several files in one high-speed session.

    ``files`` is a list of dicts:
        {"local": host path, "remote": DUT path}
    optionally with ``"unzip": <dir>`` to extract an archive after its
    checksum is verified (``unzip -o -q``; the target dir is created).

    The link is raised to ``high_baud`` when the channel supports it, then
    restored to ``default_baud`` in a finally block (a failure can never
    leave the console at the wrong speed).  Returns a list of per-file
    result dicts (an unzip result adds ``"unzip": <dir>``).
    """
    def _log(m):
        if log is not None:
            log(m)

    def _send(command, tag=""):
        return _send_wait(channel, command, prompt_re, 20.0, tag)

    high = _switch_baud(channel, high_baud, prompt_re, _log)
    if high:
        _log(f"deploy link raised to {high_baud}")
    else:
        _log(f"baud switch unavailable; streaming at current rate")
    results: list = []
    try:
        _send("stty -echo", "stty -echo")
        for spec in files:
            # M78-2: never START another file after the row budget is
            # spent (the in-flight file finishes so the DUT console stays
            # in a clean heredoc-free state)
            if deadline and time.monotonic() >= deadline:
                raise PushError(
                    f"push budget exceeded before {spec['remote']}")
            res = push_file(channel, spec["local"], spec["remote"],
                            log=_log, progress=progress, prompt_re=prompt_re)
            if spec.get("unzip"):
                target = str(spec["unzip"])
                _send(f"mkdir -p {target}", "mkdir unzip target")
                out = _send(f"cd {target} && unzip -o -q {spec['remote']} "
                            f"&& echo UNZIP_OK", "unzip")
                if "UNZIP_OK" not in out:
                    raise PushError(f"unzip failed for {spec['remote']}: "
                                    f"{out[-160:]!r}")
                res["unzip"] = target
                _log(f"unzipped {os.path.basename(spec['remote'])} -> "
                     f"{target}")
            results.append(res)
        _send("stty echo", "stty echo")
    finally:
        if high:
            if not _switch_baud(channel, default_baud, prompt_re, _log):
                _log(f"WARNING: could not restore {default_baud}; the "
                     f"console may stay at {high_baud}")
            else:
                _log(f"deploy link restored to {default_baud}")
    return results
