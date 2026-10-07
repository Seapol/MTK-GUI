# -*- coding: utf-8 -*-
"""Virtual hardware rack - the simulation backend used in Virtual mode.

The production station runs on Windows with the real rack:

  * Keysight DAQ973A mainframe (GPIB) with two DAQM908A 40-ch
    multiplexers (CH101-140 / CH201-240 -> TP_P1..TP_P80, 2-wire OHM and
    DCV shared) and one DAQM907A (100 kHz totalizer -> CLK1, two 16-bit
    AO channels -> TP_ADC0/1, 16-ch open-drain DIO -> fixture control)
  * Keysight U2355A USB DAQ: 12 analog inputs (power-rails up-sequence
    capture -> CSV + waveform), two counters up to 6 MHz (CLK2/CLK3),
    24 TTL DIO (DUT GPIO through level shifters)
  * Keysight N5747A PSU (60 V / 12.5 A) feeding VIN, with the E-Stop
    loop hard-wired into its J1 inhibit input
  * pneumatic fixture with a control board carrying four signals:
    press (out, H = clamp down), inpos (in, H = locked), DUT presence
    (in, active-low) and E-Stop healthy (in, active-low)

This module simulates every one of those instruments so the whole test
flow can be developed and verified on macOS without hardware.  It is
deliberately written as plain Python (no Qt): the future Real backend
will implement the same method signatures with SCPI/VISA calls, which
keeps the Windows bring-up down to connection parameters and command
checks.

Measurements are stochastic but realistic: healthy values sit well
inside the YAML limits with instrument-grade noise, while the
FaultPolicy injects out-of-limit values (FAIL) or instrument faults
(Error) at the configured percentages.
"""

import hashlib
import math
import random
import re
from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# fault policy
# ---------------------------------------------------------------------------


class FaultPolicy:
    """Single-draw fault injection for one virtual rack.

    One uniform draw per test case makes the two outcomes mutually
    exclusive, so the configured percentages are exact (unlike two
    independent rolls, whose probabilities overlap):

        u < err_pct                       -> Error
        err_pct <= u < err_pct + fail_pct -> FAIL
        otherwise                         -> healthy
    """

    def __init__(self, fail_pct=0.0, err_pct=0.0, seed=None):
        self.rng = random.Random(seed)
        self.fail_pct = float(fail_pct)
        self.err_pct = float(err_pct)

    def set_ratios(self, fail_pct, err_pct):
        self.fail_pct = float(fail_pct)
        self.err_pct = float(err_pct)

    def roll(self, allow_fail=True, allow_error=True):
        """Draw one fault for a test case: 'FAIL', 'Error' or None."""
        u = self.rng.random() * 100.0
        if allow_error and u < self.err_pct:
            return "Error"
        if allow_fail and u < self.err_pct + self.fail_pct:
            return "FAIL"
        return None


# ---------------------------------------------------------------------------
# result container
# ---------------------------------------------------------------------------


@dataclass
class Measurement:
    """One executed measurement / operation.

    verdict  - 'PASS', 'FAIL', 'Error' or 'Done'
    text     - content of the table Measured cell
    lines    - Event Log lines (SCPI-style, mirroring future Real logs)
    value    - numeric measured value when applicable
    failed_point - label of the failing channel/point (aggregate tests)
    """

    verdict: str
    text: str = "—"
    lines: List[str] = field(default_factory=list)
    value: Optional[float] = None
    failed_point: Optional[str] = None


def _hash_rng(text, salt=0):
    """Deterministic per-name RNG so a given net keeps its character
    (healthy resistance level, rise time, ...) across runs."""
    h = hashlib.md5(f"{text}:{salt}".encode("utf-8")).hexdigest()
    return random.Random(int(h[:12], 16))


def _float(text, default=None):
    try:
        return float(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


_TP_P_RE = re.compile(r"TP_P(\d+)", re.IGNORECASE)
_TP_C_RE = re.compile(r"TP_C(\d+)", re.IGNORECASE)


def tp_index(name):
    """Return ('P', n) / ('C', n) parsed from a step name or None."""
    m = _TP_P_RE.search(name or "")
    if m:
        return "P", int(m.group(1))
    m = _TP_C_RE.search(name or "")
    if m:
        return "C", int(m.group(1))
    return None


def daqm_channel(tp_number):
    """DAQ973A channel for a probe point TP_P1..TP_P80.

    DAQM908A #1 (slot 1): CH101-140 -> TP_P1..P40
    DAQM908A #2 (slot 2): CH201-240 -> TP_P41..P80
    """
    if tp_number <= 40:
        return 1, 100 + tp_number
    return 2, 200 + (tp_number - 40)


# ---------------------------------------------------------------------------
# Keysight N5747A PSU
# ---------------------------------------------------------------------------


class VirtualPSU:
    """N5747A: 60 V / 12.5 A single output, LAN/USB/GPIB.

    Models output state, V/I setpoints, ~0.3 % readback and the J1
    hardware inhibit driven by the E-Stop loop."""

    IDN = "Keysight,N5747A"

    def __init__(self, rng):
        self.rng = rng
        self.output_on = False
        self.v_set = 0.0
        self.i_set = 0.0
        self.inhibited = False

    def reset(self):
        self.output_on = False
        self.v_set = 0.0
        self.i_set = 0.0
        self.inhibited = False

    def set_output(self, on, voltage=0.0, current=0.0, load_a=0.6):
        """Switch the output; returns (ok, lines).  An active E-Stop
        inhibit keeps the output off (hardware loop, no software bypass).
        """
        if on:
            if self.inhibited:
                self.output_on = False
                return False, [
                    "PSU: SOUR:VOLT %.2f; SOUR:CURR %.2f; OUTP ON"
                    % (voltage, current),
                    "PSU: OUTP inhibited by J1 RI/FLT (E-Stop loop open) "
                    "-> output stays OFF -> Error",
                ]
            self.v_set = float(voltage)
            self.i_set = float(current)
            self.output_on = True
            v_rd = self.v_set * (1 + self.rng.gauss(0, 0.0015))
            i_rd = load_a * (1 + self.rng.gauss(0, 0.05))
            return True, [
                "PSU: SOUR:VOLT %.2f; SOUR:CURR %.2f; OUTP ON"
                % (self.v_set, self.i_set),
                "PSU: MEAS:VOLT? %.3f V; MEAS:CURR? %.3f A (4-wire "
                "remote sense) -> output ON" % (v_rd, i_rd),
            ]
        self.output_on = False
        return True, [
            "PSU: OUTP OFF; MEAS:VOLT? %.3f V"
            % abs(self.rng.gauss(0, 0.002))
        ]

    def read_voltage(self):
        if not self.output_on:
            return self.rng.gauss(0, 0.001)
        return self.v_set * (1 + self.rng.gauss(0, 0.0015))


# ---------------------------------------------------------------------------
# pneumatic fixture
# ---------------------------------------------------------------------------


class VirtualFixture:
    """Fixture control board (DAQM907A open-drain DIO, 4 of 16 ch used).

    Signals: press (out, H clamp down), inpos (in, H locked), presence
    (in, active-low = DUT present), estop (in, active-low = healthy).
    """

    def __init__(self, rng):
        self.rng = rng
        self.press = "L"
        self.inpos = "L"
        self.present = True
        self.estop_triggered = False

    def reset(self):
        self.press = "L"
        self.inpos = "L"
        self.estop_triggered = False

    def drive(self, signal, level, fault):
        """Execute one fixture op; returns (verdict, lines).

        fault - None / 'Error' from the policy; an Error models a
        pneumatic timeout, a missing DUT or an open E-Stop loop.
        """
        if signal == "press" and level == "H":
            if fault == "Error":
                # pneumatic valve / lid timeout, or no DUT on the bed
                if self.rng.random() < 0.5:
                    return "Error", [
                        "FIX: DIO write press=H; waiting inpos ...",
                        "FIX: DUT presence input HIGH (no DUT on the bed) "
                        "-> clamp aborted -> Error",
                    ]
                return "Error", [
                    "FIX: DIO write press=H; waiting inpos ...",
                    "FIX: inpos timeout (lid not locked within 5.0 s) "
                    "-> Error",
                ]
            self.press = "H"
            settle = 0.35 + self.rng.uniform(0, 0.2)
            self.inpos = "H"
            return "Done", [
                "FIX: DIO write press=H (clamp down)",
                "FIX: DUT presence input LOW (DUT detected)",
                "FIX: inpos=H locked after %.2f s" % settle,
            ]
        if signal == "press" and level == "L":
            self.press = "L"
            self.inpos = "L"
            return "Done", [
                "FIX: DIO write press=L (release)",
                "FIX: inpos=L released",
            ]
        if signal == "inpos" and level == "H":
            if fault == "Error" or self.inpos != "H":
                return "Error", [
                    "FIX: read inpos=%s (expected H = locked) -> Error"
                    % self.inpos
                ]
            return "Done", ["FIX: read inpos=H (locked) -> verified"]
        if signal == "inpos" and level == "L":
            self.inpos = "L"
            return "Done", ["FIX: fixture unlocked (inpos=L)"]
        if signal == "estop":
            if level == "L":
                if fault == "Error":
                    self.estop_triggered = True
                    return "Error", [
                        "FIX: read E-Stop input HIGH (button pressed / "
                        "loop open) -> PSU inhibit active -> Error",
                    ]
                self.estop_triggered = False
                return "Done", [
                    "FIX: read E-Stop input LOW (healthy, loop closed)"
                ]
            self.estop_triggered = True
            return "Done", ["FIX: E-Stop input HIGH (triggered)"]
        return "Done", ["FIX: %s=%s executed" % (signal, level)]

    def dio_test(self, fault):
        """Aggregate DIO loopback of the 4 used control signals."""
        expected = {"press": self.press, "inpos": self.inpos,
                    "presence": "L" if self.present else "H",
                    "estop": "L" if not self.estop_triggered else "H"}
        if fault == "Error":
            return Measurement("Error", "—", [
                "FIX: DAQM907A DIO scan: comm timeout -> Error"])
        if fault == "FAIL":
            bad = "inpos"
            return Measurement("FAIL", "3/4 ch", [
                "FIX: DAQM907A DIO loopback: press/presence/estop ok",
                "FIX: DIO mismatch on '%s' -> 3/4 ch -> FAIL" % bad],
                failed_point=bad)
        lines = ["FIX: DAQM907A DIO loopback: %s"
                 % ", ".join(f"{k}={v}" for k, v in expected.items()),
                 "FIX: 4/4 signals verified"]
        return Measurement("PASS", "4/4 ch", lines)


# ---------------------------------------------------------------------------
# Keysight DAQ973A mainframe (DAQM908A x2 + DAQM907A)
# ---------------------------------------------------------------------------


class VirtualDAQ973A:
    """Simulates the 6.5-digit mainframe used for ICT DC measurements."""

    IDN = "Keysight,DAQ973A"

    def __init__(self, rng):
        self.rng = rng

    # -- 2-wire ohm, unpowered short screening ---------------------------
    def measure_ohm(self, tp_name, r_min, fault):
        tp = tp_index(tp_name)
        n = tp[1] if tp else 0
        slot, ch = daqm_channel(max(1, n))
        base_rng = _hash_rng(tp_name or "net", salt=1)
        # healthy in-circuit rail impedance: log-uniform 7 .. 3000 ohm,
        # stable per net, with run-to-run variation (sigma ~12 %)
        base = math.exp(base_rng.uniform(math.log(7.0), math.log(3000.0)))
        if fault == "Error":
            return Measurement("Error", "—", [
                f"DAQM: slot{slot} CH{ch}: FUNC RES; READ? timeout "
                f"(2-wire OHM) -> Error"])
        if fault == "FAIL":
            value = self.rng.uniform(0.05, min(1.45, r_min - 0.05))
            return Measurement("FAIL", f"{value:.2f}", [
                f"DAQM: slot{slot} CH{ch}: 2-wire OHM = {value:.2f} OHM "
                f"(limit >= {r_min:g} OHM) -> SHORT -> FAIL"],
                value=value, failed_point=tp_name)
        value = base * math.exp(self.rng.gauss(0, 0.12))
        value = max(value, r_min + 0.5)
        verdict = "PASS" if value >= r_min else "FAIL"
        line = (f"DAQM: slot{slot} CH{ch}: 2-wire OHM = {value:.2f} OHM "
                f"(limit >= {r_min:g} OHM) -> {verdict}")
        return Measurement(verdict, f"{value:.2f}", [line], value=value)

    # -- DC voltage, powered, +/-0.1 % production limits -----------------
    def measure_dcv(self, tp_name, lo, hi, powered, fault):
        tp = tp_index(tp_name)
        n = tp[1] if tp else 0
        slot, ch = daqm_channel(max(1, n))
        if lo is None or hi is None:
            # ground reference test point (TP_GND): expect ~0 V whether
            # the DUT is powered or not
            if fault == "Error":
                return Measurement("Error", "—", [
                    f"DAQM: slot{slot} CH{ch}: FUNC VOLT:DC; READ? timeout "
                    f"-> Error"])
            if fault == "FAIL":
                value = self.rng.choice((-1.0, 1.0))                     * self.rng.uniform(0.10, 0.60)
                return Measurement("FAIL", f"{value:.3f}", [
                    f"DAQM: slot{slot} CH{ch}: GND reference DCV = "
                    f"{value:.3f} V (expected ~0 V, +/-50 mV) -> FAIL"],
                    value=value, failed_point=tp_name)
            value = self.rng.gauss(0.0, 0.002)
            verdict = "PASS" if abs(value) < 0.05 else "FAIL"
            return Measurement(verdict, f"{value:.3f}", [
                f"DAQM: slot{slot} CH{ch}: GND reference DCV = "
                f"{value:.3f} V (~0 V) -> {verdict}"], value=value)
        nominal = (lo + hi) / 2.0
        sigma = max(nominal * 0.0003, 0.0005)  # 6.5-digit DMM grade
        if fault == "Error":
            return Measurement("Error", "—", [
                f"DAQM: slot{slot} CH{ch}: FUNC VOLT:DC; READ? timeout "
                f"-> Error"])
        if not powered:
            value = self.rng.gauss(0, 0.001)
            return Measurement("FAIL", f"{value:.3f}", [
                f"DAQM: slot{slot} CH{ch}: DCV = {value:.3f} V but PSU "
                f"output is OFF ({lo:g}..{hi:g} V expected) -> FAIL"],
                value=value, failed_point=tp_name)
        if fault == "FAIL":
            band = max(nominal * 0.005, 0.01)
            if self.rng.random() < 0.5:
                value = hi + self.rng.uniform(0.2, 1.0) * band
            else:
                value = lo - self.rng.uniform(0.2, 1.0) * band
            value = max(0.0, value)
            return Measurement("FAIL", f"{value:.3f}", [
                f"DAQM: slot{slot} CH{ch}: DCV = {value:.3f} V "
                f"({lo:g}..{hi:g} V) -> out of limit -> FAIL"],
                value=value, failed_point=tp_name)
        value = nominal + self.rng.gauss(0, sigma)
        verdict = "PASS" if lo <= value <= hi else "FAIL"
        line = (f"DAQM: slot{slot} CH{ch}: DCV = {value:.3f} V "
                f"({lo:g}..{hi:g} V) -> {verdict}")
        return Measurement(verdict, f"{value:.3f}", [line], value=value)

    # -- DAQM907A totalizer: CLK1 <= 100 kHz ------------------------------
    def measure_totalizer(self, tp_name, lo, hi, powered, fault):
        nominal = (lo + hi) / 2.0
        sigma = (hi - lo) * 0.2
        if fault == "Error":
            return Measurement("Error", "—", [
                "DAQM: DAQM907A totalizer: gate timeout -> Error"])
        if not powered:
            value = 0.0
            return Measurement("FAIL", f"{value:,.1f}", [
                f"DAQM: DAQM907A totalizer {tp_name}: 0 Hz (DUT unpowered) "
                f"-> FAIL"], value=value, failed_point=tp_name)
        if fault == "FAIL":
            value = hi + (hi - lo) * self.rng.uniform(0.3, 0.8)
            return Measurement("FAIL", f"{value:,.1f}", [
                f"DAQM: DAQM907A totalizer {tp_name}: {value:,.1f} Hz "
                f"({lo:g}..{hi:g} Hz) -> FAIL"], value=value,
                failed_point=tp_name)
        value = nominal + self.rng.gauss(0, sigma)
        verdict = "PASS" if lo <= value <= hi else "FAIL"
        return Measurement(verdict, f"{value:,.1f}", [
            f"DAQM: DAQM907A totalizer {tp_name}: {value:,.1f} Hz "
            f"({lo:g}..{hi:g} Hz) -> {verdict}"], value=value)

    # -- DAQM907A AO -> ADC loopback, +/-12 V, 16-bit --------------------
    def ao_stimulus(self, powered, fault):
        if fault == "Error":
            return Measurement("Error", "—", [
                "DAQM: DAQM907A AO: self-test comm error -> Error"])
        levels = (-12.0, -5.0, 0.0, 5.0, 12.0)
        if fault == "FAIL" or not powered:
            bad_ch = self.rng.choice(("AO0", "AO1"))
            return Measurement("FAIL", "mismatch", [
                f"DAQM: DAQM907A AO stimulus {bad_ch} -> TP_ADC readback "
                f"mismatch (>0.5 V error) -> FAIL"],
                failed_point=bad_ch)
        worst = 0.0
        for ch in ("AO0", "AO1"):
            for v in levels:
                rd = v + self.rng.gauss(0, 0.004)
                worst = max(worst, abs(rd - v))
        vmax = 12.0 + self.rng.gauss(0, 0.003)
        return Measurement("PASS", f"{vmax:.3f}", [
            "DAQM: DAQM907A AO0/AO1 sweep -12..+12 V -> TP_ADC0/1 "
            "readback within 0.02 V",
            f"DAQM: worst readback error {worst*1000:.1f} mV -> PASS"],
            value=vmax)


# ---------------------------------------------------------------------------
# Keysight U2355A USB DAQ
# ---------------------------------------------------------------------------


class VirtualU2355A:
    """12-ch AI capture, two 6 MHz counters, 24 TTL DIO, 2 spare AO."""

    IDN = "Keysight,U2355A"

    def __init__(self, rng):
        self.rng = rng

    def measure_counter(self, counter, tp_name, lo, hi, powered, fault):
        nominal = (lo + hi) / 2.0
        sigma = (hi - lo) * 0.2  # ~20 ppm on a +/-100 ppm window
        if fault == "Error":
            return Measurement("Error", "—", [
                f"DAQ: U2355A CTR{counter}: count gate timeout -> Error"])
        if not powered:
            return Measurement("FAIL", "0.0", [
                f"DAQ: U2355A CTR{counter} {tp_name}: 0 Hz (DUT "
                f"unpowered) -> FAIL"], value=0.0, failed_point=tp_name)
        if fault == "FAIL":
            value = hi + (hi - lo) * self.rng.uniform(0.3, 0.8)
            return Measurement("FAIL", f"{value:,.1f}", [
                f"DAQ: U2355A CTR{counter} {tp_name}: {value:,.1f} Hz "
                f"({lo:g}..{hi:g} Hz) -> FAIL"], value=value,
                failed_point=tp_name)
        value = nominal + self.rng.gauss(0, sigma)
        verdict = "PASS" if lo <= value <= hi else "FAIL"
        return Measurement(verdict, f"{value:,.1f}", [
            f"DAQ: U2355A CTR{counter} {tp_name}: {value:,.1f} Hz "
            f"({lo:g}..{hi:g} Hz) -> {verdict}"], value=value)

    def gpio_test(self, fault):
        """24-ch DUT GPIO walking pattern through level shifters."""
        if fault == "Error":
            return Measurement("Error", "—", [
                "DAQ: U2355A DIO bank: USB transfer error -> Error"])
        if fault == "FAIL":
            ch = self.rng.randrange(24)
            return Measurement("FAIL", "23/24 ch", [
                "DAQ: U2355A DIO walking 1/0 via level shifter "
                "(1.8/3.3/5 V)",
                f"DAQ: GPIO CH{ch:02d} readback mismatch -> 23/24 ch "
                f"-> FAIL"], failed_point=f"GPIO CH{ch:02d}")
        return Measurement("PASS", "24/24 ch", [
            "DAQ: U2355A DIO walking 1/0 via level shifter "
            "(1.8/3.3/5 V)",
            "DAQ: 24/24 GPIO channels verified"])

    def capture_rails(self, rails, start_s, end_s, rate_hz, powered,
                      fault):
        """Simulate the 12-ch AI recording of the power-rails up sequence.

        Returns (frac_samples, volt_samples, anomaly) where each list is
        ordered like ``rails`` (name, color, vnom, ramp_offset_s).  The
        plot/AI-review consume fractions of nominal; the CSV stores the
        volt samples (DUT-side, i.e. divider reconstructed).  A FAIL
        fault corrupts one rail (stuck at 0 V or excessive ripple/overshoot)
        so the AI wave review has something to flag.

        Realism (user direction): the rails come up STAGGERED (per-rail
        startup delay - sequenced power-up instead of a simultaneous
        ramp), each rail has its OWN rise time / overshoot / ripple
        signature (hashed per rail name), and every later rail turning
        on produces a small decaying LOAD-STEP SAG on the rails that
        are already up.
        """
        rng = random.Random()  # fresh entropy for every capture
        n = max(1, int(round((end_s - start_s) * rate_hz)))
        power_idx = int(round(abs(min(start_s, 0.0)) * rate_hz))
        anomaly = None
        bad_rail = -1
        bad_mode = None
        if fault == "FAIL" and rails:
            bad_rail = rng.randrange(len(rails))
            bad_mode = rng.choice(("stuck", "ripple"))
        # per-rail analog "personality" + turn-on schedule (hashed per
        # name so every capture of the same project looks alike)
        starts = []
        for idx, (name, _color, vnom, offset) in enumerate(rails):
            cr = _hash_rng(name, salt=2)
            if offset > 0.0:
                delay = offset
            else:
                # sequenced power-up: staggered by position + jitter
                delay = 0.02 * idx + cr.uniform(0.0, 0.04)
            starts.append(power_idx + int(delay * rate_hz))
        frac, volts = [], []
        for idx, (name, _color, vnom, offset) in enumerate(rails):
            cr = _hash_rng(name, salt=2)
            rise_ms = cr.uniform(1.5, 12.0)          # own rise time
            overshoot = cr.uniform(0.004, 0.045)
            overshoot2 = cr.choice((0.0, 0.0, 0.35))  # 2nd-order bump
            ripple_pct = cr.uniform(0.0008, 0.0035)
            ripple_hz = cr.uniform(80, 400)
            ripple2_pct = cr.uniform(0.0, 0.0012)     # beat frequency
            ripple2_hz = cr.uniform(500, 900)
            noise_pct = 0.0006
            sag_pct = cr.uniform(0.006, 0.015)        # load-step sag
            sag_tau = cr.uniform(0.010, 0.025)
            if idx == bad_rail:
                anomaly = name
                if bad_mode == "ripple":
                    overshoot = 0.12
                    ripple_pct = 0.06
            ramp_pts = max(1, int((rise_ms / 1000.0) * rate_hz))
            off_pts = starts[idx]
            v_series, f_series = [], []
            for i in range(n):
                t = (i - power_idx) / rate_hz
                if not powered or (idx == bad_rail and bad_mode == "stuck"):
                    v = rng.gauss(0, 0.0008)
                elif i < power_idx:
                    v = rng.gauss(0, 0.0005)
                else:
                    j = i - off_pts
                    if j < 0:
                        frac0 = 0.0
                    elif j < ramp_pts:
                        x = j / ramp_pts
                        frac0 = x * x * (3 - 2 * x)  # smoothstep
                    else:
                        frac0 = 1.0
                    settle_t = max(0.0, (j - ramp_pts) / rate_hz)
                    over = overshoot * math.exp(-settle_t / 0.02)
                    # second-order bump ~2 rise-times after the ramp
                    bump_t = 2.0 * ramp_pts / rate_hz
                    bump = (overshoot2 * overshoot
                            * math.exp(-max(0.0, settle_t - bump_t) / 0.012)
                            if settle_t > bump_t else 0.0)
                    rip = (ripple_pct * math.sin(2 * math.pi * ripple_hz * t)
                           + ripple2_pct
                           * math.sin(2 * math.pi * ripple2_hz * t))
                    noise = noise_pct * rng.gauss(0, 1)
                    # load-step sag: a LATER rail energizing loads the
                    # already-up rails (small decaying dip)
                    sag = 0.0
                    for jdx, jstart in enumerate(starts):
                        if jdx == idx or jdx <= idx:
                            continue
                        dt = (i - jstart) / rate_hz
                        if dt > 0.0:
                            sag -= sag_pct * math.exp(-dt / sag_tau)
                    frac0 = max(0.0, min(1.18,
                                         frac0
                                         + (over + bump) * (frac0 > 0)
                                         + rip + noise + sag))
                    v = frac0 * vnom
                v_series.append(v)
                f_series.append(v / vnom if vnom else 0.0)
            volts.append(v_series)
            frac.append(f_series)
        return frac, volts, anomaly


# ---------------------------------------------------------------------------
# facade
# ---------------------------------------------------------------------------


class VirtualRack:
    """Owns every virtual instrument and routes workflow steps to them."""

    def __init__(self, fail_pct=0.0, err_pct=0.0, seed=None):
        self.rng = random.Random(seed)
        self.policy = FaultPolicy(fail_pct, err_pct,
                                  seed=self.rng.randrange(1 << 30))
        self.psu = VirtualPSU(self.rng)
        self.fixture = VirtualFixture(self.rng)
        self.daqm = VirtualDAQ973A(self.rng)
        self.daq = VirtualU2355A(self.rng)

    # -- configuration / lifecycle ---------------------------------------
    def set_fault_ratios(self, fail_pct, err_pct):
        self.policy.set_ratios(fail_pct, err_pct)

    def reset_cycle(self):
        """Power everything down and release the fixture (new unit)."""
        self.psu.reset()
        self.fixture.reset()

    # -- operation steps --------------------------------------------------
    def init_instruments(self, instruments, reset=False):
        verb = "reset" if reset else "init"
        idn = {"DAQM": VirtualDAQ973A.IDN, "DAQ": VirtualU2355A.IDN,
               "PSU": VirtualPSU.IDN}
        fault = self.policy.roll(allow_fail=False)
        lines, failed = [], None
        for abbr in instruments or ["DAQM", "DAQ", "PSU"]:
            if fault == "Error" and failed is None and self.rng.random() < 0.6:
                lines.append(f"{abbr}: *RST; *IDN? -> no response "
                             f"({verb}) -> Error")
                failed = abbr
            else:
                lines.append(f"{abbr}: *RST; *IDN? {idn.get(abbr, abbr)} "
                             f"-> {verb} OK")
        if reset:
            self.reset_cycle()
        if failed:
            return Measurement("Error", "—", lines)
        return Measurement("Done", "—", lines)

    def execute_op(self, name, params):
        """Run one ICT/FCT operation step; returns Measurement."""
        p = dict(params or {})
        t = p.get("type") or "generic"
        fault = self.policy.roll(allow_fail=False)
        if t in ("instruments", "reset"):
            return self.init_instruments(p.get("instruments"),
                                         reset=(t == "reset"))
        if t == "fixture":
            verdict, lines = self.fixture.drive(
                p.get("signal", "press"), p.get("level", "H"), fault)
            return Measurement(verdict, "—", lines)
        if t == "power":
            # the E-Stop loop is hard-wired to the PSU J1 inhibit
            self.psu.inhibited = self.fixture.estop_triggered
            if "voltage" in p:
                ok, lines = self.psu.set_output(
                    True, float(p.get("voltage", 5.0)),
                    float(p.get("current", 1.0)))
            else:
                ok, lines = self.psu.set_output(False)
            if fault == "Error" and ok:
                lines = [lines[0] if lines else "PSU: command sent",
                         "PSU: no reply (USB/GPIB timeout) -> Error"]
                ok = False
            return Measurement("Done" if ok else "Error", "—", lines)
        return Measurement("Done", "—", [f"{name} executed"])

    # -- measurement steps ------------------------------------------------
    def measure_row(self, kind, name, unit, lo_s, hi_s, force=None):
        """Execute one ICT measurement row.

        force - None (policy roll), 'FAIL' or 'Error' (context-menu
        simulated failure overrides the policy).
        """
        fault = force or self.policy.roll()
        powered = self.psu.output_on
        lo = _float(lo_s)
        hi = _float(hi_s)
        tp = tp_index(name)
        n_low = name.lower()

        # name-routed aggregate tests first: the ADC stimulus row also
        # carries unit "V" and must not fall into the DCV branch
        if "adc" in n_low and "stimulus" in n_low:
            return self.daqm.ao_stimulus(powered, fault)
        if "fixture dio" in n_low:
            return self.fixture.dio_test(fault)
        if "gpio" in n_low:
            return self.daq.gpio_test(fault)

        if kind == "Static Impedance" or (unit or "").strip() == "Ω":
            r_min = lo if lo is not None else 1.5
            return self.daqm.measure_ohm(name, r_min, fault)

        if kind == "Power Voltage" or (unit or "").strip() == "V":
            return self.daqm.measure_dcv(name, lo, hi, powered, fault)

        if kind == "Clock Hz" or (unit or "").strip() == "Hz":
            if lo is None or hi is None:
                return Measurement("Error", "—",
                                   [f"{name}: limits missing -> Error"])
            # CLK1 (RTC, 32.768 kHz) -> DAQM907A totalizer;
            # CLK2/CLK3 (4/6 MHz) -> U2355A counters
            if tp and tp[0] == "C" and tp[1] >= 2:
                counter = 1 if tp[1] == 2 else 2
                return self.daq.measure_counter(
                    counter, name, lo, hi, powered, fault)
            return self.daqm.measure_totalizer(
                name, lo, hi, powered, fault)

        # unknown aggregate test: healthy placeholder
        if fault == "Error":
            return Measurement("Error", "—", [f"{name}: instrument timeout "
                                              f"-> Error"])
        if fault == "FAIL":
            return Measurement("FAIL", "mismatch",
                               [f"{name}: unexpected reading -> FAIL"])
        return Measurement("PASS", "ok", [f"{name}: ok -> PASS"])

    # -- power-rails capture ----------------------------------------------
    def capture_rails(self, rails, start_s, end_s, rate_hz, force=None):
        # force=None rolls the fault policy; "PASS" forces a healthy
        # capture (properties dialog preview); FAIL/Error are forced.
        fault = self.policy.roll() if force is None else force
        if fault == "Error":
            return None, None, "error"
        frac, volts, anomaly = self.daq.capture_rails(
            rails, start_s, end_s, rate_hz, self.psu.output_on, fault)
        return frac, volts, anomaly
