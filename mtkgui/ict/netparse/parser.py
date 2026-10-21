# -*- coding: utf-8 -*-
"""Formal "Parse Nets for ICT" orchestration (headless core).

Takes the raw NET/SPF text and extracts every valid ICT-testable net,
categorized into the three test objects:

* **Power nets**  - supply rails (VDD / VCC / nVn / VPRE ...);
* **Clock nets**  - single-ended clock nets (CLK / XTAL / OSC ...);
* **GPIO nets**   - remaining signal nets (GPIO channel candidates).

Filtered out (invalid / non-testable, with the reason kept):

* reference grounds (``gnd_ref``) move to the GND set;
* differential pairs (``diff_pair``) - not a single-ended ICT object;
* nets without any valid member pin - no test point possible;
* SIGNAL nets matching the Exclude Parse Nets regex.
"""
from __future__ import annotations

import os
import re

from .classify import classify_nets
from .formats import detect_netlist_format, parse_netlist_auto
from .model import (NET_TYPE_CLOCK_SINGLE, NET_TYPE_DIFF_PAIR,
                    NET_TYPE_GND_REF, NET_TYPE_POWER, NET_TYPE_SIGNAL,
                    ParseNetsResult)
from .netlist import read_text_any_encoding
from .rules import EXCLUDED_REASON, apply_user_rules, exclude_pattern

_FILTER_REASONS = {
    NET_TYPE_GND_REF: "reference ground (measurement loop)",
    NET_TYPE_DIFF_PAIR: "differential pair (not an ICT test object)",
    NET_TYPE_SIGNAL: "",          # placeholder, never filtered as such
}


def parse_testable_nets(net_text: str,
                        rules: dict | None = None) -> ParseNetsResult:
    """Formally parse the raw netlist text and extract the testable
    nets (headless core - unit-testable without Qt).

    Args:
        net_text: Raw netlist text (SPF or NET - auto-detected).
        rules:    User custom classification regexes (core standard
                  Step 2: user rules > system defaults; an explicit
                  empty key suppresses the name-based default for that
                  category).  GND is system-auto, never user-configured.

    Returns:
        :class:`ParseNetsResult` with the three categories.

    Raises:
        ValueError: The text contains no recognizable netlist content
                    (no nets at all) - a clear, non-silent error.
    """
    netlist = parse_netlist_auto(net_text)
    if not netlist.nets:
        raise ValueError(
            "no nets found - the file has no recognizable netlist "
            "content (wrong file or unsupported format)")
    collection = classify_nets(netlist)
    result = ParseNetsResult(total=len(collection.nets))
    result.format = detect_netlist_format(net_text)
    for rec in collection.nets:
        # Step 2: user regex override (user rules > system defaults;
        # explicit-empty key = no name matching for that category)
        rec.net_type = apply_user_rules(rec.name, rec.net_type, rules)
        # Exclude Parse Nets regex: matching SIGNAL nets never become
        # ICT test objects (user regex when configured, factory
        # default otherwise; an explicit empty value disables it)
        pattern = exclude_pattern(rules)
        if pattern and rec.net_type == NET_TYPE_SIGNAL:
            try:
                if re.search(pattern, rec.name):
                    result.filtered.append(
                        (rec.name, EXCLUDED_REASON))
                    result.filtered_records.append(rec)
                    continue
            except re.error:
                pass
        members = [t for t in rec.members if "." in t or
                   t.upper().startswith("TP")]
        if not members:
            # invalid: a net without any testable member pin cannot
            # get a test point -> filtered with the reason
            result.filtered.append(
                (rec.name, "no valid member pin (no test point)"))
            result.filtered_records.append(rec)
            continue
        if rec.net_type == NET_TYPE_POWER:
            rec.members = members
            result.power.append(rec)
        elif rec.net_type == NET_TYPE_CLOCK_SINGLE:
            rec.members = members
            result.clock.append(rec)
        elif rec.net_type == NET_TYPE_SIGNAL:
            rec.members = members
            result.gpio.append(rec)
        elif rec.net_type == NET_TYPE_GND_REF:
            # reference grounds: measurement-loop references, default
            # Do Not Test (they appear in the Parsed Nets table)
            rec.members = members
            result.gnd.append(rec)
        else:
            # diff_pair: documented, non-testable object
            result.filtered.append(
                (rec.name, _FILTER_REASONS.get(
                    rec.net_type, "not an ICT test object")))
            result.filtered_records.append(rec)
    return result


def parse_nets_file(path: str,
                    rules: dict | None = None) -> ParseNetsResult:
    """Read + formally parse a netlist file.

    Args:
        path:  Netlist file path.
        rules: User custom classification regexes.

    Returns:
        :class:`ParseNetsResult` with ``source`` set to the file name.

    Raises:
        FileNotFoundError: The path does not exist / is unreadable.
        ValueError:        The file contains no recognizable netlist.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"netlist file not found: {path}")
    result = parse_testable_nets(read_text_any_encoding(path), rules)
    result.source = os.path.basename(path)
    return result
