# -*- coding: utf-8 -*-
"""M3 rule-layer architecture: frozen base + external learnable rules.

The M1+M2 rule set is FROZEN as the base library (module constants,
:data:`mtkgui.ict.netparse.rules.RULES_VERSION`).  An EXTERNAL,
learnable JSON rule library (schema ``mtkgui.ict.netparse.rules.v1``)
layers ON TOP for this run WITHOUT touching code:

* ``tokens.add``      - word-anchored tokens classified BEFORE the
                        generic base tables (owner-confirmed wins);
* ``tokens.remove``   - a base token deleted for this run (the base
                        module tables are patched per run and restored
                        afterwards);
* ``tokens.reweight`` - a confidence override for one class token;
* ``device_roles.add``- extra part-number markers for this run;
* ``clock_nominal_freq.add`` - extra nominal-frequency table entries;
* ``entries``         - verbatim regex rules evaluated BEFORE the
                        generic token tables (exact name wins).

Every applied rule is recorded (``ParseNetsResult.applied_rules`` /
JSON ``applied_rules``) so any result stays auditable.  With no
external file the behaviour is IDENTICAL to M2 (backward compatible).

Learn-loop support: :func:`suggest` extracts learnable candidates
from low-confidence / ambiguous nets for a HUMAN review gate (no
auto-apply), and :func:`regression_gate` protects the five approved
projects from learned-rule regressions.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager

from . import classify, confidence, device_roles, isolation, rules
from .model import (NET_TYPE_CLOCK_SINGLE, NET_TYPE_POWER,
                    NET_TYPE_SIGNAL, ParseNetsResult)

RULES_SCHEMA = "mtkgui.ict.netparse.rules.v1"
BASE_SCHEMA = "mtkgui.ict.netparse.base_rules.v1"

#: token classes an external file may add tokens to
_ADD_KEYS = ("power", "clock", "control_io", "interface", "mux")
_REMOVE_KEYS = ("power", "clock", "control_io", "interface", "mux")
_WEIGHTS = ("high", "medium", "low")

_CLASS_TYPES = {"power": NET_TYPE_POWER, "clock": NET_TYPE_CLOCK_SINGLE,
                "control_io": NET_TYPE_SIGNAL}


def is_external_rules(data: dict) -> bool:
    """True when a ``--rules`` JSON is an M3 external rule library."""
    return isinstance(data, dict) and str(
        data.get("schema", "")).startswith("mtkgui.ict.netparse.rules")


def load_external(paths: list[str]) -> dict:
    """Load + merge external rule files in the given order.

    Merge semantics: ``add`` appends, ``remove`` accumulates,
    ``reweight`` / ``device_roles.add`` / ``clock_nominal_freq.add``
    merge by key (later files override earlier), ``entries`` are
    concatenated in file order.
    """
    merged: dict = {
        "schema": RULES_SCHEMA, "version": "1.0",
        "applies_to": ["all"],
        "tokens": {"add": {k: [] for k in _ADD_KEYS},
                   "remove": {k: [] for k in _REMOVE_KEYS},
                   "reweight": {}},
        "device_roles": {"add": {}},
        "clock_nominal_freq": {"add": {}},
        "isolation": {"passive_prefixes": [], "active_roles": [],
                      "active_categories": []},
        "entries": []}
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except OSError as exc:
            raise ValueError(f"cannot read external rules file: "
                             f"{exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid external rules JSON "
                             f"({path}): {exc}") from exc
        if not is_external_rules(data):
            raise ValueError(
                f"{path}: not an external rules file (schema "
                f"{RULES_SCHEMA} expected)")
        tokens = data.get("tokens") or {}
        for key in _ADD_KEYS:
            merged["tokens"]["add"][key] += [
                str(t) for t in (tokens.get("add") or {}).get(key, [])]
        for key in _REMOVE_KEYS:
            merged["tokens"]["remove"][key] += [
                str(t) for t in (tokens.get("remove") or {}).get(key, [])]
        for cls, weights in (tokens.get("reweight") or {}).items():
            slot = merged["tokens"]["reweight"].setdefault(str(cls), {})
            for token, weight in (weights or {}).items():
                if str(weight).lower() not in _WEIGHTS:
                    raise ValueError(
                        f"{path}: invalid reweight weight "
                        f"{weight!r} for token {token!r}")
                slot[str(token)] = str(weight).lower()
        merged["device_roles"]["add"].update(
            {str(k): str(v) for k, v in
             (data.get("device_roles") or {}).get("add", {}).items()})
        merged["clock_nominal_freq"]["add"].update(
            {str(k): str(v) for k, v in
             (data.get("clock_nominal_freq") or {}).get("add", {}).items()})
        # M7: DIO-write isolation tables (add semantics, same learning
        # mechanism as the token / device-role sections)
        iso = data.get("isolation") or {}
        for key in ("passive_prefixes", "active_roles",
                    "active_categories"):
            merged["isolation"][key] += [
                str(value) for value in (iso.get(key) or [])]
        for entry in data.get("entries", []):
            if not entry.get("pattern") or not entry.get("class"):
                raise ValueError(
                    f"{path}: external entry needs 'pattern' and "
                    f"'class'")
            try:
                re.compile(str(entry["pattern"]))
            except re.error as exc:
                raise ValueError(
                    f"{path}: invalid entry pattern "
                    f"{entry['pattern']!r}: {exc}") from exc
            if entry["class"] not in dict(_CLASS_TYPES, others="others"):
                raise ValueError(
                    f"{path}: invalid entry class {entry['class']!r}")
            merged["entries"].append(dict(entry))
        merged["version"] = str(data.get("version") or merged["version"])
    return merged


# ------------------------------------------------------------- base dump
def export_base_rules() -> dict:
    """Read-only snapshot of the CURRENT frozen base rule set.

    The module code remains the authoritative base; this snapshot is
    for audit / comparison (``--export-base``).
    """
    from .capacity import DEFAULT_LIMITS
    return {
        "schema": BASE_SCHEMA,
        "rules_version": rules.RULES_VERSION,
        "regex": dict(rules.DEFAULT_RULES),
        "tokens": {
            "power": list(confidence._POWER_WEAK_TOKENS),
            "clock": list(classify._CLOCK_PREFIX_TOKENS)
                     + list(classify._CRYSTAL_TOKENS)
                     + list(classify._CLOCK_SUFFIX_TOKENS),
            "control_io": sorted({a for anchors, _ in
                                  rules._CONTROL_IO_TOKENS.values()
                                  for a in anchors}),
            "interface": list(rules.PROTOCOL_TOKENS),
            "mux": list(rules.MUX_TOKENS),
        },
        "clock_exclusions": {
            "iface_anchor": list(classify._CLOCK_IFACE_ANCHOR_TOKENS),
            "iface2": list(classify._CLOCK_IFACE2_TOKENS),
        },
        "device_roles": {role: list(markers) for role, markers in
                         device_roles._ROLE_MARKERS.items()},
        "clock_nominal_freq": [{"pattern": pattern.pattern, "hz": hz}
                               for pattern, hz in confidence._NOMINAL_HZ],
        # M7: DIO-write isolation tables (control-IO active/passive)
        "isolation": {
            "active_roles": sorted(isolation.ACTIVE_ROLES),
            "active_categories": sorted(isolation.ACTIVE_CATEGORIES),
            "passive_prefixes": sorted(isolation.PASSIVE_PREFIXES)},
        "thresholds": {"conflict_high": confidence.CONFLICT_HIGH},
        "capacity_defaults": {
            "power_pts": DEFAULT_LIMITS.power_pts,
            "rails_up": DEFAULT_LIMITS.rails_up,
            "clock_lf": DEFAULT_LIMITS.clock_lf,
            "clock_hf": DEFAULT_LIMITS.clock_hf,
            "ctrl_io": DEFAULT_LIMITS.ctrl_io},
    }


# ------------------------------------------------------- per-run patching
def _filtered(tokens, removed: set[str]) -> tuple:
    return tuple(t for t in tokens if t.upper() not in removed)


@contextmanager
def layer_context(ext: dict, log: list | None = None):
    """Patch the base token tables for ONE parse run, then restore.

    Covers ``tokens.remove`` (protocol / mux / clock / control_io /
    power token tables), ``device_roles.add`` and
    ``clock_nominal_freq.add``.  The removals and additions are
    recorded into *log* as applied-rule audit entries.
    """
    removed = {key: {t.upper() for t in
                     (ext.get("tokens") or {}).get("remove", {}).get(key, [])}
               for key in _REMOVE_KEYS}
    saved: list[tuple] = []

    def patch(module, name, value):
        saved.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    try:
        if removed["interface"]:
            proto = _filtered(rules.PROTOCOL_TOKENS, removed["interface"])
            patch(rules, "PROTOCOL_TOKENS", proto)
            patch(rules, "PROTOCOL_RE", rules._word_anchored(proto))
            patch(rules, "_CONTROL_IO_INTERFACE_RE", re.compile(
                r"(^|_)(FPGA)([0-9A-Z_]*)?|"
                + rules._word_anchored(proto).pattern, re.IGNORECASE))
            patch(confidence, "_PROTOCOL_RE", re.compile(
                "|".join(list(proto) + ["GPIO"]), re.IGNORECASE))
        if removed["mux"]:
            mux = _filtered(rules.MUX_TOKENS, removed["mux"])
            patch(rules, "MUX_TOKENS", mux)
            patch(rules, "MUX_RE", rules._word_anchored(mux))
        if removed["clock"]:
            patch(classify, "_CLOCK_PREFIX_TOKENS",
                  _filtered(classify._CLOCK_PREFIX_TOKENS,
                            removed["clock"]))
            patch(classify, "_CLOCK_PREFIX_RE", re.compile(
                r"(^|_)("
                + "|".join(classify._CLOCK_PREFIX_TOKENS)
                + r")([0-9_].*)?$", re.IGNORECASE))
            patch(classify, "_CRYSTAL_TOKENS",
                  _filtered(classify._CRYSTAL_TOKENS, removed["clock"]))
            patch(classify, "_CRYSTAL_TOKEN_RE", re.compile(
                r"(^|_)("
                + "|".join(classify._CRYSTAL_TOKENS)
                + r")([0-9A-Z_]*)?$", re.IGNORECASE))
            patch(classify, "_CLOCK_SUFFIX_TOKENS",
                  _filtered(classify._CLOCK_SUFFIX_TOKENS,
                            removed["clock"]))
            patch(classify, "_CLOCK_SUFFIX_RE", re.compile(
                r"("
                + "|".join("_" + t for t in classify._CLOCK_SUFFIX_TOKENS)
                + r")([0-9_]*)$", re.IGNORECASE))
        # the clock interface-exclusion tables mix base clock tokens
        # (SPI / MLB / ...) with protocol tokens (ENET / MIPI / PCIE):
        # BOTH the clock and the interface removal lists apply here
        iface_removed = removed["clock"] | removed["interface"]
        if iface_removed:
            patch(classify, "_CLOCK_IFACE_ANCHOR_TOKENS",
                  _filtered(classify._CLOCK_IFACE_ANCHOR_TOKENS,
                            iface_removed))
            patch(classify, "_CLOCK_IFACE_ANCHOR_RE", re.compile(
                r"(^|_)("
                + "|".join(classify._CLOCK_IFACE_ANCHOR_TOKENS)
                + r")([0-9A-Z_]*)?", re.IGNORECASE))
        if removed["control_io"]:
            patch(rules, "_CONTROL_IO_RULES",
                  rules.build_control_io_rules(tuple(removed["control_io"])))
        if removed["power"]:
            patch(confidence, "_POWER_WEAK_TOKENS",
                  _filtered(confidence._POWER_WEAK_TOKENS,
                            removed["power"]))
            patch(confidence, "_POWER_WEAK_RE", re.compile(
                "|".join(confidence._POWER_WEAK_TOKENS), re.IGNORECASE))

        role_add = (ext.get("device_roles") or {}).get("add") or {}
        if role_add:
            merged = {role: list(markers) for role, markers in
                      device_roles._ROLE_MARKERS.items()}
            for marker, role in role_add.items():
                if role not in merged:
                    raise ValueError(
                        f"device_roles.add: unknown role {role!r} "
                        f"(clock_gen|interface|fpga|load|control_chip)")
                merged[role] = list(merged[role]) + [marker]
            patch(device_roles, "_ORDERED",
                  device_roles.build_ordered(merged))

        freq_add = (ext.get("clock_nominal_freq") or {}).get("add") or {}
        if freq_add:
            extra = []
            for token, hz in freq_add.items():
                try:
                    extra.append((re.compile(re.escape(token),
                                             re.IGNORECASE), float(hz)))
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"clock_nominal_freq.add: invalid hz for "
                        f"{token!r}: {hz!r}") from exc
            patch(confidence, "_NOMINAL_HZ",
                  tuple(confidence._NOMINAL_HZ) + tuple(extra))
        yield
    finally:
        for module, name, value in reversed(saved):
            setattr(module, name, value)
    if log is not None:
        for key in _REMOVE_KEYS:
            for token in sorted((ext.get("tokens") or {})
                                .get("remove", {}).get(key, [])):
                log.append({"id": f"remove:{token}", "kind":
                            "tokens.remove", "class": key,
                            "value": token,
                            "provenance": "external:tokens.remove"})


# -------------------------------------------------- external classification
def _token_hit(name: str, tokens: list[str]) -> str:
    """First added token matching *name* word-anchored ("" = none)."""
    for token in tokens:
        if re.search(r"(^|_)" + re.escape(token) + r"([0-9A-Z_]*)?",
                     name, re.IGNORECASE):
            return token
    return ""


def classify_external_hits(collection, ext: dict) -> dict[str, dict]:
    """Per-net external classification (entries first, then tokens).

    Returns ``{net name: hit}`` where hit carries ``id / kind / class /
    sub_class / value``.  GND / diff-pair records are never touched.
    """
    hits: dict[str, dict] = {}
    entries = [(re.compile(str(e["pattern"])), e)
               for e in ext.get("entries", [])]
    add = (ext.get("tokens") or {}).get("add") or {}
    for rec in collection.nets:
        if rec.net_type in ("gnd_ref", "diff_pair"):
            continue
        for pattern, entry in entries:
            if pattern.search(rec.name):
                hits[rec.name] = {
                    "id": str(entry.get("id") or "entry"),
                    "kind": "entry", "class": str(entry["class"]),
                    "sub_class": str(entry.get("sub_class") or ""),
                    "value": entry["pattern"]}
                break
        if rec.name in hits:
            continue
        for key in _ADD_KEYS:
            token = _token_hit(rec.name, add.get(key, []))
            if not token:
                continue
            hits[rec.name] = {
                "id": f"token:{token}", "kind": "tokens.add",
                "class": "others" if key in ("interface", "mux")
                else key,
                "sub_class": key if key in ("interface", "mux") else "",
                "value": token}
            break
    return hits


def route_external(result: ParseNetsResult, rec, hit: dict) -> None:
    """Route one externally-classified record into its bucket."""
    rec.members = [t for t in rec.members
                   if "." in t or t.upper().startswith("TP")]
    class_key = hit["class"]
    rec.net_type = _CLASS_TYPES.get(class_key, NET_TYPE_SIGNAL)
    rec.provenance = f"external:{hit['id']}"
    rec.sub_class = hit.get("sub_class", "")
    bucket = ("others" if class_key == "others"
              else class_key if class_key in _CLASS_TYPES else "others")
    getattr(result, bucket).append(rec)


def apply_reweight(result: ParseNetsResult, ext: dict,
                   log: list | None = None) -> None:
    """Confidence reweight (``tokens.reweight``): override the B1
    confidence of classified nets carrying the token."""
    reweight = (ext.get("tokens") or {}).get("reweight") or {}
    for cls, weights in reweight.items():
        if cls not in ("power", "clock", "control_io"):
            continue
        applied: list[str] = []
        for rec in getattr(result, cls):
            token = _token_hit(rec.name, list(weights))
            if token:
                rec.confidence = weights[token]
                applied.append(rec.name)
        if applied and log is not None:
            log.append({"id": f"reweight:{cls}", "kind": "reweight",
                        "class": cls,
                        "value": json.dumps(weights, sort_keys=True),
                        "provenance": "external:reweight",
                        "nets": applied})


# ---------------------------------------------------------------- suggest
_COMMON = {"BB", "DUT", "R", "RN", "TP", "J", "U", "N", "TP1"}


def suggest(result: ParseNetsResult, library: dict | None = None) \
        -> list[dict]:
    """Learnable-rule candidates from low-confidence nets (human
    review gate - NO auto-apply).

    Sources: ``others`` nets with ``sub_class`` ambiguous /
    unclassified plus classified nets with ``low`` confidence.  Each
    candidate carries ``{candidate, suggested_action, class, reason,
    evidence}``; a repeated unknown member part number produces a
    ``device_roles.add`` suggestion.
    """
    from .device_roles import role_for_part_number

    known = ({t.upper() for t in rules.PROTOCOL_TOKENS}
             | {t.upper() for t in rules.MUX_TOKENS}
             | {t.upper() for t in classify._CLOCK_PREFIX_TOKENS}
             | {t.upper() for t in classify._CRYSTAL_TOKENS}
             | {t.upper() for t in classify._CLOCK_SUFFIX_TOKENS}
             | {a.upper() for anchors, _ in
                rules._CONTROL_IO_TOKENS.values() for a in anchors}
             | {t.upper() for t in confidence._POWER_WEAK_TOKENS}
             | _COMMON)
    hint_classes = (
        (re.compile(r"CLK|XTAL|OSC|MCLK|REFCLK|SUSCLK", re.I), "clock"),
        (re.compile(r"VDD|VCC|V BAT|VBAT|VIN|PWR|V[0-9]", re.I), "power"),
        (re.compile(r"RST|RESET|_EN|CS|MODE|BOOT", re.I), "control_io"))
    candidates: list[dict] = []
    refdes_nets: dict[str, set[str]] = {}
    pool: list = []
    for rec in result.others:
        if rec.sub_class in ("ambiguous", "unclassified"):
            pool.append(rec)
    for bucket in ("power", "clock", "control_io"):
        pool.extend(r for r in getattr(result, bucket)
                    if r.confidence == "low")
    for rec in pool:
        name = rec.name
        current = ("others/" + rec.sub_class
                   if rec.sub_class else result.category(name) or "signal")
        target = next((cls for pattern, cls in hint_classes
                       if pattern.search(name)), "")
        tokens = [t for t in re.split(r"[^A-Za-z0-9]+", name) if t]
        unknown = sorted({t for t in tokens
                          if t.upper() not in known and len(t) >= 3},
                         key=lambda t: (-len(t), t))
        if target and unknown:
            action = f"tokens.add.{target} += [\"{unknown[0]}\"]"
            reason = (f"token {unknown[0]} is not in the base tables; "
                      f"name hints {target}")
        else:
            action = f"entry ^{re.escape(name)}$ -> {target or 'others'}"
            reason = ("no class-hint token; a verbatim owner-reviewed "
                      "entry is the safe learnable rule")
        candidates.append({
            "candidate": name,
            "suggested_action": action,
            "class": target or "others",
            "reason": reason,
            "evidence": {"current": current,
                         "confidence": rec.confidence,
                         "provenance": rec.provenance}})
        for token in rec.members:
            refdes = token.split(".", 1)[0]
            if "." in token:
                refdes_nets.setdefault(refdes, set()).add(name)
    if library:
        seen: dict[str, str] = {}
        for refdes, nets in refdes_nets.items():
            entry = library.get(refdes)
            if not entry:
                continue
            info = entry if isinstance(entry, dict) else \
                {"part_number": str(entry), "description": ""}
            if role_for_part_number(info.get("part_number", ""),
                                    info.get("description", "")):
                continue
            pn = info.get("part_number") or ""
            if pn and len(nets) >= 2:
                seen[refdes] = pn
        for refdes, pn in sorted(seen.items()):
            candidates.append({
                "candidate": refdes,
                "suggested_action": f"device_roles.add += {{\"{pn}\": "
                                    f"\"<role>\"}}",
                "class": "device_roles",
                "reason": (f"part {pn} repeats on "
                           f"{len(refdes_nets[refdes])} candidate nets "
                           f"and has no known device role"),
                "evidence": {"nets": sorted(refdes_nets[refdes])}})
    return candidates


# ---------------------------------------------------------------- gate
def regression_gate(baseline: dict, current: dict) -> tuple[bool, list]:
    """M3 1.4 regression gate over the five approved projects.

    Args:
        baseline: ``{pid: {"overall": x, "legacy": y, "amb": n}}``
                  (approved snapshot, recomputed with the SAME metric).
        current:  same shape from the re-run.

    Returns:
        ``(ok, violations)`` - ok is True when for EVERY project
        ``overall`` and ``legacy`` do not decrease and ``amb`` does
        not increase.
    """
    violations: list[str] = []
    for pid, base in baseline.items():
        cur = current.get(pid)
        if cur is None:
            violations.append(f"{pid}: missing current metrics")
            continue
        if cur["overall"] < base["overall"] - 1e-9:
            violations.append(
                f"{pid}: overall_conf {cur['overall']:.3f} < baseline "
                f"{base['overall']:.3f}")
        if cur["legacy"] < base["legacy"] - 1e-9:
            violations.append(
                f"{pid}: legacy_conf {cur['legacy']:.3f} < baseline "
                f"{base['legacy']:.3f}")
        if cur["amb"] > base["amb"]:
            violations.append(
                f"{pid}: ambiguous {cur['amb']} > baseline "
                f"{base['amb']}")
    return (not violations), violations
