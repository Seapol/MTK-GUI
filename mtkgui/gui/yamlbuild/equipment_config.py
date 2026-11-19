# -*- coding: utf-8 -*-
"""v2 node 04 Equipment Config — headless data model (Qt-free).

Encodes the seven-tab equipment configuration as data and pure
functions: instrument enables + capacity, power source + derived
mechanism, power-net channel allocation, clock resource mapping, the
12-rail capture, the ATE fixture signal vocabulary and the completeness
gate the wizard checks before ``[Next: 05 >]``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Instruments (tab 1) - six rows, cascade from the mainframe
# ---------------------------------------------------------------------------
#: (key, label, default enabled, parent key or None)
INSTRUMENT_ROWS = (
    ("daq973a", "DAQ973A  mainframe", True, None),
    ("daqm908a_1", "DAQM908A #1  40 V/Ohm", True, "daq973a"),
    ("daqm908a_2", "DAQM908A #2  40 V/Ohm", True, "daq973a"),
    ("daqm907a", "DAQM907A  totalizer + 16 DIO", True, "daq973a"),
    ("u2355a", "U2355A  2 counters", True, None),
    ("n5747a", "N5747A  PSU 60 V / 12.5 A", True, None),
)

INSTRUMENT_KEYS = tuple(r[0] for r in INSTRUMENT_ROWS)
INSTRUMENT_LABEL = {r[0]: r[1] for r in INSTRUMENT_ROWS}
INSTRUMENT_PARENT = {r[0]: r[3] for r in INSTRUMENT_ROWS}

#: 40 V/Ohm points per DAQM908A module; two modules = 80
POINTS_PER_908A = 40
#: DAQM907A digital ports (8 out + 8 in)
DIO_OUT_PER_907A = 8
DIO_IN_PER_907A = 8
#: U2355A counter channels
COUNTERS_PER_U2355A = 2

# ---------------------------------------------------------------------------
# Power source + derived mechanism (tab 2)
# ---------------------------------------------------------------------------
SOURCE_PSU = "psu"
SOURCE_ADAPTER = "adapter"
MECHANISM_PSU = "psu"
MECHANISM_PSU_RELAY = "psu_relay"
MECHANISM_RELAY = "relay"
MECHANISM_MANUAL = "manual"

DEFAULT_PROMPT_ON = "Insert the DUT power adapter, then press Go."
DEFAULT_PROMPT_OFF = "Remove the DUT power adapter, then press Go."

# ---------------------------------------------------------------------------
# Clock (tab 4)
# ---------------------------------------------------------------------------
TOTALIZER_MAX_HZ = 100_000          # <= 100 kHz -> DAQM907A totalizer
COUNTER_MAX_HZ = 6_000_000          # <= 6 MHz -> U2355A counter
RESOURCE_TOTALIZER = "daqm907a:totalizer"
RESOURCE_COUNTER = "u2355a:counter"
RESOURCE_OUT_OF_RANGE = "out of range"

DEFAULT_CLOCK_PPM = 50
DEFAULT_GATE_S = 1.0

# ---------------------------------------------------------------------------
# Rails (tab 5)
# ---------------------------------------------------------------------------
RAIL_LIMIT = 12                     # U2355A AI pool
DEFAULT_RAIL_RATE_HZ = 20000
DEFAULT_RAIL_WINDOW_MS = 1000
DEFAULT_RAIL_ARM_LEAD_MS = 100
RAIL_TOLERANCE_PCT = 5.0            # +/- 5 %


@dataclass
class PowerRow:
    """Tab 3 row - one power net, one 908A channel, two tests."""

    net: str
    tp: str = ""
    r_gnd_min_ohm: float = 30.0
    nominal_v: float = 0.0
    min_v: float = 0.0
    max_v: float = 0.0
    channel: str = ""               # "daqm908a_1:12"
    not_tested: bool = False


@dataclass
class ClockRow:
    """Tab 4 row - one single-ended clock net."""

    net: str
    tp: str = ""
    nominal_hz: float = 0.0
    ppm: float = DEFAULT_CLOCK_PPM
    resource: str = ""
    not_tested: bool = False


@dataclass
class RailRow:
    """Tab 5 row - one rail in the up-sequence capture."""

    rail: str
    nominal_v: float = 0.0
    min_v: float = 0.0
    max_v: float = 0.0
    ai_channel: str = ""            # "u2355a:ai1"
    order: int = 1
    not_tested: bool = False


@dataclass
class RailsConfig:
    """Tab 5 capture parameters + selected rails."""

    rate_hz: int = DEFAULT_RAIL_RATE_HZ
    window_ms: int = DEFAULT_RAIL_WINDOW_MS
    arm_lead_ms: int = DEFAULT_RAIL_ARM_LEAD_MS
    record_only: bool = True
    rows: list[RailRow] = field(default_factory=list)


@dataclass
class FixtureSignal:
    """One fixture signal bit (port 1 output or port 2 input)."""

    key: str
    port: int
    bit: int
    label: str
    used: bool = True
    enabled: bool = True
    polarity: int = 1              # GOOD level on port 2 inputs


#: fixture signal vocabulary, in fixed order (§6)
FIXTURE_SIGNALS = (
    FixtureSignal("relay", 1, 0, "Power switch relay", polarity=1),
    FixtureSignal("clamped", 2, 0, "Clamped", polarity=1),
    FixtureSignal("inpos", 2, 1, "Cylinder in position", polarity=1),
    FixtureSignal("presence", 2, 2, "DUT presence", polarity=0),
    FixtureSignal("estop", 2, 3, "E-stop healthy", polarity=0),
    FixtureSignal("relay_closed", 2, 4, "Relay closed", polarity=1),
    FixtureSignal("peripheral_all_in", 2, 5, "Peripherals all in",
                  polarity=0),
    FixtureSignal("peripheral_all_out", 2, 6, "Peripherals all out",
                  polarity=0),
)

FIXTURE_TYPE_ATE = "ate"
FIXTURE_TYPE_MANUAL = "manual"


@dataclass
class FixtureConfig:
    """Tab 6 fixture (ATE) state."""

    type: str = FIXTURE_TYPE_ATE
    port1: str = "301"
    port2: str = "302"
    probe_pins: int = 96
    relay_channel: str = ""         # "daqm907a:1:0" / "" (not assigned)
    signals: dict[str, FixtureSignal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.signals:
            self.signals = {s.key: s for s in FIXTURE_SIGNALS}


@dataclass
class PeripheralsConfig:
    """Tab 7 peripheral declarations (need for node 06)."""

    peripheral_detect_enabled: bool = False
    wifi: bool = False
    bt: bool = False
    router: bool = False
    dut_console: bool = False


@dataclass
class EquipmentConfig:
    """The whole node 04 payload."""

    instruments: dict[str, bool] = field(default_factory=dict)
    source: str = SOURCE_PSU
    psu_voltage: float = 12.0
    psu_current_limit: float = 3.0
    release_delay_ms: int = 200
    prompt_on: str = DEFAULT_PROMPT_ON
    prompt_off: str = DEFAULT_PROMPT_OFF
    power_rows: list[PowerRow] = field(default_factory=list)
    clock_rows: list[ClockRow] = field(default_factory=list)
    rails: RailsConfig = field(default_factory=RailsConfig)
    fixture: FixtureConfig = field(default_factory=FixtureConfig)
    peripherals: PeripheralsConfig = field(
        default_factory=PeripheralsConfig)
    check_run: bool = False

    def __post_init__(self) -> None:
        if not self.instruments:
            self.instruments = {k: True for k in INSTRUMENT_KEYS}


def default_config() -> EquipmentConfig:
    return EquipmentConfig()


# ---------------------------------------------------------------------------
# Instruments + capacity
# ---------------------------------------------------------------------------
def capacity_components(instruments: dict[str, bool]) -> dict[str, int]:
    """Return the enabled counts behind the live capacity line."""
    enabled = instruments.get
    points = sum(
        POINTS_PER_908A for k in ("daqm908a_1", "daqm908a_2")
        if enabled(k, True))
    dio_out = DIO_OUT_PER_907A if enabled("daqm907a", True) else 0
    dio_in = DIO_IN_PER_907A if enabled("daqm907a", True) else 0
    counters = COUNTERS_PER_U2355A if enabled("u2355a", True) else 0
    psu = 1 if enabled("n5747a", True) else 0
    return {"v_ohm_pts": points, "dio_out": dio_out, "dio_in": dio_in,
            "counters": counters, "psu": psu}


def capacity_line(instruments: dict[str, bool]) -> str:
    """The live tab-1 capacity line (§1)."""
    cap = capacity_components(instruments)
    return (f"{cap['v_ohm_pts']} V/Ohm pts | "
            f"{cap['dio_out']} DIO out / {cap['dio_in']} DIO in (907A) | "
            f"{cap['counters']} counters (U2355A) | {cap['psu']} PSU")


# ---------------------------------------------------------------------------
# Power source + mechanism (tab 2)
# ---------------------------------------------------------------------------
def derive_mechanism(source: str, relay_enabled: bool) -> str:
    """The single mechanism implied by source + relay (§2)."""
    if source == SOURCE_PSU:
        return MECHANISM_PSU_RELAY if relay_enabled else MECHANISM_PSU
    return MECHANISM_RELAY if relay_enabled else MECHANISM_MANUAL


# ---------------------------------------------------------------------------
# Clock (tab 4)
# ---------------------------------------------------------------------------
def map_clock_resource(nominal_hz: float) -> str:
    """Frequency decides the resource; ``> 6 MHz`` is out of range."""
    if nominal_hz <= TOTALIZER_MAX_HZ:
        return RESOURCE_TOTALIZER
    if nominal_hz <= COUNTER_MAX_HZ:
        return RESOURCE_COUNTER
    return RESOURCE_OUT_OF_RANGE


def clock_limits_hz(nominal_hz: float, ppm: float) -> tuple[float, float]:
    """Min / Max from nominal and a page-level ppm tolerance."""
    delta = nominal_hz * ppm / 1_000_000.0
    return nominal_hz - delta, nominal_hz + delta


def clock_resolution_ppm(freq_hz: float, gate_s: float) -> float:
    """Resolution the totalizer/counter delivers for a gate time."""
    return 1_000_000.0 / (freq_hz * gate_s)


# ---------------------------------------------------------------------------
# Rails (tab 5)
# ---------------------------------------------------------------------------
def rail_limits_v(nominal_v: float) -> tuple[float, float]:
    """Min / Max around nominal at +/- 5 %."""
    return (nominal_v * (1 - RAIL_TOLERANCE_PCT / 100.0),
            nominal_v * (1 + RAIL_TOLERANCE_PCT / 100.0))


# ---------------------------------------------------------------------------
# Completeness gate (before [Next: 05 >])
# ---------------------------------------------------------------------------
def validate(config: EquipmentConfig) -> tuple[bool, str]:
    """Return ``(ok, first_failing_item)`` per §9."""
    if not config.check_run:
        return False, "instrument check not run"

    # 1. source chosen
    if config.source not in (SOURCE_PSU, SOURCE_ADAPTER):
        return False, "power-on source not selected"

    # 2. every power row allocated or not tested (missing nominal -> TBD,
    #    allowed)
    missing_power = sum(
        1 for r in config.power_rows
        if not r.not_tested and not r.channel)
    if missing_power:
        return False, f"{missing_power} power nets not allocated"

    # 3. every clock row has a resource or is not tested
    missing_clock = sum(
        1 for r in config.clock_rows
        if not r.not_tested and not r.resource)
    if missing_clock:
        return False, f"{missing_clock} clock nets not allocated"

    # 4. adapter requires the relay channel or both prompts
    if config.source == SOURCE_ADAPTER:
        relay = config.fixture.signals.get("relay")
        relay_ok = bool(config.fixture.relay_channel)
        prompts_ok = bool(config.prompt_on.strip() and
                          config.prompt_off.strip())
        if not (relay_ok or prompts_ok):
            return False, "adapter power needs the fixture relay or a prompt"

    # 5. ATE fixture only: wiring completeness + gauge rules are checked
    #    at the panel level (per-row editing); a Manual fixture has none.

    # 7. rail rows: AI channel present, no duplicate
    if config.rails.rows:
        used_ai: set[str] = set()
        for r in config.rails.rows:
            if r.not_tested:
                continue
            if not r.ai_channel:
                return False, "rail missing AI channel"
            if r.ai_channel in used_ai:
                return False, "duplicate rail AI channel"
            used_ai.add(r.ai_channel)

    # 8. ATE fixture only: three-digit port addresses
    if config.fixture.type == FIXTURE_TYPE_ATE:
        for port in (config.fixture.port1, config.fixture.port2):
            if not (port.isdigit() and len(port) == 3):
                return False, "fixture port address malformed"

    return True, ""


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------
def emit_equipment_config(config: EquipmentConfig) -> dict:
    """Serialize to the ``equipment_config`` section (§8)."""
    return {
        "instruments": {k: {"enabled": config.instruments.get(k, True)}
                        for k in INSTRUMENT_KEYS},
        "power_on_off": {
            "source": config.source,
            "psu": {"voltage": config.psu_voltage,
                    "current_limit": config.psu_current_limit},
            "release_delay_ms": config.release_delay_ms,
            "prompts": {"on": config.prompt_on, "off": config.prompt_off},
        },
        "channels": {
            "power": [
                {"net": r.net, "tp": r.tp,
                 "r_gnd_min_ohm": r.r_gnd_min_ohm,
                 "nominal_v": r.nominal_v, "min_v": r.min_v,
                 "max_v": r.max_v, "channel": r.channel or None,
                 "not_tested": r.not_tested}
                for r in config.power_rows],
            "clock": [
                {"net": r.net, "tp": r.tp, "nominal_hz": r.nominal_hz,
                 "ppm": r.ppm, "resource": r.resource or None,
                 "not_tested": r.not_tested}
                for r in config.clock_rows],
            "rails": {
                "rate_hz": config.rails.rate_hz,
                "window_ms": config.rails.window_ms,
                "arm_lead_ms": config.rails.arm_lead_ms,
                "record_only": config.rails.record_only,
                "rows": [
                    {"rail": r.rail, "nominal_v": r.nominal_v,
                     "min_v": r.min_v, "max_v": r.max_v,
                     "ai_channel": r.ai_channel or None,
                     "order": r.order, "not_tested": r.not_tested}
                    for r in config.rails.rows],
            },
        },
        "fixture": {
            "type": config.fixture.type,
            "port1": config.fixture.port1,
            "port2": config.fixture.port2,
            "probe_pins": config.fixture.probe_pins,
            "relay_channel": config.fixture.relay_channel or None,
            "signals": {k: {"used": s.used, "enabled": s.enabled}
                        for k, s in config.fixture.signals.items()},
        },
        "peripherals": {
            "peripheral_detect": {
                "enabled": config.peripherals.peripheral_detect_enabled},
            "wifi": {"declared": config.peripherals.wifi},
            "bt": {"declared": config.peripherals.bt},
            "router": {"declared": config.peripherals.router},
            "dut_console": {"declared": config.peripherals.dut_console},
        },
        "dio_unused": 24,
    }


def parse_equipment_config(data: dict) -> EquipmentConfig:
    """Parse the ``equipment_config`` section back to a model."""
    config = EquipmentConfig()
    instruments = data.get("instruments") or {}
    for key in INSTRUMENT_KEYS:
        entry = instruments.get(key) or {}
        config.instruments[key] = bool(entry.get("enabled", True))

    power = data.get("power_on_off") or {}
    config.source = power.get("source", SOURCE_PSU)
    psu = power.get("psu") or {}
    config.psu_voltage = float(psu.get("voltage", 12.0))
    config.psu_current_limit = float(psu.get("current_limit", 3.0))
    config.release_delay_ms = int(power.get("release_delay_ms", 200))
    prompts = power.get("prompts") or {}
    config.prompt_on = prompts.get("on", DEFAULT_PROMPT_ON)
    config.prompt_off = prompts.get("off", DEFAULT_PROMPT_OFF)

    channels = data.get("channels") or {}
    config.power_rows = [
        PowerRow(net=r.get("net", ""), tp=r.get("tp", ""),
                 r_gnd_min_ohm=float(r.get("r_gnd_min_ohm", 30.0)),
                 nominal_v=float(r.get("nominal_v", 0.0)),
                 min_v=float(r.get("min_v", 0.0)),
                 max_v=float(r.get("max_v", 0.0)),
                 channel=r.get("channel") or "",
                 not_tested=bool(r.get("not_tested", False)))
        for r in (channels.get("power") or [])]
    config.clock_rows = [
        ClockRow(net=r.get("net", ""), tp=r.get("tp", ""),
                 nominal_hz=float(r.get("nominal_hz", 0.0)),
                 ppm=float(r.get("ppm", DEFAULT_CLOCK_PPM)),
                 resource=r.get("resource") or "",
                 not_tested=bool(r.get("not_tested", False)))
        for r in (channels.get("clock") or [])]

    rails = (channels.get("rails") or {})
    config.rails = RailsConfig(
        rate_hz=int(rails.get("rate_hz", DEFAULT_RAIL_RATE_HZ)),
        window_ms=int(rails.get("window_ms", DEFAULT_RAIL_WINDOW_MS)),
        arm_lead_ms=int(rails.get("arm_lead_ms", DEFAULT_RAIL_ARM_LEAD_MS)),
        record_only=bool(rails.get("record_only", True)),
        rows=[
            RailRow(rail=r.get("rail", ""),
                    nominal_v=float(r.get("nominal_v", 0.0)),
                    min_v=float(r.get("min_v", 0.0)),
                    max_v=float(r.get("max_v", 0.0)),
                    ai_channel=r.get("ai_channel") or "",
                    order=int(r.get("order", 1)),
                    not_tested=bool(r.get("not_tested", False)))
            for r in (rails.get("rows") or [])])

    fixture = data.get("fixture") or {}
    config.fixture = FixtureConfig(
        type=fixture.get("type", FIXTURE_TYPE_ATE),
        port1=fixture.get("port1", "301"),
        port2=fixture.get("port2", "302"),
        probe_pins=int(fixture.get("probe_pins", 96)),
        relay_channel=fixture.get("relay_channel") or "")
    signals = fixture.get("signals") or {}
    for key, sig in config.fixture.signals.items():
        entry = signals.get(key) or {}
        sig.used = bool(entry.get("used", sig.used))
        sig.enabled = bool(entry.get("enabled", sig.enabled))

    peripherals = data.get("peripherals") or {}
    det = peripherals.get("peripheral_detect") or {}
    config.peripherals.peripheral_detect_enabled = bool(
        det.get("enabled", False))
    config.peripherals.wifi = bool(
        (peripherals.get("wifi") or {}).get("declared", False))
    config.peripherals.bt = bool(
        (peripherals.get("bt") or {}).get("declared", False))
    config.peripherals.router = bool(
        (peripherals.get("router") or {}).get("declared", False))
    config.peripherals.dut_console = bool(
        (peripherals.get("dut_console") or {}).get("declared", False))

    return config
