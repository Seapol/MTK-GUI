# -*- coding: utf-8 -*-
"""Native Concept-HDL text-SPF parser (spec B1-01-00 branch A).

Reads the structured ``[Document]`` / ``[Drawing]`` / ``[Component]`` /
``[Net]`` blocks of a Cadence Concept-HDL SPF export:

* ``[Drawing]`` carries the drawing title (project-name priority 1);
* ``[Component]`` lines hold ``RefDes`` + part number pairs;
* ``[Net]`` lines hold net names with member pins - these feed the
  SPF-vs-netlist cross check (net names not matching the external
  Allegro netlist produce a WARNING, never an error).

A file without any recognizable SPF block (or an empty file) is
corrupt: :class:`SpfParseError` terminates the parse (ERROR log
upstream).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from mtkgui.gui.yamlbuild.parser import read_text_any_encoding


class SpfParseError(ValueError):
    """The SPF file is corrupt / not a recognizable Concept-HDL export."""


@dataclass
class SpfData:
    """Parsed native text SPF.

    Attributes:
        drawing_title: ``[Drawing]`` title ("" when absent).
        components:    (refdes, part_number) pairs in file order.
        nets:          net name -> member pin tokens.
        document_meta: ``[Document]`` key/value lines (informational).
    """

    drawing_title: str = ""
    components: list[tuple[str, str]] = field(default_factory=list)
    nets: dict[str, list[str]] = field(default_factory=dict)
    document_meta: dict[str, str] = field(default_factory=dict)


_SECTION_RE = re.compile(r"^\s*\[([A-Za-z]+)\]\s*$")
_KEY_VALUE_RE = re.compile(r"^\s*([A-Za-z_ ]+)\s*[:=]\s*(.+?)\s*$")
_REFDES_RE = re.compile(r"^[A-Za-z]+\d+")


def parse_spf(text: str) -> SpfData:
    """Parse Concept-HDL text-SPF content.

    Args:
        text: Raw SPF text (already decoded).

    Returns:
        :class:`SpfData` with components, nets and the drawing title.

    Raises:
        SpfParseError: Empty input or no recognizable SPF section.
    """
    if not (text or "").strip():
        raise SpfParseError("empty SPF file")
    data = SpfData()
    section = ""
    seen_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "//", ";", "*")):
            continue
        head = _SECTION_RE.match(line)
        if head:
            section = head.group(1).upper()
            seen_section = True
            continue
        if section == "DOCUMENT":
            kv = _KEY_VALUE_RE.match(line)
            if kv:
                data.document_meta[kv.group(1).strip().lower()] = \
                    kv.group(2).strip()
        elif section == "DRAWING":
            if not data.drawing_title and not _looks_like_junk(line):
                data.drawing_title = line
        elif section == "COMPONENT":
            comp = _parse_component_line(line)
            if comp is not None:
                data.components.append(comp)
        elif section == "NET":
            _parse_net_line(line, data.nets)
    if not seen_section:
        raise SpfParseError(
            "no [Document]/[Drawing]/[Component]/[Net] section found")
    return data


def _looks_like_junk(line: str) -> bool:
    """True for separator / decoration lines not usable as a title."""
    stripped = line.strip()
    return (len(stripped) < 3 or stripped.isdigit()
            or stripped.startswith(("=", "-", "#", "*")))


def _parse_component_line(line: str) -> tuple[str, str] | None:
    """Extract ``(refdes, part_number)`` from one [Component] line.

    Tolerant shapes: ``U1 ; MM9ZJS_64``, ``U1 MM9ZJS_64`` and
    ``U1 = MM9ZJS_64``.  Lines without a leading RefDes are skipped.
    """
    sides = re.split(r"[;=]", line)
    head = sides[0].split()
    if not head:
        return None
    refdes = head[0]
    if not _REFDES_RE.match(refdes):
        return None
    tail = sides[1].split() if len(sides) > 1 else []
    part = tail[0] if tail else (head[1] if len(head) > 1 else "")
    return refdes, part


def _parse_net_line(line: str, nets: dict[str, list[str]]) -> None:
    """Add one [Net] block line (``name pin pin ...``) to *nets*."""
    tokens = line.split()
    if not tokens:
        return
    name = tokens[0].strip('"')
    pins = [t for t in tokens[1:] if re.match(r"^[\w.\-\[\]/#]+$", t)]
    nets.setdefault(name, []).extend(pins)


def cross_check_nets(spf_nets: dict[str, list[str]],
                     netlist_nets: dict[str, list[str]]) -> list[str]:
    """Cross-check the SPF-internal net list against the external one.

    Args:
        spf_nets:     Net name -> members parsed from the SPF [Net] block.
        netlist_nets: Net name -> members parsed from the Allegro .net.

    Returns:
        WARNING lines for every name mismatch (SPF-only and
        netlist-only names), in a stable order.
    """
    warnings: list[str] = []
    for name in spf_nets:
        if name not in netlist_nets:
            warnings.append(
                f"net '{name}' exists in SPF but not in the external "
                "netlist")
    for name in netlist_nets:
        if name not in spf_nets:
            warnings.append(
                f"net '{name}' exists in the external netlist but not "
                "in the SPF")
    return warnings
