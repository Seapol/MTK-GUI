# -*- coding: utf-8 -*-
"""Declarative field schemas for the twelve Yaml Build modules.

Every module owns an independent parameter schema (interface_spec.md
section 31): the block config dialogs, the parameter validation and
the Excel exchange are all generated from these tables, so the twelve
modules never share state and fields cannot drift between UI, YAML
and Excel.  Rack-ATE instrument parameters live ONLY in block 03
(instruments); blocks 02 and 04-06/10 reference them read-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mtkgui.gui.yamlbuild.stages import STAGE_BY_KEY

#: field types
T_STR = "str"
T_INT = "int"
T_FLOAT = "float"
T_BOOL = "bool"
T_CHOICE = "choice"
T_TEXT = "text"          # multiline free text (one spec entry per line)

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


@dataclass(frozen=True)
class FieldSpec:
    """One parameter field of a module.

    Attributes:
        name:     Parameter key (YAML / Excel column).
        label:    UI label.
        ftype:    One of T_STR / T_INT / T_FLOAT / T_BOOL / T_CHOICE /
                  T_TEXT.
        default:  Default value (str for T_TEXT lines joined by \n).
        required: Empty value is a validation error when True.
        minimum:  Inclusive lower bound for numeric types.
        maximum:  Inclusive upper bound for numeric types.
        choices:  Allowed values for T_CHOICE.
        multiline: T_TEXT renders a multi-line editor.
        max_lines: Upper bound of non-empty T_TEXT lines (None = no
                   limit; e.g. the 12-net power capture list).
        pattern:  Regex the string value must match (optional).
        unit:     Unit shown in the UI / Excel (informational).
        remarks:  Column for the Excel exchange.
    """

    name: str
    label: str
    ftype: str = T_STR
    default: object = ""
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    multiline: bool = False
    max_lines: int | None = None
    pattern: str = ""
    unit: str = ""
    remarks: str = ""

    def validate(self, value) -> str:
        """Validate one value against this field spec.

        Args:
            value: Raw value (str from the UI / Excel).

        Returns:
            "" when valid, otherwise a human readable error message.
        """
        text = "" if value is None else str(value).strip()
        if self.ftype == T_BOOL:
            if text.lower() in ("", "false", "0", "no"):
                return "" if not self.required else \
                    f"{self.label}: value required"
            if text.lower() not in ("true", "1", "yes"):
                return f"{self.label}: boolean expected (true/false)"
            return ""
        if not text:
            return f"{self.label}: value required" if self.required else ""
        if self.ftype == T_TEXT and self.max_lines is not None:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if len(lines) > self.max_lines:
                return (f"{self.label}: at most {self.max_lines} entries "
                        f"allowed ({len(lines)} given)")
        if self.ftype in (T_INT, T_FLOAT):
            try:
                num = float(text)
            except ValueError:
                return f"{self.label}: number expected"
            if self.ftype == T_INT and num != int(num):
                return f"{self.label}: integer expected"
            if self.minimum is not None and num < self.minimum:
                return (f"{self.label}: {num} below minimum "
                        f"{self.minimum:g}")
            if self.maximum is not None and num > self.maximum:
                return (f"{self.label}: {num} above maximum "
                        f"{self.maximum:g}")
            return ""
        if self.ftype == T_CHOICE:
            if self.choices and text not in self.choices:
                return (f"{self.label}: must be one of "
                        f"{'/'.join(self.choices)}")
            return ""
        if self.pattern and not re.match(self.pattern, text):
            return f"{self.label}: invalid format"
        return ""


def _f(name, label, **kw) -> FieldSpec:
    return FieldSpec(name=name, label=label, **kw)


#: fixed Batch # options (P3-B2 T7): Customized and Deviation (DRQ)
#: resolve through a small dialog into the persisted string
BATCH_OPTIONS = (
    "EVT (Proto-1)",
    "DVT (Proto-2)",
    "PVT (Pilot-1)",
    "Ramp-up (Pilot-2)",
    "MP (Production)",
    "Deviation (DRQ)",
    "R&R (Return&Rework)",
    "Customized",
)
#: persisted batch prefixes for the dialog-resolved options
BATCH_CUSTOMIZED_PREFIX = "Customized: "
BATCH_DEVIATION_PREFIX = "Deviation (DRQ): "


#: Per-module field schemas (independent, per interface_spec section 31).
MODULE_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "design_input": (
        _f("product_id", "Product ID", required=True,
           remarks="Core ID extracted from the SPF file name"),
        # Project Part # is the ONLY board-level part number source:
        # manual entry (no SPF / Drawing-Title-Block auto source exists)
        _f("part_number", "Project Part #", required=True,
           remarks="manual entry - persisted as the unique board-level "
                   "part number across parse / build / test / report"),
        _f("sw_version", "SW Version (optional)",
           remarks="report metadata only - no test logic impact"),
        _f("hw_version", "HW Version (optional)",
           remarks="report metadata only - no test logic impact"),
        _f("batch", "Batch # (optional)", ftype=T_CHOICE,
           choices=BATCH_OPTIONS),
        _f("spf_file", "SPF File",
           remarks="Allegro Smart PDF imported via Import SPF"),
        _f("net_file", "NET File",
           remarks="relative path + file name of the imported NET "
                   "(load only, parsed by the Parse Nets module)"),
    ),
    "instruments": (
        _f("psu_visa", "PSU VISA Address", required=True,
           remarks="Keysight N5747A rack PSU (block03 = the ONLY "
                   "rack-ATE instrument editor)"),
        _f("daq_visa", "DAQ VISA Address", required=True,
           remarks="Keysight DAQ973A + DAQM908A/907A"),
        _f("dmm_visa", "DMM VISA Address",
           remarks="Keysight DMM (optional)"),
        _f("channel_alloc", "Channel Allocation", ftype=T_TEXT,
           remarks="one 'instrument:channel:signal' entry per line"),
        _f("self_test", "Instrument Self-Test", ftype=T_BOOL,
           default="true"),
    ),
    "parse_ict": (
        _f("netlist_file", "Netlist File", required=True),
        _f("include_nets", "Include Nets", ftype=T_TEXT,
           remarks="one net pattern per line"),
        _f("exclude_nets", "Exclude Nets", ftype=T_TEXT,
           remarks="one net pattern per line"),
        _f("filter_invalid_points", "Filter Invalid Points",
           ftype=T_BOOL, default="true"),
        _f("ict_test_file", "Import ICT Test File"),
        _f("tp_resolutions", "TP Resolutions", ftype=T_TEXT,
           remarks="one 'net=pin' (pin substitute) or 'net=skip' "
                   "(point not tested) per line, for nets without TP"),
        _f("power_capture_nets", "Power Waveform Capture Nets",
           ftype=T_TEXT, max_lines=12,
           remarks="one power net per line (max 12, auto-prefilled "
                   "from the power tree); passed READ-ONLY to block 04 "
                   "which cannot modify the selection"),
    ),
    "rails": (
        # DUT power on/off sequence (moved from the legacy power_dut
        # block, M0 redefinition: block04 owns the power-up sequence)
        _f("on_voltage_v", "Power-On Voltage", ftype=T_FLOAT,
           default="5.0", required=True, minimum=0.0, maximum=60.0,
           unit="V"),
        _f("current_limit_a", "Current Limit", ftype=T_FLOAT,
           default="1.0", required=True, minimum=0.0, maximum=12.5,
           unit="A"),
        _f("on_delay_ms", "Power-On Delay", ftype=T_INT, default="100",
           minimum=0, maximum=60000, unit="ms"),
        _f("off_delay_ms", "Power-Off Delay", ftype=T_INT, default="200",
           minimum=0, maximum=60000, unit="ms"),
        _f("off_protection", "Power-Off Protection", ftype=T_BOOL,
           default="true"),
        # impedance / voltage / rails-up sequence
        _f("sequence", "Rail Sequence", ftype=T_TEXT, required=True,
           remarks="one 'rail:delay_s' entry per line"),
        _f("voltage_tolerance_pct", "Voltage Tolerance", ftype=T_FLOAT,
           default="0.1", minimum=0.0, maximum=5.0, unit="%"),
        _f("impedance_min_ohm", "Impedance Min", ftype=T_FLOAT,
           default="1.5", minimum=0.0, unit="Ohm"),
        _f("sample_rate_hz", "Sample Rate", ftype=T_INT, default="1000",
           minimum=1, maximum=250000, unit="Hz"),
        _f("pre_trigger_s", "Pre-Trigger", ftype=T_FLOAT, default="-0.5",
           unit="s"),
        _f("post_trigger_s", "Post-Trigger", ftype=T_FLOAT, default="6.0",
           unit="s"),
        _f("anomaly_policy", "Anomaly Policy", ftype=T_CHOICE,
           choices=("stop", "warn"), default="stop"),
    ),
    "clocks": (
        _f("clocks", "Clock Definitions", ftype=T_TEXT, required=True,
           remarks="one 'name:freq_hz:tolerance_pct' per line"),
        _f("stabilize_ms", "Stabilize Time", ftype=T_INT, default="100",
           minimum=0, maximum=10000, unit="ms"),
        _f("drift_check", "Drift Detection", ftype=T_BOOL,
           default="true"),
        _f("multi_domain_check", "Multi-Clock-Domain Check",
           ftype=T_BOOL, default="false"),
    ),
    "gpios": (
        _f("groups", "Pin Groups", ftype=T_TEXT, required=True,
           remarks="one 'name:pin:mode:pull' per line"),
        _f("level_threshold_v", "Level Threshold", ftype=T_FLOAT,
           default="1.5", minimum=0.0, maximum=5.0, unit="V"),
        _f("exception_check", "Exception Check Rules", ftype=T_BOOL,
           default="true"),
    ),
    "programmer": (
        _f("protocol", "Protocol", ftype=T_CHOICE,
           choices=("SWD", "JTAG"), default="SWD"),
        _f("speed_khz", "Speed", ftype=T_INT, default="4000",
           minimum=1, maximum=100000, unit="kHz"),
        _f("timeout_ms", "Timeout", ftype=T_INT, default="30000",
           minimum=100, maximum=600000, unit="ms"),
        _f("flash_address", "Flash Address", default="0x0"),
        _f("retries", "Retries", ftype=T_INT, default="1",
           minimum=0, maximum=10),
        _f("log_level", "Log Level", ftype=T_CHOICE,
           choices=("debug", "info", "warning", "error"), default="info"),
    ),
    "peripherals": (
        _f("wifi_ssid", "Wi-Fi SSID"),
        _f("wifi_password", "Wi-Fi Password"),
        _f("bt_mac", "Bluetooth MAC", pattern=r"^[0-9A-Fa-f]{2}"
            r"(:[0-9A-Fa-f]{2}){5}$"),
        _f("uart_baud", "UART Baud", ftype=T_INT, default="115200",
           minimum=9600, maximum=921600),
        _f("i2c_addr", "I2C Address"),
        _f("spi_speed_hz", "SPI Speed", ftype=T_INT, minimum=1,
           unit="Hz"),
        _f("adc_ref_v", "ADC Reference", ftype=T_FLOAT, minimum=0.0,
           maximum=10.0, unit="V"),
        _f("init_sequence", "Init Sequence", ftype=T_TEXT,
           remarks="one init step per line"),
    ),
    "fct_parse": (
        _f("spec_file", "Test Spec File", required=True),
        _f("interfaces", "Interfaces", ftype=T_TEXT,
           remarks="one interface per line"),
        _f("protocols", "Protocols", ftype=T_TEXT,
           remarks="one protocol per line"),
        _f("custom_checks", "Custom Checks", ftype=T_TEXT,
           remarks="one check rule per line"),
    ),
    "fct_build": (
        _f("flow_steps", "FCT Flow", ftype=T_TEXT, required=True,
           remarks="one flow step per line"),
        _f("yield_threshold_pct", "Yield Threshold", ftype=T_FLOAT,
           default="98.0", minimum=0.0, maximum=100.0, unit="%"),
        _f("exception_branch", "Exception Branch", ftype=T_CHOICE,
           choices=("continue", "stop"), default="stop"),
        _f("case_link", "Case Link"),
    ),
    "validate_sequence": (
        _f("resource_conflict_check", "Resource Conflict Check",
           ftype=T_BOOL, default="true"),
        _f("param_range_check", "Parameter Range Check", ftype=T_BOOL,
           default="true"),
        _f("dependency_check", "Dependency Violation Check",
           ftype=T_BOOL, default="true"),
    ),
    "preview_export": (
        _f("export_dir", "Export Directory", default="config/plans",
           remarks="project config folder for the exported YAML"),
        _f("include_disabled", "Include Disabled Modules", ftype=T_BOOL,
           default="false"),
    ),
}


def fields_for(module_key: str) -> tuple[FieldSpec, ...]:
    """Return the field schema of one module.

    Args:
        module_key: Stage key (see stages.STAGE_KEYS).

    Returns:
        Tuple of :class:`FieldSpec`; empty for unknown keys.
    """
    return MODULE_FIELDS.get(module_key, ())


def module_title(module_key: str) -> str:
    """Return the UI title of one module.

    Args:
        module_key: Stage key.

    Returns:
        The stage title, or the key itself when unknown.
    """
    stage = STAGE_BY_KEY.get(module_key)
    return stage.title if stage else module_key
