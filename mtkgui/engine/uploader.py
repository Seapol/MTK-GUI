# -*- coding: utf-8 -*-
"""P2-8 enterprise SharePoint upload closed loop (pure incremental).

Final mass-production link: test done -> metrics -> report -> archive
(P2-7) -> unattended upload to the project SharePoint directory.

Design:

  * UploadConfig     — read from the P2-2 visual config dict
                       (``sharepoint.*`` section, P1 pass-through keys
                       finally wired here); hot-re-appliable
  * Transport        — injectable transport seam: FakeSharePoint for
                       tests/demos, HttpSharePoint for real sites
  * precheck         — connectivity + permission + directory writable
                       probe BEFORE any payload moves
  * upload           — whitelist/blacklist filter, same-hash dedup,
                       retry with resume-on-disconnect, per-file result
                       carrying cloud URL + SHA-256 + timestamp
  * outbox fallback  — failed files stay in the local outbox (never
                       deleted), pending re-upload on the next run
  * ledger + audit   — every attempt logged ``[UPLOAD]`` and recorded
                       in the JSON ledger (traceable book-keeping)

Zero changes to the test flow, reports, metrics engine or archive.
"""
from __future__ import annotations

import fnmatch
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from mtkgui.engine.archive import file_sha256  # reuse P2-7 hashing

# executable / dangerous payloads never leave the station
BLACKLIST_SUFFIXES = {".exe", ".bat", ".cmd", ".sh", ".dll", ".msi"}


class TransportError(Exception):
    """Permission / server-side rejection (no retry)."""


@dataclass
class UploadConfig:
    """Mirror of the P2-2 ``sharepoint.*`` visual config section."""
    enabled: bool = False
    site_url: str = ""
    username: str = ""
    password: str = ""
    token: str = ""
    retry_count: int = 3
    resume_on_disconnect: bool = True
    overwrite_policy: str = "keep_both"   # overwrite | keep_both | skip
    project_dir: str = ""
    whitelist: list[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, cfg: dict) -> "UploadConfig":
        sp = cfg.get("sharepoint") or {}
        return cls(
            enabled=bool(sp.get("enabled", False)),
            site_url=str(sp.get("site_url") or ""),
            username=str(sp.get("username") or ""),
            password=str(sp.get("password") or ""),
            token=str(sp.get("token") or ""),
            retry_count=int(sp.get("upload_retry_count") or 0),
            resume_on_disconnect=bool(
                sp.get("resume_on_disconnect", True)),
            overwrite_policy=str(sp.get("overwrite_policy")
                                 or "keep_both"),
            project_dir=str(sp.get("project_dir") or ""),
            whitelist=list(sp.get("archive_whitelist") or []),
        )


# ============================================================ transports
class FakeSharePoint:
    """In-memory SharePoint stand-in for tests, demos and dry runs.

    Inject faults per call site: ``fail_next_put`` / ``fail_probe`` /
    ``deny_write``.  ``uploaded`` maps remote path -> bytes.
    """

    def __init__(self, *, base="https://corp.sharepoint.com/ict"):
        self.base = base
        self.uploaded: dict[str, bytes] = {}
        self.dirs: set[str] = set()
        self.fail_next_put = 0
        self.fail_probe = False
        self.deny_write = False
        self.online = True

    # -- probe API -----------------------------------------------------
    def head(self, path: str) -> None:
        if not self.online or self.fail_probe:
            raise ConnectionError(f"site unreachable: {path}")

    def mkdirs(self, path: str) -> None:
        if self.deny_write:
            raise TransportError(f"access denied: {path}")
        self.dirs.add(path)

    def exists(self, path: str) -> bool:
        return path in self.uploaded

    def put(self, path: str, data: bytes) -> str:
        if not self.online:
            raise ConnectionError("network down")
        if self.fail_next_put > 0:
            self.fail_next_put -= 1
            raise ConnectionError(f"transfer dropped: {path}")
        if self.deny_write:
            raise TransportError(f"access denied: {path}")
        self.uploaded[path] = data
        return f"{self.base}/{path}"


class HttpSharePoint:
    """Real transport (urllib, token auth) — same seam as the fake.

    put() streams the payload with an Authorization bearer token;
    probes use HEAD requests.  ConnectionError triggers the retry /
    resume path, TransportError aborts without retry.
    """

    def __init__(self, site_url: str, token: str = "", username: str = "",
                 password: str = "", timeout: float = 30.0):
        self.site_url = site_url.rstrip("/")
        self.token = token
        self.basic = (f"Basic {username}:{password}"
                      if username or password else "")
        self.timeout = timeout

    def _request(self, method: str, url: str, data: bytes | None = None):
        req = urllib.request.Request(url, data=data, method=method)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        elif self.basic:
            req.add_header("Authorization", self.basic)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status
        except urllib.error.HTTPError as exc:
            raise TransportError(f"http {exc.code}: {url}") from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"unreachable: {url} ({exc.reason})") \
                from exc

    def head(self, path: str) -> None:
        self._request("HEAD", f"{self.site_url}/{path}")

    def mkdirs(self, path: str) -> None:
        # folder creation is a server-side PUT to the folder URL
        self._request("PUT", f"{self.site_url}/{path}")

    def exists(self, path: str) -> bool:
        try:
            self._request("HEAD", f"{self.site_url}/{path}")
            return True
        except TransportError:
            return False

    def put(self, path: str, data: bytes) -> str:
        self._request("PUT", f"{self.site_url}/{path}", data)
        return f"{self.site_url}/{path}"


# ============================================================== results
@dataclass
class UploadResult:
    name: str
    status: str                 # UPLOADED | DEDUPED | FAILED | BLOCKED
    attempts: int = 0
    sha256: str = ""
    url: str = ""
    ts: str = ""
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status,
                "attempts": self.attempts, "sha256": self.sha256,
                "url": self.url, "ts": self.ts, "detail": self.detail}


def filter_allowed(name: str, whitelist: list[str]) -> str | None:
    """Black/white-list gate: returns a reject reason or None."""
    if Path(name).suffix.lower() in BLACKLIST_SUFFIXES:
        return "blacklisted type"
    if whitelist and not any(fnmatch.fnmatch(name, pat)
                             for pat in whitelist):
        return "not in whitelist"
    return None


# ============================================================= uploader
class SharePointUploader:
    """Unattended uploader with precheck / retry / dedup / fallback."""

    LEDGER = "upload_ledger.json"

    def __init__(self, outbox, *, state_dir=None, transport=None,
                 now=None, sleep=time.sleep):
        self.outbox = Path(outbox)
        self.outbox.mkdir(parents=True, exist_ok=True)
        self.state_dir = Path(state_dir) if state_dir else self.outbox
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.transport = transport
        self.config = UploadConfig()
        self.now = now or datetime.now
        self._sleep = sleep
        self.audit: list[tuple[str, str, str]] = []
        self.ledger: list[dict] = []          # successful book-keeping
        self._load_ledger()

    # ------------------------------------------------------------ log
    def _log(self, action: str, detail: str) -> None:
        ts = self.now()
        self.audit.append((ts.isoformat(timespec="seconds"), action,
                           detail))
        print(f"[UPLOAD] {ts:%Y-%m-%d %H:%M:%S} {action}: {detail}")

    # --------------------------------------------------------- config
    def apply_config(self, cfg: dict | UploadConfig) -> None:
        """Hot update from a P2-2 config dict (or UploadConfig)."""
        if isinstance(cfg, UploadConfig):
            self.config = cfg
        else:
            self.config = UploadConfig.from_config(cfg)
        self._log("config", f"enabled={self.config.enabled} "
                            f"site={self.config.site_url or '-'} "
                            f"dir={self.config.project_dir or '-'} "
                            f"retry={self.config.retry_count}")

    # ---------------------------------------------------------- ledger
    def _load_ledger(self) -> None:
        path = self.state_dir / self.LEDGER
        if path.is_file():
            try:
                self.ledger = json.loads(
                    path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.ledger = []

    def _save_ledger(self) -> None:
        path = self.state_dir / self.LEDGER
        path.write_text(json.dumps(self.ledger, ensure_ascii=False,
                                   indent=2), encoding="utf-8")

    # -------------------------------------------------------- precheck
    def precheck(self) -> list[str]:
        """Connectivity + permission + directory-writable probes."""
        problems: list[str] = []
        cfg = self.config
        if not cfg.enabled:
            problems.append("cloud archive disabled in config")
        if not cfg.site_url:
            problems.append("site_url missing")
        if self.transport is None:
            problems.append("no transport configured")
            self._log("precheck", "; ".join(problems) or "OK")
            return problems
        try:
            self.transport.head(cfg.site_url or "/")
        except ConnectionError as exc:
            problems.append(f"connectivity: {exc}")
        dest = self._dest_dir()
        try:
            self.transport.mkdirs(dest)
        except TransportError as exc:
            problems.append(f"permission/writable: {exc}")
        except ConnectionError as exc:
            problems.append(f"connectivity: {exc}")
        self._log("precheck", "; ".join(problems) or "OK")
        return problems

    def _dest_dir(self) -> str:
        return (self.config.project_dir or "").strip("/")

    # ---------------------------------------------------------- upload
    def upload_file(self, path) -> UploadResult:
        """One file through the full gate chain."""
        path = Path(path)
        cfg = self.config
        ts = self.now()
        reason = filter_allowed(path.name, cfg.whitelist)
        if reason is not None:
            self._log("blocked", f"{path.name}: {reason}")
            return UploadResult(path.name, "BLOCKED", detail=reason)
        if not cfg.enabled or self.transport is None or not cfg.site_url:
            self._log("skip", f"{path.name}: uploader not configured")
            return UploadResult(path.name, "FAILED",
                                detail="not configured")
        digest = file_sha256(path)
        dest_dir = self._dest_dir()
        remote = f"{dest_dir}/{path.name}" if dest_dir else path.name
        # dedup: identical content already on the cloud
        for row in self.ledger:
            if row["name"] == path.name and row["sha256"] == digest \
                    and row["status"] == "UPLOADED":
                self._log("dedup", f"{path.name}: identical copy "
                                   f"already uploaded")
                return UploadResult(path.name, "DEDUPED", sha256=digest,
                                    url=row["url"], ts=ts.isoformat(
                                        timespec="seconds"),
                                    detail="same hash already on cloud")
        # overwrite policy: skip never replaces remote content
        if cfg.overwrite_policy == "skip" and \
                self.transport.exists(remote):
            self._log("dedup", f"{path.name}: remote exists, "
                               f"policy=skip")
            return UploadResult(path.name, "DEDUPED", sha256=digest,
                                ts=ts.isoformat(timespec="seconds"),
                                detail="remote exists, policy=skip")
        data = path.read_bytes()
        attempts = 0
        last_err = ""
        while attempts <= cfg.retry_count:
            attempts += 1
            try:
                url = self.transport.put(remote, data)
            except ConnectionError as exc:
                last_err = str(exc)
                if not cfg.resume_on_disconnect:
                    break
                self._log("retry", f"{path.name}: attempt {attempts} "
                                   f"failed ({exc}), resume on")
                self._sleep(0)
                continue
            except TransportError as exc:
                last_err = str(exc)
                break
            result = UploadResult(path.name, "UPLOADED",
                                  attempts=attempts, sha256=digest,
                                  url=url,
                                  ts=ts.isoformat(timespec="seconds"))
            self.ledger.append(result.to_dict())
            self._save_ledger()
            self._log("uploaded", f"{path.name} -> {url} "
                                  f"sha256={digest[:12]} "
                                  f"attempts={attempts}")
            return result
        # fallback: the file stays in the local outbox, nothing lost
        self._log("failed", f"{path.name}: kept in outbox "
                            f"({last_err or 'exhausted retries'})")
        return UploadResult(path.name, "FAILED", attempts=attempts,
                            sha256=digest,
                            ts=ts.isoformat(timespec="seconds"),
                            detail=last_err)

    def upload_pending(self, source=None) -> list[UploadResult]:
        """Upload every allowed file in the outbox (or given list)."""
        files = ([Path(p) for p in source] if source is not None
                 else sorted(p for p in self.outbox.iterdir()
                             if p.is_file()))
        return [self.upload_file(p) for p in files]

    # ---------------------------------------------------------- query
    def records(self) -> list[dict]:
        """Ledger book-keeping for the GUI 台账 view."""
        return list(self.ledger)
