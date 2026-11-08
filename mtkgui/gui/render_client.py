"""Parent-side client for the child-process DUT report renderer (M81).

Owns one persistent ``QProcess`` (started lazily on the first render), speaks
the line protocol of :mod:`mtkgui.render_proc` and re-emits it as Qt signals so
the main window can drive the foreground progress dialog.  The child does the
render; this object never touches QTextDocument.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

#: a render that takes longer than this means the child is stuck.
JOB_TIMEOUT_S = 60.0


class ReportRenderClient(QObject):
    """One report at a time, rendered by ``<exe> --render-pdf``."""

    progress = Signal(int, int)          # done, total pages
    finished = Signal(str)               # absolute pdf path
    failed = Signal(str)                 # human-readable reason

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._buffer = b""
        self._job: dict | None = None
        self._ready = False
        self._retried = False
        self._shutting_down = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(JOB_TIMEOUT_S * 1000))
        self._timer.timeout.connect(self._on_timeout)

    # -------------------------------------------------------------- api
    @property
    def busy(self) -> bool:
        """True while a job is in flight (accepted, not yet reported)."""
        return self._job is not None

    def render(self, report_dict: dict, meta: dict, path) -> bool:
        """Queue one render.  False when a job is already running."""
        if self._job is not None:
            return False
        self._job = {"type": "render", "path": str(path),
                     "meta": dict(meta or {}), "report": dict(report_dict)}
        self._retried = False
        self._ensure_proc()
        if self._ready:
            self._send_job()
        return True

    def shutdown(self) -> None:
        """Stop the child for good (window close / application quit)."""
        self._shutting_down = True
        self._timer.stop()
        self._job = None
        proc, self._proc = self._proc, None
        self._buffer = b""
        self._ready = False
        if proc is None:
            return
        proc.blockSignals(True)
        proc.closeWriteChannel()
        if not proc.waitForFinished(500):
            proc.kill()
            proc.waitForFinished(1000)
        proc.deleteLater()

    # ---------------------------------------------------------- process
    @staticmethod
    def _argv() -> list[str]:
        argv = [sys.executable]
        if not getattr(sys, "frozen", False):
            argv.append(str(Path(__file__).resolve().parents[2] / "main.py"))
        argv.append("--render-pdf")
        return argv

    def _ensure_proc(self) -> None:
        if self._proc is not None:
            return
        proc = QProcess(self)
        proc.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels)
        proc.setProcessEnvironment(
            QProcessEnvironment.systemEnvironment())
        proc.readyReadStandardOutput.connect(self._read_stdout)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        self._buffer = b""
        self._ready = False
        argv = self._argv()
        proc.start(argv[0], argv[1:])

    def _send_job(self) -> None:
        if self._proc is None or self._job is None:
            return
        payload = json.dumps(self._job, separators=(",", ":")).encode("utf-8")
        self._timer.start()
        self._proc.write(payload + b"\n")

    def _kill_proc(self) -> None:
        proc, self._proc = self._proc, None
        self._buffer = b""
        self._ready = False
        if proc is None:
            return
        proc.blockSignals(True)
        proc.kill()
        proc.waitForFinished(2000)
        proc.deleteLater()

    # ------------------------------------------------------------ events
    def _read_stdout(self) -> None:
        if self._proc is None:
            return
        self._buffer += bytes(self._proc.readAllStandardOutput())
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(event, dict):
                self._handle_event(event)

    def _handle_event(self, event: dict) -> None:
        kind = event.get("t")
        if kind == "ready":
            self._ready = True
            if self._job is not None:
                self._send_job()
            return
        if self._job is None:
            return                       # late line of a finished job
        if kind == "page":
            self.progress.emit(int(event.get("done") or 0),
                               int(event.get("total") or 0))
        elif kind == "done":
            self._finish_ok(str(event.get("path") or self._job["path"]))
        elif kind == "error":
            self._finish_failed(str(event.get("msg")
                                    or "DUT report renderer failed"))

    def _finish_ok(self, path: str) -> None:
        self._timer.stop()
        self._job = None
        self.finished.emit(path)

    def _finish_failed(self, message: str) -> None:
        self._timer.stop()
        self._job = None
        self.failed.emit(message)

    # ------------------------------------------------- error / recovery
    def _on_timeout(self) -> None:
        if self._job is None:
            return
        self._kill_proc()
        # fixed operator-facing text (the tests assert it byte for byte)
        self._finish_failed("DUT report renderer timed out after 60 s")

    def _on_error(self, _error) -> None:
        # FailedToStart and friends: the child never reached a job
        self._on_finished()

    def _on_finished(self, *_args) -> None:
        if self._shutting_down or self._proc is None:
            return
        self._proc = None
        self._ready = False
        self._buffer = b""
        if self._job is None:
            return
        if not self._retried:
            # one respawn + one retry of the SAME job
            self._retried = True
            self._ensure_proc()
            return
        path = self._job["path"]
        self._finish_failed(
            f"DUT report renderer exited unexpectedly ({path})")
