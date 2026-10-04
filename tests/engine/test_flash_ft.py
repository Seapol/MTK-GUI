# -*- coding: utf-8 -*-
"""Flash fault tolerance (P1 Task8): segmented timeouts, transient
retry, rollback, dual verify, forced release, taxonomy alignment."""
from __future__ import annotations

import pytest

from mtkgui.engine.failures import FailureKind, classify_exception
from mtkgui.engine.flash_ft import (FlashTolerance, FlashVerifyFailed,
                                    FlashWriteFailed)
from mtkgui.engine.instruments import RealGateway
from mtkgui.engine.slot_images import SlotImageRegistry
from tests.engine.conftest import scripted_drivers  # noqa: F401


def _ft(lines, retries=1):
    return FlashTolerance(retries=retries, log_fn=lines.append)


class TestPhases:
    def test_write_success_and_phase_trace(self):
        lines: list[str] = []
        ft = _ft(lines)
        out = ft.execute_write(lambda: 524288, SlotImageRegistry(),
                               "fat")
        assert out.ok and out.phase == "write"
        assert any("[FLASH_FT]" in line for line in lines)

    def test_timeout_overrun_flagged_not_fatal(self):
        lines: list[str] = []
        ft = FlashTolerance(retries=0, write_timeout_s=0.0000001,
                            log_fn=lines.append)
        out = ft.execute_write(lambda: 1, SlotImageRegistry(), "fat")
        assert out.ok and out.timed_out
        assert any("timeout budget" in line for line in lines)

    def test_transient_disconnect_retried_then_success(self):
        lines: list[str] = []
        ft = _ft(lines, retries=2)
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("usb link dropped")
            return 100

        out = ft.execute_write(flaky, SlotImageRegistry(), "fat")
        assert calls["n"] == 2 and out.ok
        assert any("transient disconnect" in line for line in lines)

    def test_retry_exhaustion_terminates_with_connection_error(self):
        lines: list[str] = []
        ft = _ft(lines, retries=1)

        def always_drop():
            raise ConnectionError("link gone")
        with pytest.raises(ConnectionError):
            ft.execute_write(always_drop, SlotImageRegistry(), "fat")
        assert any("retry budget exhausted" in line for line in lines)

    def test_write_failure_rolls_back_slot(self):
        lines: list[str] = []
        ft = _ft(lines, retries=0)
        reg = SlotImageRegistry()
        reg.mark_flashed("fat", "a" * 64)
        with pytest.raises(FlashWriteFailed):
            ft.execute_write(lambda: (_ for _ in ()).throw(
                RuntimeError("flash chip error")), reg, "fat")
        assert reg.is_dirty("fat")            # half-write never "flashed"
        assert reg.flashed_version("fat") == ""
        assert reg.should_flash("fat", "a" * 64)   # forces re-write
        assert any("rollback" in line for line in lines)

    def test_landing_verify_pass_and_fail(self):
        lines: list[str] = []
        ft = _ft(lines)
        reg = SlotImageRegistry()
        assert ft.execute_verify(lambda: "crc ok", reg, "fat").ok
        reg2 = SlotImageRegistry()
        with pytest.raises(FlashVerifyFailed):
            ft.execute_verify(lambda: (_ for _ in ()).throw(
                RuntimeError("crc mismatch")), reg2, "fat")
        assert reg2.is_dirty("fat")

    def test_verify_skipped_when_driver_has_no_hook(self):
        ft = _ft([])
        out = ft.execute_verify(None, SlotImageRegistry(), "fat")
        assert out.ok and out.detail == "skipped"

    def test_release_closes_and_never_raises(self):
        lines: list[str] = []
        ft = _ft(lines)

        class Drv:
            closed = False

            def close(self):
                self.closed = True
        d = Drv()
        ft.release(d)
        assert d.closed
        ft.release(BadClose())
        assert any("close failed" in line for line in lines)


class BadClose:
    def close(self):
        raise RuntimeError("handle stuck")


class TestTaxonomyAlignment:
    def test_retry_exhaustion_is_resource_branch(self):
        ev = classify_exception(ConnectionError("exhausted"))
        assert ev.kind is FailureKind.RESOURCE   # terminates the run

    def test_permanent_write_failure_is_engine_error_branch(self):
        ev = classify_exception(FlashWriteFailed(_phase()))
        assert ev.kind is FailureKind.ENGINE_ERROR


def _phase():
    from mtkgui.engine.flash_ft import PhaseOutcome
    return PhaseOutcome("write", ok=False, detail="chip error")


class TestGatewayIntegration:
    def _gw(self, config=None):
        return RealGateway(
            {"jlink": {"fields": {"Address": "/tmp/jlink"}}},
            config=config)

    def _flash(self, gw, tmp_path, monkeypatch):
        fdir = tmp_path / "firmware"
        fdir.mkdir()
        (fdir / "fat.bin").write_bytes(b"\xde\xad\xbe\xef")
        monkeypatch.chdir(tmp_path)
        return gw.execute_op("Flash FAT Firmware",
                             {"type": "flash", "slot": "fat",
                              "image": "firmware/fat.bin"})

    def test_happy_path_unchanged_with_ft_audit(self, tmp_path,
                                                monkeypatch,
                                                scripted_drivers):
        out = self._flash(self._gw(), tmp_path, monkeypatch)
        assert out.verdict == "Done"
        text = "\n".join(out.lines)
        assert "524288 bytes OK" in text
        assert "[FLASH_FT] driver handle closed" in text

    def test_transient_failure_retried_inside_gateway(
            self, tmp_path, monkeypatch, scripted_drivers):
        jlink_cls = scripted_drivers.JLinkDriver
        orig = jlink_cls.flash_firmware
        state = {"n": 0}

        def flaky(self, *a, **k):
            state["n"] += 1
            if state["n"] == 1:
                raise ConnectionError("first try drops")
            return type("R", (), {"value": 4})()

        jlink_cls.flash_firmware = flaky
        try:
            out = self._flash(self._gw({"firmware": {"retries": 1}}),
                              tmp_path, monkeypatch)
        finally:
            jlink_cls.flash_firmware = orig
        assert state["n"] == 2
        assert out.verdict == "Done"
        assert any("transient disconnect" in line
                   for line in out.lines)
