# -*- coding: utf-8 -*-
"""Design-input import parsers (V4.0 acceptance 3.1.1).

Pure, headless-testable parsing functions:

* schematic PDF import - the Core ID is detected from the standard
  file name (``spf-92722_revB.pdf`` -> Core ID ``92722``), the
  project name is extracted from the drawing text,
* netlist import - a tolerant line-based parser for common ASCII
  netlist dialects (``NET <name>`` / ``*SIGNAL* <name>`` /
  ``ADD_NET <name>`` headers followed by pin tokens) that extracts
  every net name and its test-point (TP) information,
* TP tolerance - nets without a TP field are reported so the user can
  assign a pin substitute or mark the point "not tested"
  (``net=pin`` / ``net=skip`` resolutions).

Text decoding is UTF-8 first, then GBK, then latin-1 - no mojibake,
no exceptions leak to the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ------------------------------------------------------------------ text


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


# ------------------------------------------------------------- schematic
_CORE_ID_RE = re.compile(r"(?<!\d)(\d{4,10})(?!\d)")


def core_id_from_filename(filename: str) -> str:
    """Detect the Core ID from a standard schematic file name.

    Standard convention: ``spf-<CoreID>_rev<X>.pdf`` (e.g.
    ``spf-92722_revB.pdf`` -> ``92722``).  The rule is the first
    standalone digit group of 4..10 digits in the base name.

    Args:
        filename: File name (with or without directories).

    Returns:
        The detected Core ID, or "" when the name carries none.
    """
    base = re.sub(r"\.[A-Za-z0-9]+$", "", filename.strip())
    match = _CORE_ID_RE.search(base)
    return match.group(1) if match else ""


def extract_pdf_text(path: str, max_pages: int = 5) -> str:
    """Extract text from a schematic PDF using the bundled QtPdf
    module (zero new dependencies).

    Args:
        path:      PDF file path.
        max_pages: Number of leading pages to scan (title block lives
                   on the first pages).

    Returns:
        Extracted text; "" when the PDF is unreadable or QtPdf is
        unavailable (never raises into the UI).
    """
    try:
        from PySide6.QtPdf import QPdfDocument
    except ImportError:
        return ""
    try:
        doc = QPdfDocument()
        error = doc.load(path)
        # PySide6 >= 6.4 returns a QPdfDocument.Error enum (int() on
        # the enum itself raises TypeError - use .value)
        if getattr(error, "value", error) != 0:
            return ""
    except Exception:  # noqa: BLE001 - never raise into the UI
        return ""
    parts: list[str] = []
    for page in range(min(max_pages, max(0, doc.pageCount()))):
        try:
            selection = doc.getAllText(page)
            parts.append(selection.text() if hasattr(selection, "text")
                         else str(selection))
        except Exception:  # noqa: BLE001 - page-level failure tolerated
            continue
    return "\n".join(parts)


_PROJECT_NAME_RE = re.compile(
    r"^\s*project(?:\s*name)?\s*[:：]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE)


def extract_project_name(pdf_text: str) -> str:
    """Extract the project name from schematic drawing text.

    Looks for an explicit ``Project: <name>`` / ``Project Name:``
    title-block entry; falls back to the first non-empty text line
    (the drawing title) when no labelled entry exists.

    Args:
        pdf_text: Extracted PDF text.

    Returns:
        The project name, or "" when nothing plausible was found.
    """
    match = _PROJECT_NAME_RE.search(pdf_text or "")
    if match:
        return match.group(1).strip()
    for line in (pdf_text or "").splitlines():
        line = line.strip()
        if len(line) >= 3 and not line.isdigit() \
                and not line.startswith(("=", "-", "#")):
            return line
    return ""


_BOARD_NAME_RE = re.compile(
    r"(?m)^\s*([A-Z][0-9A-Z]*(?:-[0-9A-Z][0-9A-Z_]*)+)\s*$")

#: labelled title-block entries ("Part No. MCIMX8QM-CPU" /
#: "Part Number: ..." / "Part # ...") - the label is case-insensitive,
#: the captured value must still be ALL-CAPS board-name shaped
_LABELLED_PART_RE = re.compile(
    r"(?i)\bpart\s*(?:no\.?|number|#)\s*[:.]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9._-]*)")
_SCH_NO_RE = re.compile(r"\bSCH[- ]?(\d{4,10})\b", re.IGNORECASE)


def extract_drawing_board_name(pdf_text: str, core_id: str = "") -> str:
    """Extract the board Project Part# / drawing title from schematic
    PDF text (real Smart-PDF drawings, e.g. ``FRDM-IMXRT700``).

    Layer 1 - labelled title-block entries (project 29420 lesson,
    2026-10-13): ``Part No. <NAME>`` lines; when a ``Schematic
    SCH-<id>`` number within +-3 lines equals the file-name Core ID
    the entry is THIS drawing's board part number and wins outright
    (old drawings list several boards in the title block - the SCH
    pairing disambiguates).

    Layer 2 - standalone-line scan: a line in ALL-CAPS board-name
    shape - at least two alnum groups joined by ``-`` (single-letter
    first groups allowed: ``X-RING-OPTIC-ETH``).  Ranking (project
    97122 lesson): the drawing title block repeats on EVERY page
    footer while a component part number appears only next to its
    refdes instances - the MOST FREQUENT candidate wins; ``Rev.``
    proximity breaks ties, then the hyphen-group count (title names
    are multi-group), then the earliest position.

    Args:
        pdf_text: Extracted PDF text (see :func:`extract_pdf_text`).
        core_id:  Core ID from the file name (enables the layer-1
                  SCH pairing; "" keeps the pure frequency ranking).

    Returns:
        The board name (e.g. ``"FRDM-IMXRT700"``, ``"MCIMX8QM-CPU"``),
        or "" when no plausible title-block name exists in the
        drawing.
    """
    text = pdf_text or ""
    lines = [ln.strip() for ln in text.splitlines()]
    # layer 1: labelled entries paired with THIS file's SCH number
    if core_id:
        core_digits = re.sub(r"\D", "", str(core_id))
        if core_digits:
            for i, line in enumerate(lines):
                labelled = _LABELLED_PART_RE.search(line)
                if not labelled:
                    continue
                value = labelled.group(1).strip()
                if not _BOARD_NAME_RE.fullmatch(value):
                    continue
                window = " ".join(lines[max(0, i - 3):i + 3])
                if any(sch == core_digits
                       for sch in _SCH_NO_RE.findall(window)):
                    return value
    # layer 2: standalone candidates ranked by frequency
    counts: dict[str, int] = {}
    near_rev: dict[str, bool] = {}
    first_at: dict[str, int] = {}
    for i, line in enumerate(lines):
        match = _BOARD_NAME_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        counts[name] = counts.get(name, 0) + 1
        first_at.setdefault(name, i)
        if not near_rev.get(name):
            window = " ".join(lines[max(0, i - 2):i + 4])
            near_rev[name] = "REV" in window.upper()
    if not counts:
        return ""
    best = sorted(
        counts,
        key=lambda n: (-counts[n], 0 if near_rev.get(n) else 1,
                       -n.count("-"), first_at[n]))
    return best[0]


# --------------------------------------------------------------- netlist
@dataclass
class NetlistData:
    """Parsed netlist content.

    Attributes:
        nets:      Ordered mapping net name -> member pin tokens.
        missing_tp: Net names that carry no TP (test point) member.
    """

    nets: dict[str, list[str]] = field(default_factory=dict)
    missing_tp: list[str] = field(default_factory=list)

    def tp_of(self, net: str) -> str:
        """Return the TP member of a net ("" when it has none)."""
        for token in self.nets.get(net, []):
            if token.upper().startswith("TP"):
                return token
        return ""

    def resolutions_text(self, resolutions: dict[str, str]) -> str:
        """Render the TP resolutions chosen for missing-TP nets.

        Args:
            resolutions: net -> substituted pin, or "skip".

        Returns:
            Multi-line ``net=pin`` / ``net=skip`` text for the
            ``tp_resolutions`` parameter.
        """
        return "\n".join(f"{net}={res}"
                         for net, res in resolutions.items())


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
