# -*- coding: utf-8 -*-
"""ICT Test Work Flow Sequence builder (block 04, user direction).

Clicking the "Build ICT Test Work Flow Sequence" card opens this
dialog: it seeds the ICT sequence from the parse result (R-GND ->
power rails (voltage) -> clock, one test per row) and then edits the
WHOLE sequence with the shared step editor - test items plus the
standard operations, the flash operations and Delay steps.  This dialog
is the single sequence edit source (the Test Work Flow page shows the
same sequence read-only as "ICT Test Results").
"""

from __future__ import annotations

import re

from PySide6.QtWidgets import QLabel, QWidget

from ...engine.steps import (METHOD_R_GND, dio_channel_index,
                               dio_name, op_step)
from ..steps_editor import StepsEditorDialog

#: Test Method -> unit (mirrors the Test Work Flow step edit dialog)
METHOD_UNITS = {
    METHOD_R_GND: "Ω",
    "Power Voltage": "V",
    "Clock Hz": "Hz",
    "DAQ AI": "V",
    "test": "—",
}

#: Test Method -> the parse-result category of the offered nets
METHOD_NET_CATEGORY = {
    METHOD_R_GND: "Power",
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
#: tests (R-GND runs BEFORE power-on: a short under power risks
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

    # R-GND rows run BEFORE power-on; legacy rows still say "Impedance"
    r_gnd = [t for t in rows
             if not is_daq_ai_row(t)
             and ("R-GND" in str(t[1]) or "Impedance" in str(t[1]))]
    rest = [t for t in rows
            if not is_daq_ai_row(t)
            and "R-GND" not in str(t[1]) and "Impedance" not in str(t[1])]
    mid = [op(n) for n in ICT_OPS_MID]
    if rail_count:
        mid.append((DAQ_AI_METHOD, daq_ai_net_label(rail_count),
                    "V", "—", "—", "—"))
    return ([op(n) for n in ICT_OPS_BEFORE_TEST] + r_gnd + mid + rest
            + [op(n) for n in ICT_OPS_AFTER_TEST])

#: the canonical generation order (user direction): R-GND ->
#: power voltage -> clock
METHOD_ORDER = (METHOD_R_GND, "Power Voltage", "Clock Hz")

#: default Auto tolerances (user direction): power rails +/- 5 %,
#: clock +/- 50 ppm (= 0.005 %)
POWER_TOL = 0.05
CLOCK_TOL_PPM = 50.0
#: R-GND min limit default (user direction 2026-10-25): 30 ohm - a
#: low-impedance rail-to-ground short would draw excessive current and
#: heat up the board, so the measured impedance must stay ABOVE it
R_GND_MIN_OHM = 30.0

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


#: the control-IO operations appended automatically when the parse
#: result carries at least one GPIO net (M9 W1) - read / write happen
#: while the DUT is powered, i.e. right after the clock tests
DIO_AUTO_OP_NAMES = ("U2355A DIO Read", "U2355A DIO Write")


def _dio_write_params(allocation: dict | None) -> dict | None:
    """M19b: the U2355A DIO Write step parameters derived from the 03
    allocation - the channels of every Control IO net armed as DIO
    Write and the drive mask (High = 1, Low = 0).  Returns None when
    no net is armed."""
    nets: list[tuple[str, str]] = []
    for row in (allocation or {}).get("gpio") or []:
        if not isinstance(row, dict):
            continue
        if row.get("op_type") != "U2355A DIO Write":
            continue
        channel = str(row.get("dio_channel") or "")
        if channel in ("", "—"):
            continue
        nets.append((dio_name(channel),
                     str(row.get("drive_level") or "")))
    if not nets:
        return None
    channels = ",".join(ch for ch, _level in nets)
    mask = 0
    for channel, level in nets:
        index = dio_channel_index(channel)
        if index is None:
            continue
        if level == "High":
            mask |= (1 << index)
    return {"type": "dio_out", "channels": channels,
            "pattern": f"0x{mask:02X}"}


def generate_sequence(testable: dict,
                      allocation: dict | None = None) -> list[tuple]:
    """The automatic sequence rows (module level so the Load-current-
    yaml flow reuses it without instantiating the dialog): per power
    net one R-GND and one Power Voltage test, per clock net one Clock
    Hz test - R-GND -> power rails (voltage) -> clock.

    Control-IO operations (M19b): the 03 allocation decides - a DIO
    Read step is appended when at least one Control IO net is armed as
    Read, a DIO Write step (with the drive channels + High/Low mask)
    when at least one net is armed as Write.  The default High Z
    (NOT TESTED) rows generate NO operation.  Without an allocation
    (legacy) the two U2355A DIO operations are appended when the parse
    result holds at least one GPIO net (M9 W1).  The Expected / Min /
    Max cells stay unset ("—"); combine with :func:`auto_fill_limits`
    for the fully derived rows."""
    testable = testable or {}
    rows: list[tuple] = []
    for method in METHOD_ORDER:
        category = METHOD_NET_CATEGORY[method]
        for net in sorted(n for n, info in testable.items()
                          if (info or {}).get("category")
                          == category):
            label = {METHOD_R_GND: f"R-GND - {net}",
                     "Power Voltage": f"Power Voltage - {net}",
                     "Clock Hz": f"Clock Hz - {net}"}.get(
                method, f"{method} - {net}")
            rows.append(("test", label,
                         METHOD_UNITS[method], "—", "—", "—"))
    dio_rows = (allocation or {}).get("gpio") or []
    has_read = any(isinstance(r, dict)
                   and r.get("op_type") == "U2355A DIO Read"
                   for r in dio_rows)
    write_params = _dio_write_params(allocation)
    if has_read:
        rows.append(op_step("U2355A DIO Read"))
    if write_params is not None:
        rows.append(op_step("U2355A DIO Write", write_params))
    if allocation is None and             any((info or {}).get("category") == "GPIO"
                for info in testable.values()):
        rows.extend(op_step(name) for name in DIO_AUTO_OP_NAMES)
    return rows


def _stored_number(value) -> float | None:
    """M8: a stored ``nominal_v`` / ``nominal_khz`` as a positive float."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def auto_fill_limits(rows: list[tuple],
                     testable: dict | None = None) -> list[tuple]:
    """Fill Expected / Min / Max from the parsed nominal values (the
    Auto semantics, table-free): Min = Expected * (1 - tolerance),
    Max = Expected * (1 + tolerance); power voltage +/- 5 % (0.001 V
    precision), clock +/- 50 ppm (0.1 Hz precision).

    The nominal comes from the ``imported.testable_nets`` entry when the
    parse knows one (``nominal_v`` / ``nominal_khz`` - M8), else it is
    parsed from the net name (P3V3 -> 3.3 V, CLK_24M -> 24 MHz).  Rows
    with no known nominal stay untouched (user-editable limits).
    """
    testable = testable or {}
    out: list[tuple] = []
    for step in rows:
        kind, name, unit, _expected, _lo, _hi = step[:6]
        method = (name.split(" - ")[0] if " - " in name else name)
        net = name.split(" - ", 1)[1] if " - " in name else ""
        info = testable.get(net) or {}
        nominal = tol = fmt = None
        if method == "Power Voltage":
            nominal = (_stored_number(info.get("nominal_v"))
                       or expected_voltage(net))
            tol, fmt = POWER_TOL, _fmt_power
        elif method == "Clock Hz":
            khz = _stored_number(info.get("nominal_khz"))
            nominal = (khz * 1000.0 if khz is not None
                       else expected_hz(net))
            tol, fmt = CLOCK_TOL_PPM * 1e-6, _fmt_clock
        if nominal is None or tol is None:
            out.append(step)
            continue
        out.append((kind, name, unit, fmt(nominal),
                    fmt(nominal * (1 - tol)),
                    fmt(nominal * (1 + tol)), *step[6:]))
    return out


def _filled(text) -> str:
    """A limit cell value that carries real content (not a dash
    placeholder)."""
    value = str(text).strip()
    return "" if value in ("", "—", "--") else value


_SKELETON_OP_NAMES = frozenset(
    ICT_OPS_BEFORE_TEST + ICT_OPS_MID + ICT_OPS_AFTER_TEST)
#: generated operations that must appear exactly once.  The DIO ops are
#: auto-appended by :func:`generate_sequence` (M9 W1) but are not part
#: of the canonical skeleton - a saved plan may already carry them.
_DEDUP_OP_NAMES = _SKELETON_OP_NAMES | frozenset(DIO_AUTO_OP_NAMES)


def _drop_repeated_skeleton_ops(rows: list[tuple]) -> list[tuple]:
    """One row per generated operation: a rebuild that passes the saved
    skeleton ops through ``standard_ict_sequence`` keeps their saved
    parameters (``by_name``) but the same rows also land in the "rest"
    block - keep the first occurrence only."""
    seen: set[str] = set()
    out: list[tuple] = []
    for step in rows:
        if step and step[0] == "op" and step[1] in _DEDUP_OP_NAMES:
            if step[1] in seen:
                continue
            seen.add(step[1])
        out.append(step)
    return out


def merge_saved_limits(rows: list[tuple],
                       previous_steps: list[tuple]) -> list[tuple]:
    """Keep previously filled Expected / Min / Max cells across a
    sequence regeneration (user direction 2026-10-14): Auto re-derives
    what it can, any manually edited value wins.  Rows are matched by
    test name; empty / dash cells fall back to the fresh derivation.
    Operation rows pass through unchanged (their saved parameters are
    merged by :func:`merge_saved_ops`)."""
    old = {s[1]: s for s in previous_steps
           if s[0] != "op" and len(s) >= 6}
    merged: list[tuple] = []
    for step in rows:
        kind, name, unit, exp, lo, hi = step[:6]
        if kind == "op":
            merged.append(step)
            continue
        prev = old.get(name)
        if prev is not None:
            exp = _filled(prev[3]) or exp
            lo = _filled(prev[4]) or lo
            hi = _filled(prev[5]) or hi
        merged.append((kind, name, unit, exp, lo, hi, *step[6:]))
    return merged


def merge_saved_ops(rows: list[tuple],
                    previous_steps: list[tuple]) -> list[tuple]:
    """Keep the saved operation rows (with their parameters) across a
    rebuild: a generated default operation is replaced in place by the
    saved row of the same name (the operator's channels / pattern win),
    and any saved operation the seed does not know (flash / Delay /
    custom) is appended."""
    saved: dict[str, tuple] = {}
    for step in previous_steps or []:
        if step and step[0] == "op" and len(step) > 1:
            saved.setdefault(step[1], step)
    seen: set[str] = set()
    out: list[tuple] = []
    for step in rows:
        if step and step[0] == "op":
            name = step[1]
            if name in saved and name not in seen:
                out.append(saved[name])
                seen.add(name)
                continue
            seen.add(name)
        out.append(step)
    for name, step in saved.items():
        if name not in seen:
            out.append(step)
            seen.add(name)
    return out


def _allocation_by_net(allocation: dict | None) -> dict:
    """Flatten the 03 Channel Allocation rows into {net: row} (M19)."""
    by_net: dict = {}
    for kind in ("power", "clock", "gpio"):
        for row in (allocation or {}).get(kind) or []:
            if isinstance(row, dict) and row.get("net"):
                by_net.setdefault(row["net"], row)
    return by_net


def apply_allocation_limits(rows: list[tuple],
                            allocation: dict | None) -> list[tuple]:
    """Override Expected / Min / Max from the 03 Channel Allocation
    rows (M19: the allocation page is the single edit point for
    nominal / limits; the 04 sequence inherits them).  Power voltage
    and clock rows matched by net name; unknown nets pass through."""
    by_net = _allocation_by_net(allocation)
    if not by_net:
        return rows
    out: list[tuple] = []
    for step in rows:
        if not step or step[0] == "op":
            out.append(step)
            continue
        kind, name, unit, exp, lo, hi = step[:6]
        method = name.split(" - ", 1)[0] if " - " in name else name
        net = name.split(" - ", 1)[1] if " - " in name else ""
        row = by_net.get(net)
        if row is None:
            out.append(step)
            continue
        if method == "R-GND" and _filled(
                str(row.get("r_gnd_min_ohm") or "")):
            # R-GND carries only a MIN limit (no nominal / no max)
            lo = row["r_gnd_min_ohm"]
            hi = "—"
            exp = "—"
        elif method == "Power Voltage" and _filled(
                str(row.get("nominal_v") or "")):
            exp = row["nominal_v"]
            lo = _filled(str(row.get("lower_v") or "")) or exp
            hi = _filled(str(row.get("upper_v") or "")) or exp
        elif method == "Clock Hz" and _filled(
                str(row.get("nominal_khz") or "")):
            khz = float(row["nominal_khz"])
            lo_khz = _stored_number(row.get("lower_khz")) or khz
            hi_khz = _stored_number(row.get("upper_khz")) or khz
            exp = _fmt_clock(khz * 1000.0)
            lo = _fmt_clock(lo_khz * 1000.0)
            hi = _fmt_clock(hi_khz * 1000.0)
        else:
            out.append(step)
            continue
        out.append((kind, name, unit, exp, lo, hi, *step[6:]))
    return out


def canonical_ict_sequence(testable: dict, previous_steps=None,
                           rail_count: int = 0,
                           allocation: dict | None = None) -> list[tuple]:
    """The ONE canonical ICT seed shared by the 04 Build dialog and the
    Load-current-yaml path (M8 W3 / M9 W1):

    1. Auto-filled test rows (R-GND -> voltage -> clock) plus the two
       auto-appended DIO operations when GPIO nets exist;
    2. saved manual limits and saved operation parameters win;
    3. the standard-operation skeleton (Power On DUT + DAQ AI rails
       capture BEFORE the voltage / clock tests, R-GND before power-on).
    """
    testable = testable or {}
    previous = list(previous_steps or [])
    rows = auto_fill_limits(generate_sequence(testable, allocation),
                            testable)
    # M19: the 03 allocation nominal / limits win over the name
    # heuristic, but a manually edited 04 value still wins over both
    rows = apply_allocation_limits(rows, allocation)
    rows = merge_saved_limits(rows, previous)
    rows = merge_saved_ops(rows, previous)
    return _drop_repeated_skeleton_ops(
        standard_ict_sequence(rows, rail_count))


class IctWorkFlowSequenceDialog(StepsEditorDialog):
    """The block-04 dialog: seeds the ICT sequence from the parse
    result and edits the WHOLE sequence - test items plus the standard
    operations, the flash operations and Delay steps - with the shared
    step editor (single sequence edit source)."""

    def __init__(self, net_provider, initial_tests=None, rail_count=0,
                 allocation=None,
                 parent: QWidget | None = None,
                 available_ops=None) -> None:
        self._net_provider = net_provider
        self._rail_count = int(rail_count)
        self._allocation = allocation
        # M9 W1: ONE canonical pipeline shared with the Load-current-yaml
        # path - Auto-filled limits plus the DIO operations when GPIO nets
        # are present, saved manual limits / user operation parameters
        # win, then the standard-operation skeleton (Power On DUT + rails
        # capture BEFORE the voltage / clock tests)
        previous = list(initial_tests or [])
        testable = net_provider() if net_provider else {}
        steps = canonical_ict_sequence(
            testable, previous, self._rail_count,
            allocation=self._allocation)
        n = len(steps)
        super().__init__(
            "ict", steps, [True] * n, [100] * n, [5000] * n, parent,
            available_ops=available_ops)
        self.setWindowTitle("Build ICT Test Work Flow Sequence")
        self.setMinimumSize(640, 460)
        # the step editor offers the nets PER TEST METHOD from the
        # parse result; the DAQ AI Net stays a read-only rail count
        self.net_catalog_provider = net_provider
        self.daq_ai_rail_count_provider = lambda: self._rail_count
        # M9 W2: make a Clock row whose limits are still empty obvious
        self._limits_hint = QLabel(self)
        self._limits_hint.setWordWrap(True)
        self._limits_hint.setStyleSheet(
            "color: #b45309; font-weight: bold;")
        self.layout().insertWidget(0, self._limits_hint)
        self._refresh_limits_hint()

    def _populate(self):
        super()._populate()
        self._refresh_limits_hint()

    def _refresh_limits_hint(self) -> None:
        """[WARNING] line listing the Clock nets Auto could not fill.

        A Clock row without Expected / Min / Max stops the run with
        ``limits missing -> Error``; surfacing it here lets the operator
        edit the row before building (M9 W2)."""
        label = getattr(self, "_limits_hint", None)
        if label is None:
            return
        missing = []
        for step in self._steps:
            if not step or step[0] != "test":
                continue
            name = str(step[1])
            if name.split(" - ")[0] != "Clock Hz":
                continue
            if any(not _filled(value) for value in step[3:6]):
                missing.append(name.split(" - ", 1)[1])
        if missing:
            label.setText(
                "[WARNING] Clock limits missing (the frequency could not be "
                "inferred) - double-click the row to fill Expected / Min / "
                "Max, otherwise the run stops with 'limits missing -> "
                "Error': " + ", ".join(missing))
            label.show()
        else:
            label.clear()
            label.hide()
