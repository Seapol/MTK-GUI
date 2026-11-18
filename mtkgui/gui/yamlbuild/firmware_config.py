# -*- coding: utf-8 -*-
"""v2-5 node 03 firmware config — Qt-free data shape + validation.

The Firmware Config node describes HOW the FAT and OOBE firmware images
are flashed (a Windows ``cmd`` / ``PowerShell`` CLI command, or a
3rd-party GUI tool), never whether a test runs.  The shape is nested
(``fat`` / ``oobe`` -> ``method`` -> ``cli`` | ``gui``) and is emitted
under the top-level ``yaml_build.firmware`` key, not inside ``modules``.

The node configures only — it has no execution state, no output tail and
no ``Abort`` control, and deliberately no timeout anywhere (a stuck
command waits until the operator aborts it on the runtime page).
"""

from __future__ import annotations

#: the two firmware slots, top FAT then OOBE
FIRMWARE_SLOTS: tuple[str, ...] = ("fat", "oobe")

#: flash methods a slot may choose, independently of the other slot
METHODS: tuple[str, ...] = ("cli", "gui")

#: Windows terminal choices for the CLI branch (not a serial console)
TERMINALS: tuple[str, ...] = ("cmd", "powershell")

#: keyword logic combinators
LOGICS: tuple[str, ...] = ("and", "or")

#: pre-v2-5 legacy keys under ``firmware:`` that must be refused on load
LEGACY_FIRMWARE_KEYS: tuple[str, ...] = ("fat_image", "oobe_image")


def legacy_key_error(key: str) -> str:
    """The named refusal for a retired firmware key (see §4.6)."""
    return (f"legacy firmware key {key!r} is not supported — "
            "re-configure flashing in the Firmware Config node")


def default_cli() -> dict:
    """Factory CLI branch (all fields default, keywords empty)."""
    return {
        "terminal": "cmd",
        "run_as_admin": False,
        "show_window": True,
        "working_dir": "",
        "command": "",
        "pass_keywords": [],
        "pass_logic": "and",
        "fail_keywords": [],
        "fail_logic": "and",
    }


def default_gui() -> dict:
    """Factory GUI branch."""
    return {"tool_path": "", "arguments": "", "prompt": ""}


def default_slot() -> dict:
    """Factory enabled CLI slot (both branches present so a method flip
    never has to invent keys)."""
    return {"enabled": True, "method": "cli",
            "cli": default_cli(), "gui": default_gui()}


def default_firmware() -> dict:
    """Factory config: FAT enabled (CLI), OOBE disabled."""
    return {
        "fat": default_slot(),
        "oobe": {"enabled": False, "method": "cli",
                 "cli": default_cli(), "gui": default_gui()},
    }


def _clean_cli(data: dict | None) -> dict:
    cli = default_cli()
    raw = data or {}
    terminal = str(raw.get("terminal") or "cmd")
    cli["terminal"] = terminal if terminal in TERMINALS else "cmd"
    cli["run_as_admin"] = bool(raw.get("run_as_admin", False))
    cli["show_window"] = bool(raw.get("show_window", True))
    cli["working_dir"] = str(raw.get("working_dir") or "")
    cli["command"] = str(raw.get("command") or "")
    cli["pass_keywords"] = _keywords(raw.get("pass_keywords"))
    cli["pass_logic"] = _logic(raw.get("pass_logic"))
    cli["fail_keywords"] = _keywords(raw.get("fail_keywords"))
    cli["fail_logic"] = _logic(raw.get("fail_logic"))
    return cli


def _clean_gui(data: dict | None) -> dict:
    gui = default_gui()
    raw = data or {}
    gui["tool_path"] = str(raw.get("tool_path") or "")
    gui["arguments"] = str(raw.get("arguments") or "")
    gui["prompt"] = str(raw.get("prompt") or "")
    return gui


def _keywords(value) -> list[str]:
    """1-3 non-empty keyword strings in entry order."""
    if isinstance(value, str):
        source = [value]
    else:
        source = list(value or [])
    return [str(k).strip() for k in source if str(k).strip()][:3]


def _logic(value) -> str:
    text = str(value or "and").lower()
    return text if text in LOGICS else "and"


def parse_firmware(data) -> tuple[dict, list[str]]:
    """Load + validate a raw ``firmware`` section.

    Returns ``(config, errors)``.  A non-mapping is one error; unknown /
    legacy keys are named refusals (each one an error); slot bodies are
    coerced to the §4.6 shape.  The returned config always carries both
    slots with factory defaults for any missing field.
    """
    if data is None:
        return default_firmware(), []
    if not isinstance(data, dict):
        return default_firmware(), ["firmware: mapping expected"]
    config = default_firmware()
    errors: list[str] = []
    for key, value in data.items():
        if key not in FIRMWARE_SLOTS:
            errors.append(legacy_key_error(str(key)))
            continue
        if value is None:
            config[key] = {"enabled": False, "method": "cli",
                           "cli": default_cli()}
            continue
        if not isinstance(value, dict):
            errors.append(f"firmware.{key}: mapping expected")
            continue
        enabled = bool(value.get("enabled", True))
        method = str(value.get("method") or "cli")
        if method not in METHODS:
            method = "cli"
        slot = {"enabled": enabled, "method": method,
                "cli": _clean_cli(value.get("cli")),
                "gui": _clean_gui(value.get("gui"))}
        config[key] = slot
    return config, errors


def emit_firmware(config: dict) -> dict:
    """The locked §4.6 YAML shape: enabled slots carry their branch,
    disabled slots collapse to ``{enabled: false}`` (fields omitted)."""
    out: dict = {}
    for slot in FIRMWARE_SLOTS:
        entry = config.get(slot) or {}
        if not entry.get("enabled", False):
            out[slot] = {"enabled": False}
            continue
        method = entry.get("method", "cli")
        node: dict = {"enabled": True, "method": method}
        if method == "gui":
            gui = _clean_gui(entry.get("gui"))
            node["gui"] = gui
        else:
            cli = _clean_cli(entry.get("cli"))
            node["cli"] = cli
        out[slot] = node
    return out
