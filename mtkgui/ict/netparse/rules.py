# -*- coding: utf-8 -*-
"""Net classification rules + user-regex override (item 24, Task 1).

Classification priority (highest -> lowest):

1. Manual single-net override
2. SPF pin attribute (POWER / GND / CLOCK / DIFF pin types)
3. User custom regex (project YAML ``net_classification_rules``)
4. Factory default regex

An EMPTY user regex skips the name matching step for that category -
classification then relies fully on the SPF pin attribute (and the
default regex for the remaining categories still applies; an empty
DEFAULT is treated the same way).  Headless: the Qt dialog lives in
``mtkgui.gui.yamlbuild.net_rules``.
"""
from __future__ import annotations

import re

from .model import (NET_TYPE_CLOCK_SINGLE, NET_TYPE_DIFF_PAIR,
                    NET_TYPE_POWER, NET_TYPE_SIGNAL)

#: M3: frozen base rule-set version (exported in the JSON output as
#: ``rules_version`` and in the ``--export-base`` snapshot)
RULES_VERSION = "2.0"

CATEGORY_POWER = "Power"
CATEGORY_GND = "GND"
CATEGORY_SE_CLOCK = "SE Clock"
CATEGORY_DIFF_PAIR = "Diff Pair"
CATEGORY_SIGNAL = "Signal"

#: the editable rule slots (key -> (label, factory default regex)).
#: GND is a SYSTEM-auto category (no user config entry - core standard
#: 5.2); its default regex stays internal for the GND integrity check.
RULE_SLOTS: tuple[tuple[str, str], ...] = (
    ("power", "Power Nets regex"),
    ("se_clock", "SE Clock Nets regex"),
    ("exclude", "Exclude Parse Nets regex"),
)

DEFAULT_RULES: dict[str, str] = {
    "power": r"^(?!.+INTB)(?:V(DD|CC|IN|OUT|PRE|SYS|BAT|BUS|AUX|CORE|IO|A|D)([0-9_].*)?|[0-9]+([.][0-9]+)?V([0-9A-Z_]*)?|P[35][V_][0-9A-Z_]*|(DCDC|DC)_([0-9]+([.][0-9]+)?V)([0-9A-Z_]*)?|[0-9A-Z_]*V(OUT|REF|SW|PWR|FB)[0-9A-Z_]*|[0-9A-Z_]+_(1V0|1V2|1V5|1V8|2V5|3V3|5V|12V|24V)([0-9A-Z_]*)?)$",
    "gnd": r"^(GND\w*|AGND\w*|DGND\w*|PGND\w*|VSS\w*)$",
    "se_clock": r"^(CLK\w*|OSC\w*|XTAL\w*|MCLK\w*|\d+MH?Z\w*)$",
    # nets matching the Exclude regex NEVER become ICT test objects
    # (differential pairs, Reset / Enable / UART / WAKE / I2C / SPI /
    # JTAG / DBGIF / DATA / ADC buses and Allegro system random
    # numeric names); an EMPTY value disables the exclusion entirely.
    # The differential PAIR DETECTION stays a kernel-internal rule
    # (no user config entry).
    "exclude": (r"(?i)(DIFF|RESET|ENABLE|UART|WAKE|I2C|SPI|JTAG|"
                r"DBGIF|DATA|ADC|_EN(_|$)|_(P|N)$|^\$?N?\d+$)"),
    "diff_pair": r"^\w+_(P|N)$",
}

# SPF pin attribute words -> category (higher priority than regex)
_PIN_TYPE_MAP: dict[str, str] = {
    "POWER": CATEGORY_POWER,
    "PWR": CATEGORY_POWER,
    "GND": CATEGORY_GND,
    "GROUND": CATEGORY_GND,
    "CLOCK": CATEGORY_SE_CLOCK,
    "CLK": CATEGORY_SE_CLOCK,
    "DIFF": CATEGORY_DIFF_PAIR,
    "DIFFERENTIAL": CATEGORY_DIFF_PAIR,
}

#: fixed exclusion patterns for the GPIO candidate extraction (Task 5)
GPIO_EXCLUDE_RE = re.compile(
    r"(RESET|SENSE|FEEDBACK|_EN\b|ENABLE|INT\b|INTERRUPT|ANALOG|"
    r"AGND|DIFF|_P$|_N$|TEST_|TP\d)", re.IGNORECASE)

#: user-rule category -> kernel net type (Step 2 override mapping)
_USER_RULE_TYPES = {
    "power": NET_TYPE_POWER,
    "se_clock": NET_TYPE_CLOCK_SINGLE,
    "diff_pair": NET_TYPE_DIFF_PAIR,
}

#: exclusion reason wording (Exclude Parse Nets regex matches)
EXCLUDED_REASON = "excluded by Exclude Parse Nets regex"

#: Allegro auto-generated system-random net names
SYSTEM_RANDOM_RE = re.compile(r"^\$?N?\d+$")

#: interface / pin-multiplex markers: a name carrying one of these is
#: a reused IO, NOT a chip-control IO (owner decision 2026-10-22).
#: M2 Fix 1/2: the FULL B2 rule-2 protocol token list, word-anchored
#: ``(^|_)`` so ``MIPI_CSI0_RST_B`` / ``EMMC_RST_B`` / ``PCIE_RST_B`` /
#: ``SDA_RST_BUFF`` are determined not-tested, while ``DDR0_CS0``
#: (memory chip-select, owner-confirmed) stays control IO.
PROTOCOL_TOKENS = (
    "I2C", "SCL", "SDA", "SPI", "QSPI", "UART", "TX", "RX", "CAN",
    "USB", "SD", "SDHC", "USDHC", "EMMC", "UFS", "PCIE", "ETH", "ENET",
    "RGMII", "MII", "SGMII", "SAI", "ESAI", "I2S", "PSI5", "MIPI",
    "DBGIF", "JTAG", "SWD", "SWCLK", "TCK", "1588", "TRACE", "PHY",
    "SERDES", "LINK", "SPDIF", "MLB", "SIM",
)
#: mux / reuse indicator TOKENS (M3: table form so an external rule
#: layer can add/remove tokens per run); the compiled MUX_RE is built
#: from this tuple
MUX_TOKENS = ("GPIO", "ALT", "MUX", "IOMUX", "REUSE", "FMUX")


def _word_anchored(tokens) -> re.Pattern:
    """Word-anchored ``(^|_)TOKEN`` matcher for a token tuple."""
    return re.compile(
        r"(^|_)(" + "|".join(tokens) + r")([0-9A-Z_]*)?", re.IGNORECASE)


#: compiled word-anchored protocol matcher (one shared definition)
PROTOCOL_RE = _word_anchored(PROTOCOL_TOKENS)
#: mux / reuse indicators: GPIO token, parenthesised mux marker or an
#: explicit ``_ALT`` / ``_MUX`` / ``_IOMUX`` / ``_REUSE`` / ``_FMUX``
#: suffix (spec M2 Fix 1)
MUX_RE = _word_anchored(MUX_TOKENS)
_PAREN_RE = re.compile(r"\([^)]*\)")
#: FPGA names are also reused-JTAG / interface carriers (M1 kept them
#: out of control IO; preserved here for the same pre-filter)
_CONTROL_IO_INTERFACE_RE = re.compile(
    r"(^|_)(FPGA)([0-9A-Z_]*)?" + "|" + PROTOCOL_RE.pattern,
    re.IGNORECASE)


def protocol_token(name: str) -> str:
    """First protocol token matched in *name* ("" = none).

    Deterministic: the leftmost word-anchored match.
    """
    if not name:
        return ""
    match = PROTOCOL_RE.search(name)
    return match.group(2).upper() if match else ""


def is_muxed(name: str) -> bool:
    """True when *name* carries a mux / reuse indicator."""
    if not name:
        return False
    if _PAREN_RE.search(name):
        return True
    return bool(MUX_RE.search(name))

#: control-semantic rule tables: anchored TOKENS per rule id + the
#: shared suffix shape (M3: table form so an external layer can remove
#: a token per run).  Active-low / rail suffixes (_B, _N, _3.3V,
#: numeric indices) are accepted after the token.
_CONTROL_IO_TOKENS: dict[str, tuple[tuple[str, ...], str]] = {
    "reset": ((  "RESET", "RST"),
              r"(?:[0-9]*)(?:_?[BN])?(?:[_0-9][0-9A-Z._+#-]*)?$"),
    "enable": (("ENABLE", "EN"),
               r"(?:(?:[0-9][0-9A-Z._+#-]*)|(?:_[0-9A-Z._+#-]+)|[BN])?$"),
    "cs":     (("CSB", "CS_N", "CSN", "CS"),
               r"(?:[0-9]*)(?:_?[ABN])?$"),
    "mode":   (("MODE", "BOOTMOD", "BOOT"),
               r"(?:[0-9_][0-9A-Z._+#-]*)?$"),
}


def build_control_io_rules(removed: tuple[str, ...] = ()) \
        -> tuple[tuple[str, re.Pattern], ...]:
    """Compile the control-IO rules, dropping *removed* tokens.

    A rule whose token list becomes empty is dropped entirely.
    """
    rules = []
    for rule_id, (anchors, suffix) in _CONTROL_IO_TOKENS.items():
        kept = tuple(a for a in anchors if a.upper() not in
                     {t.upper() for t in removed})
        if not kept:
            continue
        rules.append((rule_id, re.compile(
            r"(?:^|_)(?:" + "|".join(kept) + r")" + suffix,
            re.IGNORECASE)))
    return tuple(rules)


_CONTROL_IO_RULES: tuple[tuple[str, re.Pattern], ...] = \
    build_control_io_rules()


def control_io_rule(name: str) -> str:
    """Return the control-IO rule id for *name* ("" = not control IO).

    The carrier precondition: no parenthesized reuse marker
    (``GPIO7(MAC2_RGMII_TXCLK)`` is REUSED) and no interface/mux
    marker.  A plain un-reused GPIO without a control token is NOT
    control IO.
    """
    if not name or "(" in name:
        return ""
    if _CONTROL_IO_INTERFACE_RE.search(name):
        return ""
    for rule_id, pattern in _CONTROL_IO_RULES:
        if pattern.search(name):
            return rule_id
    return ""


def exclude_pattern(rules: dict | None) -> str:
    """The active exclusion pattern: the user's Exclude Parse Nets
    regex when configured, the factory default otherwise; an explicit
    EMPTY user value disables the exclusion entirely."""
    rules = rules or {}
    if "exclude" in rules:
        return (rules.get("exclude") or "").strip()
    return DEFAULT_RULES["exclude"]


def apply_user_rules(name: str, net_type: str,
                     rules: dict | None) -> str:
    """Step 2 user-regex override (user rules > system defaults).

    For every user-configured category (Power / SE Clock / Diff Pair
    - GND is system-auto and never overridden): a non-empty user
    pattern that matches the name re-classifies the net; an explicit
    EMPTY pattern suppresses the kernel's name-based default for that
    category (the net falls to Signal).  Categories without a user
    key keep the kernel classification unchanged.
    """
    rules = rules or {}
    matched_user = False
    for key, net_cls in _USER_RULE_TYPES.items():
        if key not in rules:
            continue
        pattern = (rules.get(key) or "").strip()
        if not pattern:
            continue
        try:
            if re.match(pattern, name):
                return net_cls
        except re.error:
            continue
        matched_user = True     # this category HAS a working pattern
    if not matched_user:
        # explicit-empty categories suppress the kernel name default
        for key, net_cls in _USER_RULE_TYPES.items():
            if key in rules and not (rules.get(key) or "").strip() \
                    and net_type == net_cls:
                return NET_TYPE_SIGNAL
    return net_type


def validate_rules(rules: dict[str, str]) -> list[str]:
    """Pre-save validation of the four regex fields.

    Checks syntax AND catastrophic backtracking risk (nested
    quantifiers such as ``(a+)+`` / ``(a|aa)+``).

    Returns:
        List of human readable error strings (empty = safe to save).
    """
    errors: list[str] = []
    for key, label in RULE_SLOTS:
        pattern = (rules.get(key) or "").strip()
        if not pattern:
            continue                    # empty = skip name matching
        try:
            parsed = re.compile(pattern)
        except re.error as exc:
            errors.append(f"{label}: invalid regex syntax ({exc})")
            continue
        if _has_nested_quantifier(parsed):
            errors.append(
                f"{label}: catastrophic backtracking risk (nested "
                "quantifier) - simplify the pattern")
    return errors


def _has_nested_quantifier(parsed) -> bool:
    """True when a repeated group contains another unbounded repeat
    (the classic catastrophic backtracking shape)."""
    import sre_parse
    if isinstance(parsed, re.Pattern):
        parsed = parsed.pattern and sre_parse.parse(parsed.pattern)
    SUBPATTERN, MAX_REPEAT = sre_parse.SUBPATTERN, sre_parse.MAX_REPEAT

    def walk(nodes, inside_repeat: bool) -> bool:
        for op, av in nodes:
            if op is MAX_REPEAT:
                lo, hi, item = av
                unbounded = hi == sre_parse.MAXREPEAT or hi > 1
                if inside_repeat and unbounded:
                    return True
                if walk(item, inside_repeat or unbounded):
                    return True
            elif op is SUBPATTERN:
                if walk(av[-1], inside_repeat):
                    return True
            elif op is sre_parse.BRANCH:
                for branch in av[1]:
                    if walk(branch, inside_repeat):
                        return True
            elif op is sre_parse.IN:
                if walk(av, inside_repeat):
                    return True
        return False

    try:
        return walk(parsed, False)
    except Exception:                   # pragma: no cover - parse guard
        return False


def classify_net(name: str,
                 spf_pin_type: str = "",
                 rules: dict[str, str] | None = None,
                 manual: str = "") -> str:
    """Classify one net name by the priority chain.

    Args:
        name:         Net name.
        spf_pin_type: SPF pin attribute ("" when unknown).
        rules:        User custom regexes ("" / missing key = skip).
        manual:       Manual single-net override (category name; wins
                      over everything).

    Returns:
        One of Power / GND / SE Clock / Diff Pair / Signal.
    """
    if manual:
        return manual
    pin = (spf_pin_type or "").strip().upper()
    if pin in _PIN_TYPE_MAP:
        return _PIN_TYPE_MAP[pin]
    rules = rules or {}
    for key, category in (("power", CATEGORY_POWER),
                          ("gnd", CATEGORY_GND),
                          ("se_clock", CATEGORY_SE_CLOCK),
                          ("signal", CATEGORY_SIGNAL),
                          ("diff_pair", CATEGORY_DIFF_PAIR)):
        if key in rules:
            # item 24 Task 1: an EXPLICITLY EMPTY custom regex skips
            # the name matching entirely for this category (no
            # factory fallback) - classification relies on the SPF
            # pin attribute then
            pattern = (rules.get(key) or "").strip()
            if pattern:
                try:
                    if re.match(pattern, name):
                        return category
                except re.error:
                    continue
        else:
            pattern = DEFAULT_RULES.get(key, "")
            if pattern and re.match(pattern, name):
                return category
    return CATEGORY_SIGNAL
