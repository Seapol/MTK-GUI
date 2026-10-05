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
        if int(error) != 0:          # QPdfDocument.Error.None == 0
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
