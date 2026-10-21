# -*- coding: utf-8 -*-
"""Tolerant text reading + generic ASCII netlist parsing.

Text decoding is UTF-8 first, then GBK, then latin-1 - no mojibake,
no exceptions leak to the caller.
"""
from __future__ import annotations

import re

from .model import NetlistData


def read_text_any_encoding(path: str) -> str:
    """Read a text file with a tolerant decode chain.

    Args:
        path: File path (netlist / text-based design data).

    Returns:
        Decoded text; undecodable bytes are replaced, never raised.
    """
    raw = Path_bytes(path)
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def Path_bytes(path: str) -> bytes:
    """Read raw file bytes.

    Args:
        path: File path.

    Returns:
        File content; empty bytes when unreadable (no exception).
    """
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return b""


_NET_HEADER_RE = re.compile(
    r"^\s*(?:\*?SIGNAL\*?|NET|ADD_NET|SIGNAL)\s+\"?([^\s\"]+)\"?\s*$",
    re.IGNORECASE)
_PIN_TOKEN_RE = re.compile(r"^[\w\.\-\[\]/#]+$")


def parse_netlist(text: str) -> NetlistData:
    """Parse ASCII netlist content (tolerant across common dialects).

    A net header is a line like ``NET <name>``, ``*SIGNAL* <name>``,
    ``SIGNAL <name>`` or ``ADD_NET <name>`` (quoted names allowed).
    Every following non-header token line adds member pins; tokens
    must look like reference designators / pin references
    (``U1.5``, ``R2-1``, ``TP3``, ``J1[2]``).

    Args:
        text: Raw netlist text.

    Returns:
        :class:`NetlistData` with all nets, member pins and the list
        of nets without a TP member.
    """
    data = NetlistData()
    current: str | None = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "//", ";", "*REMARK")):
            continue
        header = _NET_HEADER_RE.match(line)
        if header:
            current = header.group(1)
            data.nets.setdefault(current, [])
            continue
        if current is None:
            continue
        if line in ("[", "]", "(", ")"):
            continue
        for token in line.split():
            if _PIN_TOKEN_RE.match(token):
                data.nets[current].append(token)
    # TP bookkeeping
    for net, members in data.nets.items():
        if not any(m.upper().startswith("TP") for m in members):
            data.missing_tp.append(net)
    return data


def parse_netlist_file(path: str) -> tuple[NetlistData, str]:
    """Read + parse a netlist file (tolerant decode chain).

    Format routing is automatic (SPF / NET / PSTXNET / Allegro
    Report) - see :func:`mtkgui.ict.netparse.formats.parse_netlist_auto`.

    Args:
        path: Netlist file path (``.net`` / ``.net.txt``).

    Returns:
        (NetlistData, raw_text) - the raw text stays available for
        audit / re-parse without touching the file again.  Unreadable
        or empty files degrade to an empty netlist (never raise).
    """
    text = read_text_any_encoding(path)
    if not text.strip():
        return NetlistData(), text
    from .formats import parse_netlist_auto   # local: avoids a cycle
    return parse_netlist_auto(text), text
