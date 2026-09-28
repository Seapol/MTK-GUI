# -*- coding: utf-8 -*-
"""Background serial reader thread.

Blocking reads run in a QThread so the UI never freezes. Received bytes
are delivered to the UI thread via Qt signals. ``write()`` is called from
the UI thread; sharing a pyserial port between one reader thread and a
writer thread is supported on Windows / macOS / Linux, and a lock is
used to guard concurrent access.
"""

import threading

import serial
from PySide6.QtCore import QThread, Signal


class SerialWorker(QThread):
    data_received = Signal(bytes)
    error_occurred = Signal(str)
    connection_changed = Signal(bool)

    def __init__(self, port, baudrate, bytesize, parity, stopbits,
                 flow_control=False, parent=None):
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.flow_control = flow_control
        self._running = False
        self._ser = None
        self._write_lock = threading.Lock()

    def run(self):
        try:
            kwargs = dict(
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=0.05,
                rtscts=self.flow_control,
                dsrdtr=False,
            )
            if "://" in (self.port or ""):
                # pyserial URL ports (loop:// for tests, socket://, ...)
                self._ser = serial.serial_for_url(self.port, **kwargs)
            else:
                self._ser = serial.Serial(port=self.port, **kwargs)
        except Exception as exc:  # open failed
            self.error_occurred.emit(f"Failed to open port: {exc}")
            self.connection_changed.emit(False)
            return

        self._running = True
        self.connection_changed.emit(True)
        try:
            while self._running:
                try:
                    waiting = self._ser.in_waiting
                    data = self._ser.read(waiting if waiting else 1)
                except Exception as exc:
                    if self._running:
                        self.error_occurred.emit(f"Serial read error: {exc}")
                    break
                if data:
                    self.data_received.emit(data)
        finally:
            try:
                if self._ser and self._ser.is_open:
                    self._ser.close()
            except Exception:
                pass
            self._running = False
            self.connection_changed.emit(False)

    def write(self, data: bytes) -> int:
        """Called from the UI thread. Returns bytes written, or -1."""
        if not self._ser or not self._ser.is_open:
            return -1
        with self._write_lock:
            try:
                n = self._ser.write(data)
                self._ser.flush()
                return n if n is not None else len(data)
            except Exception as exc:
                self.error_occurred.emit(f"Serial write error: {exc}")
                return -1

    def stop(self):
        self._running = False
        if self._ser:
            try:
                self._ser.cancel_read()  # unblocks a waiting read on Windows
            except Exception:
                pass
        self.wait(3000)
