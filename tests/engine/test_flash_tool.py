# -*- coding: utf-8 -*-
"""Third-party flash tool CLI driver (R2 dual-path flash).

The tool profile (equipment.probes.device_params[<tool>]) drives the
third-party CLI tool in "auto" mode; the captured output keywords
decide the verdict.  All execution runs through a ScriptedExecutor -
the driver is never faked, only the executor (same pattern as the
RF drivers)."""
from __future__ import annotations

import pytest

from mtkgui.drivers.errors import InstrumentTimeoutError
from mtkgui.drivers.rf_common import CommandOutcome, ScriptedExecutor
from mtkgui.engine.flash_ft import (FlashVerifyFailed, FlashWriteFailed)
from mtkgui.engine.flash_tool import (ProgrammerProfile,
                                      judge_output, load_flash_profile,
                                      run_cli_flash)
from mtkgui.engine.instruments import RealGateway

EXE = "C:/Tools/JLink.exe"   # no spaces: ScriptedExecutor keys are
                             # space-joined token prefixes
OK_OUT = "Downloading file... [100%] O.K."


def _profile(**over) -> ProgrammerProfile:
    opts = {"exe": EXE, "device": "RT700", "interface": "SWD",
            "speed_khz": "4000", "write_cmd": "loadfile {image}",
            "verify_cmd": "verifyfile {image}", "reset_cmd": "r|g|exit",
            "ok_regex": r"O\.K\.", "verify_regex": r"O\.K\.",
            "fail_regex": "Error|FAILED", "timeout_s": "120"}
    opts.update(over)
    return ProgrammerProfile.from_options("J-Link", opts)


def _scripted(stdout: str = OK_OUT, returncode: int = 0) \
        -> ScriptedExecutor:
    return ScriptedExecutor({
        f"{EXE} loadfile": CommandOutcome(
            command=[EXE], returncode=returncode, stdout=stdout,
            stderr=""),
        f"{EXE} verifyfile": CommandOutcome(
            command=[EXE], returncode=returncode, stdout=stdout,
            stderr=""),
        f"{EXE} r|g|exit": CommandOutcome(
            command=[EXE], returncode=0, stdout="", stderr=""),
    })


# ------------------------------------------------------------ the profile
class TestProfile:
    def test_from_options_maps_every_field(self):
        p = _profile()
        assert p.exe == EXE
        assert p.device == "RT700"
        assert p.write_cmd == "loadfile {image}"
        assert p.ok_regex == r"O\.K\."
        assert p.timeout_s == 120.0

    def test_regex_accepts_list_or_string(self):
        """The editor writes a single string; hand-edited YAML may
        carry a list of alternatives - both load."""
        single = _profile(ok_regex="O\\.K\\.")
        assert single.ok_regex == r"O\.K\."
        multi = _profile(ok_regex=["Downloaded", "O\\.K\\."])
        assert multi.ok_regex == "Downloaded|O\\.K\\."

    def test_regex_list_with_junk_entries_is_tolerant(self):
        p = _profile(fail_regex=["Error", "", None])
        assert p.fail_regex == "Error"

    def test_bad_timeout_falls_back_to_default(self):
        assert _profile(timeout_s="abc").timeout_s == 120.0

    def test_command_substitutes_and_splits(self):
        argv = _profile().command("loadfile {image}", "fw/fat.bin")
        assert argv[0] == EXE
        assert argv[1:] == ["loadfile", "fw/fat.bin"]

    def test_command_carries_device_interface_speed(self):
        tpl = ("-device {device} -if {interface} -speed {speed_khz} "
               "loadfile {image}")
        argv = _profile(write_cmd=tpl).command(tpl, "fw/fat.bin")
        assert argv[1:] == ["-device", "RT700", "-if", "SWD",
                            "-speed", "4000", "loadfile", "fw/fat.bin"]


class TestLoadProfile:
    def test_none_without_block_or_tool(self):
        assert load_flash_profile({}, "J-Link") is None
        assert load_flash_profile({"probes": {}}, "J-Link") is None
        assert load_flash_profile(
            {"probes": {"device_params": {}}}, "J-Link") is None

    def test_none_without_executable(self):
        """No exe -> no CLI path (the legacy J-Link driver keeps
        running - backward compatible)."""
        assert load_flash_profile(
            {"probes": {"device_params":
                        {"J-Link": {"exe": ""}}}},
            "J-Link") is None

    def test_profile_loaded_from_equipment(self):
        p = load_flash_profile(
            {"probes": {"device_params": {"J-Link": {"exe": EXE}}}},
            "J-Link")
        assert p is not None and p.exe == EXE


# --------------------------------------------------------------- judging
class TestJudgeOutput:
    def test_ok_pattern_hit_passes(self):
        ok, reason = judge_output(OK_OUT, r"O\.K\.", "")
        assert ok and reason == ""

    def test_fail_pattern_hit_fails(self):
        ok, reason = judge_output("Cannot connect target",
                                  r"O\.K\.", "Cannot connect|Error")
        assert not ok and "Cannot connect" in reason

    def test_missing_ok_pattern_fails(self):
        ok, reason = judge_output("all done", r"O\.K\.", "")
        assert not ok and "not found" in reason

    def test_invalid_regex_fails_honestly(self):
        ok, reason = judge_output(OK_OUT, "O.K.(", "")
        assert not ok and "invalid" in reason


# ------------------------------------------------------------- CLI flash
class TestRunCliFlash:
    def test_success_runs_write_verify_reset(self):
        exe = _scripted()
        detail = run_cli_flash(_profile(), "fw/fat.bin",
                               executor=exe)
        assert detail == "CLI flash OK (J-Link)"
        assert len(exe.history) == 3
        assert exe.history[0] == [EXE, "loadfile", "fw/fat.bin"]
        assert exe.history[1] == [EXE, "verifyfile", "fw/fat.bin"]
        assert exe.history[2] == [EXE, "r|g|exit"]

    def test_flags_trim_the_command_sequence(self):
        exe = _scripted()
        run_cli_flash(_profile(), "fw/fat.bin", executor=exe,
                      verify=False, reset_run=False)
        assert len(exe.history) == 1

    def test_fail_keyword_rejects_the_write(self):
        exe = _scripted(stdout="Cannot connect target")
        with pytest.raises(FlashWriteFailed):
            run_cli_flash(_profile(), "fw/fat.bin", executor=exe)

    def test_missing_ok_keyword_rejects_the_write(self):
        exe = _scripted(stdout="downloaded, no keyword")
        with pytest.raises(FlashWriteFailed):
            run_cli_flash(_profile(), "fw/fat.bin", executor=exe)

    def test_verify_keyword_missing_fails_the_landing(self):
        exe = _scripted()
        exe.script[f"{EXE} verifyfile"] = CommandOutcome(
            command=[EXE], returncode=0, stdout="verify silent",
            stderr="")
        with pytest.raises(FlashVerifyFailed):
            run_cli_flash(_profile(), "fw/fat.bin", executor=exe)

    def test_reset_failure_is_non_blocking(self):
        """The image is already written and verified - a reset hiccup
        is logged, never raised (no slot rollback for a passed
        flash)."""
        exe = _scripted()
        exe.script[f"{EXE} r|g|exit"] = InstrumentTimeoutError("t")
        detail = run_cli_flash(_profile(), "fw/fat.bin",
                               executor=exe)
        assert detail == "CLI flash OK (J-Link)"

    def test_write_timeout_propagates_transient(self):
        """Executor timeout stays transient so the FlashTolerance
        retry budget (driver retries) applies."""
        exe = ScriptedExecutor({
            f"{EXE} loadfile": InstrumentTimeoutError("boom")})
        with pytest.raises(InstrumentTimeoutError):
            run_cli_flash(_profile(), "fw/fat.bin", executor=exe)


# ---------------------------------------------------- gateway integration
@pytest.fixture()
def fw_dir(tmp_path, monkeypatch):
    (tmp_path / "firmware").mkdir()
    (tmp_path / "firmware" / "fat.bin").write_bytes(b"\xde\xad\xbe\xef")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _gateway(**profile_over) -> RealGateway:
    opts = {"exe": EXE, "ok_regex": r"O\.K\.",
            "verify_regex": r"O\.K\.", "fail_regex": "Error|FAILED"}
    opts.update(profile_over)
    gw = RealGateway(
        {"probes": {"device_params": {"J-Link": opts}}})
    gw._flash_executor = _scripted()
    return gw


class TestGatewayCliPath:
    def test_auto_with_profile_runs_the_cli_tool(self, fw_dir):
        gw = _gateway()
        out = gw.execute_op(
            "Flash FAT Firmware",
            {"type": "flash", "slot": "fat",
             "image": "firmware/fat.bin", "mode": "auto",
             "tool": "J-Link"})
        assert out.verdict == "Done"
        assert any("CLI flash" in ln for ln in out.lines)
        assert any("[FLASH_TOOL]" in ln for ln in out.lines)

    def test_identical_image_is_reused_before_the_cli(self, fw_dir):
        """The slot registry gate runs BEFORE the CLI tool - a same-
        hash re-flash skips the third-party tool entirely."""
        gw = _gateway()
        step = {"type": "flash", "slot": "fat",
                "image": "firmware/fat.bin", "mode": "auto",
                "tool": "J-Link"}
        assert gw.execute_op("Flash FAT Firmware",
                             dict(step)).verdict == "Done"
        calls = len(gw._flash_executor.history)
        out = gw.execute_op("Flash FAT Firmware", dict(step))
        assert out.value == "reused"
        assert len(gw._flash_executor.history) == calls

    def test_fail_keyword_marks_the_slot_dirty(self, fw_dir):
        """A keyword-rejected write rolls the slot back - the next
        flash re-writes unconditionally (no half-flashed DUT)."""
        gw = _gateway(ok_regex=r"O\.K\.")
        gw._flash_executor = _scripted(stdout="Cannot connect target")
        step = {"type": "flash", "slot": "fat",
                "image": "firmware/fat.bin", "mode": "auto",
                "tool": "J-Link"}
        out = gw.execute_op("Flash FAT Firmware", dict(step))
        assert out.verdict == "Error"
        assert "write failed" in " | ".join(out.lines)
        assert gw._slot_registry.is_dirty("fat")

    def test_no_profile_falls_back_to_the_driver_path(self, fw_dir):
        """Without a tool profile the legacy J-Link driver path runs
        (here it fails honestly on the missing address - proving the
        CLI branch was NOT taken)."""
        gw = RealGateway({})
        gw._flash_executor = _scripted()
        out = gw.execute_op(
            "Flash FAT Firmware",
            {"type": "flash", "slot": "fat",
             "image": "firmware/fat.bin", "mode": "auto",
             "tool": "J-Link"})
        assert out.verdict == "Error"
        assert not any("CLI flash" in ln for ln in out.lines)
        assert gw._flash_executor.history == []
