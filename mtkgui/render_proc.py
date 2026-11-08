"""Child-process DUT PDF renderer (M81).

The certificate render holds the GIL inside the GUI interpreter: a progress
dialog drawn by the parent freezes along with the window.  So the render runs
in a separate process and the parent speaks one JSON object per line over
stdin/stdout.

Deliberately imports only stdlib + QtGui/QtWidgets: never
``mtkgui.main_window``, never QtWebEngine - the child must start fast.

Protocol::

    child -> parent   {"t": "ready"}
                      {"t": "page", "done": k, "total": n}
                      {"t": "done", "path": "...", "pt": 8.0}
                      {"t": "error", "msg": "TypeError: ..."}
    parent -> child   {"type": "render", "path": "...", "meta": {...},
                       "report": {...}}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _emit(payload: dict) -> None:
    """One protocol line, flushed immediately (the parent reads lines)."""
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _render(job: dict) -> None:
    """Render one certificate and emit the page / done lines."""
    from mtkgui.engine.report import DutReport, ReportItem
    from mtkgui.gui import dut_pdf

    payload = dict(job.get("report") or {})
    payload["items"] = [ReportItem(**item)
                        for item in (payload.get("items") or [])]
    report = DutReport(**payload)
    meta = dict(job.get("meta") or {})
    path = Path(str(job["path"]))

    html, images, chart_spec = dut_pdf.report_pdf_payload(report, meta)
    if chart_spec:
        images[dut_pdf.CHART_RESOURCE] = dut_pdf.paint_rails_chart(*chart_spec)

    def _page(done: int, total: int) -> None:
        _emit({"t": "page", "done": int(done), "total": int(total)})

    pt = dut_pdf._render_pdf(html, images, path,
                             font_scale=dut_pdf.screen_font_scale(),
                             on_page=_page)
    _emit({"t": "done", "path": str(path), "pt": pt})


def main(argv=None) -> int:
    """Run the child: announce ready, then serve jobs until stdin EOF."""
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication([])            # no argv: flags are not for Qt
    _emit({"t": "ready"})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
        except ValueError as exc:
            _emit({"t": "error", "msg": f"bad job line: {exc}"})
            continue
        if not isinstance(job, dict) or job.get("type") != "render":
            kind = job.get("type") if isinstance(job, dict) else job
            _emit({"t": "error", "msg": f"unknown job type {kind!r}"})
            continue
        try:
            _render(job)
        except Exception as exc:             # noqa: BLE001 - reported to the parent
            _emit({"t": "error", "msg": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
