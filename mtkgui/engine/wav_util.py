# -*- coding: utf-8 -*-
"""WAV helpers shared by the BT Tone editor (GUI) and the A2DP adapter.

Both sides need the file's TOTAL duration: the editor renders the
Start/End slider range and the "total" label from it, and the adapter
trims the played segment to ``[tone_start_s, tone_end_s)`` before it
hands the file to the host player.  The stdlib ``wave`` module reads the
header only (no decoder dependency); anything it cannot parse (compressed
or non-PCM wav) returns None so callers degrade gracefully instead of
raising.
"""
from __future__ import annotations

import os
import tempfile
import wave


def wav_duration_s(path: str) -> float | None:
    """Total length of `path` in seconds (None when unreadable)."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with wave.open(path, "rb") as wf:
            rate = wf.getframerate()
            if not rate:
                return None
            return float(wf.getnframes()) / float(rate)
    except (OSError, EOFError, wave.Error):
        return None


def trim_wav(path: str, start_s: float, end_s: float) -> str | None:
    """Write ``[start_s, end_s)`` of `path` to a temp wav.

    Returns the temp file path, or None when the source cannot be read
    or the resulting range is empty.  The CALLER owns the temp file
    (delete it after playback)."""
    try:
        with wave.open(path, "rb") as src:
            rate = src.getframerate()
            width = src.getsampwidth()
            channels = src.getnchannels()
            total = src.getnframes()
            first = max(0, int(round(start_s * rate)))
            last = min(total, int(round(end_s * rate)))
            if last <= first:
                return None
            src.setpos(first)
            data = src.readframes(last - first)
        fd, out = tempfile.mkstemp(suffix=".wav", prefix="fct_tone_")
        os.close(fd)
        with wave.open(out, "wb") as dst:
            dst.setnchannels(channels)
            dst.setsampwidth(width)
            dst.setframerate(rate)
            dst.writeframes(data)
        return out
    except (OSError, EOFError, ValueError, wave.Error):
        return None
