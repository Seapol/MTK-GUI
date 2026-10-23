# -*- coding: utf-8 -*-
"""M10 - SharePoint REST (``_api``) transport against mocked responses.

No network: a fake opener stands in for ``urllib`` and records the
requests, so the test asserts the exact REST calls (contextinfo digest,
``Files/add``, ``Folders/add``) and the status -> exception mapping.
"""
from __future__ import annotations

import json
import urllib.error

import pytest

from mtkgui.engine.uploader import (
    SharePointRestTransport,
    SharePointUploader,
    TransportError,
)

SITE = "https://nxp1.sharepoint.com"
ROOT = "/teams/ext158/BTD/Shared Documents/MTK Test Data"
ROOT_REF = "/teams/ext158/BTD/Shared%20Documents/MTK%20Test%20Data"
DIGEST_BODY = json.dumps({"d": {"GetContextWebInformation": {
    "FormDigestValue": "DIGEST-1"}}}).encode()


class Resp:
    def __init__(self, body: bytes = b"{}", status: int = 200):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        return self.handler(req)


def http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, f"http {code}", {}, None)


def transport(handler, **kwargs):
    opener = FakeOpener(handler)
    return SharePointRestTransport(SITE, opener=opener,
                                   folder_path=ROOT, **kwargs), opener


def ok_handler(req):
    if req.full_url.endswith("/_api/contextinfo"):
        return Resp(DIGEST_BODY)
    return Resp()


def test_put_posts_files_add_with_digest_and_returns_cloud_url():
    transport_, opener = transport(ok_handler)
    url = transport_.put("96317_report.zip", b"payload")
    assert url == f"{SITE}{ROOT}/96317_report.zip"
    add = [r for r in opener.requests
           if "/Files/add(" in r.full_url][0]
    assert f"/_api/web/GetFolderByServerRelativeUrl('{ROOT_REF}')" \
           "/Files/add(url='96317_report.zip',overwrite=true)" \
           in add.full_url
    assert add.get_method() == "POST"
    assert add.data == b"payload"
    assert add.get_header("X-requestdigest") == "DIGEST-1"
    assert add.get_header("Content-type") == "application/octet-stream"
    assert add.get_header("User-agent").startswith("Mozilla/5.0")


def test_digest_is_fetched_once_and_reused():
    transport_, opener = transport(ok_handler)
    transport_.put("a.csv", b"a")
    transport_.put("b.csv", b"b")
    context = [r for r in opener.requests
               if r.full_url.endswith("/_api/contextinfo")]
    assert len(context) == 1


def test_head_ignores_absolute_probe_and_hits_the_link_root():
    transport_, opener = transport(ok_handler)
    transport_.head(f"{SITE}/teams/ext158/BTD")   # engine precheck probe
    assert f"/_api/web/GetFolderByServerRelativeUrl('{ROOT_REF}')" \
           in opener.requests[0].full_url


def test_mkdirs_creates_each_missing_segment_and_tolerates_409():
    def handler(req):
        if "Folders/add" in req.full_url:
            raise http_error(req.full_url, 409)   # already exists
        return ok_handler(req)

    transport_, _unused = transport(handler)
    transport_.mkdirs("96317/reports")
    add = [r for r in transport_._opener.requests
           if "Folders/add" in r.full_url]
    assert len(add) == 2
    assert f"/_api/web/GetFolderByServerRelativeUrl('{ROOT_REF}')" \
           "/Folders/add('96317')" in add[0].full_url
    assert f"/_api/web/GetFolderByServerRelativeUrl('{ROOT_REF}" \
           "/96317')/Folders/add('reports')" in add[1].full_url
    # the cache keeps a repeated mkdirs off the wire
    transport_.mkdirs("96317/reports")
    assert len([r for r in transport_._opener.requests
                if "Folders/add" in r.full_url]) == 2


def test_precheck_ok_and_packaged_upload_through_the_uploader(tmp_path):
    transport_, _opener = transport(ok_handler)
    uploader = SharePointUploader(tmp_path / "outbox",
                                  state_dir=tmp_path / "state",
                                  transport=transport_)
    uploader.apply_config({"sharepoint": {
        "enabled": True, "site_url": f"{SITE}{ROOT}", "retry_count": 0}})
    assert uploader.precheck() == []
    payload = tmp_path / "report.csv"
    payload.write_text("a,b\n1,2\n", encoding="utf-8")
    result = uploader.upload_file(payload)
    assert result.status == "UPLOADED"
    assert result.url == f"{SITE}{ROOT}/report.csv"


def test_401_and_403_are_transport_errors():
    for code in (401, 403):
        transport_, _opener = transport(
            lambda req, code=code: (_ for _ in ()).throw(
                http_error(req.full_url, code)))
        with pytest.raises(TransportError) as exc:
            transport_.head()
        assert "not signed in" in str(exc.value)


def test_404_is_a_transport_error_bad_link():
    transport_, _opener = transport(
        lambda req: (_ for _ in ()).throw(http_error(req.full_url, 404)))
    with pytest.raises(TransportError) as exc:
        transport_.head()
    assert "not found" in str(exc.value)


def test_429_and_5xx_are_retryable_connection_errors():
    for code in (429, 500, 503, 504):
        transport_, _opener = transport(
            lambda req, code=code: (_ for _ in ()).throw(
                http_error(req.full_url, code)))
        with pytest.raises(ConnectionError):
            transport_.put("a.csv", b"x")


def test_network_failure_is_a_connection_error():
    def handler(req):
        raise urllib.error.URLError("no route to host")

    transport_, _opener = transport(handler)
    with pytest.raises(ConnectionError):
        transport_.head()


def test_missing_digest_is_reported():
    transport_, _opener = transport(
        lambda req: Resp(b"{}") if req.full_url.endswith(
            "/_api/contextinfo") else Resp())
    with pytest.raises(TransportError) as exc:
        transport_.put("a.csv", b"x")
    assert "form digest" in str(exc.value)


def test_current_user_title_and_login_name_fallback():
    title = json.dumps({"d": {"Title": "Jane Operator",
                             "LoginName": "i:0#.w|nxp\\jdoe"}}).encode()
    transport_, _opener = transport(lambda req: Resp(title))
    assert transport_.current_user() == "Jane Operator"

    login = json.dumps({"d": {"Title": "",
                             "LoginName": "i:0#.w|nxp\\jdoe"}}).encode()
    transport_2, _opener = transport(lambda req: Resp(login))
    assert transport_2.current_user() == "i:0#.w|nxp\\jdoe"

    transport_3, _opener = transport(lambda req: Resp(b"{}"))
    assert transport_3.current_user() == ""
