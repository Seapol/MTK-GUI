# -*- coding: utf-8 -*-
"""M83 C15: the AP_PROFILE_* writer behind "Sync from Equipment...".

Only the ticked lines change; every other byte is kept.  A key with
zero or two declaration lines blocks the whole apply (nothing written),
a built-in target is refused verbatim, and a second apply is idempotent.
"""
from __future__ import annotations

from mtkgui.engine import assets_config as assets

SCRIPT = ("#!/bin/sh\n"
          "# comment line\n"
          "AP_PROFILE_ROUTER_SSID='old-router'\n"
          "AP_PROFILE_ROUTER_PASSWORD='old-router-pw'\n"
          "AP_PROFILE_HOTSPOT_SSID='old-hotspot'\n"
          "AP_PROFILE_HOTSPOT_PASSWORD='old-hotspot-pw'\n"
          "echo \"WIFI_CONNECTED_OK\"\n")


def _write(tmp_path, text: str = SCRIPT) -> str:
    path = tmp_path / "connect_wifi.sh"
    path.write_text(text, encoding="utf-8", newline="")
    return str(path)


def test_apply_keeps_every_other_byte(tmp_path):
    path = _write(tmp_path)
    written, in_sync, errors = assets.apply_ap_profile_values(
        path, {"AP_PROFILE_ROUTER_SSID": "eq-router"})
    assert (written, in_sync, errors) == (1, 0, [])
    assert open(path, encoding="utf-8", newline="").read() == SCRIPT.replace(
        "AP_PROFILE_ROUTER_SSID='old-router'",
        "AP_PROFILE_ROUTER_SSID='eq-router'")


def test_zero_or_two_matches_blocks_the_write(tmp_path):
    zero = _write(tmp_path, SCRIPT.replace("AP_PROFILE_ROUTER_SSID='", "# "))
    before = open(zero, encoding="utf-8", newline="").read()
    written, in_sync, errors = assets.apply_ap_profile_values(
        zero, {"AP_PROFILE_ROUTER_SSID": "eq-router"})
    assert written == 0 and in_sync == 0
    assert errors and "AP_PROFILE_ROUTER_SSID" in errors[0]
    assert "0 line(s)" in errors[0]
    assert open(zero, encoding="utf-8", newline="").read() == before

    twice = _write(tmp_path, SCRIPT + "AP_PROFILE_ROUTER_SSID='again'\n")
    before_twice = open(twice, encoding="utf-8", newline="").read()
    written, in_sync, errors = assets.apply_ap_profile_values(
        twice, {"AP_PROFILE_ROUTER_SSID": "eq-router"})
    assert written == 0 and in_sync == 0
    assert errors and "2 line(s)" in errors[0]
    assert open(twice, encoding="utf-8", newline="").read() == before_twice


def test_builtin_assets_target_is_refused(tmp_path, monkeypatch):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    path = builtin / "connect_wifi.sh"
    path.write_text(SCRIPT, encoding="utf-8", newline="")
    monkeypatch.setattr(assets, "builtin_assets_dir", lambda: str(builtin))
    written, in_sync, errors = assets.apply_ap_profile_values(
        str(path), {"AP_PROFILE_ROUTER_SSID": "eq-router"})
    assert (written, in_sync) == (0, 0)
    assert errors == [assets.BUILTIN_SYNC_REFUSED]
    assert errors[0] == ("built-in assets are read-only - create the "
                         "project assets first")
    assert open(path, encoding="utf-8", newline="").read() == SCRIPT


def test_second_apply_reports_already_in_sync(tmp_path):
    path = _write(tmp_path)
    updates = {"AP_PROFILE_ROUTER_SSID": "eq-router",
               "AP_PROFILE_ROUTER_PASSWORD": "eq-router-pw",
               "AP_PROFILE_HOTSPOT_SSID": "eq-hotspot",
               "AP_PROFILE_HOTSPOT_PASSWORD": "eq-hotspot-pw"}
    assert assets.apply_ap_profile_values(path, updates) == (4, 0, [])
    first = open(path, encoding="utf-8", newline="").read()
    assert assets.apply_ap_profile_values(path, updates) == (0, 4, [])
    assert open(path, encoding="utf-8", newline="").read() == first
