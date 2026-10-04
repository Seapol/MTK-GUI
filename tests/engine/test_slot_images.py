# -*- coding: utf-8 -*-
"""Slot image registry (P1 Task7): four states, SHA-256 fingerprint,
tamper detection, reuse decision, gateway interception."""
from __future__ import annotations

import pytest

from mtkgui.engine.failures import FailureKind, classify_exception
from mtkgui.engine.instruments import RealGateway
from mtkgui.engine.slot_images import (ImageState, SlotImageError,
                                       SlotImageRegistry)
from tests.engine.conftest import scripted_drivers  # noqa: F401


@pytest.fixture()
def img(tmp_path, monkeypatch):
    fdir = tmp_path / "firmware"
    fdir.mkdir()
    path = fdir / "fat.bin"
    path.write_bytes(b"\xde\xad\xbe\xef" * 1024)
    monkeypatch.chdir(tmp_path)
    return path


def _gw(config=None):
    return RealGateway({"jlink": {"fields": {"Address": "/tmp/jlink"}}},
                       config=config)


class TestStates:
    def test_valid_image(self, img):
        rec = SlotImageRegistry().inspect(str(img), "fat")
        assert rec.state is ImageState.VALID and rec.size > 0
        assert len(rec.sha256) == 64
        assert "[SLOT_IMG]" in "\n".join(rec.log_lines())

    def test_missing_image(self, tmp_path):
        rec = SlotImageRegistry().inspect(str(tmp_path / "nope.bin"))
        assert rec.state is ImageState.MISSING

    def test_empty_image_is_corrupt(self, tmp_path):
        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        rec = SlotImageRegistry().inspect(str(p))
        assert rec.state is ImageState.CORRUPT
        assert "empty" in rec.reason

    def test_illegal_extension_is_corrupt(self, tmp_path):
        p = tmp_path / "fw.exe"
        p.write_bytes(b"data")
        assert SlotImageRegistry().inspect(str(p)).state is \
            ImageState.CORRUPT

    def test_unreadable_is_corrupt(self, img):
        class Boom:
            def __getattribute__(self, name):
                if name == "stat":
                    raise OSError("io error")
                return object.__getattribute__(self, name)
        rec = SlotImageRegistry().inspect(str(img) + "\x00x", "fat")
        assert rec.state is ImageState.MISSING   # NUL path -> not a file


class TestFingerprintAndTamper:
    def test_tampered_image_detected_as_stale(self, img):
        reg = SlotImageRegistry()
        first = reg.inspect(str(img), "fat")
        assert first.state is ImageState.VALID
        img.write_bytes(b"tampered" * 512)       # same name, new package
        second = reg.inspect(str(img), "fat")
        assert second.state is ImageState.STALE
        assert "hash changed" in second.reason
        with pytest.raises(SlotImageError):
            reg.load(str(img), "fat")

    def test_same_name_different_package_unique_hash(self, img):
        reg = SlotImageRegistry()
        h1 = reg.inspect(str(img), "fat").sha256
        img.write_bytes(b"\x00" * 4096)
        reg.inspect(str(img), "fat")             # updates known hash
        h2 = reg.inspect(str(img), "fat").sha256
        assert h1 != h2

    def test_load_valid_returns_record(self, img):
        rec = SlotImageRegistry().load(str(img), "fat")
        assert rec.state is ImageState.VALID


class TestReuse:
    def test_should_flash_and_mark(self, img):
        reg = SlotImageRegistry()
        rec = reg.inspect(str(img), "fat")
        assert reg.should_flash("fat", rec.sha256)
        reg.mark_flashed("fat", rec.sha256)
        assert not reg.should_flash("fat", rec.sha256)  # same version
        assert reg.should_flash("oobe", rec.sha256)     # other slot
        assert reg.flashed_version("fat") == rec.sha256


class TestTaxonomyLink:
    def test_slot_image_error_is_engine_error_branch(self, img):
        reg = SlotImageRegistry()
        reg.inspect(str(img), "fat")
        img.write_bytes(b"x")                    # tamper
        rec = reg.inspect(str(img), "fat")
        ev = classify_exception(SlotImageError(rec))
        assert ev.kind is FailureKind.ENGINE_ERROR


class TestGatewayIntercept:
    def test_bad_image_never_reaches_driver(self, tmp_path, monkeypatch,
                                            scripted_drivers):
        (tmp_path / "firmware").mkdir()
        (tmp_path / "firmware" / "fat.bin").write_bytes(b"")
        monkeypatch.chdir(tmp_path)
        gw = _gw()
        out = gw.execute_op("Flash FAT Firmware",
                            {"type": "flash", "slot": "fat",
                             "image": "firmware/fat.bin"})
        assert out.verdict == "Error"
        assert "slot image rejected" in " ".join(out.lines)
        assert "empty" in " ".join(out.lines)
        assert not any(c[0] == "flash"
                       for c in scripted_drivers._record.calls)

    def test_valid_image_flashes_with_slot_img_audit(self, tmp_path,
                                                     monkeypatch,
                                                     scripted_drivers):
        fdir = tmp_path / "firmware"
        fdir.mkdir()
        (fdir / "fat.bin").write_bytes(b"\xde\xad\xbe\xef")
        monkeypatch.chdir(tmp_path)
        gw = _gw()
        out = gw.execute_op("Flash FAT Firmware",
                            {"type": "flash", "slot": "fat",
                             "image": "firmware/fat.bin"})
        assert out.verdict == "Done"
        assert "state=VALID" in "\n".join(out.lines)
        assert any(c[0] == "flash"
                   for c in scripted_drivers._record.calls)

    def test_reuse_skips_second_write(self, tmp_path, monkeypatch,
                                      scripted_drivers):
        fdir = tmp_path / "firmware"
        fdir.mkdir()
        (fdir / "fat.bin").write_bytes(b"\xde\xad\xbe\xef")
        monkeypatch.chdir(tmp_path)
        gw = _gw({"firmware": {"skip_if_same_hash": True}})
        op = {"type": "flash", "slot": "fat",
              "image": "firmware/fat.bin"}
        assert gw.execute_op("Flash FAT Firmware", dict(op)).verdict \
            == "Done"
        flashes = [c for c in scripted_drivers._record.calls
                   if c[0] == "flash"]
        second = gw.execute_op("Flash FAT Firmware", dict(op))
        assert second.verdict == "Done" and second.value == "reused"
        assert len([c for c in scripted_drivers._record.calls
                    if c[0] == "flash"]) == len(flashes)  # no re-write
