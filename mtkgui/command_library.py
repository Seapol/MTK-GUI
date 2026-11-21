# -*- coding: utf-8 -*-
"""Shared command library (single source of truth for console helpers).

Commands are grouped by ``category``.  Each record has the shape
``{"category": str, "name": str, "command": str}``.

The built-in defaults below are used when ``config/command_library.json``
is missing or invalid; when the file exists its contents replace the
defaults.  The console page only reads entries whose category is
``linux`` (Wi-Fi / BT / Flash categories are configured elsewhere and
are never rendered by the console Command Helper).
"""

import json
import sys
from pathlib import Path
from typing import Iterator

DEFAULT_COMMAND_LIBRARY = [
    {"category": "linux", "name": "System info", "command": "uname -a"},
    {"category": "linux", "name": "USB devices", "command": "lsusb"},
    {"category": "linux", "name": "Kernel log tail", "command": "dmesg | tail"},
    {"category": "linux", "name": "Network interfaces", "command": "ifconfig"},
    {"category": "linux", "name": "Ping gateway", "command": "ping 8.8.8.8"},
    {"category": "linux", "name": "Process list", "command": "ps aux"},
    {"category": "wifi", "name": "Scan networks", "command": "iw dev wlan0 scan | grep SSID"},
    {"category": "bt", "name": "Scan devices", "command": "bluetoothctl scan on"},
    {"category": "flash", "name": "Flash image", "command": "uuu -b emmc image.bin"},
]


def candidate_paths() -> Iterator[Path]:
    """Locations searched for ``command_library.json``, in priority order."""
    pkg_root = Path(__file__).resolve().parent.parent
    yield pkg_root / "config" / "command_library.json"
    yield Path.cwd() / "config" / "command_library.json"
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        yield (Path(sys.executable).resolve().parent
               / "config" / "command_library.json")


def load_command_library() -> list:
    """Return the command library as a list of
    ``{"category", "name", "command"}`` dicts.

    A present (even empty) ``config/command_library.json`` replaces the
    built-in defaults; malformed entries are dropped.  The defaults are
    used only when no valid file is found.
    """
    for path in candidate_paths():
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, list):
                commands = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    category = str(item.get("category", "")).strip().lower()
                    name = str(item.get("name", "")).strip()
                    command = str(item.get("command", ""))
                    if not category or not name or not command:
                        continue
                    commands.append({
                        "category": category,
                        "name": name,
                        "command": command,
                    })
                return commands  # file exists -> use it (even if empty)
    return [dict(c) for c in DEFAULT_COMMAND_LIBRARY]
