# -*- coding: utf-8 -*-
"""AI case generation: parsed nets -> standard ICT YAML test cases.

Deterministic rule engine (offline "AI"): cross-references netlist /
schematic / excel sources into a normalized net model, extracts the
power tree, classifies the three test dimensions (impedance / voltage /
power-up timing waveform) and emits a standard ``ict_test_cases`` YAML
draft the engine already knows how to schedule.

Standard thresholds (mass-production defaults, engineer-editable in
the review Excel):
  * impedance: R >= 1.5 ohm (short detection floor)
  * voltage:   nominal +/- 1.0 % window
  * clock:     nominal +/- 200 ppm window (frequency in Hz)
  * timing:    power-up sequence waveform capture (op + test rows)
"""
from __future__ import annotations

from datetime import datetime, timezone

from .netlist import (CLASS_CLOCK, CLASS_POWER, CLASS_SIGNAL,
                      NetlistParser, rail_depth)

AI_GEN_VERSION = "P1-16.1"

IMPEDANCE_MIN_OHM = 1.5
VOLTAGE_TOL_PCT = 1.0
CLOCK_PPM = 200

# per-class instrument assignment (engine instrument abbreviations)
INSTRUMENTS = {CLASS_POWER: "DAQM", CLASS_CLOCK: "DAQ",
               CLASS_SIGNAL: "DAQM"}

# optional YAML keys this module owns (documented in interface_spec.md)
EXTRA_FIELDS = ("priority", "power_domain", "upstream", "downstream",
                "instrument", "test_dim", "notes", "ai_meta")


def _case(name: str, kind: str, unit: str, lo, hi, *, dim: str,
          e=None, extra: dict | None = None) -> dict:
    row = {"name": name, "kind": kind, "enable": True,
           "wait_ms": 100, "timeout_ms": 5000,
           "unit": unit,
           "threshold_min": lo if lo is not None else "—",
           "threshold_max": hi if hi is not None else "—"}
    if e is not None:
        row["instrument"] = INSTRUMENTS.get(e.net_class, "DAQM")
        row["test_dim"] = dim
        if dim != "timing":
            row["notes"] = ""
    row.update(extra or {})
    return row


class CaseGenerator:
    """Net model -> ``ict_test_cases`` YAML draft generator."""

    def __init__(self, log_fn=None):
        self.parser = NetlistParser(log_fn=log_fn)
        self.log = log_fn or (lambda line: None)

    def load_nets(self, paths: list[str]) -> dict:
        """Cross-parse multiple sources; later sources enrich earlier
        ones (same net name merges pins / topology).  Keys keep the
        original net spelling; cross-source dedupe is case-insensitive."""
        nets: dict = {}
        seen: dict[str, str] = {}
        for path in paths:
            for e in self.parser.parse(path).values():
                key = e.name.lower()
                if key in seen:
                    base = nets[seen[key]]
                    for p in e.pins:
                        if p not in base.pins:
                            base.pins.append(p)
                    base.rail_parent = base.rail_parent or e.rail_parent
                    base.via = base.via or e.via
                    base.seq = base.seq or e.seq
                else:
                    seen[key] = e.name
                    nets[e.name] = e
        return nets

    def generate(self, source_paths: list[str]) -> dict:
        """Returns the full YAML fragment to merge into the project
        config: {"ict_test_cases": [...], "ict_case_audit": {...}}."""
        nets = self.load_nets(source_paths)
        power = sorted((e for e in nets.values()
                        if e.net_class == CLASS_POWER),
                       key=lambda e: rail_depth(nets, e.name))
        clocks = sorted((e for e in nets.values()
                         if e.net_class == CLASS_CLOCK),
                        key=lambda e: e.name)
        signals = sorted((e for e in nets.values()
                          if e.net_class == CLASS_SIGNAL),
                         key=lambda e: e.name)
        cases: list[dict] = []
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # pre-flight op rows (fixture / power-up) copied from the
        # standard ICT opening sequence
        for name in ("Init Instruments", "Fixture Clamp Down",
                     "Fixture Lock", "Fixture E-Stop Healthy"):
            cases.append(_case(name, "op", "—", None, None, dim="op"))
        cases.append(_case("Power On DUT", "op", "—", None, None,
                           dim="op"))

        # impedance shorts sweep first (stop_if_any_short gate)
        if power:
            cases.append(_case(
                f"Impedance Shorts ({len(power)} pts)", "test", "Ω",
                IMPEDANCE_MIN_OHM, None, dim="impedance",
                extra={"notes": "short detection before power-up"}))

        # per-rail rows, upstream-first (tree depth order)
        for e in power:
            depth = rail_depth(nets, e.name)
            prio = depth + 1
            common = {"priority": prio,
                      "power_domain": e.rail_parent or "SOURCE",
                      "upstream": e.rail_parent or "—",
                      "downstream": "—", "instrument":
                      INSTRUMENTS[CLASS_POWER]}
            nom = e.nominal_v
            if nom is not None:
                tol = nom * VOLTAGE_TOL_PCT / 100.0
                volt = _case(f"PWR {e.name} Voltage", "test", "V",
                             round(nom - tol, 4), round(nom + tol, 4),
                             dim="voltage", e=e,
                             extra=dict(common, downstream="—"))
                cases.append(volt)
            if e.seq:
                cases.append(_case(
                    f"PWR {e.name} Power-Up Sequence (SEQ {e.seq})",
                    "test", "s", 0.0, None, dim="timing", e=e,
                    extra=dict(common,
                               notes="waveform capture on rails log")))

        # clocks: frequency window via ppm
        for e in clocks:
            nom = e.nominal_v if (e.nominal_v or 0) > 100 else 32768.0
            tol = nom * CLOCK_PPM / 1e6
            cases.append(_case(
                f"CLK {e.name} Frequency", "test", "Hz",
                round(nom - tol, 2), round(nom + tol, 2), dim="voltage",
                e=e,
                extra={"priority": 1, "power_domain": "—",
                       "upstream": "—", "downstream": "—",
                       "instrument": INSTRUMENTS[CLASS_CLOCK]}))

        # plain signals: continuity only
        for e in signals:
            cases.append(_case(
                f"SIG {e.name} Continuity", "test", "Ω",
                IMPEDANCE_MIN_OHM, None, dim="impedance", e=e,
                extra={"priority": 3, "power_domain": "—",
                       "upstream": "—", "downstream": "—",
                       "instrument": INSTRUMENTS[CLASS_SIGNAL]}))

        for c in cases:
            c.setdefault("ai_meta", {
                "gen_version": AI_GEN_VERSION, "gen_time": now,
                "sources": list(source_paths)})

        audit = {"ai_version": AI_GEN_VERSION, "gen_time": now,
                 "sources": list(source_paths),
                 "nets": len(nets),
                 "power": len(power), "clock": len(clocks),
                 "signal": len(signals), "cases": len(cases)}
        self.log(f"[CASEGEN] generated {len(cases)} case(s) "
                 f"from {len(nets)} net(s) (power={len(power)} "
                 f"clock={len(clocks)} signal={len(signals)})")
        return {"ict_test_cases": cases, "ict_case_audit": audit}
