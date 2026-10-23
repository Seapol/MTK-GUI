# -*- coding: utf-8 -*-
"""Net-parse data model and shared constants.

Headless: no Qt, no ``mtkgui.gui`` imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field

NET_TYPE_GND_REF = "gnd_ref"
NET_TYPE_DIFF_PAIR = "diff_pair"
NET_TYPE_POWER = "power"
NET_TYPE_CLOCK_SINGLE = "clock_single"
NET_TYPE_SIGNAL = "signal"

NET_TYPES = (NET_TYPE_GND_REF, NET_TYPE_DIFF_PAIR, NET_TYPE_POWER,
             NET_TYPE_CLOCK_SINGLE, NET_TYPE_SIGNAL)

#: the ICT test-object categories (Channel Allocation order)
CATEGORY_POWER = "Power"
CATEGORY_CLOCK = "Clock"
CATEGORY_GPIO = "GPIO"
CATEGORY_GND = "GND"
CATEGORY_OTHERS = "Others"
CATEGORIES = (CATEGORY_POWER, CATEGORY_CLOCK, CATEGORY_GPIO)

#: Human-facing label for the control-IO bucket (owner naming direction
#: 2026-10-22).  The internal JSON key / constant stays ``control_io``
#: for schema stability.
CATEGORY_CONTROL_IO_LABEL = "Un-reused GPIO / EN / RST / CS / MODE"

#: ``others`` sub-classes (M2: capacity / bridge_duplicate / ambiguous)
class SubClass:
    SYSTEM_RANDOM = "system_random"
    UNCLASSIFIED = "unclassified"
    CAPACITY = "capacity"
    BRIDGE_DUPLICATE = "bridge_duplicate"
    #: determined not-tested: protocol-bus net (never an ICT object)
    INTERFACE = "interface"
    #: determined not-tested: reused / pin-multiplexed IO
    MUXED = "muxed"
    #: genuinely undecidable: >=2 class features, no winner
    AMBIGUOUS = "ambiguous"


SUBCLASS_SYSTEM_RANDOM = SubClass.SYSTEM_RANDOM
SUBCLASS_UNCLASSIFIED = SubClass.UNCLASSIFIED


@dataclass
class NetlistData:
    """Parsed netlist content.

    Attributes:
        nets:       Ordered mapping net name -> member pin tokens.
        missing_tp: Net names that carry no TP (test point) member.
    """

    nets: dict[str, list[str]] = field(default_factory=dict)
    missing_tp: list[str] = field(default_factory=list)

    def tp_of(self, net: str) -> str:
        """Return the TP member of a net ("" when it has none)."""
        for token in self.nets.get(net, []):
            if token.upper().startswith("TP"):
                return token
        return ""

    def resolutions_text(self, resolutions: dict[str, str]) -> str:
        """Render the TP resolutions chosen for missing-TP nets.

        Args:
            resolutions: net -> substituted pin, or "skip".

        Returns:
            Multi-line ``net=pin`` / ``net=skip`` text for the
            ``tp_resolutions`` parameter.
        """
        return "\n".join(f"{net}={res}"
                         for net, res in resolutions.items())


@dataclass
class NetRecord:
    """One classified net (draft state, pre test-point selection).

    Attributes:
        name:     Net name.
        members:  Member pin tokens (``U1.5``, ``J2.3``, ``TP4`` ...).
        net_type: One of :data:`NET_TYPES`.
        sub_class: ``others`` sub-class (``system_random`` /
            ``unclassified``); "" for every other bucket.
        provenance: Which rule / fallback produced the classification
            (e.g. ``rule:se_clock``, ``exclude:regex``).
        nominal / tolerance_pct / jumper_controlled:
            Business parameters bound back from the formal power tree
            by ``bind_power_tree_to_nets`` (None until bound).
        priority: M2 B1 ranking stamp
            ``{class, score, band, stage, rank}`` (None until ranked).
    """

    name: str
    members: list[str]
    net_type: str = NET_TYPE_SIGNAL
    sub_class: str = ""
    provenance: str = ""
    priority: dict | None = None
    nominal: str | None = None
    tolerance_pct: str | None = None
    jumper_controlled: bool | None = None
    is_reference_gnd: bool = False
    is_alternative_testpoint: bool = False
    confidence: str = ""    # B1: high / medium / low ("" = not stamped)
    #: M3: input-rail evidence (main power input, ranked first)
    input_rail: bool = False
    #: M3: free-text hint carried for the GUI / user (algorithm never
    #: generates notes)
    note: str = ""
    meta: dict | None = None    # B1.5 audit (conflict scores, ...)
    #: M7: DIO-write isolation assessment (control-IO nets only).
    #: True = passive-only, False = active IO source found,
    #: None = cannot confirm; ``isolation_checked`` separates "not
    #: assessed" from a real None verdict.
    isolated: bool | None = None
    active_drivers: list[str] = field(default_factory=list)
    isolation_checked: bool = False


@dataclass
class NetCollection:
    """Classified net collection (draft).

    Attributes:
        nets:       NetRecord list in netlist order.
        diff_pairs: ``(_P name, _N name)`` sibling tuples.
    """

    nets: list[NetRecord] = field(default_factory=list)
    diff_pairs: list[tuple[str, str]] = field(default_factory=list)

    def by_name(self, name: str) -> NetRecord | None:
        """Return the record for *name* (None when absent)."""
        for rec in self.nets:
            if rec.name == name:
                return rec
        return None

    def pins_of(self, refdes: str) -> dict[str, str]:
        """pin -> net mapping for one component (netlist ground truth).

        Used by the power-tree drafter and the Device Library Editor
        pin-net view.
        """
        pins: dict[str, str] = {}
        prefix = refdes + "."
        for rec in self.nets:
            for token in rec.members:
                if token.startswith(prefix):
                    pins[token[len(prefix):]] = rec.name
        return pins


@dataclass
class ParseNetsResult:
    """Formal net parse result (the Channel Allocation data source).

    Attributes:
        power / clock / control_io / others / gnd: NetRecord lists per
                              test role (``others`` carries
                              ``sub_class``).
        filtered:             (net name, reason) of every dropped net.
        filtered_records:     The dropped NetRecords (name + reason
                              above) - the Filtered Nets table uses
                              them to move a net back into the parsed
                              set.
        total:                Net count in the raw file.
        invalid_lines:        Malformed raw lines (report only).
        format:               ``detect_netlist_format()`` result.
        source:               File name when parsed from a file.
    """

    power: list[NetRecord] = field(default_factory=list)
    clock: list[NetRecord] = field(default_factory=list)
    control_io: list[NetRecord] = field(default_factory=list)
    others: list[NetRecord] = field(default_factory=list)
    gnd: list[NetRecord] = field(default_factory=list)
    filtered: list[tuple[str, str]] = field(default_factory=list)
    filtered_records: list[NetRecord] = field(default_factory=list)
    total: int = 0
    invalid_lines: list[str] = field(default_factory=list)
    format: str = ""
    source: str = ""
    #: B0 bridge merge report: {representative net: [bridged nets]}
    bridge_report: dict[str, list[str]] = field(default_factory=dict)
    #: B0 unknown-value bridge warnings (warning-budgeted)
    warnings: list[str] = field(default_factory=list)
    #: B5 user overrides applied on this result {net: class}
    user_override: dict[str, str] = field(default_factory=dict)
    #: M3 external rule layer audit: every applied external rule
    #: (id / kind / class / value / provenance / affected nets)
    applied_rules: list[dict] = field(default_factory=list)

    @property
    def gpio(self) -> list[NetRecord]:
        """Compatible view: the old ``gpio`` bucket = control IO +
        others (existing consumers keep working in this milestone)."""
        return self.control_io + self.others

    def category(self, name: str) -> str:
        """Category of one net ("" when not testable)."""
        for cat, records in (
                (CATEGORY_POWER, self.power),
                (CATEGORY_CLOCK, self.clock),
                (CATEGORY_CONTROL_IO_LABEL, self.control_io),
                (CATEGORY_OTHERS, self.others),
                (CATEGORY_GND, self.gnd)):
            if any(r.name == name for r in records):
                return cat
        return ""

    def summary(self) -> str:
        """One-line counts summary for the Event Log."""
        return (f"power={len(self.power)} clock={len(self.clock)} "
                f"control_io={len(self.control_io)} "
                f"others={len(self.others)} gnd={len(self.gnd)} "
                f"filtered={len(self.filtered)}")
