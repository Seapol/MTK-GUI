# -*- coding: utf-8 -*-
"""ICT Test Work Flow Sequence builder (block 04, user direction).

Clicking the "Build ICT Test Work Flow Sequence" card opens this
dialog: it seeds the ICT sequence from the parse result (impedance ->
power rails (voltage) -> clock, one test per row) and then edits the
WHOLE sequence with the shared step editor - test items plus the
standard operations, the flash operations and Delay steps.  This dialog
is the single sequence edit source (the Test Work Flow page shows the
same sequence read-only as "ICT Test Results").
"""

from __future__ import annotations

import re

from PySide6.QtWidgets import QWidget

from ..steps_editor import StepsEditorDialog

#: Test Method -> unit (mirrors the Test Work Flow step edit dialog)
METHOD_UNITS = {
    "Static Impedance": "Ω",
    "Power Voltage": "V",
    "Clock Hz": "Hz",
    "DAQ AI": "V",
    "test": "—",
}

#: Test Method -> the parse-result category of the offered nets
METHOD_NET_CATEGORY = {
    "Static Impedance": "Power",
    "Power Voltage": "Power",
    "DAQ AI": "Power",
    "Clock Hz": "Clock",
    "test": "GPIO",
}

#: the DAQ AI test needs NO net / limits here: the Power rails are
#: already allocated in Channel Allocation - adding the test row is
#: enough (user direction)
DAQ_AI_METHOD = "DAQ AI"


def daq_ai_rail_count(channel_allocation) -> int:
    """Number of power rails assigned to DAQ AI channels (U2355A AI).

    The DAQ AI test has no free net: its scope is every net already
    allocated to a DAQ AI channel in Channel Allocation.
    """
    return sum(
        1 for row in (channel_allocation or {}).get("power") or []
        if "U2355A AI" in str(row.get("power_rails") or ""))


def daq_ai_net_label(count: int) -> str:
    """The read-only DAQ AI 'Net' label (count = assigned power rails)."""
    return f"{int(count)} Power rails assigned on DAQ channels"


def is_daq_ai_row(row) -> bool:
    """True for a DAQ AI sequence row (kind drives it, name-agnostic)."""
    return bool(row) and row[0] == DAQ_AI_METHOD

#: canonical ICT standard-operation skeleton around the generated
#: tests (impedance runs BEFORE power-on: a short under power risks
#: damaging the board).  The Build ICT dialog is the single sequence
#: EDIT source; this skeleton is the canonical SEED reused by the
#: Load-current-yaml flow and the ICT demo build script so they emit
#: the same sequence the dialog would.
ICT_OPS_BEFORE_TEST = ("Init Instruments", "Fixture Clamp Down",
                       "Fixture Lock", "Fixture E-Stop Healthy")
ICT_OPS_MID = ("Power On DUT",)
ICT_OPS_AFTER_TEST = ("Power Off DUT", "Fixture Unlock",
                      "Fixture Release", "Reset Instruments")


def standard_ict_sequence(tests: list, rail_count: int = 0) -> list[tuple]:
    """The canonical ICT sequence: the standard-operation skeleton
    around the test rows, with the derived DAQ AI power-rails capture
    placed right AFTER Power On DUT and BEFORE the voltage / clock
    tests (user direction 2026-10-14).

    Any operation row already present in ``tests`` is kept (its saved
    parameters win); the DAQ AI rows in ``tests`` collapse into the one
    derived capture row whose Net is the running rail count.
    """
    from mtkgui.engine.steps import op_step

    rows = list(tests or [])
    by_name = {s[1]: s for s in rows
               if s and s[0] == "op" and len(s) > 1}

    def op(name: str):
        return by_name.get(name) or op_step(name)

    impedance = [t for t in rows
                 if not is_daq_ai_row(t) and "Impedance" in str(t[1])]
    rest = [t for t in rows
            if not is_daq_ai_row(t) and "Impedance" not in str(t[1])]
    mid = [op(n) for n in ICT_OPS_MID]
    if rail_count:
        mid.append((DAQ_AI_METHOD, daq_ai_net_label(rail_count),
                    "V", "—", "—", "—"))
    return ([op(n) for n in ICT_OPS_BEFORE_TEST] + impedance + mid + rest
            + [op(n) for n in ICT_OPS_AFTER_TEST])

#: the canonical generation order (user direction): impedance ->
#: power rails (voltage) -> clock
METHOD_ORDER = ("Static Impedance", "Power Voltage", "Clock Hz")

#: default Auto tolerances (user direction): power rails +/- 5 %,
#: clock +/- 50 ppm (= 0.005 %)
POWER_TOL = 0.05
CLOCK_TOL_PPM = 50.0

_V_RE = re.compile(r"(\d+)V(\d+)")            # 3V3 / 1V8 / 1V05
#: plain form: "V" NOT followed by a digit.  A "\b" boundary rejected
#: "12V_DECT_1" ("_" is a word char) and parsed it as no nominal -> the
#: rail showed 0.000 V in the report; the lookahead accepts it while
#: still rejecting the 3V3-style names (handled by _V_RE above).
_V_PLAIN_RE = re.compile(r"(\d+)V(?![0-9])")  # 24V / 5V / 12V_DECT_1


def expected_voltage(net: str) -> float | None:
    """Parse the nominal voltage from a power-net name
    (P3V3_LDO -> 3.3, MCU_1V8 -> 1.8, VIN_24V -> 24.0)."""
    m = _V_RE.search(net or "")
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = _V_PLAIN_RE.search(net or "")
    if m:
        return float(m.group(1))
    return None


def expected_hz(net: str) -> float | None:
    """Parse the nominal frequency from a clock-net name
    (CLK_24M -> 24 MHz, OSC_125M -> 125 MHz, CLK_32K -> 32 kHz)."""
    for suffix, mult in (("G", 1e9), ("M", 1e6), ("K", 1e3)):
        m = re.search(rf"(\d+(?:\.\d+)?)\s*{suffix}", net or "",
                      re.IGNORECASE)
        if m:
            return float(m.group(1)) * mult
    return None


def _fmt_power(value: float) -> str:
    """Power limits / expected: 0.001 V precision (user direction)."""
    return f"{value:.3f}"


def _fmt_clock(value: float) -> str:
    """Clock limits / expected: 0.1 Hz precision (user direction)."""
    return f"{value:.1f}"


def generate_sequence(testable: dict) -> list[tuple]:
    """The automatic sequence rows (module level so the Load-current-
    yaml flow reuses it without instantiating the dialog): per power
    net one Static Impedance and one Power Voltage test, per clock net
    one Clock Hz test - impedance -> power rails (voltage) -> clock.
    The Expected / Min / Max cells stay unset ("\"—\""); combine with
    :func:`auto_fill_limits` for the fully derived rows."""
    testable = testable or {}
    rows: list[tuple] = []
    for method in METHOD_ORDER:
        category = METHOD_NET_CATEGORY[method]
        for net in sorted(n for n, info in testable.items()
                          if (info or {}).get("category")
                          == category):
            label = {"Static Impedance": f"Static Impedance - {net}",
                     "Power Voltage": f"Power Voltage - {net}",
                     "Clock Hz": f"Clock Hz - {net}"}.get(
                method, f"{method} - {net}")
            rows.append(("test", label,
                         METHOD_UNITS[method], "—", "—", "—"))
    return rows


def auto_fill_limits(rows: list[tuple]) -> list[tuple]:
    """Fill Expected / Min / Max from the parsed nominal values (the
    Auto semantics, table-free): Min = Expected * (1 - tolerance),
    Max = Expected * (1 + tolerance); power voltage +/- 5 % (0.001 V
    precision), clock +/- 50 ppm (0.1 Hz precision).  The nominal is
    parsed from the net name (P3V3 -> 3.3 V, CLK_24M -> 24 MHz).
    Rows without a parseable nominal stay untouched."""
    out: list[tuple] = []
    for step in rows:
        kind, name, unit, _expected, _lo, _hi = step
        method = (name.split(" - ")[0] if " - " in name else name)
        net = name.split(" - ", 1)[1] if " - " in name else ""
        nominal = tol = fmt = None
        if method == "Power Voltage":
            nominal, tol, fmt = (expected_voltage(net),
                                 POWER_TOL, _fmt_power)
        elif method == "Clock Hz":
            nominal, tol, fmt = (expected_hz(net),
                                 CLOCK_TOL_PPM * 1e-6, _fmt_clock)
        if nominal is None or tol is None:
            out.append(step)
            continue
        out.append((kind, name, unit, fmt(nominal),
                    fmt(nominal * (1 - tol)),
                    fmt(nominal * (1 + tol))))
    return out


def _filled(text) -> str:
    """A limit cell value that carries real content (not a dash
    placeholder)."""
    value = str(text).strip()
    return "" if value in ("", "—", "--") else value


def merge_saved_limits(rows: list[tuple],
                       previous_steps: list[tuple]) -> list[tuple]:
    """Keep previously filled Expected / Min / Max cells across a
    sequence regeneration (user direction 2026-10-14): Auto re-derives
    what it can, any manually edited value wins.  Rows are matched by
    test name; empty / dash cells fall back to the fresh derivation."""
    old = {s[1]: s for s in previous_steps
           if s[0] != "op" and len(s) >= 6}
    merged: list[tuple] = []
    for kind, name, unit, exp, lo, hi in rows:
        prev = old.get(name)
        if prev is not None:
            exp = _filled(prev[3]) or exp
            lo = _filled(prev[4]) or lo
            hi = _filled(prev[5]) or hi
        merged.append((kind, name, unit, exp, lo, hi))
    return merged


class IctWorkFlowSequenceDialog(StepsEditorDialog):
    """The block-04 dialog: seeds the ICT sequence from the parse
    result and edits the WHOLE sequence - test items plus the standard
    operations, the flash operations and Delay steps - with the shared
    step editor (single sequence edit source)."""

    def __init__(self, net_provider, initial_tests=None, rail_count=0,
                 parent: QWidget | None = None) -> None:
        self._net_provider = net_provider
        self._rail_count = int(rail_count)
        steps = (list(initial_tests) if initial_tests
                 else auto_fill_limits(generate_sequence(
                     net_provider() if net_provider else {})))
        n = len(steps)
        super().__init__(
            "ict", steps, [True] * n, [100] * n, [5000] * n, parent)
        self.setWindowTitle("Build ICT Test Work Flow Sequence")
        self.setMinimumSize(640, 460)
        # the step editor offers the nets PER TEST METHOD from the
        # parse result; the DAQ AI Net stays a read-only rail count
        self.net_catalog_provider = net_provider
        self.daq_ai_rail_count_provider = lambda: self._rail_count
