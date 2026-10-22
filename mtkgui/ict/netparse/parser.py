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

from .bridge import merge_power_bridges
from .classify import classify_nets
from .confidence import resolve_conflicts, stamp_confidence
from .formats import detect_netlist_format, parse_netlist_auto
from .model import (NET_TYPE_CLOCK_SINGLE, NET_TYPE_DIFF_PAIR,
                    NET_TYPE_GND_REF, NET_TYPE_POWER, NET_TYPE_SIGNAL,
                    SUBCLASS_SYSTEM_RANDOM, SUBCLASS_UNCLASSIFIED,
                    ParseNetsResult)
from .netlist import read_text_any_encoding
from .rules import (EXCLUDED_REASON, SYSTEM_RANDOM_RE, apply_user_rules,
                    control_io_rule, exclude_pattern)

_FILTER_REASONS = {
    NET_TYPE_GND_REF: "reference ground (measurement loop)",
    NET_TYPE_DIFF_PAIR: "differential pair (not an ICT test object)",
    NET_TYPE_SIGNAL: "",          # placeholder, never filtered as such
}


def parse_testable_nets(net_text: str, rules: dict | None = None,
                        library: dict[str, str] | None = None,
                        external: dict | None = None) \
        -> ParseNetsResult:
    """Formally parse the raw netlist text and extract the testable
    nets (headless core - unit-testable without Qt).

    Args:
        net_text: Raw netlist text (SPF or NET - auto-detected).
        rules:    User custom classification regexes (core standard
                  Step 2: user rules > system defaults; an explicit
                  empty key suppresses the name-based default for that
                  category).  GND is system-auto, never user-configured.
        library:  Optional ``refdes -> part_number`` map (M2 device
                  knowledge base, built from the BOM).  ``None``
                  keeps the M1 no-library behaviour unchanged.
        external: Optional M3 external learnable rule layer
                  (:mod:`.rule_layers` merged JSON).  ``None`` keeps
                  the M2 behaviour unchanged (backward compatible).

    Returns:
        :class:`ParseNetsResult` with the three categories.

    Raises:
        ValueError: The text contains no recognizable netlist content
                    (no nets at all) - a clear, non-silent error.
    """
    from contextlib import nullcontext

    from .rule_layers import (apply_reweight, classify_external_hits,
                              layer_context, route_external)

    netlist = parse_netlist_auto(net_text)
    if not netlist.nets:
        raise ValueError(
            "no nets found - the file has no recognizable netlist "
            "content (wrong file or unsupported format)")
    ext_log: list[dict] = []
    with (layer_context(external, ext_log) if external
          else nullcontext()):
        collection = classify_nets(netlist, library)
        result = ParseNetsResult(total=len(collection.nets))
        result.format = detect_netlist_format(net_text)
        hits = classify_external_hits(collection, external) \
            if external else {}
        for rec in collection.nets:
            # M3 external layer: owner-confirmed rules beat the base
            # tables INCLUDING the Exclude regex (entries first, then
            # token adds; every hit is auditable via applied_rules)
            hit = hits.get(rec.name)
            if hit:
                route_external(result, rec, hit)
                result.applied_rules.append(
                    {"id": hit["id"], "kind": hit["kind"],
                     "class": hit["class"], "value": hit["value"],
                     "provenance": f"external:{hit['id']}",
                     "nets": [rec.name]})
                continue
            # Step 2: user regex override (user rules > system defaults;
            # explicit-empty key = no name matching for that category)
            physical_type = rec.net_type
            rec.net_type = apply_user_rules(rec.name, rec.net_type, rules)
            if rec.net_type != physical_type:
                rec.provenance = "user_rule"
            # Exclude Parse Nets regex: matching SIGNAL nets never become
            # ICT test objects (user regex when configured, factory
            # default otherwise; an explicit empty value disables it)
            pattern = exclude_pattern(rules)
            if pattern and rec.net_type == NET_TYPE_SIGNAL:
                try:
                    if re.search(pattern, rec.name):
                        # Exclude wins over Control-IO keywords (interface
                        # buses are never tested); the sub-class still tells
                        # an auto-generated random name apart.
                        rec.sub_class = (
                            SUBCLASS_SYSTEM_RANDOM
                            if SYSTEM_RANDOM_RE.match(rec.name)
                            else SUBCLASS_UNCLASSIFIED)
                        rec.provenance = "exclude:regex"
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
                # test-role split (owner direction 2026-10-22):
                # control IO = chip-control tokens on an un-reused IO;
                # everything else is "others" (system_random/unclassified).
                rule = control_io_rule(rec.name)
                if rule:
                    rec.provenance = f"control_io:{rule}"
                    rec.members = members
                    result.control_io.append(rec)
                elif SYSTEM_RANDOM_RE.match(rec.name):
                    rec.sub_class = SUBCLASS_SYSTEM_RANDOM
                    rec.provenance = "rule:system_random"
                    rec.members = members
                    result.others.append(rec)
                else:
                    rec.sub_class = SUBCLASS_UNCLASSIFIED
                    rec.provenance = "fallback:unclassified"
                    rec.members = members
                    result.others.append(rec)
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
        # M2 B1: every classified net carries a confidence
        stamp_confidence(result, library)
        if external:
            # M3 reweight AFTER the B1 stamp (external override)
            apply_reweight(result, external, ext_log)
        if library:
            # M2 B0: passive-bridge rail merge (power only, library mode)
            result.bridge_report = merge_power_bridges(result, library)
            # M2 B1.5: cross-class conflict resolution (library mode)
            resolve_conflicts(result, library)
    if external:
        result.applied_rules.extend(ext_log)
    return result


def parse_nets_file(path: str, rules: dict | None = None,
                    library: dict[str, str] | None = None,
                    external: dict | None = None) \
        -> ParseNetsResult:
    """Read + formally parse a netlist file.

    Args:
        path:     Netlist file path.
        rules:    User custom classification regexes.
        library:  Optional M2 library.
        external: Optional M3 external rule layer.

    Returns:
        :class:`ParseNetsResult` with ``source`` set to the file name.

    Raises:
        FileNotFoundError: The path does not exist / is unreadable.
        ValueError:        The file contains no recognizable netlist.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"netlist file not found: {path}")
    result = parse_testable_nets(read_text_any_encoding(path), rules,
                                 library, external)
    result.source = os.path.basename(path)
    return result


#: B5 override target class -> bucket attribute
_OVERRIDE_BUCKETS = {
    "power": "power", "clock": "clock", "control_io": "control_io",
    "others": "others",
}


def apply_user_overrides(result: ParseNetsResult,
                         overrides: dict[str, str]) -> dict[str, str]:
    """B5: apply a ``{net: class}`` user-override map in place.

    The override takes precedence over the algorithmic class: the net
    record is moved to the target bucket (``power`` / ``clock`` /
    ``control_io`` / ``others``).  Returns the applied subset.
    """
    if not overrides:
        return {}
    buckets = ("power", "clock", "control_io", "others", "gnd")
    applied: dict[str, str] = {}
    for net, target in overrides.items():
        target = str(target).strip().lower()
        if target not in _OVERRIDE_BUCKETS:
            continue
        found = None
        for bucket in buckets:
            for rec in getattr(result, bucket):
                if rec.name == net:
                    found = (bucket, rec)
                    break
            if found:
                break
        if not found:
            continue
        bucket, rec = found
        if bucket == target:
            applied[net] = target
            continue
        getattr(result, bucket).remove(rec)
        if target == "others":
            rec.net_type = NET_TYPE_SIGNAL
            rec.sub_class = SUBCLASS_UNCLASSIFIED
        else:
            rec.net_type = (NET_TYPE_POWER if target == "power"
                            else NET_TYPE_CLOCK_SINGLE
                            if target == "clock" else NET_TYPE_SIGNAL)
            rec.sub_class = ""
        rec.provenance = "user_override"
        rec.confidence = "high"
        getattr(result, _OVERRIDE_BUCKETS[target]).append(rec)
        applied[net] = target
    if applied:
        result.user_override = dict(applied)
    return applied
