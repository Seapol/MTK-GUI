# -*- coding: utf-8 -*-
"""M10 - SharePoint share-link parsing + signed-in session state."""
from __future__ import annotations

import pytest

from mtkgui.engine.sharepoint_site import (
    SharePointSession,
    join_folder,
    parse_browser_cookies,
    parse_sharepoint_link,
    session_cookies,
)

SITE = "https://nxp1.sharepoint.com"

MODERN = ("https://nxp1.sharepoint.com/:f:/r/teams/ext158/BTD/Shared"
          "%20Documents/MTK%20Test%20Data?d=w1234&csf=1&web=1&e=abcd")
CLASSIC = ("https://nxp1.sharepoint.com/:f:/teams/ext158/BTD/Shared "
           "Documents/MTK Test Data?d=w1234")
PLAIN = ("https://nxp1.sharepoint.com/teams/ext158/BTD/Shared Documents/"
         "MTK Test Data")
SUB = ("https://nxp1.sharepoint.com/:f:/r/teams/ext158/BTD/Shared"
       "%20Documents/MTK%20Test%20Data/96317?d=w1")


def test_modern_share_link_is_decoded_and_query_stripped():
    parsed = parse_sharepoint_link(MODERN)
    assert parsed.site == "https://nxp1.sharepoint.com"
    assert parsed.folder_path == \
        "/teams/ext158/BTD/Shared Documents/MTK Test Data"


def test_classic_share_link():
    parsed = parse_sharepoint_link(CLASSIC)
    assert parsed.site == "https://nxp1.sharepoint.com"
    assert parsed.folder_path == \
        "/teams/ext158/BTD/Shared Documents/MTK Test Data"


def test_plain_direct_url():
    parsed = parse_sharepoint_link(PLAIN)
    assert parsed.site == "https://nxp1.sharepoint.com"
    assert parsed.folder_path == \
        "/teams/ext158/BTD/Shared Documents/MTK Test Data"


def test_sub_folder_link_is_the_upload_root():
    parsed = parse_sharepoint_link(SUB)
    assert parsed.folder_path == \
        "/teams/ext158/BTD/Shared Documents/MTK Test Data/96317"


def test_site_root_link():
    parsed = parse_sharepoint_link("https://nxp1.sharepoint.com/")
    assert parsed.site == "https://nxp1.sharepoint.com"
    assert parsed.folder_path == ""


def test_invalid_links_are_rejected():
    for bad in ("", "   ", "nxp1.sharepoint.com/teams/ext158",
                "ftp://nxp1.sharepoint.com/x"):
        with pytest.raises(ValueError):
            parse_sharepoint_link(bad)


def test_join_folder():
    assert join_folder("/a/b", "c") == "/a/b/c"
    assert join_folder("/a/b/", "/c/") == "/a/b/c"
    assert join_folder("", "c") == "/c"
    assert join_folder("/a/b", "") == "/a/b"
    assert join_folder("", "") == "/"


def test_session_cookies_filter_by_name_and_host():
    items = [
        {"name": "FedAuth", "value": "f", "domain": ".sharepoint.com",
         "path": "/"},
        {"name": "rtFa", "value": "r", "domain": "nxp1.sharepoint.com",
         "path": "/"},
        {"name": "other", "value": "x", "domain": ".sharepoint.com",
         "path": "/"},
        {"name": "FedAuth", "value": "z", "domain": ".example.com",
         "path": "/"},
    ]
    kept = session_cookies(items, "nxp1.sharepoint.com")
    assert [c["name"] for c in kept] == ["FedAuth", "rtFa"]
    assert kept[0]["domain"] == ".sharepoint.com"


def test_session_round_trip_and_jar(tmp_path):
    session = SharePointSession(
        site="https://nxp1.sharepoint.com",
        folder_path="/teams/ext158/BTD/Shared Documents/MTK Test Data",
        user="Jane Operator", link=MODERN, signed_in_at="2026-10-23T10:00:00",
        cookies=[{"name": "FedAuth", "value": "abc",
                  "domain": ".sharepoint.com", "path": "/",
                  "secure": True}])
    path = session.save(tmp_path / "state" / "session.json")
    assert path.exists()
    restored = SharePointSession.load(path)
    assert restored is not None and restored.signed_in
    assert restored.user == "Jane Operator"
    assert restored.jar()._cookies[".sharepoint.com"]["/"]["FedAuth"].value \
        == "abc"


def test_load_missing_or_empty_session(tmp_path):
    assert SharePointSession.load(tmp_path / "absent.json") is None
    empty = SharePointSession(site="https://nxp1.sharepoint.com")
    assert not empty.signed_in
    empty.save(tmp_path / "empty.json")
    assert SharePointSession.load(tmp_path / "empty.json") is None


# ---------------------------------------------------------- browser import
BROWSER_JSON = """[
  {"name":"FedAuth","value":"FA_ABC","domain":".nxp1.sharepoint.com",
   "path":"/","secure":true,"session":true},
  {"name":"rtFa","value":"RT_XYZ","domain":".nxp1.sharepoint.com",
   "path":"/","secure":true,"session":true},
  {"name":"bogus","value":"nope","domain":".nxp1.sharepoint.com",
   "path":"/","secure":true},
  {"name":"_EDGE_S","value":"x","domain":".msedge.net",
   "path":"/","secure":true}
]"""


def test_browser_cookies_json_array_keeps_session_pair():
    cookies, errors = parse_browser_cookies(BROWSER_JSON, SITE)
    assert [c["name"] for c in cookies] == ["FedAuth", "rtFa"]
    assert not errors


def test_browser_cookies_name_value_lines_fallback():
    cookies, errors = parse_browser_cookies("FedAuth=FA_LINE\nrtFa=RT_LINE",
                                            SITE)
    assert [c["name"] for c in cookies] == ["FedAuth", "rtFa"]
    assert not errors
    assert cookies[0]["domain"] == "nxp1.sharepoint.com"
    assert cookies[0]["secure"] is True


def test_browser_cookies_missing_rtfa_reports_requirement():
    cookies, errors = parse_browser_cookies("FedAuth=ONLY", SITE)
    assert [c["name"] for c in cookies] == ["FedAuth"]
    assert any("rtFa" in m for m in errors)


def test_browser_cookies_empty_or_no_site():
    cookies, errors = parse_browser_cookies("  ", SITE)
    assert not cookies and errors
    cookies, errors = parse_browser_cookies("FedAuth=X", "")
    assert not cookies and any("site link" in m for m in errors)


def test_browser_cookies_wrong_domain_dropped():
    cookies, errors = parse_browser_cookies(
        '[{"name":"FedAuth","value":"X","domain":"evil.com",'
        '"path":"/","secure":true}]', SITE)
    assert not cookies
    assert any("No FedAuth / rtFa" in m for m in errors)


def test_browser_cookies_non_array_json_rejected():
    cookies, errors = parse_browser_cookies('{"name":"FedAuth"}', SITE)
    assert not cookies
    assert any("not a cookie array" in m for m in errors)
