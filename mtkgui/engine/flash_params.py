# -*- coding: utf-8 -*-
"""Flash parameter model, validation and traceability (P1 Task6).

Replaces the loose flash op_params dict with a structured, validated
parameter object.  Purely additive: the runner, the failure taxonomy
and the scheduler are untouched - only the RealGateway flash branch
consults this module, and only BEFORE any driver call is made, so an
illegal parameter is intercepted before the flash flow starts.

Priority order (interface_spec.md aligned: dynamic step parameters >
project config > engine defaults):
    step op_params  (the "CLI" level - per-step dynamic values)
    config "firmware" section (firmware.<slot>_image, baudrate, ...)
    engine defaults

Every effective field records its source ("step" / "config" /
"default") and [FLASH_PARAM] log lines allow full audit / replay.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace

ALLOWED_IMAGE_EXTS = (".bin", ".hex", ".srec", ".elf", ".mot")
ALLOWED_SLOTS = ("fat", "oobe")
DEFAULT_BAUDRATE_KHZ = 4000        # J-Link interface speed
DEFAULT_TIMEOUT_S = 60.0
MAX_TIMEOUT_S = 600.0
MAX_RETRIES = 5
ADDRESS_RE = r"^0x[0-9A-Fa-f]{1,16}$"
ADDRESS_ALIGN = 0x4                # 32-bit word alignment


class FlashParamError(ValueError):
    """One illegal flash parameter (field + value + allowed range)."""

    def __init__(self, field: str, value, reason: str, allowed: str,
                 source: str = "default"):
        self.field = field
        self.value = value
        self.reason = reason
        self.allowed = allowed
        self.source = source
        super().__init__(
            f"flash param '{field}' illegal value {value!r}: {reason} "
            f"(allowed: {allowed}) [source={source}]")


@dataclass
class FlashParams:
    """Complete structured flash parameter set (all fields hosted)."""
    image: str = ""
    slot: str = ""
    device: str = ""
    address: str | None = None       # e.g. "0x60000000" (QSPI XIP)
    offset: int | None = None        # byte offset, mutually exclusive
    baudrate_khz: int = DEFAULT_BAUDRATE_KHZ
    timeout_s: float = DEFAULT_TIMEOUT_S
    retries: int = 0                 # extra driver-level attempts (0-5)
    verify: bool = True
    reset_run: bool = True
    erase: bool = False
    encrypt: bool = False
    base_dir: str | None = None      # image relative-to directory
    sources: dict[str, str] = field(default_factory=dict)

    def resolved_image(self) -> str:
        if self.base_dir and self.image and not os.path.isabs(self.image):
            return os.path.join(self.base_dir, self.image)
        return self.image


def _pick(op: dict, cfg: dict, key: str, default, cast):
    """Priority: step op_params > config firmware section > default."""
    if key in op and op[key] is not None:
        return cast(op[key]), "step"
    if key in cfg and cfg[key] is not None:
        return cast(cfg[key]), "config"
    return default, "default"


def resolve_flash_params(op_params: dict, config: dict | None = None,
                         base_dir: str | None = None) -> FlashParams:
    """Build the structured parameter object with source tracing."""
    op = dict(op_params or {})
    cfg_fw = dict((config or {}).get("firmware") or {})
    slot = str(op.get("slot", "") or "")
    p = FlashParams(base_dir=base_dir)
    src = p.sources

    # image: step > firmware.<slot>_image > "" (empty -> config error)
    if op.get("image"):
        p.image = str(op["image"])
        src["image"] = "step"
    elif slot and cfg_fw.get(f"{slot}_image"):
        p.image = str(cfg_fw[f"{slot}_image"])
        src["image"] = "config"
    else:
        src["image"] = "default"

    for key, attr, default, cast in (
            ("device", "device", "", str),
            ("address", "address", None, str),
            ("offset", "offset", None, int),
            ("baudrate", "baudrate_khz", DEFAULT_BAUDRATE_KHZ, int),
            ("timeout_s", "timeout_s", DEFAULT_TIMEOUT_S, float),
            ("retries", "retries", 0, int),
            ("verify", "verify", True, bool),
            ("reset_run", "reset_run", True, bool),
            ("erase", "erase", False, bool),
            ("encrypt", "encrypt", False, bool)):
        value, source = _pick(op, cfg_fw, key, default, cast)
        setattr(p, attr, value)
        src[attr] = source

    p.slot = slot
    src["slot"] = "step" if op.get("slot") else "default"
    return p


def validate_flash_params(p: FlashParams) -> list[FlashParamError]:
    """Full legality validation; returns every violation found."""
    errors: list[FlashParamError] = []
    src = p.sources

    def err(field, value, reason, allowed):
        errors.append(FlashParamError(field, value, reason, allowed,
                                      src.get(field, "default")))

    # image: required, non-empty, legal extension, must exist
    if not p.image or not p.image.strip():
        err("image", p.image, "must not be empty",
            f"one of {ALLOWED_SLOTS} slots with firmware.<slot>_image")
    else:
        name = os.path.basename(p.image)
        if not name.lower().endswith(ALLOWED_IMAGE_EXTS):
            err("image", p.image,
                "illegal image file extension",
                f"extension in {ALLOWED_IMAGE_EXTS}")
        if "\x00" in p.image:
            err("image", p.image, "illegal control character",
                "printable path without NUL")
        if not os.path.isfile(p.resolved_image()):
            err("image", p.image, "file does not exist",
                f"existing file under "
                f"'{p.base_dir or os.getcwd()}'")

    # slot: optional but restricted
    if p.slot and p.slot not in ALLOWED_SLOTS:
        err("slot", p.slot, "unknown firmware slot",
            f"slot in {ALLOWED_SLOTS}")

    # address / offset: mutual exclusion + format / alignment / range
    if p.address is not None and p.offset is not None:
        err("address", p.address,
            "mutually exclusive with 'offset'",
            "give address OR offset, not both")
    if p.address is not None:
        if not re.match(ADDRESS_RE, str(p.address)):
            err("address", p.address, "illegal hex address format",
                "0x-prefixed hex, 1-16 digits")
        elif int(str(p.address), 16) % ADDRESS_ALIGN:
            err("address", p.address, "address not word-aligned",
                f"multiple of 0x{ADDRESS_ALIGN:X}")
    if p.offset is not None:
        if not 0 <= p.offset <= 0xFFFFFFFF:
            err("offset", p.offset, "out of 32-bit range",
                "0 .. 0xFFFFFFFF")

    # numeric ranges
    if not 1 <= p.baudrate_khz <= 100000:
        err("baudrate_khz", p.baudrate_khz, "out of range",
            "1 .. 100000 kHz")
    if not 0.0 < p.timeout_s <= MAX_TIMEOUT_S:
        err("timeout_s", p.timeout_s, "out of range",
            f"0 < t <= {MAX_TIMEOUT_S:g} s")
    if not 0 <= p.retries <= MAX_RETRIES:
        err("retries", p.retries, "out of range",
            f"0 .. {MAX_RETRIES}")
    for flag in ("verify", "reset_run", "erase", "encrypt"):
        if not isinstance(getattr(p, flag), bool):
            err(flag, getattr(p, flag), "must be a boolean",
                "true / false")
    return errors


def flash_param_log_lines(p: FlashParams,
                          errors: list[FlashParamError] | None = None
                          ) -> list[str]:
    """[FLASH_PARAM] audit lines: effective value + source per field."""
    lines = ["[FLASH_PARAM] effective parameters:"]
    for attr in ("image", "slot", "device", "address", "offset",
                 "baudrate_khz", "timeout_s", "retries", "verify",
                 "reset_run", "erase", "encrypt"):
        lines.append(f"[FLASH_PARAM]   {attr}="
                     f"{getattr(p, attr)!r} "
                     f"(source={p.sources.get(attr, 'default')})")
    if errors:
        for e in errors:
            lines.append(f"[FLASH_PARAM] VALIDATION FAIL: {e}")
    else:
        lines.append("[FLASH_PARAM] validation: PASS")
    return lines


def with_retry_budget(p: FlashParams) -> FlashParams:
    """Clamp the driver-level retry count into the legal range
    (never negative, never above MAX_RETRIES)."""
    clamped = max(0, min(int(p.retries), MAX_RETRIES))
    return replace(p, retries=clamped)
