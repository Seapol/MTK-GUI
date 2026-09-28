# -*- coding: utf-8 -*-
"""Background SSH shell channel.

Mirrors the :class:`~mtkgui.serial_worker.SerialWorker` interface
(``data_received`` / ``error_occurred`` / ``connection_changed`` signals
plus ``write()`` / ``stop()``) so the multi-console container can treat a
serial port and an SSH shell the same way.

A single interactive shell is opened with ``invoke_shell()``; remote
output is polled in the worker thread and delivered as raw bytes.
``paramiko`` is imported lazily so the GUI starts even when it is not
installed — opening an SSH channel then reports a clear error.
"""

import threading
import time

from PySide6.QtCore import QThread, Signal


class SshWorker(QThread):
    data_received = Signal(bytes)
    error_occurred = Signal(str)
    connection_changed = Signal(bool)

    def __init__(self, host, port, username, password, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port or 22
        self.username = username
        self.password = password
        self._running = False
        self._client = None
        self._chan = None
        self._write_lock = threading.Lock()

    def run(self):
        try:
            import paramiko
        except ImportError:
            self.error_occurred.emit(
                "SSH support unavailable: paramiko is not installed "
                "(pip install paramiko)")
            self.connection_changed.emit(False)
            return

        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(
                paramiko.AutoAddPolicy())
            self._client.connect(
                hostname=self.host,
                port=int(self.port),
                username=self.username,
                password=self.password,
                timeout=8,
                allow_agent=False,
                look_for_keys=False,
            )
            self._chan = self._client.invoke_shell()
            self._chan.settimeout(0.2)
        except Exception as exc:
            self.error_occurred.emit(f"SSH connect failed: {exc}")
            self._cleanup()
            self.connection_changed.emit(False)
            return

        self._running = True
        self.connection_changed.emit(True)
        try:
            while self._running:
                try:
                    if self._chan.recv_ready():
                        data = self._chan.recv(4096)
                        if data:
                            self.data_received.emit(data)
                    else:
                        time.sleep(0.03)
                except Exception as exc:
                    if self._running:
                        self.error_occurred.emit(f"SSH read error: {exc}")
                    break
        finally:
            self._cleanup()
            self._running = False
            self.connection_changed.emit(False)

    def write(self, data: bytes) -> int:
        """Called from the UI thread. Returns bytes sent, or -1."""
        if not self._chan:
            return -1
        with self._write_lock:
            try:
                n = self._chan.send(data)
                return n
            except Exception as exc:
                self.error_occurred.emit(f"SSH write error: {exc}")
                return -1

    def _cleanup(self):
        try:
            if self._chan:
                self._chan.close()
        except Exception:
            pass
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass

    def stop(self):
        self._running = False
        self.wait(4000)
