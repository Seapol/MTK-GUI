# -*- coding: utf-8 -*-
"""Event Log level model (M11).

An Event Log entry carries two independent notions:

* the AUDIT line - exactly one ``YYYY-MM-DD HH:MM:SS`` stamp followed
  by the message text (embedded leading stamps from callers / producer
  signals are stripped first), and
* the DISPLAY level - "Detailed" shows every entry, "Simplified" shows
  only what an operator needs: test results (``TEST``), warnings,
  errors and the explicitly marked business events (``IMPORTANT``).

Role defaults live in the main window (Operator -> Simplified,
Supervisor -> Detailed, supervisor switchable and persisted); this
module stays pure (regex + plain functions) so the rules are testable
without a QApplication.
"""

from __future__ import annotations

import re

#: real log levels (the producer level carried by the signal lines)
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

#: display-only classes
TEST = "TEST"            # test-result line (PASS / FAIL / Done / Error)
IMPORTANT = "IMPORTANT"  # explicitly marked business event

#: the two persisted display modes (QSettings "event_log/level")
SIMPLIFIED = "simplified"
DETAILED = "detailed"

#: levels that survive the Simplified filter - WARNING / ERROR / TEST
#: are NEVER hidden in any mode
SIMPLIFIED_LEVELS = frozenset({TEST, "WARNING", "ERROR", IMPORTANT})

#: a LEADING embedded timestamp: full date-time or time-only, with one
#: optional space after the closing bracket.  A stamp that is not at
#: the start of the text is part of the message and stays untouched.
_LEADING_STAMP_RE = re.compile(
    r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] ?"
    r"|^\[\d{2}:\d{2}:\d{2}\] ?")

#: producer level tag carried by the yaml-build / workflow signals
#: ("[INFO] ...", "[WARN] ..."); the tag STAYS in the text, it only
#: feeds the level model
_LEVEL_TAG_RE = re.compile(
    r"^\[(DEBUG|INFO|WARN|WARNING|ERROR)\]\s*", re.IGNORECASE)

#: plain-text producer prefix ("WARNING: ...", "ERROR: ...") - keeps
#: warnings / errors visible in the Simplified mode even when the
#: producer only spelled the level into the message
_LEVEL_PREFIX_RE = re.compile(r"^(DEBUG|WARNING|ERROR)\s*:\s*",
                              re.IGNORECASE)

#: verdict tokens of a test-result line (mirrors the highlighting rule
#: of ``main_window._colorize_verdicts``, plus "Done")
_VERDICT_RE = re.compile(r"\b(pass|passed|fail|failed|error|done)\b",
                         re.IGNORECASE)


def strip_leading_stamp(text):
    """Remove embedded timestamps at the START of ``text``.

    Repeated stamps (a caller-added ``[HH:MM:SS]`` in front of a full
    ``[YYYY-MM-DD HH:MM:SS]``) are all removed so the rendered line
    carries exactly ONE stamp.  Strips at most three leading stamps.

    Args:
        text: The raw entry text.

    Returns:
        The text without leading embedded stamps.
    """
    out = str(text)
    for _ in range(3):
        new = _LEADING_STAMP_RE.sub("", out, count=1)
        if new == out:
            break
        out = new
    return out


def normalize_level(level):
    """Map a producer level string onto the level model.

    ``WARN`` becomes ``WARNING``; unknown / empty values become
    ``INFO``; ``TEST`` and ``IMPORTANT`` pass through.

    Args:
        level: Level name (any case) or None.

    Returns:
        One of :data:`LOG_LEVELS`, :data:`TEST` or
        :data:`IMPORTANT`.
    """
    name = str(level or "").strip().upper()
    if name == "WARN":
        return "WARNING"
    if name in LOG_LEVELS or name in (TEST, IMPORTANT):
        return name
    return "INFO"


def is_test_result(text):
    """True when ``text`` carries a verdict token (PASS / FAIL / Done /
    Error): the line is a test result."""
    return bool(_VERDICT_RE.search(str(text)))


def resolve_level(text, level="INFO"):
    """Final level of one entry.

    Precedence (M11 F2):

    1. an explicit ``TEST`` / ``IMPORTANT`` mark wins,
    2. a leading ``[LEVEL]`` producer tag (yaml-build / workflow
       signals) - or a plain ``WARNING:`` / ``ERROR:`` message prefix -
       is consumed by the level model,
    3. plain ``INFO`` / ``DEBUG`` lines carrying a verdict token are
       auto-classified as ``TEST``.

    Args:
        text: The entry text (already stamp-deduplicated).
        level: The explicit level passed by the caller.

    Returns:
        The resolved level name.
    """
    explicit = normalize_level(level)
    if explicit in (TEST, IMPORTANT):
        return explicit
    tag = _LEVEL_TAG_RE.match(str(text))
    prefix = None if tag else _LEVEL_PREFIX_RE.match(str(text))
    if tag:
        resolved = normalize_level(tag.group(1))
    elif prefix:
        resolved = normalize_level(prefix.group(1))
    else:
        resolved = explicit
    if resolved in ("DEBUG", "INFO") and is_test_result(text):
        return TEST
    return resolved


def should_display(level, detailed):
    """Display filter.

    Args:
        level: The resolved entry level.
        detailed: True for the Detailed mode, False for Simplified.

    Returns:
        True when the entry is shown in that mode.
    """
    if detailed:
        return True
    return normalize_level(level) in SIMPLIFIED_LEVELS
