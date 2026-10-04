# -*- coding: utf-8 -*-
"""Flash parameter model + validation (P1 Task6): structure, full
legality checks, priority/override, precise rejection, [FLASH_PARAM]
trace lines and gateway interception."""
from __future__ import annotations

import pytest

from mtkgui.engine.failures import FailureKind, classify_exception
from mtkgui.engine.flash_params import (DEFAULT_BAUDRATE_KHZ,
                                        DEFAULT_TIMEOUT_S,
                                        FlashParamError, FlashParams,
                                        flash_param_log_lines,
                                        resolve_flash_params,
                                        validate_flash_params,
                                        with_retry_budget)
from mtkgui.engine.instruments import RealGateway
from tests.engine.conftest import make_config

from tests.engine.conftest import scripted_drivers  # noqa: F401


@pytest.fixture()
def fw_dir(tmp_path, monkeypatch):
    """A directory containing one legal firmware image; the test CWD."""
    (tmp_path / "firmware").mkdir()
    (tmp_path / "firmware" / "fat.bin").write_bytes(b"\xde\xad\xbe\xef")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _good(**over) -> FlashParams:
    p = resolve_flash_params({"type": "flash", "slot": "fat",
                              "image": "firmware/fat.bin"})
    for k, v in over.items():
        setattr(p, k, v)
    return p


# ------------------------------------------------------------- resolution
class TestResolution:
    def test_step_params_win_over_config(self):
        config = {"firmware": {"fat_image": "cfg/fat.bin",
                               "baudrate": 2000}}
        p = resolve_flash_params(
            {"slot": "fat", "image": "step/fat.bin",
             "baudrate": 8000}, config)
        assert p.image == "step/fat.bin"
        assert p.sources["image"] == "step"
        assert p.baudrate_khz == 8000 and p.sources["baudrate_khz"] == "step"

    def test_config_wins_over_defaults(self):
        config = {"firmware": {"fat_image": "cfg/fat.bin",
                               "timeout_s": 120.0,
                               "encrypt": True}}
        p = resolve_flash_params({"slot": "fat"}, config)
        assert p.image == "cfg/fat.bin" and p.sources["image"] == "config"
        assert p.timeout_s == 120.0 and p.sources["timeout_s"] == "config"
        assert p.encrypt is True and p.sources["encrypt"] == "config"

    def test_engine_defaults_when_nothing_given(self):
        p = resolve_flash_params({"slot": "fat"})
        assert p.baudrate_khz == DEFAULT_BAUDRATE_KHZ
        assert p.timeout_s == DEFAULT_TIMEOUT_S
        assert p.verify is True and p.encrypt is False
        assert all(s == "default" for k, s in p.sources.items()
                   if k in ("baudrate_khz", "timeout_s", "verify",
                            "encrypt"))

    def test_all_fields_hosted(self, fw_dir):
        p = _good(address="0x60000000", baudrate_khz=12000,
                  timeout_s=90.0, retries=2, encrypt=True)
        errors = validate_flash_params(p)
        assert errors == []
        assert p.sources["address"] == "default"  # set post-resolve


# ------------------------------------------------------------- validation
class TestValidation:
    def test_valid_params_pass(self, fw_dir):
        assert validate_flash_params(_good()) == []

    def test_empty_image_rejected(self):
        errors = validate_flash_params(resolve_flash_params({}))
        assert any(e.field == "image" and "empty" in e.reason
                   for e in errors)

    def test_missing_file_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)          # no firmware/ here
        errors = validate_flash_params(_good())
        assert any(e.field == "image" and "does not exist" in e.reason
                   for e in errors)

    def test_illegal_extension_rejected(self, fw_dir):
        errors = validate_flash_params(_good(image="firmware/fat.exe"))
        assert any(e.field == "image" and "extension" in e.reason
                   for e in errors)

    def test_base_dir_join_for_relative_image(self, fw_dir):
        p = _good()
        p.base_dir = str(fw_dir)
        (fw_dir / "firmware" / "fat.bin").exists()
        assert validate_flash_params(p) == []

    def test_address_format_and_alignment(self, fw_dir):
        assert validate_flash_params(
            _good(address="0x60000000")) == []
        bad_fmt = validate_flash_params(_good(address="60000000"))
        assert any(e.field == "address" and "format" in e.reason
                   for e in bad_fmt)
        bad_align = validate_flash_params(_good(address="0x60000002"))
        assert any(e.field == "address" and "aligned" in e.reason
                   for e in bad_align)

    def test_address_offset_mutually_exclusive(self, fw_dir):
        errors = validate_flash_params(
            _good(address="0x60000000", offset=16))
        assert any("mutually exclusive" in e.reason for e in errors)

    def test_offset_range(self, fw_dir):
        errors = validate_flash_params(_good(offset=-1))
        assert any(e.field == "offset" for e in errors)
        assert validate_flash_params(_good(offset=0x100)) == []

    def test_numeric_ranges(self, fw_dir):
        for over, field in (({"baudrate_khz": 0}, "baudrate_khz"),
                            ({"baudrate_khz": 200000}, "baudrate_khz"),
                            ({"timeout_s": 0.0}, "timeout_s"),
                            ({"timeout_s": 601.0}, "timeout_s"),
                            ({"retries": 6}, "retries"),
                            ({"retries": -1}, "retries")):
            errors = validate_flash_params(_good(**over))
            assert any(e.field == field for e in errors), over

    def test_boolean_flags_type_checked(self, fw_dir):
        errors = validate_flash_params(_good(verify="yes"))
        assert any(e.field == "verify" and "boolean" in e.reason
                   for e in errors)

    def test_illegal_slot_rejected(self, fw_dir):
        p = _good()
        p.slot = "main"
        errors = validate_flash_params(p)
        assert any(e.field == "slot" for e in errors)

    def test_error_message_carries_field_value_allowed(self, fw_dir):
        errors = validate_flash_params(_good(baudrate_khz=0))
        e = errors[0]
        assert e.field == "baudrate_khz" and e.value == 0
        assert "1 .. 100000 kHz" in e.allowed
        assert "baudrate_khz" in str(e)

    def test_retry_budget_clamped(self):
        assert with_retry_budget(FlashParams(retries=99)).retries == 5
        assert with_retry_budget(FlashParams(retries=-3)).retries == 0


# ------------------------------------------------------------------ trace
class TestTraceability:
    def test_log_lines_show_sources_and_result(self, fw_dir):
        config = {"firmware": {"baudrate": 8000}}
        p = resolve_flash_params({"slot": "fat",
                                  "image": "firmware/fat.bin"}, config)
        lines = flash_param_log_lines(p, validate_flash_params(p))
        text = "\n".join(lines)
        assert text.count("[FLASH_PARAM]") >= 12
        assert "baudrate_khz=8000 (source=config)" in text
        assert "verify=True (source=default)" in text
        assert "image='firmware/fat.bin' (source=step)" in text
        assert "validation: PASS" in text

    def test_log_lines_show_validation_fail(self):
        lines = flash_param_log_lines(FlashParams(), [FlashParamError(
            "image", "", "must not be empty", "a path")])
        assert any("VALIDATION FAIL" in line for line in lines)


# ------------------------------------------------- failure taxonomy link
class TestTaxonomyLink:
    def test_flash_param_error_is_engine_error_branch(self):
        ev = classify_exception(FlashParamError("image", "", "empty",
                                                "path"))
        assert ev.kind is FailureKind.ENGINE_ERROR   # freeze + alarm


# ------------------------------------------------------ gateway intercept
class TestGatewayIntercept:
    def _gw(self, config=None):
        """Gateway over the scripted stub drivers (request the
        `scripted_drivers` fixture in each test to activate it)."""
        return RealGateway(
            {"jlink": {"fields": {"Address": "/tmp/jlink"}}},
            config=config)

    def test_illegal_param_never_reaches_driver(self, tmp_path,
                                                monkeypatch,
                                                scripted_drivers):
        (tmp_path / "firmware").mkdir()
        monkeypatch.chdir(tmp_path)          # image missing on purpose
        gw = self._gw()
        out = gw.execute_op("Flash FAT Firmware",
                            {"type": "flash", "slot": "fat",
                             "image": "firmware/fat.bin"})
        assert out.verdict == "Error"        # intercepted early
        assert "flash parameters rejected" in " ".join(out.lines)
        assert "does not exist" in " ".join(out.lines)
        # the stub driver was never asked to flash
        assert not any(c[0] == "flash"
                       for c in scripted_drivers._record.calls)

    def test_valid_param_flashes_and_traces(self, fw_dir,
                                            scripted_drivers):
        gw = self._gw({"firmware": {"baudrate": 8000}})
        out = gw.execute_op("Flash FAT Firmware",
                            {"type": "flash", "slot": "fat",
                             "image": "firmware/fat.bin"})
        assert out.verdict == "Done"
        text = "\n".join(out.lines)
        assert "bytes OK" in text
        assert "[FLASH_PARAM]" in text and "validation: PASS" in text

    def test_config_image_used_when_step_gives_none(self, fw_dir,
                                                    scripted_drivers):
        gw = self._gw({"firmware": {"fat_image": "firmware/fat.bin"}})
        out = gw.execute_op("Flash FAT Firmware",
                            {"type": "flash", "slot": "fat"})
        assert out.verdict == "Done"
        assert any("source=config" in line for line in out.lines)
