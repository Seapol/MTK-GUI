# -*- coding: utf-8 -*-
"""Schematic PDF import helpers (V4.0 acceptance 3.1.1).

Pure, headless-testable parsing functions:

* schematic PDF import - the Core ID is detected from the standard
  file name (``spf-92722_revB.pdf`` -> Core ID ``92722``), the
  project name is extracted from the drawing text.

The netlist parsing core lives in :mod:`mtkgui.ict.netparse`.
"""

from __future__ import annotations

import re

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
