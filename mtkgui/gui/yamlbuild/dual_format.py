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
#: Cadence "Export Logic" netlist (pstxnet.dat style) features
_PSTX_FEATURE_RE = re.compile(
    r"^\s*(?:FILE_TYPE\s*=\s*NETLIST|NET_NAME\b|PART_NAME\b)",
    re.IGNORECASE)
#: Allegro Report CSV export (the "net report" flavor):
#: a header line "Net Name,Net Pins" followed by "name,pin pin pin"
_REPORT_HEADER_RE = re.compile(r"^\s*Net Name\s*,\s*Net Pins",
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
        ``"pstxnet"`` when Cadence Export-Logic netlist features lead
        it, ``"net"`` when Allegro NET header features lead it, and
        ``"unknown"`` when neither side proves its format (the caller
        falls back to the tolerant NET chain).
    """
    spf_score = 0
    net_score = 0
    pstx_score = 0
    report_score = 0
    seen = 0
    for raw_line in (text or "").splitlines():
        line = raw_line.lstrip("\ufeff").strip()
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
        if _PSTX_FEATURE_RE.match(line):
            pstx_score += 1
            continue
        if _REPORT_HEADER_RE.match(line) or line == "Allegro Report":
            report_score += 1
            continue
        if _NET_HEADER_RE.match(line) or _NET_MARKER_RE.match(line):
            net_score += 1
    best = max(spf_score, net_score, pstx_score, report_score)
    if best == 0:
        return "unknown"
    if spf_score == best:
        return "spf"
    if report_score == best and report_score > 0:
        return "allegro_report"
    if pstx_score == best and pstx_score > 0:
        return "pstxnet"
    return "net"


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


def parse_pstxnet(text: str) -> NetlistData:
    """Parse a Cadence "Export Logic" netlist (pstxnet.dat style).

    Typical shape::

        FILE_TYPE=NETLIST;
        PART_NAME
         'U1'
         'MIMXRT798S';

        NET_NAME
         'GND'
         '@NETLIST_LIB.GND(SCH_1):...'
         C_SIGNAL='@...',
         P U1.1;
         P C1.2;

    Every ``NET_NAME`` block contributes its quoted net name; the
    member pins are all ``refdes.pin`` shaped tokens (``P U1.1;``)
    found before the next ``NET_NAME``.  Tolerant to comments
    (``{ ... }``), property lines and free spacing.

    Args:
        text: Raw pstxnet text (any encoding already resolved).

    Returns:
        The unified :class:`NetlistData`.
    """
    data = NetlistData()
    current: str | None = None
    expect_name = False
    _pin_token = re.compile(r"^[A-Za-z]+\d+[\.\-]\S+$|^\d+[A-Za-z]*$"
                            r"|^[A-Za-z]+\d+$")
    for raw_line in (text or "").splitlines():
        line = raw_line.lstrip("\ufeff").strip()
        if not line:
            continue
        if line.upper().startswith("NET_NAME"):
            current = None              # name arrives on the next
            expect_name = True          # quoted line
            continue
        quoted = re.match(r"^'([^']+)'\s*;?\s*$", line)
        if quoted is not None:
            if expect_name:
                current = quoted.group(1).strip()
                data.nets.setdefault(current, [])
                expect_name = False
            continue                    # PART_NAME / property quotes
        if expect_name:
            expect_name = False         # safety: block without quotes
        if current is None:
            continue
        if line.startswith("{") or line.upper().startswith(
                ("FILE_TYPE", "PRIM_FILE", "COMPILE")):
            continue
        # strip the leading pin-kind marker and the trailing semicolon
        token_line = line[2:] if line[:2].upper().startswith(
            ("P ", "S ")) else line
        token_line = token_line.rstrip(";").strip()
        for token in token_line.replace(",", " ").split():
            token = token.strip('"').rstrip(";")
            if _pin_token.match(token) and not token.isalpha():
                data.nets[current].append(token)
    data.missing_tp = [
        net for net, members in data.nets.items()
        if not any(m.upper().startswith("TP") for m in members)]
    return data


def parse_allegro_report(text: str) -> NetlistData:
    """Parse an Allegro Report CSV net export (the "net report"
    flavor, as produced by Tools > Reports > Net List report).

    Shape (``Allegro Report`` title + ``Net Name,Net Pins`` header,
    then one row per net)::

        Net Name,Net Pins
        5V_SDA_PSW,C48.1 D43.A U17.C2 U17.D1
        AGND,C186.2 C190.2 R2174.1

    Quoted net names (``"A,B"``, embedded commas) are supported; pin
    tokens are space separated.

    Args:
        text: Raw report text (any encoding already resolved).

    Returns:
        The unified :class:`NetlistData`.
    """
    data = NetlistData()
    in_table = False
    _pin_ok = re.compile(r"^[\w\.\-\[\]/#]+$")
    for raw_line in (text or "").splitlines():
        line = raw_line.lstrip("\ufeff").strip()
        if not line:
            continue
        if not in_table:
            if _REPORT_HEADER_RE.match(line):
                in_table = True
            continue
        name, _, pins_part = line.partition(",")
        name = name.strip().strip('"').strip()
        if not name:
            continue
        members = data.nets.setdefault(name, [])
        for token in pins_part.split():
            token = token.strip('"').strip()
            if token and _pin_ok.match(token):
                members.append(token)
    data.missing_tp = [
        net for net, members in data.nets.items()
        if not any(m.upper().startswith("TP") for m in members)]
    return data


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
    text = (text or "").lstrip("\ufeff")   # UTF-8 BOM never breaks a
    if fmt == "spf":                       # first-line header match
        spf = parse_spf(text)          # mature SPF chain (may raise)
        data = NetlistData()
        for name, members in spf.nets.items():
            data.nets[name] = list(members)
        data.missing_tp = [
            net for net, members in data.nets.items()
            if not any(m.upper().startswith("TP") for m in members)]
        return data
    if fmt == "pstxnet":
        data = parse_pstxnet(text)
        if data.nets:
            return data
    if fmt == "allegro_report":
        data = parse_allegro_report(text)
        if data.nets:
            return data
    # NET (and unknown fallback): tolerant NET chain after cleaning
    data = parse_netlist(clean_net_text(text))
    if data.nets:
        return data
    # clear diagnostic: what the file LOOKS like (helps report the
    # exact unsupported dialect instead of a generic no-nets error)
    first = ""
    for raw_line in (text or "").splitlines():
        line = raw_line.lstrip("\ufeff").strip()
        if line:
            first = line[:80]
            break
    raise ValueError(
        f"no nets found (detected format: {fmt}; first line: "
        f"{first!r}) - the file has no recognizable netlist content "
        "(SPF sections / *SIGNAL* or NET blocks / Export-Logic "
        "NET_NAME blocks)")
