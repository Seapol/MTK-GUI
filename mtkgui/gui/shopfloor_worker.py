# -*- coding: utf-8 -*-
"""Off-thread SharePoint upload that drives the shopfloor light (M86).

A run must never wait on the cloud: every retry moment hands its files to one
:class:`ShopfloorUploadWorker`, which uploads them with the certificate
manifest filter, writes ``state.json`` once and reports back through a signal.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from mtkgui import report_paths, sharepoint_store
from mtkgui.engine.sharepoint_site import SharePointSession
from mtkgui.engine.uploader import (
    MANIFEST_PATTERNS,
    HttpSharePoint,
    SharePointRestTransport,
    SharePointUploader,
    UploadConfig,
)

SESSION_FILE = "session.json"

#: state -> (LED colour key from LED_COLORS, tooltip) - no fifth colour
LIGHT_UI = {
    "off": ("disconnected", "SharePoint upload off or not configured"),
    "ok": ("connected", "Last upload succeeded - nothing pending"),
    "busy": ("untested", "Uploading, or files waiting to retry"),
    "fail": ("error", "Upload failed - files stay in the outbox"),
}


def light_ui(state: dict) -> tuple[str, str]:
    """``(colour key, tooltip)`` for one persisted shopfloor state."""
    name = str((state or {}).get("light") or "off")
    return LIGHT_UI.get(name, LIGHT_UI["off"])


def state_root() -> Path:
    """Where the dialog persists the signed-in session."""
    return Path(__file__).resolve().parents[1] / "config" / "sharepoint_state"


def build_uploader(section: dict, *, state_dir=None, transport=None):
    """An uploader wired to this project; None when not configured."""
    site = str((section or {}).get("site_url") or "").strip()
    if not site:
        return None
    if transport is None:
        session = SharePointSession.load(
            Path(state_dir or state_root()) / SESSION_FILE)
        if session is not None and session.cookies:
            transport = SharePointRestTransport(
                session.site or site, session.jar(),
                folder_path=session.folder_path, timeout=8.0)
        else:
            transport = HttpSharePoint(
                site, token=str(section.get("token") or ""), timeout=8.0)
    target = sharepoint_store.project_dir()
    uploader = SharePointUploader(target, state_dir=target,
                                  transport=transport)
    cfg = UploadConfig.from_config({"sharepoint": section})
    cfg.dest_segments = [report_paths.project_key(),
                         sharepoint_store.identity_folder()]
    if not cfg.whitelist:
        cfg.whitelist = list(MANIFEST_PATTERNS)
    uploader.apply_config(cfg)
    return uploader


class ShopfloorUploadWorker(QThread):
    """One upload batch off the GUI thread; writes state.json once."""

    #: ok, uploaded files, still-pending files, reason ("" when ok)
    done = Signal(bool, int, int, str)

    def __init__(self, files, section: dict, *, state_dir=None,
                 transport=None, parent=None):
        super().__init__(parent)
        self.files = [Path(path) for path in (files or [])]
        self.section = dict(section or {})
        self.state_dir = Path(state_dir) if state_dir else state_root()
        self.transport = transport

    def run(self):
        files = [path for path in self.files if path.is_file()]
        now = datetime.now().isoformat(timespec="seconds")
        if not files:
            sharepoint_store.save_state(light="off", last_result="",
                                        pending=[])
            self.done.emit(True, 0, 0, "")
            return
        uploader = build_uploader(self.section, state_dir=self.state_dir,
                                  transport=self.transport)
        if uploader is None:
            sharepoint_store.save_state(
                light="off", last_result="", last_attempt_ts=now,
                pending=[str(path) for path in files])
            self.done.emit(False, 0, len(files), "not configured")
            return
        results = uploader.upload_pending(source=files)
        uploaded = [result for result in results
                    if result.status in ("UPLOADED", "DEDUPED")]
        failed = [result for result in results if result.status == "FAILED"]
        left = [str(path) for path, result in zip(files, results)
                if result.status == "FAILED"]
        url = next((result.url for result in uploaded if result.url), "")
        if failed:
            sharepoint_store.save_state(
                light="fail", last_result="FAILED", last_url=url,
                last_attempt_ts=now, pending=left)
            self.done.emit(False, len(uploaded), len(left),
                           failed[0].detail or "upload failed")
            return
        sharepoint_store.save_state(
            light="ok", last_result="OK", last_url=url,
            last_attempt_ts=now, pending=[])
        self.done.emit(True, len(uploaded), 0, "")


__all__ = ["LIGHT_UI", "ShopfloorUploadWorker", "build_uploader", "light_ui",
           "state_root"]
