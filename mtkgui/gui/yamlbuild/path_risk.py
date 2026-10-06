# -*- coding: utf-8 -*-
"""Test path complexity risk evaluation (Parse nets for ICT).

Topology-based loop risk scoring - NO PCB layout / geometry input is
available or required.  For every net that carries an instrument test
channel (power rail voltage, SE clock, GPIO test) the algorithm walks
the netlist bridge graph from the test net to the nearest star GND
reference net and counts:

* the series passive components (R / L / C / J / SJ) on that path,
* the intermediate nets strictly between the test net and GND.

Both counts add up (capped at 10) into ``loop_risk_score``:

* 0-3   Low    - no warning,
* 4-6   Medium - yellow advisory warning,
* 7-10  High   - red critical advisory warning.

The warning is ADVISORY ONLY - it never blocks a channel assignment;
the engineer manually accepts the risk.  GND nets are the common star
reference and are never scored themselves.

Thresholds (medium / high lower bounds) are GUI-configurable and
persist in the project YAML (section ``path_risk``).  GUI layer only -
the parsing core and the test engine are untouched.
"""

from __future__ import annotations

from mtkgui.gui.yamlbuild.power_alloc import find_bridges

#: factory default score thresholds (configurable on the GUI)
DEFAULT_THRESHOLDS: dict[str, int] = {"medium_min": 4, "high_min": 7}

#: score cap (the range is 0..10)
MAX_SCORE = 10

#: risk levels
LEVEL_LOW = "Low"
LEVEL_MEDIUM = "Medium"
LEVEL_HIGH = "High"

#: fixed advisory wording (requirement 3) - shown for Medium AND High
WARNING_MESSAGE = (
    "Warning: Complex test path detected. More series passive "
    "components may introduce parasitic inductance/resistance and "
    "cause measurement inaccuracy for impedance or clock test. "
    "Please review test point placement.")


def normalize_thresholds(thresholds: dict | None) -> dict[str, int]:
    """Clamp user thresholds onto the valid domain.

    Args:
        thresholds: Raw ``{"medium_min": int, "high_min": int}``.

    Returns:
        Normalized thresholds with 1 <= medium_min < high_min <= 10.
    """
    raw = dict(thresholds or {})
    try:
        medium = int(raw.get("medium_min", DEFAULT_THRESHOLDS["medium_min"]))
    except (TypeError, ValueError):
        medium = DEFAULT_THRESHOLDS["medium_min"]
    try:
        high = int(raw.get("high_min", DEFAULT_THRESHOLDS["high_min"]))
    except (TypeError, ValueError):
        high = DEFAULT_THRESHOLDS["high_min"]
    medium = max(1, min(9, medium))
    high = max(medium + 1, min(MAX_SCORE, high))
    return {"medium_min": medium, "high_min": high}


def build_adjacency(net_members: dict[str, list[str]]) -> dict:
    """Undirected net graph from the bridge detection.

    Args:
        net_members: net name -> member pin tokens (``U1.5`` style).

    Returns:
        net -> list of ``(neighbor_net, bridge_kind)`` edges.
    """
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for bridge in find_bridges(net_members or {}):
        a, b = bridge["nets"]
        adjacency.setdefault(a, []).append((b, bridge["kind"]))
        adjacency.setdefault(b, []).append((a, bridge["kind"]))
    return adjacency


def loop_risk_score(net: str, adjacency: dict,
                    gnd_nets: set[str]) -> int:
    """Score one net's test path to the star GND reference (BFS).

    The score is ``series passives + intermediate nets`` along the
    shortest bridge path from the test net to any GND net, capped at
    :data:`MAX_SCORE`.  A GND net itself, or a net with no path to
    GND, scores 0.

    Args:
        net:       The test net (test point side).
        adjacency: Graph from :func:`build_adjacency`.
        gnd_nets:  GND reference net names (NOT scored themselves).

    Returns:
        ``loop_risk_score`` in 0..10.
    """
    if net in gnd_nets:
        return 0
    # BFS: (current net, path edges [(neighbor, kind), ...] from net)
    frontier: list[tuple[str, list[tuple[str, str]]]] = [(net, [])]
    visited = {net}
    while frontier:
        current, path = frontier.pop(0)
        for neighbor, kind in adjacency.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            next_path = [*path, (neighbor, kind)]
            if neighbor in gnd_nets:
                # path complete: passives on the path + the nets
                # strictly between the test net and GND
                passives = sum(1 for _n, k in next_path
                               if k == "passive")
                intermediates = len(next_path) - 1
                return min(MAX_SCORE, passives + intermediates)
            frontier.append((neighbor, next_path))
    return 0     # no path to the GND reference: no loop risk


def risk_level(score: int, thresholds: dict | None = None) -> str:
    """Map a score onto Low / Medium / High by the thresholds.

    Args:
        score:       ``loop_risk_score`` (0..10).
        thresholds: ``{"medium_min", "high_min"}`` (defaults apply).

    Returns:
        One of :data:`LEVEL_LOW` / :data:`LEVEL_MEDIUM` /
        :data:`LEVEL_HIGH`.
    """
    limits = normalize_thresholds(thresholds)
    if score >= limits["high_min"]:
        return LEVEL_HIGH
    if score >= limits["medium_min"]:
        return LEVEL_MEDIUM
    return LEVEL_LOW


def evaluate_paths(nets: list[str], net_members: dict[str, list[str]],
                   gnd_nets: set[str],
                   thresholds: dict | None = None) -> dict:
    """Evaluate the path risk for every scored net (headless core).

    GND nets passed in ``nets`` are skipped (requirement 7: GND only
    acts as the common star reference).

    Args:
        nets:        Net names carrying an instrument test channel.
        net_members: Net member pins (bridge graph source).
        gnd_nets:    GND reference net names.
        thresholds:  Optional GUI-configured score thresholds.

    Returns:
        ``net -> {"score", "level", "warning"}``; ``warning`` is True
        for Medium AND High (advisory only, never blocking).
    """
    gnd = set(gnd_nets or ())
    adjacency = build_adjacency(net_members or {})
    result: dict[str, dict] = {}
    for net in nets:
        if net in gnd:
            continue
        score = loop_risk_score(net, adjacency, gnd)
        level = risk_level(score, thresholds)
        result[net] = {
            "score": score,
            "level": level,
            "warning": level in (LEVEL_MEDIUM, LEVEL_HIGH),
        }
    return result
