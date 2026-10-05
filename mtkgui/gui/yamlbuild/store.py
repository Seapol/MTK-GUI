# -*- coding: utf-8 -*-
"""Persistence of the Yaml Build model state (V4.0 rule 六-3).

All module parameters and Enable states survive GUI restarts and page
switches.  The store is a single JSON file keyed by the project
identity (Design Input product/part) so multiple tenant projects
never overwrite each other (multi-tenant isolation, rule 六-2).
"""

from __future__ import annotations

import json
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "config"
STATE_FILE = STATE_DIR / "yamlbuild_state.json"


def load_project_state(project_key: str) -> dict | None:
    """Load one project's persisted model state.

    Args:
        project_key: Project identity (model.project_key()).

    Returns:
        The stored state dict, or None when absent / unreadable.
    """
    try:
        if not STATE_FILE.is_file():
            return None
        data = json.loads(
            STATE_FILE.read_text(encoding="utf-8"))
        entry = (data.get("projects") or {}).get(project_key)
        return entry if isinstance(entry, dict) else None
    except (OSError, ValueError):
        return None  # silent fallback: a broken store keeps defaults


def save_project_state(project_key: str, state: dict) -> bool:
    """Persist one project's model state (merge into the store).

    Args:
        project_key: Project identity.
        state:       Model state (model.to_dict()).

    Returns:
        True on success; False (silently) when writing failed - the
        GUI must never break because persistence did.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        data = {"projects": {}}
        if STATE_FILE.is_file():
            try:
                data = json.loads(
                    STATE_FILE.read_text(encoding="utf-8")) or data
            except ValueError:
                data = {"projects": {}}
        projects = data.setdefault("projects", {})
        entry = dict(state)
        entry["project_key"] = project_key
        projects[project_key] = entry
        STATE_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8")
        return True
    except OSError:
        return False
