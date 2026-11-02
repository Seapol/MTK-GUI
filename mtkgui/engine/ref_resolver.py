# -*- coding: utf-8 -*-
"""ref_resolver — runtime references from FCT steps to the Equipment node.

M50: shared test parameters live ONCE in the project ``equipment:``
section (M49a schema).  A step stores a dotted reference instead of a
copy of the value::

    equipment.peripherals.wifi.ap_ssid
    equipment.dut.ssh.ip

``resolve`` reads the CURRENT project yaml at build / validation time,
``describe`` gives the human label shown in the step dialog.

RED LINE: pure data, no Qt, no I/O.
"""
from __future__ import annotations

REF_ROOT = "equipment."

#: path -> (human label, expected value kind)
#: kind "text" = any scalar (str / int / float / bool), "number" = int
#: or float only.
EQUIPMENT_PATHS = {
    "equipment.dut.ssh.ip": ("SSH Login - IP address", "text"),
    "equipment.dut.ssh.username": ("SSH Login - Username", "text"),
    "equipment.dut.ssh.password": ("SSH Login - Password", "text"),
    "equipment.dut.console.channel": ("DUT Console - Channel", "text"),
    "equipment.dut.console.port": ("DUT Console - Serial port", "text"),
    "equipment.dut.console.baud": ("DUT Console - Baud rate", "number"),
    "equipment.dut.console.parity": ("DUT Console - Parity", "text"),
    "equipment.dut.wifi.ssid": ("DUT Wi-Fi - SSID", "text"),
    "equipment.dut.wifi.interface": ("DUT Wi-Fi - Interface", "text"),
    "equipment.dut.bluetooth.name": ("DUT Bluetooth - Name", "text"),
    "equipment.dut.bluetooth.bd_addr": ("DUT Bluetooth - BD address",
                                        "text"),
    "equipment.peripherals.wifi.ap_ssid": ("PC Wi-Fi - AP SSID", "text"),
    "equipment.peripherals.wifi.ap_ip": ("PC Wi-Fi - AP IP", "text"),
    "equipment.peripherals.wifi.host_ip": ("PC Wi-Fi - Host IP", "text"),
    "equipment.peripherals.wifi.ap_password": ("PC Wi-Fi - AP password",
                                               "text"),
    "equipment.peripherals.bluetooth.adapter": ("PC Bluetooth - Adapter",
                                                "text"),
    "equipment.peripherals.bluetooth.scan_targets": (
        "PC Bluetooth - Scan targets", "text"),
    "equipment.peripherals.router.setup_mode": ("Ethernet Router - Setup "
                                                "mode", "text"),
    "equipment.peripherals.router.router_ip": ("Ethernet Router - Router "
                                               "IP", "text"),
    "equipment.peripherals.router.dut_ip": ("Ethernet Router - DUT IP",
                                            "text"),
    "equipment.jlink.install_path": ("J-Link - Install path", "text"),
    "equipment.jlink.executable": ("J-Link - Executable", "text"),
    "equipment.jlink.device": ("J-Link - Device", "text"),
    "equipment.control_board.dio.press": ("Control Board - Press",
                                          "text"),
    "equipment.control_board.dio.inpos": ("Control Board - In-position",
                                          "text"),
    "equipment.control_board.dio.presence": ("Control Board - DUT "
                                             "presence", "text"),
    "equipment.control_board.dio.estop": ("Control Board - E-stop",
                                          "text"),
}

#: the plain-config entries store their fields under a ``fields`` map keyed
#: by the shown label; these aliases find that value.
_FIELD_ALIASES = {
    "equipment.jlink.install_path": ("fields", "Install path"),
    "equipment.jlink.executable": ("fields", "Executable"),
    "equipment.jlink.device": ("fields", "Device"),
}


class RefError(ValueError):
    """A reference cannot be resolved (unknown / missing / wrong type)."""


def is_ref(path) -> bool:
    """True when *path* looks like a reference (dotted, ``equipment.``)."""
    text = str(path or "").strip()
    return text.startswith(REF_ROOT) and not any(
        not part for part in text.split("."))


def describe(path) -> str:
    """Human-readable target label of one reference (path as fallback)."""
    text = str(path or "").strip()
    label = (EQUIPMENT_PATHS.get(text) or ("", ""))[0]
    return label or text


def _lookup(path: str, yaml_data: dict):
    """Raw value at *path* (raises RefError when absent)."""
    node = yaml_data or {}
    alias = _FIELD_ALIASES.get(path)
    keys = list(alias) if alias else path.split(".")[1:]
    for key in keys:
        if isinstance(node, dict) and key in node:
            node = node[key]
            continue
        raise RefError(f"reference {path!r} is not set in this project's "
                       "equipment configuration")
    return node


def resolve(path, yaml_data):
    """Return the CURRENT equipment value of one reference path.

    Args:
        path:      dotted reference (``equipment.dut.ssh.ip``).
        yaml_data: the project yaml dict (may be the ``equipment`` node
                   alone or the whole project document).

    Raises:
        RefError: unknown path / missing value / wrong (non-scalar)
                  value - the message names the path.
    """
    text = str(path or "").strip()
    if not is_ref(text):
        raise RefError(f"{text!r} is not an equipment reference "
                       f"(expected a dotted path starting with "
                       f"{REF_ROOT!r})")
    if text not in EQUIPMENT_PATHS:
        raise RefError(f"unknown equipment reference {text!r} - it does "
                       "not match the Equipment yaml schema")
    data = yaml_data or {}
    node = data.get("equipment") if isinstance(data, dict) \
        and "equipment" in data else data
    value = _lookup(text, node if isinstance(node, dict) else {})
    if isinstance(value, (dict, list, tuple, set)):
        raise RefError(f"reference {text!r} resolves to a {type(value).__name__}"
                       " - a single scalar value is required")
    kind = EQUIPMENT_PATHS[text][1]
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            try:
                return int(str(value).strip())
            except (TypeError, ValueError):
                raise RefError(f"reference {text!r} has the wrong type "
                               f"({value!r}) - a number is required")
    return value


def effective(ref, override, yaml_data):
    """The value a step uses: the override when set, else the resolved
    reference (None when neither is usable)."""
    text = str(override or "").strip()
    if text:
        return text
    if not str(ref or "").strip():
        return None
    try:
        return resolve(ref, yaml_data)
    except RefError:
        return None


def validate_refs(steps, yaml_data) -> list:
    """Validate every ``ref`` carried by one step list.

    Args:
        steps:     FctStep objects (or dicts with ``name`` / ``ref``).
        yaml_data: project yaml dict / equipment node (None = no data,
                   only the path syntax is checked).

    Returns:
        list of error strings, each naming the step and the path.
    """
    errors: list = []
    for step in steps or []:
        name = str(getattr(step, "name", "") if not isinstance(step, dict)
                   else step.get("name", "") or "<unnamed>")
        refs = (getattr(step, "ref", None) if not isinstance(step, dict)
                else step.get("ref")) or {}
        if not isinstance(refs, dict):
            errors.append(f"step {name!r}: ref must be a mapping")
            continue
        for field_key, path in refs.items():
            text = str(path or "").strip()
            if not text:
                errors.append(f"step {name!r}: empty reference for "
                              f"{field_key!r}")
                continue
            if not is_ref(text):
                errors.append(f"step {name!r}: {field_key} {text!r} is not "
                              f"an equipment reference")
                continue
            if text not in EQUIPMENT_PATHS:
                errors.append(f"step {name!r}: unknown reference {text!r}")
                continue
            if yaml_data is None:
                continue
            try:
                resolve(text, yaml_data)
            except RefError as exc:
                errors.append(f"step {name!r}: {exc}")
    return errors
