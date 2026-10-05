# -*- coding: utf-8 -*-
"""Dynamic GUI version label source (M0 feature).

Encoding rule: ``vX.Y.Z.xxxx``

* X = major version (current baseline: 4)
* Y = branch iteration (b1 -> 1)
* Z = minor iteration (m1 -> 1)
* xxxx = 4-digit random build number (0000-9999, regenerated on
  every CI build)

The CI pipeline writes ``resources/version.json`` into the app
resource folder on each build; the GUI loads it at startup and
renders ``full_version`` into the status bar label.  A missing or
broken file falls back to the static ``v4.1.1.0000`` text plus a
warning log line - the label is display-only either way.
"""

from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path

logger = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parent.parent
VERSION_JSON = APP_ROOT / "resources" / "version.json"

#: static fallback when version.json is missing / unreadable (spec 4)
FALLBACK_VERSION = "v4.1.1.0000"

_FULL_RE = re.compile(r"^v\d+\.\d+\.\d+\.\d{4}$")


def load_gui_version(path: Path | None = None) -> tuple[str, str | None]:
    """Load the GUI version string (spec items 2-4).

    Resolution: ``full_version`` from version.json when it matches
    ``vX.Y.Z.xxxx``; otherwise the string is rebuilt from the four
    integer components; otherwise the static fallback.

    Args:
        path: Optional version.json override (tests); defaults to the
              app resource folder.

    Returns:
        ``(version, warning)`` - ``warning`` is None on success and
        carries the fallback reason otherwise (also emitted through
        the ``mtkgui.gui_version`` logger at WARNING level).
    """
    path = path or VERSION_JSON
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warning = (f"version.json missing or unreadable ({exc}); "
                   f"using static fallback {FALLBACK_VERSION}")
        logger.warning(warning)
        return FALLBACK_VERSION, warning
    if not isinstance(data, dict):
        warning = (f"version.json is not an object; using static "
                   f"fallback {FALLBACK_VERSION}")
        logger.warning(warning)
        return FALLBACK_VERSION, warning

    full = str(data.get("full_version", "")).strip()
    if _FULL_RE.match(full):
        return full, None
    # full_version absent / malformed: rebuild from the components
    try:
        version = "v{}.{}.{}.{}".format(
            int(data["major"]), int(data["branch"]),
            int(data["minor"]), f"{int(data['build']):04d}")
        if _FULL_RE.match(version):
            return version, None
    except (KeyError, TypeError, ValueError):
        pass
    warning = (f"version.json has no valid version payload; using "
               f"static fallback {FALLBACK_VERSION}")
    logger.warning(warning)
    return FALLBACK_VERSION, warning


def generate_version_json(path: Path | None = None, major: int = 4,
                          branch: int = 1, minor: int = 1) -> dict:
    """Write a fresh version.json (CI build pipeline helper).

    The 4-digit build number is regenerated randomly on every call
    (0000-9999).

    Args:
        path:   Output path (defaults to the app resource folder).
        major:  Major version (baseline 4).
        branch: Branch iteration (b1 -> 1).
        minor:  Minor iteration (m1 -> 1).

    Returns:
        The written payload dict.
    """
    path = path or VERSION_JSON
    build = f"{random.randint(0, 9999):04d}"
    payload = {
        "major": major,
        "branch": branch,
        "minor": minor,
        "build": build,
        "full_version": f"v{major}.{branch}.{minor}.{build}",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n",
                    encoding="utf-8")
    return payload
