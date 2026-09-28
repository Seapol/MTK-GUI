# -*- coding: utf-8 -*-
"""Configurable quick-command snippets.

Quick commands are generic serial snippets (not tied to any specific
AT command set). They are loaded from ``config/commands.json``; if that
file is missing or invalid the built-in defaults below are used.

JSON entry format::

    [
        {"label": "AT", "command": "AT", "crlf": true},
        {"label": "Version", "command": "version", "crlf": true}
    ]

The destination port (DUT / AUX / Both) is chosen in the UI.
"""

import json
import sys
from pathlib import Path

MAX_QUICK_COMMANDS = 15

DEFAULT_COMMANDS = [
    {"label": "AT", "command": "AT", "crlf": True},
    {"label": "ATI", "command": "ATI", "crlf": True},
    {"label": "ATE0", "command": "ATE0", "crlf": True},
    {"label": "help", "command": "help", "crlf": True},
    {"label": "version", "command": "version", "crlf": True},
    {"label": "status", "command": "status", "crlf": True},
    {"label": "reset", "command": "reset", "crlf": True},
]


def candidate_paths():
    """Locations searched for commands.json, in priority order."""
    pkg_root = Path(__file__).resolve().parent.parent
    yield pkg_root / "config" / "commands.json"
    yield Path.cwd() / "config" / "commands.json"
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        yield Path(sys.executable).resolve().parent / "config" / "commands.json"


def load_commands():
    """Return a list of {"label", "command", "crlf"} dicts.

    If the file exists (even if empty ``[]``), its contents are
    returned.  Defaults are used only when the file is missing
    or invalid.
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
                    label = str(item.get("label", "")).strip()
                    command = str(item.get("command", ""))
                    if not label or not command:
                        continue
                    commands.append({
                        "label": label,
                        "command": command,
                        "crlf": bool(item.get("crlf", True)),
                    })
                return commands  # file exists -> use it (even if empty)
    return [dict(c) for c in DEFAULT_COMMANDS]


def user_commands_path():
    """Where user-added quick commands are persisted."""
    return Path(__file__).resolve().parent.parent / "config" / "commands.json"


def save_commands(commands):
    """Persist the quick command list to ``config/commands.json``.

    Entries are normalized to {"label", "command", "crlf"}; the list is
    capped at :data:`MAX_QUICK_COMMANDS`. Returns the stored list.
    """
    clean = []
    for item in commands[:MAX_QUICK_COMMANDS]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        command = str(item.get("command", ""))
        if not label or not command:
            continue
        clean.append({
            "label": label,
            "command": command,
            "crlf": bool(item.get("crlf", True)),
        })
    path = user_commands_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean
