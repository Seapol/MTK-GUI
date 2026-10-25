# -*- coding: utf-8 -*-
"""Learn net classification rules from a new project (headless).

Scans a project's net-name list and reports how the current rules
classify it (Power / Clock / Control IO / Others) BEFORE vs AFTER a
learned rule suggestion, so an operator can see at a glance whether
the regexes need tuning for a new board.

Learning is conservative: the suggested rules are the CURRENT rules
plus one extra anchored branch per category, built from tokens found
in the nets that currently fall into ``Others``.  Nothing is removed;
the operator Tests / saves (or ignores) the suggestion.
"""

from __future__ import annotations

import re

from .rules import (CATEGORY_POWER, CATEGORY_SE_CLOCK, DEFAULT_RULES,
                    classify_net, control_io_rule)

#: the four comparison buckets shown in the Learn panel
BUCKETS = ("Power", "Clock", "Control IO", "Others")

#: tokens that point to a POWER rail when found in an "Others" net
_VOLT_TOKENS = ("1V0", "1V2", "1V5", "1V8", "2V5", "3V3", "5V", "12V",
                "24V")
#: tokens that point to a single-ended CLOCK when found in an "Others"
_CLOCK_TOKENS = ("CLK", "OSC", "XTAL", "MCLK", "RTC", "MHZ", "KHZ")
#: tokens that point to an EXCLUDED bus / differential name
_EXCLUDE_TOKENS = ("DIFF", "RESET", "ENABLE", "UART", "WAKE", "I2C",
                   "SPI", "JTAG", "DBGIF", "DATA", "ADC")

#: a differential pair member is excluded from ICT test objects
_DIFF_MEMBER_RE = re.compile(r"_[PN]$", re.IGNORECASE)
#: Allegro system-random numeric names are excluded too
_SYSTEM_RANDOM_RE = re.compile(r"^\$?N?\d+$")


def read_net_names(path: str) -> list[str]:
    """Extract the pure net names from an Allegro ``.net`` file.

    A line is ``NET_NAME,REFDES.PIN...``; the net name is the token
    before the first comma.  Comment / directive lines (``#``, ``(``)
    and bare numeric lines are skipped.
    """
    names: list[str] = []
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        raise ValueError(f"cannot read NET file: {exc}") from exc
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("("):
            continue
        m = re.match(r"^\S+", line)
        if m:
            names.append(m.group(0).split(",")[0].strip())
    return [n for n in names
            if n and not re.match(r"^\d+(\.\d+)?$", n)]


def _bucket(name: str, rules: dict | None) -> str:
    """Classify ONE net into the four comparison buckets (name only;
    SPF attributes are not part of the learn scan)."""
    if control_io_rule(name):
        return "Control IO"
    kind = classify_net(name, rules=rules)
    if kind == CATEGORY_POWER:
        return "Power"
    if kind == CATEGORY_SE_CLOCK:
        return "Clock"
    return "Others"


def _effective_rules(current: dict | None) -> dict[str, str]:
    """Current rules with the factory defaults filled in for slots the
    user has NOT configured (classification always sees the defaults)."""
    out = dict(current or {})
    for key in ("power", "se_clock", "exclude"):
        out.setdefault(key, DEFAULT_RULES[key])
    return out


def _bucket_conflict(name: str, old_rules: dict, new_rules: dict) -> str:
    """Bucket under the NEW rules, demoting cross-category flips.

    When the OLD rules placed the net in a definite bucket (Power /
    Clock / Control IO) and the learned rules move it to a DIFFERENT
    bucket, the re-classification is low-confidence: it lands in
    ``Others`` and the operator adjusts it manually.
    """
    old = _bucket(name, old_rules)
    new = _bucket(name, new_rules)
    if old != "Others" and new != old:
        return "Others"
    return new


def count_by_category(names: list[str],
                      rules: dict | None = None) -> dict[str, int]:
    """Bucket counts under ONE rule set."""
    counts = {b: 0 for b in BUCKETS}
    for name in names:
        counts[_bucket(name, rules)] += 1
    return counts


def _learned_tokens(names: list[str], tokens: tuple[str, ...]) -> list[str]:
    """Tokens actually present (case-insensitive) in the names."""
    upper = {n.upper() for n in names if n}
    return [t for t in tokens if any(t in u for u in upper)]


def _extra_pattern(tokens: list[str], shape: str) -> str | None:
    """One anchored branch built from the learned tokens."""
    if not tokens:
        return None
    return shape.format("|".join(tokens))


def _merge(base: str | None, extra: str) -> str:
    """Current pattern + one learned branch (``|`` merge).

    The factory ``exclude`` pattern starts with a GLOBAL ``(?i)`` flag
    which is only legal at the expression start; when the base is
    wrapped for merging, that flag is hoisted to the front so the
    merged pattern still compiles.  The learned branch carries its own
    scoped ``(?i:...)`` flags and is never altered.
    """
    base = (base or "").strip()
    if not base:
        return extra
    prefix = ""
    if base.startswith("(?i)"):
        prefix, base = "(?i)", base[4:].strip()
    return prefix + f"(?:{base})|{extra}"


def _power_extra(tokens: list[str]) -> str | None:
    """``NAME_<V>`` / ``NAME<digits>V`` power-form endings (scoped
    case-insensitive so the branch can merge after the base)."""
    if not tokens:
        return None
    inner = (rf"(?:[0-9A-Z_]+_({ '|'.join(tokens) })"
             rf"([0-9A-Z_]*)?|[0-9]+V([0-9A-Z_]*)?)")
    return rf"(?i:{inner})$"


def _clock_extra(tokens: list[str]) -> str | None:
    """``CLK...`` / ``OSC...`` / ``12MHZ`` name prefixes."""
    return rf"(?i:^({ '|'.join(tokens) })[0-9A-Z_]*$)"


def _exclude_extra(tokens: list[str]) -> str | None:
    """Bare bus / diff / random-name markers."""
    diff = r"_[PN]$"
    random = r"^\$?N?\d+$"
    bits = [rf"(?:{ '|'.join(tokens) })|{diff}|{random}"]
    return r"(?i:(?:" + "|".join(bits) + "))"


def learn_rules(names: list[str],
                current: dict[str, str] | None = None) -> dict:
    """Learn suggested rules + before/after statistics.

    Returns:
        {
          "rules":      suggested rule dict (current + learned branches),
          "before":     bucket counts under the CURRENT rules,
          "after":      bucket counts under the SUGGESTED rules,
          "learned":    {key: [tokens found]} for the three slots,
        }
    """
    names = [str(n).strip() for n in (names or []) if str(n).strip()]
    current = _effective_rules(current or {})
    before = count_by_category(names, current)

    others = [n for n in names if _bucket(n, current) == "Others"]
    volt = _learned_tokens(others, _VOLT_TOKENS)
    clock = _learned_tokens(others, _CLOCK_TOKENS)
    excl = _learned_tokens(others, _EXCLUDE_TOKENS)
    if any(_DIFF_MEMBER_RE.match(n) or _SYSTEM_RANDOM_RE.match(n)
           for n in others):
        excl = sorted(set(excl) | {"DIFF_PAIR"})

    suggested = dict(current)
    pe = _power_extra(volt)
    ce = _clock_extra(clock)
    ee = _exclude_extra(excl) if excl else None
    if pe:
        suggested["power"] = _merge(current.get("power"), pe)
    if ce:
        suggested["se_clock"] = _merge(current.get("se_clock"), ce)
    if ee:
        suggested["exclude"] = _merge(current.get("exclude"), ee)

    # After-buckets apply the CONFLICT rule: a net the old rules placed
    # in a definite bucket that the learned rules move elsewhere is
    # low-confidence -> Others (operator adjusts it manually).
    after = {b: 0 for b in BUCKETS}
    conflicts: list[str] = []
    for name in names:
        bucket = _bucket_conflict(name, current, suggested)
        after[bucket] += 1
        if bucket == "Others" and _bucket(name, current) != "Others":
            conflicts.append(name)
    return {
        "rules": suggested,
        "before": before,
        "after": after,
        "conflicts": conflicts,
        "learned": {
            "power": volt, "se_clock": clock, "exclude": excl,
        },
    }
