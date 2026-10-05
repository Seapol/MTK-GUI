# -*- coding: utf-8 -*-
"""Smart-PDF schematic text-stream parser (spec B1-01-00 branch B).

Concept-HDL Publish Smart-PDF (``SPF-xxxx.pdf``) carries only a
printable text layer - there is NO structured ``[Component]`` /
``[Net]`` block, therefore:

* RefDes / part numbers are recovered by regex from the text stream;
* the SPF-internal net list does NOT exist, so the SPF-vs-netlist
  cross check is skipped entirely (the caller logs that limitation);
* image OCR is forbidden by spec - only the text layer is read.

PDF parsing is inherently lossy: every consumer must surface the
"review component library" warnings (handled upstream).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# RefDes tokens: U1 / R12 / C3 / J2 / TP5 / D1 / Q1 / L1 / SJ1 ...
_REFDES_RE = re.compile(
    r"\b([UJCRLDQTPS]{1,2}\d{1,4}[A-Z]?)\b(?!\.)")
# part numbers: letter-led tokens with an embedded digit, long enough
# to be a real ordering code (MM9ZJS_64, MK22FN512, TPS62840...)
_PART_RE = re.compile(
    r"\b([A-Z][A-Z0-9]{2,}[0-9][A-Z0-9_\-]{2,})\b")
# drawing-title style lines in the title block
_TITLE_LINE_RE = re.compile(
    r"^\s*(?:drawing(?:\s*title)?|title)\s*[:：]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE)


@dataclass
class PdfSchematicData:
    """Regex-recovered schematic facts from a Smart-PDF text layer.

    Attributes:
        drawing_title: Title-block drawing title ("" when absent).
        components:    (refdes, part_number) pairs, best effort,
                       in discovery order; part may be "".
        meta_title:    PDF document metadata Title ("" when absent).
    """

    drawing_title: str = ""
    components: list[tuple[str, str]] = field(default_factory=list)
    meta_title: str = ""


def parse_pdf_schematic(pdf_text: str, meta_title: str = "") \
        -> PdfSchematicData:
    """Recover RefDes / part numbers from Smart-PDF text.

    Args:
        pdf_text:   Text extracted from the PDF (text layer only).
        meta_title: PDF document metadata Title (may be empty).

    Returns:
        :class:`PdfSchematicData` (never raises - a blank text layer
        is already rejected upstream as a scanned image).
    """
    text = pdf_text or ""
    data = PdfSchematicData(meta_title=(meta_title or "").strip())

    title = _TITLE_LINE_RE.search(text)
    if title:
        data.drawing_title = title.group(1).strip()
    else:
        for line in text.splitlines():
            line = line.strip()
            if len(line) >= 3 and not line.isdigit() \
                    and not line.startswith(("=", "-", "#", "*")):
                data.drawing_title = line
                break

    seen: set[str] = set()
    refdes_list: list[str] = []
    for match in _REFDES_RE.finditer(text):
        refdes = match.group(1)
        if refdes not in seen:
            seen.add(refdes)
            refdes_list.append(refdes)

    parts = _PART_RE.findall(text)
    # pair each RefDes with the closest following part number (best
    # effort - PDF text order is not guaranteed; human review is
    # mandatory for Smart-PDF sources)
    for i, refdes in enumerate(refdes_list):
        part = parts[i] if i < len(parts) else ""
        data.components.append((refdes, part))
    return data
