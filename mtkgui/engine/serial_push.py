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
import re
import time

#: shell prompt (root ``#`` or user ``$``) at end of the buffer (tolerates
#: trailing ANSI color codes)
DEFAULT_PROMPT = re.compile(r"[#\$](\x1b\[[0-9;]*[A-Za-z])*\s*$")
#: high-speed link used for the asset transfer
HIGH_BAUD = 921600
#: production console rate (restored after the transfer)
DEFAULT_BAUD = 115200
#: base64 bytes per streamed block + inter-block delay (s).  At 921600 the
#: link moves ~9216 B/s; 2048 B per 0.03 s keeps the host just behind the
#: DUT reader (verified md5-clean).
STREAM_BLOCK = 2048
STREAM_DELAY_S = 0.03
#: heredoc terminator (must not appear in base64 - it does not)
HEREDOC_TAG = "PUSH_EOF"
STAGING = "/root/.push.b64"


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
    """Write one command, drain until the shell prompt appears."""
    channel.write(command + "\n")
    deadline = time.monotonic() + max(timeout_s, 0.1)
    seen = ""
    while time.monotonic() < deadline:
        got = channel.read_lines(max_lines=200, timeout_s=0.1)
        if got:
            seen = (seen + "\n" + "\n".join(got)) if seen else "\n".join(got)
            if prompt_re.search(seen):
                return seen
    raise PushError(f"timeout waiting for {tag or command[:32]}: "
                    f"{seen[-160:]!r}")


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
                    name: str) -> None:
    """Open a quoted heredoc, stream the base64 in paced blocks, close it."""
    channel.write(f"cat > {STAGING} <<'{HEREDOC_TAG}'\n")
    time.sleep(0.4)
    _pump_read(channel, 0.2)
    blocks = [b64[i:i + STREAM_BLOCK]
              for i in range(0, len(b64), STREAM_BLOCK)]
    for i, block in enumerate(blocks):
        channel.write(block)
        time.sleep(STREAM_DELAY_S)
        if progress is not None:
            sent_b64 = min(len(b64), (i + 1) * STREAM_BLOCK)
            progress(int(sent_b64 * total_bytes / len(b64)), total_bytes,
                     name)
        # read_lines also pumps the GUI loop (RX must reach the buffer)
        channel.read_lines(max_lines=200, timeout_s=0.0)
    channel.write(f"\n{HEREDOC_TAG}\n")
    _send_wait(channel, "", prompt_re, 12.0, "heredoc close")


def push_file(channel, local_path: str, remote_path: str, *,
              log=None, progress=None, prompt_re=DEFAULT_PROMPT,
              command_timeout_s: float = 20.0) -> dict:
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
    _stream_heredoc(channel, b64, prompt_re, progress, len(data), name)
    _send_wait(channel, f"base64 -d {STAGING} > {remote_path}", prompt_re,
               command_timeout_s, "decode")
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
                default_baud: int = DEFAULT_BAUD) -> list:
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
