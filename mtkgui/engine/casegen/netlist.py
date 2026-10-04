# -*- coding: utf-8 -*-
"""Netlist source parsing for the AI case-generation closed loop.

Accepted source formats (all parsed offline, deterministic):

* Netlist (``.net``) - simple text netlist::

      # comment
      NET 3V3 U1.VDD C2.1 R5.2
      RAIL 3V3 FROM 5V LDO
      SEQ 3V3 2          # power-up sequence order (timing test)
      NET CLKOUT1 U3.4
      NET GPIO1 U1.10 R2.1

* Schematic (``.sch`` / ``.json``) - JSON dump::

      {"nets": {"3V3": ["U1.VDD", "C2.1"], ...},
       "rails": [{"rail": "3V3", "from": "5V", "via": "LDO"}]}

* ICT Excel template (``.xlsx``) - first sheet with a header row that
  must contain a net-name column (``NET`` / ``Net`` / ``网络名称``);
  optional columns: CLASS/类型, FROM, SEQ, VOLTAGE.  Unknown columns
  are ignored so vendor templates keep working.

The parser only extracts facts (nets, classes, rail topology); every
judgement (thresholds, priorities, grouping) lives in generator.py.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

CLASS_POWER = "power"
CLASS_CLOCK = "clock"
CLASS_SIGNAL = "signal"

_POWER_RE = re.compile(
    r"(^|\b)(v\d+[a-z]?_\d+[a-z]|vbat|vdd|vcc|vbus|vsys|pwr|[125]v[0-9]?[a-z]?|"
    r"3v3|1v8|2v5|1v2|5v0|vpp|vref)\b", re.IGNORECASE)
_CLOCK_RE = re.compile(
    r"(clk|clock|xtal|osc|32\.768|mclk|rtc)", re.IGNORECASE)
_SEQ_RE = re.compile(r"(\d+(\.\d+)?v)", re.IGNORECASE)


@dataclass
class RailEdge:
    """One power-tree edge: child rail fed from parent rail."""
    rail: str
    parent: str
    via: str = ""

    def log_line(self) -> str:
        return (f"[CASEGEN] rail {self.rail} <- {self.parent}"
                + (f" (via {self.via})" if self.via else ""))


@dataclass
class NetEntry:
    """One normalized net: identity, class and provenance."""
    name: str
    pins: list[str] = field(default_factory=list)
    net_class: str = CLASS_SIGNAL
    source: str = "netlist"
    rail_parent: str = ""
    via: str = ""
    seq: int = 0
    nominal_v: float | None = None


def _classify(name: str) -> str:
    if _CLOCK_RE.search(name):
        return CLASS_CLOCK
    if _POWER_RE.search(name):
        return CLASS_POWER
    return CLASS_SIGNAL


def _nominal_voltage(name: str) -> float | None:
    # "3V3"/"1V8" style -> 3.3 / 1.8 ; "5V" -> 5.0
    m = re.search(r"(\d+(?:\.\d+)?)V(\d+)?", name, re.IGNORECASE)
    if m:
        base = float(m.group(1))
        frac = m.group(2)
        if frac:
            return base + int(frac) / 10 ** len(frac)
        return base
    if name.upper() in ("VBAT",):
        return 3.7
    return None


def _clean_name(name: str) -> str:
    """Unified naming: trim, collapse blanks, keep case (nets are
    case-sensitive in hardware, but dedupe is case-insensitive)."""
    return " ".join(str(name).split())


class NetlistParser:
    """Multi-source net extraction with normalization rules applied:
    dedupe, empty-net drop, same-name merge, naming unification."""

    def __init__(self, log_fn=None):
        self.log = log_fn or (lambda line: None)

    def _emit(self, line: str) -> None:
        self.log(line)

    # ----------------------------------------------------------- parse
    def parse(self, path: str) -> dict[str, NetEntry]:
        lower = str(path).lower()
        if lower.endswith((".json", ".sch")):
            entries = self._parse_schematic(path)
        elif lower.endswith((".net", ".txt", ".netlist")):
            entries = self._parse_net_text(path)
        elif lower.endswith(".xlsx"):
            entries = self._parse_excel(path)
        else:
            raise ValueError(
                f"[CASEGEN] unsupported source file {path!r} "
                "(expected .net / .json / .xlsx)")
        entries = self._normalize(entries)
        self._emit(f"[CASEGEN] parsed {path!r}: {len(entries)} net(s)")
        return entries

    # ------------------------------------------------------- text net
    def _parse_net_text(self, path: str) -> tuple[dict[str, NetEntry],
                                                  list[RailEdge]]:
        nets: dict[str, list[str]] = {}
        rails: list[RailEdge] = []
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith(("#", "*", "//", ";")):
                    continue
                parts = line.split()
                head = parts[0].upper()
                if head == "NET" and len(parts) >= 2:
                    nets.setdefault(parts[1], []).extend(parts[2:])
                elif head == "RAIL" and len(parts) >= 4 \
                        and parts[2].upper() == "FROM":
                    rails.append(RailEdge(rail=parts[1], parent=parts[3],
                                          via=parts[4] if len(parts) > 4
                                          else ""))
                elif head == "SEQ" and len(parts) >= 3:
                    rails.append(RailEdge(rail=parts[1], parent="",
                                          via=f"seq:{parts[2]}"))
        self._rails_meta = rails
        out: dict[str, NetEntry] = {}
        for name, pins in nets.items():
            e = NetEntry(name=name, pins=pins,
                         net_class=_classify(name))
            e.nominal_v = _nominal_voltage(name)
            for r in rails:
                if r.rail == name and r.via.startswith("seq:"):
                    e.seq = int(r.via.split(":", 1)[1])
            out[name] = e
        return out

    # ----------------------------------------------------- schematic
    def _parse_schematic(self, path: str) -> dict[str, NetEntry]:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        nets = doc.get("nets") or {}
        rails = [RailEdge(rail=r.get("rail", ""),
                          parent=r.get("from") or r.get("parent", ""),
                          via=r.get("via", ""))
                 for r in (doc.get("rails") or [])]
        self._rails_meta = rails
        out: dict[str, NetEntry] = {}
        for name, pins in nets.items():
            e = NetEntry(name=name, pins=[str(p) for p in pins],
                         net_class=_classify(name), source="schematic")
            e.nominal_v = _nominal_voltage(name)
            for r in rails:
                if r.rail == name and r.via.startswith("seq:"):
                    e.seq = int(r.via.split(":", 1)[1])
            out[name] = e
        return out

    # --------------------------------------------------------- excel
    def _parse_excel(self, path: str) -> dict[str, NetEntry]:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return {}
        header = [str(c or "").strip().upper() for c in rows[0]]
        col = {h: i for i, h in enumerate(header)}
        name_key = next((k for k in ("NET", "NETNAME", "网络名称",
                                     "NET NAME") if k in col), None)
        if name_key is None:
            raise ValueError("[CASEGEN] excel template: no net-name "
                             f"column in header {header}")
        cls_i = col.get("CLASS") or col.get("类型")
        from_i = col.get("FROM")
        seq_i = col.get("SEQ")
        self._rails_meta = []
        out: dict[str, NetEntry] = {}
        for row in rows[1:]:
            name = row[col[name_key]] if col[name_key] < len(row) else None
            name = _clean_name(name or "")
            if not name or name.lower() in ("net", "-"):
                continue
            e = NetEntry(name=name, source="excel")
            if cls_i is not None and cls_i < len(row) and row[cls_i]:
                c = str(row[cls_i]).strip().lower()
                e.net_class = (c if c in (CLASS_POWER, CLASS_CLOCK,
                                          CLASS_SIGNAL)
                               else _classify(name))
            else:
                e.net_class = _classify(name)
            if from_i is not None and from_i < len(row) and row[from_i]:
                parent = _clean_name(row[from_i])
                e.rail_parent = parent
                self._rails_meta.append(RailEdge(rail=name, parent=parent))
            if seq_i is not None and seq_i < len(row) and row[seq_i]:
                try:
                    e.seq = int(row[seq_i])
                except (TypeError, ValueError):
                    pass
            e.nominal_v = _nominal_voltage(name)
            out[name] = e
        return out

    # ---------------------------------------------------- normalize
    def _normalize(self, entries: dict) -> dict[str, NetEntry]:
        """Auto-regularization: merge same-name nets (case-insensitive),
        drop empty nets, unify names.  Keys keep the original net
        spelling; dedupe is case-insensitive."""
        merged: dict[str, NetEntry] = {}
        seen: dict[str, str] = {}          # lower name -> original key
        for e in entries.values():
            key = e.name.lower()
            if key in seen:
                base = merged[seen[key]]
                for p in e.pins:
                    if p not in base.pins:
                        base.pins.append(p)
                self._emit(f"[CASEGEN] merged duplicate net "
                           f"{e.name!r} into {base.name!r}")
                continue
            if not e.name:
                self._emit("[CASEGEN] dropped empty net name")
                continue
            seen[key] = e.name
            merged[e.name] = e
        # drop fully-empty text-netlist nets (no pins and no topology
        # role); excel/schematic nets are name-only by design
        rail_names = {r.rail for r in getattr(self, "_rails_meta", [])}
        for name in [n for n, e in merged.items()
                     if not e.pins and e.source == "netlist"
                     and n not in rail_names and not e.rail_parent]:
            self._emit(f"[CASEGEN] dropped empty net {name!r}")
            del merged[name]
        # apply rail parents
        for r in getattr(self, "_rails_meta", []):
            if r.parent and r.rail in merged:
                merged[r.rail].rail_parent = r.parent
                merged[r.rail].via = r.via
        return merged

    def power_tree(self, entries: dict[str, NetEntry]) -> dict[str, list[str]]:
        """Parent -> child rails adjacency (upstream-first)."""
        tree: dict[str, list[str]] = {}
        for e in entries.values():
            if e.net_class == CLASS_POWER and e.rail_parent:
                tree.setdefault(e.rail_parent, []).append(e.name)
        return tree


def rail_depth(entries: dict[str, NetEntry], name: str) -> int:
    """Depth in the power tree (source rail = 0) - used for priority."""
    depth, cur, seen = 0, name, set()
    while True:
        e = entries.get(cur)
        if e is None or not e.rail_parent or cur in seen:
            return depth
        seen.add(cur)
        cur = e.rail_parent
        depth += 1
