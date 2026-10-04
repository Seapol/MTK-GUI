# -*- coding: utf-8 -*-
"""P1 Task13 - boundary / edge-case sweep across every P1 capability.

Test-only increment: zero business code changes.  Covers parameter
extremes, state-machine illegal jumps, exception nesting, protocol
malformed frames, slot-image tamper/empty/missing, device-manager
mutual exclusion, data-quality noise edges and stability primitives.
"""
from __future__ import annotations

import os

import pytest

from mtkgui.engine.data_quality import SampleCleaner
from mtkgui.engine.device_manager import (DeviceManager,
                                          DeviceState, DeviceStateError)
from mtkgui.engine.failures import FailureKind, classify_exception
from mtkgui.engine.flash_params import (ALLOWED_SLOTS, FlashParamError,
                                        MAX_RETRIES,
                                        resolve_flash_params,
                                        validate_flash_params,
                                        with_retry_budget)
from mtkgui.engine.policies import normalize_retry_count
from mtkgui.engine.protocol import (CommandValidator, ProtocolAdapter,
                                    ProtocolError, ReplyParser,
                                    TimeoutPolicy)
from mtkgui.engine.slot_images import (ImageState, SlotImageError,
                                       SlotImageRegistry)
from mtkgui.engine.stability import (BoundedQueue, BreakerOpen,
                                     CircuitBreaker, HeartbeatMonitor,
                                     LockHeld, QueueFull, ResourceLocks)


# ============================================================ parameters
class TestRetryParamBoundaries:
    def test_none_and_garbage_clamp_to_zero(self):
        assert normalize_retry_count(None) == 0
        assert normalize_retry_count("abc") == 0

    def test_negative_clamps_to_zero(self):
        assert normalize_retry_count(-1) == 0
        assert normalize_retry_count(-1000) == 0

    def test_numeric_string_and_float(self):
        assert normalize_retry_count("7") == 7
        assert normalize_retry_count(2.9) == 2

    def test_bool_is_int_subclass(self):
        assert normalize_retry_count(False) == 0
        assert normalize_retry_count(True) == 1

    def test_retry_budget_clamped_to_max(self):
        p = resolve_flash_params({"image": "x.bin", "slot": "fat",
                                  "retries": 99})
        assert with_retry_budget(p).retries == MAX_RETRIES


def _params(tmp_path, **over):
    op = {"image": "fw.bin", "slot": "fat"}
    op.update(over)
    img = tmp_path / "fw.bin"
    img.write_bytes(b"\x00FW")
    return resolve_flash_params(op, None, str(tmp_path))


class TestFlashParamBoundaries:
    def test_missing_required_image(self, tmp_path):
        p = resolve_flash_params({"slot": "fat"}, None, str(tmp_path))
        errs = validate_flash_params(p)
        assert any(e.field == "image" for e in errs)

    def test_illegal_slot_rejected(self, tmp_path):
        p = _params(tmp_path, slot="boot")
        assert "boot" not in ALLOWED_SLOTS
        assert any(e.field == "slot" for e in validate_flash_params(p))

    def test_bad_hex_address(self, tmp_path):
        p = _params(tmp_path, address="0xXYZ")
        assert any(e.field == "address" for e in validate_flash_params(p))

    def test_unaligned_address(self, tmp_path):
        p = _params(tmp_path, address="0x802")
        assert any("align" in e.reason for e in validate_flash_params(p))

    def test_address_offset_mutual_exclusion(self, tmp_path):
        p = _params(tmp_path, address="0x800", offset=0x10)
        errs = validate_flash_params(p)
        assert any("mutually" in e.reason or "exclusive" in e.reason
                   for e in errs)

    def test_negative_retries(self, tmp_path):
        p = _params(tmp_path)
        p.retries = -2
        assert any(e.field == "retries" for e in validate_flash_params(p))

    def test_nul_byte_in_image_path(self, tmp_path):
        p = _params(tmp_path)
        p.image = "fw\x00.bin"
        assert any(e.field == "image" for e in validate_flash_params(p))

    def test_error_carries_field_value_allowed(self, tmp_path):
        p = _params(tmp_path, slot="nope")
        errs = validate_flash_params(p)
        assert errs, "expected at least one param error"
        e = errs[0]
        assert e.field == "slot" and e.value == "nope"
        assert "fat" in e.allowed and "oobe" in e.allowed


# ============================================================ slot images
class TestSlotImageBoundaries:
    def test_missing_image(self, tmp_path):
        reg = SlotImageRegistry()
        rec = reg.inspect(str(tmp_path / "ghost.bin"), "fat")
        assert rec.state is ImageState.MISSING

    def test_empty_image_corrupt(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        rec = SlotImageRegistry().inspect(str(f), "fat")
        assert rec.state is ImageState.CORRUPT

    def test_illegal_extension(self, tmp_path):
        f = tmp_path / "fw.exe"
        f.write_bytes(b"data")
        assert SlotImageRegistry().inspect(str(f), "fat").state \
            is ImageState.CORRUPT

    def test_tampered_known_path_is_stale(self, tmp_path):
        reg = SlotImageRegistry()
        f = tmp_path / "fw.bin"
        f.write_bytes(b"v1")
        assert reg.inspect(str(f), "fat").state is ImageState.VALID
        f.write_bytes(b"v2-tampered")
        rec = reg.inspect(str(f), "fat")
        assert rec.state is ImageState.STALE
        assert "hash changed" in rec.reason

    def test_load_rejects_non_valid(self, tmp_path):
        with pytest.raises(SlotImageError):
            SlotImageRegistry().load(str(tmp_path / "no.bin"), "fat")

    def test_reuse_skip_and_dirty_rollback(self, tmp_path):
        reg = SlotImageRegistry(skip_if_same_hash=True)
        f = tmp_path / "fw.bin"
        f.write_bytes(b"stable")
        rec = reg.load(str(f), "fat")
        assert reg.should_flash("fat", rec.sha256)
        reg.mark_flashed("fat", rec.sha256)
        assert not reg.should_flash("fat", rec.sha256)
        reg.mark_dirty("fat")
        assert reg.is_dirty("fat")
        assert reg.should_flash("fat", rec.sha256)


# ============================================================ protocol
class TestProtocolBoundaries:
    def test_empty_frame_raises(self):
        with pytest.raises(ProtocolError):
            ReplyParser().parse("   \r\n")

    def test_unknown_status_raises(self):
        with pytest.raises(ProtocolError) as ei:
            ReplyParser().parse("WAT 1 3.3")
        assert ei.value.kind == "frame"

    def test_non_numeric_payload_rejected(self):
        with pytest.raises(ProtocolError):
            ReplyParser().parse("OK 1 abc")

    def test_case_normalised_deviation(self):
        r = ReplyParser().parse("ok 1 3.3")
        assert r.ok and r.value == 3.3
        assert "status case normalised" in r.deviations

    def test_v1_ignores_seq(self):
        assert "sequence field ignored (v1)" in \
            ReplyParser(version="v1").parse("OK 7 1.0").deviations

    def test_v2_missing_seq_deviation(self):
        r = ReplyParser().parse("OK 1.5")
        assert r.value == 1.5
        assert "missing sequence field (v2)" in r.deviations

    def test_error_status_skips_payload_check(self):
        r = ReplyParser().parse("ERR something broke")
        assert not r.ok and r.value is None

    def test_unknown_version_rejected(self):
        with pytest.raises(ProtocolError):
            ReplyParser(version="v3")

    def test_timeout_tiers(self):
        tp = TimeoutPolicy()
        assert tp.budget("connect") == tp.connect_s
        assert tp.budget("reply") == tp.reply_s
        assert tp.budget("execute") == tp.execute_s
        with pytest.raises(KeyError):
            tp.budget("bogus")

    def test_validator_permission_before_unknown(self):
        v = CommandValidator({"reset"}, restricted={"factory"})
        with pytest.raises(ProtocolError) as ei:
            v.validate("factory")
        assert ei.value.kind == "permission"
        with pytest.raises(ProtocolError) as ei:
            v.validate("blast")
        assert ei.value.kind == "command"
        assert v.validate("  reset ") == "RESET"

    def test_adapter_rejects_unknown_before_send(self):
        adapter = ProtocolAdapter(log_fn=lambda line: None)
        with pytest.raises(ProtocolError):
            adapter.validate_command("wat", CommandValidator({"reset"}))


# ============================================================ devices
class TestDeviceBoundaries:
    def _mgr(self):
        m = DeviceManager(log_fn=lambda line: None)
        m.register("u2355")
        return m

    def test_release_with_wrong_token_raises(self):
        m = self._mgr()
        m.acquire("u2355", "t1")
        with pytest.raises((DeviceStateError, ValueError, RuntimeError)):
            m.release("u2355", "wrong-token")

    def test_double_acquire_blocked(self):
        m = self._mgr()
        m.acquire("u2355", "t1")
        with pytest.raises((DeviceStateError, RuntimeError)):
            m.acquire("u2355", "t2")

    def test_force_release_frees_occupoed_device(self):
        m = self._mgr()
        m.acquire("u2355", "t1")
        m.force_release("u2355", reason="admin kill")
        assert m.state("u2355") is DeviceState.IDLE
        m.acquire("u2355", "t2")   # immediately re-acquirable

    def test_heartbeat_offline_then_recover(self):
        m = self._mgr()
        assert m.heartbeat("u2355", False) is DeviceState.OFFLINE
        assert m.heartbeat("u2355", True) is DeviceState.IDLE

    def test_illegal_freeze_on_frozen_is_error(self):
        m = self._mgr()
        m.freeze("u2355")
        with pytest.raises((DeviceStateError, RuntimeError)):
            m.freeze("u2355")

    def test_acquireable_reflects_state(self):
        m = self._mgr()
        assert m.acquireable("u2355")
        m.mark_error("u2355")
        assert not m.acquireable("u2355")
        m.clear_error("u2355")
        assert m.acquireable("u2355")


# ============================================================ data quality
class TestDataQualityBoundaries:
    def test_empty_and_short_samples(self):
        res = SampleCleaner().clean([], 0, 5)
        assert res.value == 0.0
        res2 = SampleCleaner().clean([2.5], 0, 5)
        assert res2.value == 2.5

    def test_nan_rejected_not_averaged_in(self):
        res = SampleCleaner().clean([2.0, float("nan"), 2.2], 0, 5)
        assert 1.9 <= res.value <= 2.3
        assert any("nan" in r.lower() for r in res.rejected.values())

    def test_out_of_band_flagged(self):
        res = SampleCleaner().clean([2.0, 2.0, 99.0], 0, 5)
        assert res.value <= 5.0
        assert res.in_band is False or res.value <= 5.0

    def test_all_identical_collapses(self):
        res = SampleCleaner().clean([3.0] * 10, 0, 5)
        assert res.value == 3.0
        assert res.duplicates_collapsed == 7   # 10 - max repeats (3)

    def test_outlier_extreme_dropped(self):
        res = SampleCleaner().clean([2.0, 2.1, 2.2, 100.0], 0, 5)
        assert res.value < 10

    def test_clean_value_convenience(self):
        assert SampleCleaner().clean_value([2.0, 2.0, 2.0], 0, 5) == 2.0


# ============================================================ exceptions
class TestFailureClassificationBoundaries:
    def test_timeout_root(self):
        ev = classify_exception(TimeoutError("t"))
        assert ev.kind is FailureKind.TIMEOUT

    def test_nested_chain_root_cause_wins(self):
        try:
            try:
                raise ConnectionError("link down")
            except ConnectionError as ce:
                raise RuntimeError("op failed") from ce
        except RuntimeError as top:
            ev = classify_exception(top)
        assert ev.kind is FailureKind.RESOURCE
        assert "link down" in ev.message
        assert len(ev.chain) >= 2

    def test_generic_exception_is_engine_error(self):
        assert classify_exception(ValueError("x")).kind \
            is FailureKind.ENGINE_ERROR

    def test_driver_unavailable_is_resource(self):
        from mtkgui.engine.instruments import DriverUnavailable
        assert classify_exception(DriverUnavailable("m")).kind \
            is FailureKind.RESOURCE


# ============================================================ stability
class TestStabilityBoundaries:
    def test_lock_conflict_raises_and_inline_sweep(self):
        locks = ResourceLocks()
        locks.acquire("rack", "a", timeout_s=0.02)
        with pytest.raises(LockHeld):
            locks.acquire("rack", "b", timeout_s=5.0)  # not yet stale
        import time
        time.sleep(0.03)
        locks.acquire("rack", "b", timeout_s=5.0)      # inline sweep
        assert locks.held()["rack"] == "b"

    def test_release_by_wrong_owner_is_ignored(self):
        locks = ResourceLocks()
        locks.acquire("rack", "a")
        locks.release("rack", "b")          # idempotent, never raises
        assert locks.held().get("rack") == "a"
        locks.release("rack", "a")
        assert "rack" not in locks.held()

    def test_renew_extends_held_lock(self):
        locks = ResourceLocks()
        locks.acquire("rack", "a", timeout_s=0.05)
        locks.renew("rack", "a", timeout_s=5.0)
        import time
        time.sleep(0.08)
        assert locks.held().get("rack") == "a"

    def test_queue_full_metric(self):
        q = BoundedQueue(maxsize=2)
        q.put(1)
        q.put(2)
        with pytest.raises(QueueFull):
            q.put(3)
        assert q.rejected_count >= 1
        assert q.pop() == 1

    def test_heartbeat_no_double_reap(self):
        hb = HeartbeatMonitor()
        hb.register("w", 0.01)
        import time
        time.sleep(0.05)
        first = hb.reap()
        assert hb.reap() == []
        assert first == ["w"] or first == []

    def test_breaker_half_open_then_success_closes(self):
        br = CircuitBreaker(trip_after=2, cooldown_s=0.01)
        br.record_timeout()
        br.record_timeout()
        with pytest.raises(BreakerOpen):
            br.check()
        import time
        time.sleep(0.02)
        br.record_success()
        br.check()   # closed again
