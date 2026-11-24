# -*- coding: utf-8 -*-
"""iperf_server — host-side iperf3 server lifecycle (m119/D).

The DUT measures throughput as an iperf3 *client*; somebody must be
listening on the host.  On the Windows rack nobody was, so the client
failed instantly, the row produced no measurement - and before m119 the
judge still reported PASS at exactly the configured limit.

``ensure_server`` therefore guarantees a listener before the row runs:

* a listening 127.0.0.1:5201 (or the configured server IP) is reused;
* otherwise the first ``iperf3`` on PATH (incl. the WinGet layout) is
  started detached, and the port is re-probed for a few seconds;
* every failure returns a human-readable reason -> the row reports
  ERROR "iperf server unavailable", never a DUT FAIL.

The process is stopped at interpreter exit, and ``stop_server()`` is
available for an explicit teardown.
"""
from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import time

PORT = 5201
_START_TIMEOUT_S = 6.0
_SERVER = None


def _port_open(host: str, port: int = PORT, timeout_s: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _candidates() -> list:
    names = ["iperf3", "iperf3.exe"]
    found = []
    for name in names:
        path = shutil.which(name)
        if path:
            found.append(path)
    # WinGet keeps the binary out of PATH on some images
    local = os.environ.get("LOCALAPPDATA") or ""
    pkgs = os.path.join(local, "Microsoft", "WinGet", "Packages")
    if pkgs and os.path.isdir(pkgs):
        for root, _dirs, files in os.walk(pkgs):
            for fname in files:
                if fname.lower() == "iperf3.exe":
                    found.append(os.path.join(root, fname))
    return found


def find_binary() -> str:
    cands = _candidates()
    return cands[0] if cands else ""


def _start(binary: str) -> None:
    global _SERVER
    kwargs = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    else:
        kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    _SERVER = subprocess.Popen(
        [binary, "-s", "-p", str(PORT)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs)


def _health(host: str) -> bool:
    """One-second client run: proves the listener really moves bytes.

    A server left behind by an interrupted client accepts the TCP
    connection and then answers nothing (measured on the Windows rack:
    0 bytes for 186 s).  A port probe cannot see that, a short real test
    can.
    """
    binary = find_binary()
    if not binary:
        return False
    try:
        res = subprocess.run(
            [binary, "-c", host, "-p", str(PORT), "-t", "1", "-J"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8,
            check=False)
    except Exception:                     # noqa: BLE001 - health probe
        return False
    return res.returncode == 0 and b'"sum_received"' in (res.stdout or b"")


def ensure_server(host: str = "127.0.0.1", log=None,
                  restart: bool = True) -> str:
    """Make sure a *working* iperf3 server answers on ``host``.

    Returns "" when the server is up, otherwise a reason string starting
    with "iperf server unavailable".

    m119: a server started by an earlier row (or left behind by an
    interrupted client) can be wedged while still accepting connections,
    so the server this module owns is stopped and started again, and any
    listener we do not own must pass a one-second throughput probe."""
    probe = host if host and host != "0.0.0.0" else "127.0.0.1"
    if restart:
        stop_server()
    if _port_open(probe):
        if log:
            log(f"iperf server: reusing the listener on {probe}:{PORT}")
        if _health(probe):
            return ""
        return (f"iperf server unavailable ({probe}:{PORT} accepts "
                "connections but moves no bytes - a wedged server; "
                "stop it and re-run)")
    binary = find_binary()
    if not binary:
        return "iperf server unavailable (iperf3 binary not found)"
    if log:
        log(f"iperf server: starting {binary} on port {PORT}")
    try:
        _start(binary)
    except OSError as exc:
        return f"iperf server unavailable ({exc})"
    deadline = time.monotonic() + _START_TIMEOUT_S
    while time.monotonic() < deadline:
        if _port_open(probe, timeout_s=0.4):
            if log:
                log(f"iperf server: listening on {probe}:{PORT}")
            atexit.register(stop_server)
            return ""
        time.sleep(0.25)
    return (f"iperf server unavailable (started {os.path.basename(binary)} "
            f"but {probe}:{PORT} never answered)")


def stop_server() -> None:
    global _SERVER
    proc, _SERVER = _SERVER, None
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:                     # noqa: BLE001 - best effort
        try:
            proc.kill()
        except Exception:                 # noqa: BLE001
            pass
