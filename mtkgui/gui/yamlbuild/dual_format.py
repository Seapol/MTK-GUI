# -*- coding: utf-8 -*-
"""Dual-format netlist entry: automatic SPF / NET branch routing
(Parse Nets for ICT core-algorithm standard, section 4).

The standard mass-production input is a Concept-HDL text SPF
(``[Document] / [Drawing] / [Component] / [Net]`` blocks); the newly
supported input is a standard Allegro NET netlist (``*SIGNAL*`` /
``NET <name>`` blocks, optional ``.SUBCKT`` structures and ``+``
continuation lines).

Routing is fully automatic from the FILE HEADER FEATURES - never from
the file extension, never a manual choice:

* SPF section headers in the head of the file  -> the mature SPF
  parsing chain (:func:`mtkgui.gui.designinput.spf_parser.parse_spf`);
* NET header features                          -> the NET chain
  (:func:`mtkgui.gui.yamlbuild.parser.parse_netlist`) after the
  NET-specific cleaning (subckt removal, continuation join, common
  junk filtering).

Both branches emit the EXACT same structured output
(:class:`mtkgui.gui.yamlbuild.parser.NetlistData`) - the downstream
classification, topology, test-point selection, risk scoring, power
tree and YAML persistence are format-unaware (zero adaptation).
The existing NET parsing logic itself is untouched (red line).
"""

from __future__ import annotations

import re

from mtkgui.gui.designinput.spf_parser import parse_spf
from mtkgui.gui.yamlbuild.parser import NetlistData, parse_netlist

#: how many leading non-empty lines the header scan inspects
HEADER_SCAN_LINES = 40

#: SPF (Concept-HDL) section-header feature
_SPF_SECTION_RE = re.compile(r"^\s*\[([A-Za-z]+)\]\s*$")
#: SPF sections that prove a Concept-HDL export (not a bare INI)
_SPF_PROOF = {"DOCUMENT", "DRAWING", "COMPONENT", "NET"}
#: Allegro NET marker features
_NET_HEADER_RE = re.compile(
    r"^\s*(?:\*SIGNAL\*|\*?SIGNAL\*?|NET|ADD_NET)\s+\"?[^\s\"]+\"?\s*$",
    re.IGNORECASE)
_NET_MARKER_RE = re.compile(r"^\s*\$?(PACKAGES|NETS|END)\b",
                            re.IGNORECASE)
#: SPICE-style subckt lines carried by some NET exports (removed)
_SUBCKT_RE = re.compile(r"^\s*\.(SUBCKT|ENDS|END|OPTIONS|INCLUDE)\b",
                        re.IGNORECASE)


def detect_netlist_format(text: str) -> str:
    """Detect the netlist format from the file header features.

    Args:
        text: Raw netlist text (any encoding already resolved).

    Returns:
        ``"spf"`` when Concept-HDL SPF section features lead the file,
        ``"net"`` when Allegro NET header features lead it, and
        ``"unknown"`` when neither side proves its format (the caller
        falls back to the tolerant NET chain).
    """
    spf_score = 0
    net_score = 0
    seen = 0
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        seen += 1
        if seen > HEADER_SCAN_LINES:
            break
        head = _SPF_SECTION_RE.match(line)
        if head:
            if head.group(1).upper() in _SPF_PROOF:
                spf_score += 2      # a proofing SPF section header
            continue
        if _NET_HEADER_RE.match(line) or _NET_MARKER_RE.match(line):
            net_score += 1
    if spf_score > net_score:
        return "spf"
    if net_score > 0:
        return "net"
    return "unknown"


def clean_net_text(text: str) -> str:
    """NET-format specific cleaning (directive 4.2).

    * drops SPICE-style subckt / option lines (``.SUBCKT`` / ``.ENDS``
      / ``.END`` / ``.OPTIONS`` / ``.INCLUDE``),
    * joins ``+`` continuation lines onto their previous line,
    * leaves every other byte to the existing tolerant NET parser
      (the parser core itself is NOT modified).
    """
    out: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        if _SUBCKT_RE.match(stripped):
            continue
        if stripped.startswith("+") and out:
            # continuation: merge onto the previous physical line
            out[-1] = out[-1].rstrip() + " " + stripped[1:].strip()
            continue
        out.append(line)
    return "\n".join(out)


def parse_netlist_auto(text: str) -> NetlistData:
    """Detect the format, run the matching branch, return the unified
    structured output.

    Both branches produce :class:`NetlistData` with the identical
    semantics (net name -> member pin tokens, ``missing_tp`` list), so
    every downstream consumer is format-unaware.

    Args:
        text: Raw netlist text (SPF or NET, auto-detected).

    Returns:
        The unified :class:`NetlistData`.

    Raises:
        ValueError: No nets at all after both branches (clear,
                    non-silent error - wrong file or empty input).
    """
    fmt = detect_netlist_format(text)
    if fmt == "spf":
        spf = parse_spf(text)          # mature SPF chain (may raise)
        data = NetlistData()
        for name, members in spf.nets.items():
            data.nets[name] = list(members)
        data.missing_tp = [
            net for net, members in data.nets.items()
            if not any(m.upper().startswith("TP") for m in members)]
        return data
    # NET (and unknown fallback): tolerant NET chain after cleaning
    data = parse_netlist(clean_net_text(text))
    if data.nets:
        return data
    raise ValueError(
        "no nets found - the file has no recognizable netlist "
        "content (SPF sections or *SIGNAL* / NET blocks)")
