# -*- coding: utf-8 -*-
"""Global identity variables (core standard 5.3).

Every Event-Log entry automatically carries the Station ID and the
User - both derived from the operating system, adapted to Windows and
macOS, unique by source and never manually editable in the GUI:

* Station ID - the current computer host name
  (``platform.node()``, falls back to ``socket.gethostname()``);
* User       - the current OS login account name
  (``getpass.getuser()``, falls back to the USER / USERNAME / LOGNAME
  environment variables).

Headless, dependency-free, unit-testable without Qt.
"""

from __future__ import annotations

import getpass
import os
import platform


def get_station_id() -> str:
    """Return the Station ID (the current computer host name).

    Windows and macOS alike; never empty (a stable placeholder keeps
    the Event-Log format intact when the host name is unavailable).

    Returns:
        The host name, or ``"UNKNOWN-STATION"`` as the last resort.
    """
    try:
        name = (platform.node() or "").strip()
    except Exception:                       # pragma: no cover - safety
        name = ""
    if not name:
        try:
            import socket
            name = (socket.gethostname() or "").strip()
        except Exception:                   # pragma: no cover - safety
            name = ""
    return name or "UNKNOWN-STATION"


def get_user() -> str:
    """Return the current OS login account name.

    Windows and macOS alike; never empty (a stable placeholder keeps
    the Event-Log format intact when the account name is unavailable).

    Returns:
        The login name, or ``"UNKNOWN-USER"`` as the last resort.
    """
    try:
        name = (getpass.getuser() or "").strip()
    except Exception:                       # pragma: no cover - safety
        name = ""
    if not name:
        for var in ("USER", "USERNAME", "LOGNAME"):
            name = (os.environ.get(var) or "").strip()
            if name:
                break
    return name or "UNKNOWN-USER"


def identity_prefix() -> str:
    """The Event-Log identity prefix: ``[StationID|User]``."""
    return f"[{get_station_id()}|{get_user()}]"
