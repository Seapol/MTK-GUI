# -*- coding: utf-8 -*-
"""Power tree draft + channel allocation core (item 24, Tasks 2-6).

Headless data model + algorithms, unit-testable without Qt:

* :class:`PowerTree`  - power net nodes, auto wiring from passive /
  regulator bridges, the passive-bridge pruning rule with audit log,
  the Stage 0..N grouping (stage increments ONLY across an active
  converter) and manual override support.
* :class:`allocate_channels` - sequential channel assignment for the
  SE clock / GPIO tables with manual overrides and the "Do Not Test"
  auto-marking once the pool is exhausted.

Persistence: every structure offers ``to_dict`` / ``from_dict`` for
the project YAML sections ``power_tree`` / ``se_clock_allocation`` /
``gpio_allocation``.  GUI layer only - the parsing core and the test
engine are untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: passive bridge components (R / L / C / J / SJ) - pruning applies
PASSIVE_RE = re.compile(r"^(R|L|C|J|SJ)\d", re.IGNORECASE)
#: every other refdes bridging two power nets counts as an ACTIVE
#: converter (DCDC / LDO / PMIC / switch) - pruning does NOT apply
#: and the stage counter increments across it.

NODE_PRIMARY = "primary"
NODE_NORMAL = "normal"
NODE_LOAD = "load"
NODE_ISLAND = "island"

#: power stage levels 0..6 (user direction: manual stage edits clamp
#: to this range; the automatic build keeps its BFS result)
MAX_STAGE = 6

#: U2355A DIO is reserved for fixture IO - GPIO tests may ONLY use
#: the DAQM907A DIO 16-ch open-drain resource (42 V / 400 mA)
GPIO_DIO_CHANNELS: tuple[str, ...] = tuple(
    f"DAQM907A DIO{n:02d}" for n in range(1, 17))
#: SE clock capture pool (rack reality: DAQM907A totalizer + the two
#: U2355A counters; the U2355A DIO stays fixture-reserved).  Each
#: resource carries a fixed frequency band (user direction):
#: DAQM907A TOT 0 ~ 100 kHz, the U2355A counters 0.1 Hz ~ 6 MHz.
CLOCK_CHANNELS: tuple[str, ...] = (
    "DAQM907A TOT", "U2355A CTR0", "U2355A CTR1")
CLOCK_BANDS: dict[str, str] = {
    "DAQM907A TOT": "0 ~ 100 kHz",
    "U2355A CTR0": "0.1 Hz ~ 6 MHz",
    "U2355A CTR1": "0.1 Hz ~ 6 MHz",
}
#: DAQM908A sense resource for the Power-net Impedance / Voltage
#: measurements: card #1 CH101-CH140, card #2 CH201-CH240
DAQM908A_SENSE_CHANNELS: tuple[str, ...] = tuple(
    f"DAQM908A #{card} CH{ch}"
    for card, base in ((1, 101), (2, 201))
    for ch in range(base, base + 40))
#: U2355A analog-input capture pool for the Power rails: the hardware
#: offers AI x16 but the GUI provides ONLY 12 channels (balanced
#: sampling rate - user direction)
U2355A_AI_CHANNELS: tuple[str, ...] = tuple(
    f"U2355A AI{n:02d}" for n in range(1, 13))

DONT_TEST = "Not Test"
ASSIGNED = "Assigned"


# ------------------------------------------------- AI topology helpers
#: voltage token inside a rail name (VDD_3V3 -> 3.3, 5V_USB -> 5,
#: VDD_0V8_P2 -> 0.8, DCDC_1V8 -> 1.8, 12V -> 12)
_VOLT_RE = re.compile(
    r"(?<![0-9A-Za-z])(\d{1,2})V(\d{1,2})?(?![0-9A-Za-z])")
#: input-supply name patterns (primary fallback heuristic)
_PRIMARY_RE = re.compile(
    r"(?i)(^VIN|_VIN|^V\w*BUS|VBUS|VBAT|^DC_|_IN$|VPWR)")


def voltage_from_name(name: str) -> str | None:
    """Parse the rail voltage encoded in a net name.

    Args:
        name: Power net name (``VDD_3V3``, ``DCDC_1V8``, ``5V_USB``).

    Returns:
        The voltage as a plain string (``"3.3"``, ``"5"``) or None
        when the name carries no voltage token.
    """
    m = _VOLT_RE.search(name or "")
    if not m:
        return None
    whole, frac = m.group(1), m.group(2)
    value = float(f"{whole}.{frac}") if frac else float(whole)
    return f"{value:g}"


def auto_primaries(power: list[str], bridges: list[dict]) -> list[str]:
    """Heuristic primary (source) detection for the power tree.

    Every bridge (passive AND regulator) with two decodable unequal
    rail voltages is directed from the HIGHER voltage to the LOWER
    one; nodes without an incoming directed edge become stage-0
    primaries (the BFS then assigns the stages - no more all-stage-1
    islands).  When no voltage pair is decodable the input-supply
    name pattern (VIN / VBUS / VBAT / DC_ / *_IN) is used as the
    fallback heuristic.

    Args:
        power:   Power net names.
        bridges: Bridge dicts (``find_bridges`` output).

    Returns:
        The primary net names (possibly empty - the caller falls back
        to the island default).
    """
    volts = {p: voltage_from_name(p) for p in power}
    incoming: set[str] = set()
    directed = False
    for bridge in bridges:
        a, c = bridge["nets"]
        va, vc = volts.get(a), volts.get(c)
        if va and vc and float(va) != float(vc):
            src, dst = ((a, c) if float(va) > float(vc) else (c, a))
            incoming.add(dst)
            directed = True
    if directed:
        primaries = sorted(set(power) - incoming)
        return primaries or sorted(set(power))
    return sorted(p for p in power if _PRIMARY_RE.search(p))


def auto_fill_voltage(tree: "PowerTree") -> int:
    """Auto-fill Expected Voltage from the rail-name voltage token and
    the +/-5 % limit tolerances (user direction: the automation does
    the groundwork, the user edits afterwards).  Nodes already carrying
    a voltage (manual override) are never touched; names without a
    voltage token stay blank for manual entry.

    Args:
        tree: The built power tree draft.

    Returns:
        The number of nodes whose voltage was auto-filled.
    """
    filled = 0
    for node in tree.nodes.values():
        if node.expected_voltage:
            continue
        volt = voltage_from_name(node.name)
        if not volt:
            continue
        node.expected_voltage = volt
        if not node.tol_upper:
            node.tol_upper = "5%"
        if not node.tol_lower:
            node.tol_lower = "5%"
        filled += 1
    return filled


# --------------------------------------------------------------- bridges
def find_bridges(net_members: dict[str, list[str]]) -> list[dict]:
    """Detect passive / regulator bridges between power-style nets.

    A bridge is any reference designator whose pins sit on exactly
    two different nets; its kind is ``passive`` for R/L/C/J/SJ
    prefixes and ``regulator`` (active) for everything else.

    Args:
        net_members: net name -> member pin tokens (``U1.5`` style).

    Returns:
        List of ``{"refdes", "kind", "nets": (netA, netB)}`` dicts.
    """
    refdes_nets: dict[str, set[str]] = {}
    for net, members in (net_members or {}).items():
        for token in members:
            refdes = token.split(".")[0].split("-")[0].split("[")[0]
            if not refdes or refdes.upper().startswith("TP"):
                continue
            refdes_nets.setdefault(refdes, set()).add(net)
    bridges: list[dict] = []
    for refdes, nets in sorted(refdes_nets.items()):
        if len(nets) != 2:
            continue
        a, b = sorted(nets)
        kind = ("passive" if PASSIVE_RE.match(refdes)
                else "regulator")
        bridges.append({"refdes": refdes, "kind": kind,
                        "nets": (a, b)})
    return bridges


# ------------------------------------------------------------- power tree
@dataclass
class PowerNode:
    """One node of the power tree draft (Task 2)."""

    name: str
    node_type: str = NODE_NORMAL      # primary / normal / load / island
    dont_test: bool = False
    expected_voltage: str = ""
    tol_upper: str = ""
    tol_lower: str = ""
    dependencies: str = ""            # firmware / enable signal / ...
    upstream: list[str] = field(default_factory=list)
    downstream: list[str] = field(default_factory=list)
    stage: int | None = None
    stage_override: int | None = None
    row: int | None = None            # manual canvas row (vertical drag)
    pruned: bool = False
    pruned_reason: str = ""
    locked: bool = False              # load nodes: read-only

    def to_dict(self) -> dict:
        return {
            "name": self.name, "node_type": self.node_type,
            "dont_test": self.dont_test,
            "expected_voltage": self.expected_voltage,
            "tol_upper": self.tol_upper, "tol_lower": self.tol_lower,
            "dependencies": self.dependencies,
            "upstream": list(self.upstream),
            "downstream": list(self.downstream),
            "stage": self.stage,
            "stage_override": self.stage_override,
            "row": self.row,
            "pruned": self.pruned, "pruned_reason": self.pruned_reason,
            "locked": self.locked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PowerNode":
        node = cls(name=str(data.get("name") or ""))
        for key in ("node_type", "expected_voltage", "tol_upper",
                    "tol_lower", "dependencies", "pruned_reason"):
            if data.get(key):
                setattr(node, key, str(data[key]))
        for key in ("upstream", "downstream"):
            value = data.get(key)
            if isinstance(value, list):
                setattr(node, key, [str(v) for v in value])
        for key in ("dont_test", "pruned", "locked"):
            setattr(node, key, bool(data.get(key)))
        if data.get("stage") is not None:
            node.stage = int(data["stage"])
        if data.get("stage_override") is not None:
            node.stage_override = int(data["stage_override"])
        if data.get("row") is not None:
            node.row = int(data["row"])
        return node


class PowerTree:
    """The power tree draft graph (nodes + directed edges + stages)."""

    def __init__(self) -> None:
        self.nodes: dict[str, PowerNode] = {}
        self.audit_log: list[dict] = []   # pruning audit trail
        self.adjacency: dict[str, list[tuple[str, str]]] = {}

    def assign_stages(self, _bridges: list[dict] | None = None) -> None:
        """Re-run the BFS stage assignment (Task 3): primaries are
        stage 0, the stage increments ONLY across an active converter
        bridge.  Manual ``stage_override`` values always win."""
        for node in self.nodes.values():
            if node.stage_override is None:
                node.stage = None
        visited = {n for n, node in self.nodes.items()
                   if node.node_type == NODE_PRIMARY}
        frontier = [(n, 0) for n in visited]
        while frontier:
            name, stage = frontier.pop(0)
            for neighbor, kind in self.adjacency.get(name, []):
                child = self.nodes.get(neighbor)
                if child is None or neighbor in visited:
                    continue
                visited.add(neighbor)
                step = 1 if kind == "regulator" else 0
                if child.stage_override is not None:
                    child.stage = child.stage_override
                    stage_next = child.stage
                else:
                    stage_next = stage + step
                    child.stage = stage_next
                frontier.append((neighbor, stage_next))
        for node in self.nodes.values():
            if node.stage is None:
                node.stage = 1     # islands: first conversion default

    # ------------------------------------------------------------- build
    @classmethod
    def build(cls, power_nets: list[str],
              bridges: list[dict],
              primaries: list[str] | None = None) -> "PowerTree":
        """Auto-build the draft: one node per filtered power net, the
        bridges form an undirected adjacency, then a BFS from every
        primary directs the edges (upstream = closer to a primary)
        and assigns the stages."""
        tree = cls()
        primaries = list(primaries or [])
        for name in power_nets:
            tree.nodes[name] = PowerNode(
                name=name,
                node_type=(NODE_PRIMARY if name in primaries
                           else NODE_ISLAND))
        # undirected adjacency: neighbor -> (name, kind)
        adjacency: dict[str, list[tuple[str, str]]] = {}
        for bridge in bridges:
            a, b = bridge["nets"]
            if a in tree.nodes and b in tree.nodes:
                adjacency.setdefault(a, []).append((b, bridge["kind"]))
                adjacency.setdefault(b, []).append((a, bridge["kind"]))
        tree.adjacency = adjacency
        # BFS from the primaries: direct the edges + assign stages
        visited: set[str] = {n for n in tree.nodes
                             if n in primaries}
        frontier = [(p, 0) for p in primaries if p in tree.nodes]
        while frontier:
            name, stage = frontier.pop(0)
            node = tree.nodes.get(name)
            if node is not None and node.stage_override is None:
                node.stage = stage
            for neighbor, kind in adjacency.get(name, []):
                child = tree.nodes.get(neighbor)
                if child is None or neighbor in visited:
                    continue
                visited.add(neighbor)
                step = 1 if kind == "regulator" else 0
                child.stage = stage + step
                if neighbor not in node.downstream:
                    node.downstream.append(neighbor)
                if name not in child.upstream:
                    child.upstream.append(name)
                frontier.append((neighbor, child.stage))
        tree._classify()
        for node in tree.nodes.values():
            if node.stage is None:
                node.stage = 1     # islands: first conversion default
        return tree

    def _classify(self) -> None:
        """Node types: primaries stay primary; nodes without any
        upstream reference stay island; nodes without downstream are
        load candidates (grey read-only)."""
        for node in self.nodes.values():
            if node.node_type == NODE_PRIMARY:
                continue
            if not node.upstream:
                node.node_type = NODE_ISLAND
            elif not node.downstream:
                node.node_type = NODE_LOAD
                node.locked = True
            else:
                node.node_type = NODE_NORMAL

    # ------------------------------------------------------------ pruning
    def prune_passive(self, bridges: list[dict]) -> list[dict]:
        """Pruning rule (Task 2): two power nets connected ONLY via a
        passive R/L/C/J/SJ bridge -> keep the load-side net, prune
        the upstream one from the tree (it stays in the global net
        list).  Active converter bridges skip pruning.  Every prune
        is written to the audit log and can be restored manually."""
        pruned: list[dict] = []
        for bridge in bridges:
            if bridge["kind"] != "passive":
                continue
            a, b = bridge["nets"]
            na, nb = self.nodes.get(a), self.nodes.get(b)
            if na is None or nb is None or na.pruned or nb.pruned:
                continue
            # direction: the node listing the other as downstream is
            # upstream; default to (a upstream) when undetermined
            if a in nb.upstream or b in na.downstream:
                upstream, load = na, nb
            elif b in na.upstream or a in nb.downstream:
                upstream, load = nb, na
            else:
                upstream, load = na, nb
            upstream.pruned = True
            upstream.pruned_reason = (
                f"passive bridge {bridge['refdes']} -> load-side "
                f"{load.name} kept")
            self.audit_log.append({
                "net": upstream.name,
                "reason": upstream.pruned_reason,
                "refdes": bridge["refdes"], "kept": load.name,
            })
            pruned.append({"net": upstream.name, "kept": load.name,
                           "refdes": bridge["refdes"]})
        return pruned

    def restore_pruned(self, net_name: str) -> bool:
        """Manual restore of one pruned node (audit stays)."""
        node = self.nodes.get(net_name)
        if node is None or not node.pruned:
            return False
        node.pruned = False
        node.pruned_reason = ""
        self.audit_log.append({"net": net_name,
                               "reason": "manual restore",
                               "refdes": "", "kept": ""})
        return True

    def active_nodes(self) -> list[PowerNode]:
        """Non-pruned nodes in insertion order."""
        return [n for n in self.nodes.values() if not n.pruned]

    # ------------------------------------------------- manual graph edits
    def derive_downstream(self) -> None:
        """The downstream links are NOT user-defined (user direction:
        a node only defines its upstream) - they are derived as the
        exact reverse of the upstream links of the whole tree."""
        for node in self.nodes.values():
            node.downstream = []
        for node in self.nodes.values():
            for up in node.upstream:
                if up in self.nodes and up != node.name:
                    parent = self.nodes[up]
                    if node.name not in parent.downstream:
                        parent.downstream.append(node.name)

    def rebuild_adjacency(self) -> None:
        """Rebuild the undirected adjacency from the stored upstream /
        downstream links (after a YAML load or manual flow-arrow
        edits); every manual link counts as a regulator hop for the
        stage BFS (manual stage overrides always win)."""
        adjacency: dict[str, list[tuple[str, str]]] = {}
        for node in self.nodes.values():
            for up in node.upstream:
                if up in self.nodes and up != node.name:
                    adjacency.setdefault(up, []).append(
                        (node.name, "regulator"))
                    adjacency.setdefault(node.name, []).append(
                        (up, "regulator"))
        self.adjacency = adjacency

    def _reaches(self, start: str, goal: str) -> bool:
        """BFS over the downstream links: can ``start`` reach ``goal``."""
        seen: set[str] = set()
        frontier = [start]
        while frontier:
            name = frontier.pop(0)
            if name == goal:
                return True
            if name in seen:
                continue
            seen.add(name)
            frontier.extend(self.nodes[name].downstream
                            if name in self.nodes else [])
        return False

    def link(self, source: str, target: str) -> tuple[bool, str]:
        """Manual flow-arrow link (GUI drag): ``source`` becomes THE
        upstream of ``target``.  Rules (user direction):

        * the upstream reference stays UNIQUE - a previous upstream is
          replaced (the old edge is removed on both ends);
        * a primary power input NEVER gets an upstream;
        * self-links and cycles are rejected.

        Returns ``(ok, message)``; on success the tree is
        re-classified, the adjacency rebuilt and the stages re-run
        (overrides preserved)."""
        src = self.nodes.get(source)
        dst = self.nodes.get(target)
        if src is None or dst is None or src.pruned or dst.pruned:
            return False, "unknown or pruned node"
        if source == target:
            return False, "a node cannot reference itself"
        if dst.node_type == NODE_PRIMARY:
            return False, (f"{target} is the primary power input - "
                           "it has no upstream")
        if source in dst.upstream:
            return True, "link already exists"
        # consistency first: the downstream side is derived
        self.derive_downstream()
        if self._reaches(target, source):
            return False, "link rejected: it would create a cycle"
        # unique upstream: the new link REPLACES the previous one; the
        # downstream side follows from the upstream links
        dst.upstream = [source]
        self.audit_log.append({
            "net": target,
            "reason": f"manual flow link: {source} -> {target}",
            "refdes": "", "kept": ""})
        self.derive_downstream()
        self._classify()
        self.rebuild_adjacency()
        self.assign_stages()
        return True, f"linked {source} -> {target}"

    def set_stage(self, name: str, stage: int) -> int:
        """Manual stage edit (horizontal drag): clamps to 0..MAX_STAGE,
        stores the override and re-runs the stage BFS.  Returns the
        clamped stage."""
        stage = max(0, min(MAX_STAGE, int(stage)))
        node = self.nodes.get(name)
        if node is None or node.pruned:
            return stage
        node.stage_override = stage
        node.stage = stage
        self.assign_stages()
        return stage

    # -------------------------------------------------------- persistence
    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "audit_log": list(self.audit_log),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PowerTree":
        tree = cls()
        for node_data in (data or {}).get("nodes") or []:
            node = PowerNode.from_dict(node_data)
            if node.name:
                tree.nodes[node.name] = node
        tree.audit_log = [dict(a) for a in
                          (data or {}).get("audit_log") or []]
        # the downstream side is derived from the upstream links (a
        # draft saved with manual downstream lists is normalized)
        tree.derive_downstream()
        return tree


# ---------------------------------------------------------- allocators
def allocate_channels(nets: list[str], pool: tuple[str, ...],
                      overrides: dict[str, str] | None = None
                      ) -> list[dict]:
    """Sequential channel assignment (Tasks 4 / 5).

    Nets are assigned pool channels in order; once the pool is
    consumed the remaining nets are auto-marked ``Not Test``.  A
    manual override (net -> channel or ``Not Test``) always wins.

    Args:
        nets:      Ordered net names (filtered candidates only).
        pool:      Available channels in assignment order.
        overrides: Manual channel / "Not Test" per net.

    Returns:
        Rows: ``{"net", "channel", "status"}`` with status
        Assigned / Not Test.
    """
    overrides = overrides or {}
    free = list(pool)
    rows: list[dict] = []
    for net in nets:
        override = (overrides.get(net) or "").strip()
        if override == DONT_TEST:
            rows.append({"net": net, "channel": "", "status": DONT_TEST})
            continue
        if override:
            rows.append({"net": net, "channel": override,
                         "status": ASSIGNED})
            if override in free:
                free.remove(override)
            continue
        if free:
            rows.append({"net": net, "channel": free.pop(0),
                         "status": ASSIGNED})
        else:
            rows.append({"net": net, "channel": "",
                         "status": DONT_TEST})
    return rows
