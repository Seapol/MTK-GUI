# -*- coding: utf-8 -*-
"""Third-party flash GUI launcher (M33 Flash_GUI step).

The Flash_GUI test step (kind ``flash_gui``) opens the third-party
flash tool's GUI and lets the operator judge the outcome with the
Go / Stop dialog.  This module owns the one piece of machinery that
still needs to live outside the runner: the best-effort detached
launch.  The legacy CLI profile / keyword judge / programmatic flash
driver was retired in M33 (flashing is now an operator-driven GUI
step, not a machine-parsed op).
"""
from __future__ import annotations


def launch_tool_gui(exe: str, args: str = "") -> tuple[bool, str]:
    """Best-effort detached launch of the third-party GUI tool.

    Returns ``(started, detail)``.  NEVER raises - a GUI that cannot
    be started is logged and the operator may still flash by hand.
    ``args`` is the optional CLI argument string configured on the
    Equipment page (M64); it is split on whitespace and passed after the
    executable.  Empty args = the pre-M64 behaviour.
    Prefers ``QProcess.startDetached`` (the Qt-safe way to hand a
    process to the desktop) and falls back to a detached
    ``subprocess.Popen`` when Qt is unavailable (headless engine)."""
    exe = str(exe or "").strip()
    if not exe:
        return False, "no GUI path configured (not launched)"
    argv = str(args or "").split()
    try:
        from PySide6.QtCore import QProcess
        result = QProcess.startDetached(exe, argv)
        started = result[0] if isinstance(result, tuple) else bool(result)
        if started:
            return True, "launched (detached)"
    except Exception:                    # noqa: BLE001 - fallback below
        pass
    try:
        import subprocess
        import sys
        kwargs = ({"creationflags": 0x00000008}      # DETACHED_PROCESS
                  if sys.platform.startswith("win")
                  else {"start_new_session": True})
        subprocess.Popen([exe] + argv, **kwargs)
        return True, "launched (detached)"
    except Exception as exc:             # noqa: BLE001 - logged only
        return False, f"launch failed: {type(exc).__name__}: {exc}"
