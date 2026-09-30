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
FCT_METHODS = [
    "MessageOK", "MessageYesNo", "MessageGoStop",
    "SendtoConsole", "WaitforConsole", "CapturefromConsole",
    "Delay",
    "SendtoCLI", "WaitforCLI", "CapturefromCLI",
    "WIFI", "Bluetooth",
]


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
# the log wording (instruments / reset / fixture / power / flash).
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
    "Flash FAT Firmware": {
        "type": "flash", "slot": "fat"},
    "Flash OOBE Firmware": {
        "type": "flash", "slot": "oobe"},
}


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
    if t == "flash":
        slot = (params or {}).get("slot", "")
        image = (params or {}).get("image", "")
        return f"JLink {slot} {image}".strip()
    if t == "power" and "voltage" in (params or {}):
        return (f"{params['voltage']:g}V/"
                f"{params.get('current', 0):g}A")
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
    if t == "flash":
        slot = p.get("slot", "")
        image = p.get("image") or f"<{slot} image not configured>"
        lines = [f"J-Link loadfile {image}"]
        if p.get("verify", True):
            lines.append("J-Link verify OK")
        lines.append("J-Link reset & run")
        return lines
    if t == "power":
        if "voltage" in p:
            return [f"N5747A set {p['voltage']:.2f} V / "
                    f"{p.get('current', 0.0):.2f} A -> output ON, "
                    f"readback OK"]
        return ["N5747A output OFF"]
    return [f"{name} executed"]


def op_instrument_abbr(params: dict | None) -> str:
    """Status-bar instrument behind an operation step."""
    t = (params or {}).get("type") or ""
    if t == "power":
        return "PSU"
    if t == "fixture":
        return "DAQM"   # fixture control board sits on DAQM907A DIO
    if t == "flash":
        return "JLINK"
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


def is_impedance_short(step: tuple) -> bool:
    """True for every Impedance Shorts test row — the scope of the
    'Stop if any short' policy. Detected by the Static Impedance
    test method, by unit Ω (per-net rows), or by the legacy
    aggregate name containing 'impedance short'."""
    if step[0] == "Static Impedance":
        return True
    unit = step[2].strip()
    if unit == "Ω":
        return True
    name = step[1].lower()
    return "impedance" in name and "short" in name


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
