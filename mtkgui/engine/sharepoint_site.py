# -*- coding: utf-8 -*-
"""M10 - real SharePoint site links + signed-in session state.

The Report > SharePoint Upload dialog runs against the real NXP site
(``nxp1.sharepoint.com``).  Two pieces live here (no Qt, no network):

  * :func:`parse_sharepoint_link` - normalise the folder share link the
    operator pastes into ``site`` (scheme + host) and ``folder_path``
    (server-relative, URL-decoded, query stripped).  Modern
    ``/:f:/r/teams/...`` and classic ``/:f:/teams/...`` share links as
    well as plain direct URLs are accepted; a sub-folder link simply
    becomes the upload root.
  * :class:`SharePointSession` - the signed-in session captured by the
    embedded login window: session cookies (FedAuth / rtFa) + the
    display name.  Persisted as JSON under
    ``mtkgui/config/sharepoint_state/session.json``.  No password and
    no application token is ever stored.
"""
from __future__ import annotations

import http.cookiejar
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

#: cookies the SharePoint / AAD sign-in leaves on the site host
SESSION_COOKIE_NAMES: tuple[str, ...] = ("FedAuth", "rtFa")


def parse_browser_cookies(text: str,
                          site_url: str = "") -> tuple[list[dict], list[str]]:
    """Parse cookies exported from the operator's OWN browser (Edge /
    Chrome) into the session-cookie list the GUI accepts, so the
    embedded sign-in window can be skipped entirely.

    Accepted input formats:

      * Cookie-Editor / EditThisCookie JSON export - a JSON array of
        cookie objects with ``name`` / ``value`` / ``domain`` / ``path``
        / ``secure`` fields (any extra fields are ignored);
      * manual ``name=value`` lines - one cookie per line, the site
        host is used as the cookie domain (handy when copying FedAuth /
        rtFa straight from DevTools -> Application -> Cookies).

    Only the SharePoint session cookies (``FedAuth`` / ``rtFa``) whose
    domain matches ``site_url`` are kept - everything else is dropped.

    Returns ``(cookies, errors)``: ``errors`` carries human-readable
    problems (empty paste / not JSON / no site link / a session cookie
    missing) so the GUI can explain what to fix instead of failing
    silently.
    """
    errors: list[str] = []
    text = (text or "").strip()
    if not text:
        return [], ["Nothing to import - paste the cookies first."]
    host = host_of(site_url)
    if not host:
        return [], ["No SharePoint site link - enter the site link in the "
                    "SharePoint Connection box first."]

    entries: list[dict] = []
    try:
        data = json.loads(text)
    except ValueError:
        # fall back to manual name=value lines (one cookie per line)
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if "=" not in ln:
                continue
            name, _, value = ln.partition("=")
            name = name.strip().strip('"')
            value = value.strip().strip('"')
            if name and value:
                entries.append({"name": name, "value": value,
                                "domain": host, "path": "/",
                                "secure": True})
    else:
        if not isinstance(data, list):
            return [], ["The pasted text is not a cookie array - export "
                        "the cookies as a JSON list (Cookie-Editor "
                        "'Export') or paste one name=value line per row."]
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            value = str(item.get("value") or "")
            domain = str(item.get("domain") or "").strip().lstrip(".")
            path = str(item.get("path") or "/") or "/"
            secure = bool(item.get("secure", False))
            if not name:
                continue
            entries.append({"name": name, "value": value,
                            "domain": domain, "path": path,
                            "secure": secure})

    kept: list[dict] = []
    for entry in entries:
        # session_cookies() keeps FedAuth / rtFa whose domain matches
        # the site host (domain-only matching, host_only_domain and
        # session flags are irrelevant to the REST transport)
        kept.extend(session_cookies([entry], host))
    names = {c["name"] for c in kept}
    if not kept:
        errors.append(
            f"No FedAuth / rtFa session cookie found for {host}. Check "
            "that the site link matches the browser domain you copied "
            "the cookies from.")
    else:
        for need in SESSION_COOKIE_NAMES:
            if need not in names:
                errors.append(
                    f"Missing the {need} session cookie - SharePoint "
                    "needs BOTH FedAuth and rtFa. Copy both from the "
                    "browser (DevTools -> Application -> Cookies).")
    return kept, errors

#: share-link markers: modern (``:f:/r/``) first, then the classic form
_SHARE_MARKERS: tuple[str, ...] = ("/:f:/r/", "/:f:/")


@dataclass(frozen=True)
class SharePointSite:
    """``site`` (scheme://host) + ``folder_path`` (server-relative)."""

    site: str
    folder_path: str = ""
    raw: str = ""


def parse_sharepoint_link(link: str) -> SharePointSite:
    """Folder share link -> :class:`SharePointSite`.

    Accepted formats (all with an optional ``?d=...&csf=1&web=1`` query
    that is dropped):

      * ``https://<host>/:f:/r/teams/<...>``   modern folder share
      * ``https://<host>/:f:/teams/<...>``     classic folder share
      * ``https://<host>/teams/<...>``         plain direct URL

    The path is URL-decoded (``%20`` -> space).  A link pointing at a
    sub-folder is simply the upload root - callers pass relative
    sub-paths to the transport.
    """
    raw = (link or "").strip()
    if not raw:
        raise ValueError("empty SharePoint link")
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError(f"not an http(s) SharePoint link: {raw!r}")
    path = unquote(parts.path or "/")
    for marker in _SHARE_MARKERS:
        idx = path.find(marker)
        if idx >= 0:
            path = f"{path[:idx]}/{path[idx + len(marker):]}"
            break
    return SharePointSite(site=f"{parts.scheme.lower()}://{parts.netloc}",
                          folder_path=path.rstrip("/"), raw=raw)


def join_folder(folder_path: str, relative: str = "") -> str:
    """Server-relative path of ``relative`` under ``folder_path``."""
    base = str(folder_path or "").strip("/")
    base = f"/{base}" if base else ""
    rel = str(relative or "").strip("/")
    if not rel:
        return base or "/"
    return f"{base}/{rel}"


def host_of(site: str) -> str:
    return urlsplit(str(site or "")).netloc.lower()


def session_cookies(items, host: str) -> list[dict]:
    """Session cookies (FedAuth / rtFa) for ``host`` from raw cookie
    snapshots (dicts with name / value / domain / path / secure)."""
    host = str(host or "").lower()
    kept: list[dict] = []
    for item in items or []:
        name = str(item.get("name") or "")
        domain = str(item.get("domain") or "").lower().lstrip(".")
        if name not in SESSION_COOKIE_NAMES or not domain:
            continue
        if host and not (host == domain or host.endswith(f".{domain}")):
            continue
        kept.append({"name": name, "value": str(item.get("value") or ""),
                     "domain": str(item.get("domain") or ""),
                     "path": str(item.get("path") or "/"),
                     "secure": bool(item.get("secure", False))})
    return kept


@dataclass
class SharePointSession:
    """Signed-in state: session cookies + the SharePoint user name."""

    site: str = ""
    folder_path: str = ""
    user: str = ""
    link: str = ""
    signed_in_at: str = ""
    cookies: list[dict] = field(default_factory=list)

    @property
    def signed_in(self) -> bool:
        return bool(self.site and self.cookies)

    def jar(self) -> http.cookiejar.CookieJar:
        """A ``http.cookiejar`` populated with the session cookies so
        the REST transport can send the same browser session."""
        jar = http.cookiejar.CookieJar()
        fallback = host_of(self.site)
        for item in self.cookies:
            name = str(item.get("name") or "")
            domain = str(item.get("domain") or fallback)
            if not name or not domain:
                continue
            jar.set_cookie(http.cookiejar.Cookie(
                version=0, name=name, value=str(item.get("value") or ""),
                port=None, port_specified=False, domain=domain,
                domain_specified=True,
                domain_initial_dot=domain.startswith("."),
                path=str(item.get("path") or "/"), path_specified=True,
                secure=bool(item.get("secure", False)), expires=None,
                discard=False, comment=None, comment_url=None, rest={},
                rfc2109=False))
        return jar

    # ------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {"site": self.site, "folder_path": self.folder_path,
                "user": self.user, "link": self.link,
                "signed_in_at": self.signed_in_at,
                "cookies": [dict(c) for c in self.cookies]}

    @classmethod
    def from_dict(cls, data) -> "SharePointSession":
        if not isinstance(data, dict):
            return cls()
        cookies = data.get("cookies")
        return cls(site=str(data.get("site") or ""),
                   folder_path=str(data.get("folder_path") or ""),
                   user=str(data.get("user") or ""),
                   link=str(data.get("link") or ""),
                   signed_in_at=str(data.get("signed_in_at") or ""),
                   cookies=[dict(c) for c in cookies
                            if isinstance(c, dict)] if isinstance(
                               cookies, list) else [])

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False,
                                   indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path) -> "SharePointSession | None":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        session = cls.from_dict(data)
        return session if session.signed_in else None
