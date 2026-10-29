# -*- coding: utf-8 -*-
"""Step definitions and helpers for the test flow engine.

Extracted verbatim from mtkgui.test_workflow_page.py (task T2, pure
extraction): the standard operation catalog (OP_STEPS), the FCT test
methods, the run-step template and the small mapping helpers used by
both the page and the runner.

Step tuple shape (ICT, mirrors the YAML schema):
    (kind, name, unit, measured, threshold_min, threshold_max[, op_params])
Standard operation steps carry a params dict (saved to YAML as
"op_params"); measurement rows use "—" placeholders.
"""
from __future__ import annotations

import re

from .results import StepStatus

# FCT test methods (Test Method column in the step editor / YAML kind)
#
# The three "*toConsole" methods (user direction 2026-10-18) are the
# Console-domain operator dialogs and are DIFFERENT from the plain
# standard-operation MessageOK / MessageYesNo / MessageGoStop:
#   Phase 1 - WAIT the expected message from the Console channel;
#   Phase 2 - notify the operator and take the answer:
#     * MessageOKtoConsole      : OK notice, NO command sent, the
#                                 Console is NOT blocked;
#     * MessageGoStoptoConsole  : modal GO / STOP (blocks the Console
#                                 while awaiting the answer) - GO sends
#                                 "y" and continues, STOP sends "n" and
#                                 stops the run, timeout -> FAIL;
#     * MessageYesNotoConsole   : modal Yes / No (blocks the Console)
#                                 - Yes/No send "y"/"n" and BOTH
#                                 continue, timeout -> FAIL + stop.
FCT_METHODS = [
    "MessageOK", "MessageYesNo", "MessageGoStop",
    "MessageOKtoConsole", "MessageYesNotoConsole",
    "MessageGoStoptoConsole",
    "SendtoConsole", "WaitforConsole", "CapturefromConsole",
    "Delay",
    "SendtoCLI", "WaitforCLI", "CapturefromCLI",
    "WIFI", "Bluetooth",
]

#: Console-domain operator dialog methods (wait-for-message + notify)
MESSAGE_CONSOLE_KINDS = ("MessageOKtoConsole", "MessageYesNotoConsole",
                         "MessageGoStoptoConsole")


def fct_kind_from_name(name: str) -> str:
    """Derive the FCT test method from a 'Method: description' name;
    standard operation names -> kind "op"."""
    if name.strip() in OP_STEPS:
        return "op"
    prefix = name.split(":", 1)[0].strip()
    return prefix if prefix in FCT_METHODS else "MessageOK"


# FCT test methods that drive a serial console channel.  In Virtual mode
# they run for real against the simulated DUT (mtkgui.virtual_dut):
# send the command, then search the channel read buffer for the expected
# keyword(s) parsed from the step name.
CONSOLE_KINDS = ("SendtoConsole", "WaitforConsole", "CapturefromConsole",
                 "SendtoCLI", "WaitforCLI", "CapturefromCLI")

# 'Pass' or "OK" / "wifi_test --scan" -> quoted segments of a step name
_QUOTED_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"")


def console_keyword_fallback(rest: str) -> str:
    """Keyword for console steps whose name carries no quoted segment:
    the text after the last comma minus the '(expected)' marker."""
    tail = rest.split(",")[-1]
    return tail.replace("(expected)", "").strip().strip("'\"").strip()


# standard operation steps: name -> params dict.  The params are stored
# on every op step (7th tuple element), saved to YAML as "op_params",
# edited in the sequence editor (per-type fields) and printed to the
# Event Log when the step executes.  "type" selects the parameter UI and
# the log wording (instruments / reset / fixture / power / dio_*).
OP_STEPS: dict[str, dict] = {
    "Init Instruments": {
        "type": "instruments", "instruments": ["DAQM", "DAQ", "PSU"]},
    "Reset Instruments": {
        "type": "reset", "instruments": ["DAQM", "DAQ", "PSU"]},
    "Fixture Clamp Down": {
        "type": "fixture", "signal": "press", "level": "H"},
    "Fixture Release": {
        "type": "fixture", "signal": "press", "level": "L"},
    "Fixture Lock": {
        "type": "fixture", "signal": "inpos", "level": "H"},
    "Fixture Unlock": {
        "type": "fixture", "signal": "inpos", "level": "L"},
    "Fixture E-Stop Healthy": {
        "type": "fixture", "signal": "estop", "level": "L"},
    "Power On DUT": {
        "type": "power", "voltage": 5.0, "current": 1.0},
    "Power Off DUT": {
        "type": "power"},
    # M7: U2355A DIO bank standard operations (digital input / output).
    # Read is reference-only (no judgement); Write drives the bank and
    # is guarded by the isolation preflight in the runner.
    "U2355A DIO Read": {
        "type": "dio_read"},
    "U2355A DIO Write": {
        "type": "dio_out", "channels": "DIO01-DIO08", "pattern": "0x00"},
}


#: trailing channel number of a DIO channel name (``DIO07`` -> 7)
_DIO_NUM_RE = re.compile(r"(\d+)\s*$")
#: one DIO channel token, with or without the instrument prefix
#: (``DIO01`` / ``U2355A DIO01``) and an optional ``-`` range
_DIO_TOKEN_RE = re.compile(
    r"(?:U2355A\s+)?DIO\s*\d+(?:\s*-\s*(?:U2355A\s+)?DIO\s*\d+)?", re.I)


def dio_name(channel: str) -> str:
    """Canonical DIO channel name (``U2355A DIO07`` -> ``DIO07``)."""
    match = re.search(r"DIO\s*(\d+)", str(channel or ""), re.I)
    return f"DIO{int(match.group(1)):02d}" if match else ""


def dio_channel_index(channel: str) -> int | None:
    """Zero-based bank bit of a DIO channel name (None when unnamed)."""
    match = _DIO_NUM_RE.search(str(channel or ""))
    return int(match.group(1)) - 1 if match else None


def expand_dio_channels(channels: str) -> list[str]:
    """``DIO01-DIO08`` / ``U2355A DIO01-DIO08`` / ``DIO01,DIO02`` ->
    canonical channel name list (``DIO01`` ...)."""
    text = str(channels or "").strip()
    if not text:
        return []
    tokens = _DIO_TOKEN_RE.findall(text) or re.split(r"[,;]+", text)
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        parts = re.split(r"\s*-\s*", token.strip())
        if len(parts) == 2:
            first = dio_channel_index(parts[0])
            last = dio_channel_index(parts[1])
            if first is not None and last is not None and first <= last:
                for num in range(first + 1, last + 2):
                    name = f"DIO{num:02d}"
                    if name not in seen:
                        seen.add(name)
                        out.append(name)
                continue
        name = dio_name(token)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def dio_pattern_value(pattern: str, channels: str = "") -> int:
    """Parse a U2355A DIO pattern -> integer bit mask.

    Accepts HEX (``0x3C``), a per-channel list (``DIO01=1,DIO02=0``)
    or a plain 0/1 level list in *channels* order.
    """
    text = str(pattern or "").strip()
    if not text:
        return 0
    if text.lower().startswith("0x"):
        try:
            return int(text, 16)
        except ValueError:
            return 0
    tokens = [t for t in re.split(r"[,;\s]+", text) if t]
    if tokens and all("=" in t for t in tokens):
        value = 0
        for token in tokens:
            channel, _, level = token.partition("=")
            index = dio_channel_index(channel)
            if index is not None and \
                    str(level).strip().upper() in ("1", "H", "HIGH", "ON"):
                value |= 1 << index
        return value
    if tokens and all(t in ("0", "1") for t in tokens):
        order = expand_dio_channels(channels)
        value = 0
        for pos, bit in enumerate(tokens):
            index = (dio_channel_index(order[pos]) if pos < len(order)
                     else pos)
            if bit == "1" and index is not None:
                value |= 1 << index
        return value
    try:
        return int(text, 0)
    except ValueError:
        return 0


def op_step(name: str, params: dict | None = None) -> tuple:
    """Build a 7-tuple op step; params default from the catalog."""
    if params is None:
        params = OP_STEPS.get(name, {})
    return ("op", name, "—", "—", "—", "—", dict(params))


def op_summary(params: dict | None) -> str:
    """Short parameter summary for the sequence list label."""
    t = (params or {}).get("type")
    if t in ("instruments", "reset"):
        return "+".join((params or {}).get("instruments", []))
    if t == "fixture":
        return f"{(params or {}).get('signal', '')}=" \
               f"{(params or {}).get('level', '')}"
    if t == "power" and "voltage" in (params or {}):
        return (f"{params['voltage']:g}V/"
                f"{params.get('current', 0):g}A")
    if t == "dio_out":
        return (f"{(params or {}).get('channels', '')} = "
                f"{(params or {}).get('pattern', '')}")
    if t == "dio_read":
        return "24 ch Control IO"
    return ""


def op_status_lines(name: str, params: dict | None) -> list[str]:
    """Per-sub-action Event Log status lines for one op step."""
    p = dict(params) if params else {}
    t = p.get("type") or OP_STEPS.get(name, {}).get("type", "generic")
    if t in ("instruments", "reset"):
        verb = "reset" if t == "reset" else "init"
        return ([f"{inst} {verb} OK"
                 for inst in p.get("instruments", [])] or [f"{verb} OK"])
    if t == "fixture":
        sig, lvl = p.get("signal", "press"), p.get("level", "H")
        return [f"drive {sig}={lvl} -> state verified"]
    if t == "power":
        if "voltage" in p:
            return [f"N5747A set {p['voltage']:.2f} V / "
                    f"{p.get('current', 0.0):.2f} A -> output ON, "
                    f"readback OK"]
        return ["N5747A output OFF"]
    if t == "dio_read":
        return ["U2355A DIO bank read (reference levels only)"]
    if t == "dio_out":
        return [f"U2355A DIO {p.get('channels', '')} = "
                f"{p.get('pattern', '')} -> written"]
    return [f"{name} executed"]


def op_instrument_abbr(params: dict | None) -> str:
    """Status-bar instrument behind an operation step."""
    t = (params or {}).get("type") or ""
    if t == "power":
        return "PSU"
    if t == "fixture":
        return "DAQM"   # fixture control board sits on DAQM907A DIO
    if t in ("dio_read", "dio_out"):
        return "DAQ"    # U2355A USB DAQ
    return "DAQM"


def meas_instrument_abbr(kind: str, name: str) -> str:
    """Status-bar instrument behind a measurement step."""
    from ..virtual_hardware import tp_index  # local: avoids import cycle

    tp = tp_index(name)
    # CLK2/CLK3 (TP_C02/C03) and DUT GPIO run on the U2355A;
    # everything else (OHM/DCV, totalizer CLK1, AO, fixture DIO)
    # runs on the DAQ973A mainframe
    if "gpio" in name.lower():
        return "DAQ"
    if kind == "Clock Hz" and tp and tp[0] == "C" and tp[1] >= 2:
        return "DAQ"
    return "DAQM"


#: ICT R-to-GND test method (user naming direction 2026-10-21).
#: Legacy YAML / project files used "Static Impedance"; the loader
#: normalizes that name to R-GND so old projects keep working.
METHOD_R_GND = "R-GND"
METHOD_R_GND_LEGACY = "Static Impedance"


def normalize_ict_method(value: str) -> str:
    """Map the legacy Static Impedance method to its R-GND name."""
    return METHOD_R_GND if value == METHOD_R_GND_LEGACY else value


def normalize_ict_step_name(name: str) -> str:
    """Map a legacy 'Static Impedance - <net>' row name to R-GND."""
    prefix = METHOD_R_GND_LEGACY + " - "
    if name.startswith(prefix):
        return METHOD_R_GND + " - " + name[len(prefix):]
    return normalize_ict_method(name)


def is_r_gnd_method(value: str) -> bool:
    """True for the R-GND method (new name or legacy Static Impedance)."""
    return value in (METHOD_R_GND, METHOD_R_GND_LEGACY)


def is_impedance_short(step: tuple) -> bool:
    """True for every R-GND (legacy Impedance Shorts) test row — the
    scope of the 'Stop if any short' policy. Detected by the R-GND
    test method, by unit Ω (per-net rows), or by the legacy aggregate
    name containing 'impedance short'."""
    if is_r_gnd_method(step[0]):
        return True
    unit = step[2].strip()
    if unit == "Ω":
        return True
    name = step[1].lower()
    return ("impedance" in name or "r-gnd" in name) and "short" in name


def steps_template(ict_count: int, fct_count: int,
                   overall_en: list) -> list[tuple]:
    """Run steps for the stages enabled in Overall Flow only."""
    steps: list[tuple] = []
    if overall_en[0]:
        # the DAQ AI capture is a regular ICT row (kind "DAQ AI")
        steps += [("ict", r) for r in range(ict_count)]
        steps.append(("stage", 0))
    if overall_en[1]:
        if fct_count:
            steps.append(("fctconn",))  # console connect before FCT
        steps += [("fct", r) for r in range(fct_count)]
        steps.append(("stage", 1))
    return steps


def parse_console_step(name: str) -> tuple[list[str], str]:
    """Split an FCT console step name into its quoted segments and
    the remaining text: "SendtoCLI: \\"wifi_test --scan\\",
    'Pass'/'Success' (expected)" -> (["wifi_test --scan", "Pass",
    "Success"], ': "wifi_test --scan", ...')."""
    _, _, rest = name.partition(":")
    quoted = [a or b for a, b in _QUOTED_RE.findall(rest)]
    return quoted, rest


def display_text(status, kind_hint: str = "") -> str:
    """Map an engine StepStatus (or a legacy status string) to the
    table status text used by _set_status.

    Op steps report "Done" on success (legacy wording); measurement
    steps report "PASS". Legacy strings pass through unchanged so the
    page can keep writing "Pending" / "Skip" directly."""
    if isinstance(status, StepStatus):
        if status is StepStatus.PASS:
            return "Done" if kind_hint == "op" else "PASS"
        return {StepStatus.FAIL: "FAIL",
                StepStatus.ERROR: "Error",
                StepStatus.RUNNING: "RUNNING",
                StepStatus.IGNORED: "Ignore"}[status]
    return status
