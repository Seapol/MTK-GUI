# -*- coding: utf-8 -*-
"""SPF first-page title extraction (P3-B2 T7).

The Project Name is the first-page title content of a Concept-HDL
text SPF: the first descriptive line of the ``[Drawing]`` block.
Structure resolution stays with the full SPF parser; this helper only
answers "what does the title say" (no section parsing side effects).
"""

from __future__ import annotations


def extract_spf_project_name(text: str) -> str:
    """Return the SPF first-page title ("" when none is found).

    Args:
        text: Raw SPF text (any encoding already resolved).

    Returns:
        The title line, stripped; empty when the ``[Drawing]`` block
        is missing or carries no title line.
    """
    in_drawing = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("[drawing]"):
            in_drawing = True
            continue
        if stripped.startswith("["):
            if in_drawing:
                return ""          # [Drawing] block ended, no title
            continue
        if in_drawing:
            return stripped
    return ""
