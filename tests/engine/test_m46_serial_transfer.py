# -*- coding: utf-8 -*-
"""M46: Serial Push / Pull steps + hardened serial transport.

Covers the combined-document §5 assertions:

* chunked base64 + ACK protocol against a mocked console channel;
* baud negotiation round trip (raise -> transfer -> BOTH sides restored)
  and an EXPLICIT failure when a side cannot be restored;
* the read-only transfer-time estimate;
* Push Browse default (current project ``assets/``, bundled template
  fallback) and the row -> step mapping (no legacy "deploy" residue);
* transport hardening: quiet window, marker framing with interleaved
  console output, echo verify retry then explicit FAIL, throttle.
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from mtkgui.engine import serial_transfer as st
from mtkgui.engine import serial_transport as stp
from mtkgui.engine.fct_test_config import (
    KIND_SERIAL_PULL,
    KIND_SERIAL_PUT,
    STEP_EXTERNAL_TOOL,
    STEP_TYPE_SERIAL_PULL,
    STEP_TYPE_SERIAL_PUT,
    ConsoleCommand,
    default_assets_dir,
    _console_row_steps,
    console_command_for_label,
)


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------
class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, sec: float) -> None:
        self.t += max(float(sec), 0.001)


class FakeChannel:
    """Console channel driven by regex -> response callables."""

    kind = "serial"

    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or Clock()
        self.written: list = []
        self._lines: list = []
        self.responders: list = []
        self.baud_changes: list = []
        self.fail_baud: set = set()
        self.fail_write: str = ""

    # -- channel API ---------------------------------------------------
    def write(self, text: str) -> None:
        if self.fail_write and re.search(self.fail_write, text):
            raise RuntimeError(f"write failed: {text.strip()}")
        self.written.append(text)
        for pattern, make in self.responders:
            m = re.search(pattern, text)
            if m is not None:
                self._lines.extend(make(m))

    def read_lines(self, max_lines: int = 200, timeout_s: float = 0.0) -> list:
        out = self._lines[:max_lines]
        del self._lines[:len(out)]
        return out

    def set_baudrate(self, baud: int) -> bool:
        if int(baud) in self.fail_baud:
            return False
        self.baud_changes.append(int(baud))
        return True

    def push_lines(self, *lines: str) -> None:
        self._lines.extend(lines)


def _push_channel(clock: Clock, size: int, *, fail_baud=(),
                  confirm_restore=True) -> FakeChannel:
    ch = FakeChannel(clock)
    ch.fail_baud = set(fail_baud)

    def ack(m):
        return [f"ACK {m.group(1)}"]

    def done(m):
        return [f"PUT_OK {size}"]

    def baud_ok(m):
        rate = int(m.group(1))
        if rate == 115200 and not confirm_restore:
            return []
        return [f"BAUD_OK {rate}"]

    ch.responders = [
        (r"^PUT_CHUNK (\d+) ", ack),
        (r"^PUT_DONE", done),
        (r"^echo BAUD_OK (\d+)", baud_ok),
    ]
    return ch


# ---------------------------------------------------------------------------
# §1 row -> step mapping
# ---------------------------------------------------------------------------
def test_serial_rows_map_to_external_tool_steps():
    for label in (STEP_TYPE_SERIAL_PUT, STEP_TYPE_SERIAL_PULL):
        cmd = console_command_for_label(label, label)
        steps = _console_row_steps(cmd, "console_serial")
        assert len(steps) == 1
        step = steps[0]
        assert step.step_type == STEP_EXTERNAL_TOOL
        assert step.channel == "console_serial"
        spec = step.params["fct_serial_transfer"]
        assert spec["direction"] == ("push"
                                    if cmd.kind == KIND_SERIAL_PUT
                                    else "pull")
        assert spec["remote"] == "/root/"
        assert spec["baud"] == 0
        assert spec["console_baud"] == 115200
        assert step.timeout_s == 600.0


def test_row_round_trip_keeps_serial_baud_and_no_deploy_residue():
    cmd = ConsoleCommand(kind=KIND_SERIAL_PUT, name="push",
                         local="/tmp/src", remote="/root/",
                         serial_baud=921600, timeout=600.0)
    data = cmd.to_dict()
    assert data["serial_baud"] == 921600
    assert "deploy" not in data
    back = ConsoleCommand._from_dict_v2(data)
    assert back.serial_baud == 921600


def test_legacy_console_rows_gain_no_deploy_or_transfer():
    legacy = {"kind": "send", "name": "uname", "send": "uname -r"}
    cmd = ConsoleCommand._from_dict_v2(legacy)
    assert cmd.serial_baud == 0
    assert "deploy" not in cmd.to_dict()
    steps = _console_row_steps(cmd, "console_serial")
    assert all("fct_serial_transfer" not in s.params for s in steps)


# ---------------------------------------------------------------------------
# §1 Push / Pull protocol
# ---------------------------------------------------------------------------
def test_push_chunked_ack_protocol(tmp_path):
    clock = Clock()
    payload = b"A" * 700
    local = tmp_path / "blob.bin"
    local.write_bytes(payload)
    ch = _push_channel(clock, len(payload))
    progress: list = []
    result = st.push_file(ch, str(local), "/root/blob.bin", log=None,
                          progress=lambda d, t, n: progress.append((d, t)),
                          sleep=clock.sleep, now=clock.now)
    assert result["bytes"] == len(payload)
    chunks = [w for w in ch.written if w.startswith("PUT_CHUNK ")]
    assert len(chunks) == len(st._split_b64(payload))
    assert chunks[0].startswith("PUT_CHUNK 1 ")
    assert any(w.startswith("PUT_DONE") for w in ch.written)
    # the receiver shell is busybox-compatible (base64 -d / wc / rm)
    receiver = next(w for w in ch.written if w.startswith("rm -f "))
    assert "base64 -d" in receiver and "wc -c" in receiver
    assert progress and progress[-1][0] == len(payload)


def test_push_size_mismatch_is_an_explicit_failure(tmp_path):
    clock = Clock()
    local = tmp_path / "blob.bin"
    local.write_bytes(b"x" * 10)
    ch = _push_channel(clock, 5)          # DUT reports the wrong size
    with pytest.raises(st.SerialTransferError) as exc:
        st.push_file(ch, str(local), "/root/blob.bin",
                     sleep=clock.sleep, now=clock.now)
    assert "size mismatch" in str(exc.value)


def test_pull_writes_the_file_and_acks_every_chunk(tmp_path):
    clock = Clock()
    data = b"hello world"
    b64 = base64.b64encode(data).decode()
    ch = FakeChannel(clock)

    def script(m):
        assert "PULL_CHUNK" in m.string
        return [f"PULL_START {len(data)}", f"PULL_CHUNK 1 {b64}",
                f"PULL_OK {len(data)}"]

    ch.responders = [(r"S=.*PULL_START", script)]
    dest = tmp_path / "out" / "hello.txt"
    result = st.pull_file(ch, "/root/hello.txt", str(dest),
                          sleep=clock.sleep, now=clock.now)
    assert dest.read_bytes() == data
    assert result["bytes"] == len(data)
    assert "ACK 1\n" in ch.written
    assert "base64" in next(w for w in ch.written if "PULL_START" in w)


# ---------------------------------------------------------------------------
# §1 baud negotiation + restore
# ---------------------------------------------------------------------------
def test_baud_round_trip_raises_then_restores_both_sides(tmp_path):
    clock = Clock()
    payload = b"B" * 20
    local = tmp_path / "blob.bin"
    local.write_bytes(payload)
    ch = _push_channel(clock, len(payload))
    st.push_file(ch, str(local), "/root/blob.bin", baud=921600,
                 console_baud=115200, sleep=clock.sleep, now=clock.now)
    # Host port: up to 921600 then back to 115200
    assert ch.baud_changes == [921600, 115200]
    dut = [w.strip() for w in ch.written]
    assert "stty 921600" in dut
    assert dut[-2].startswith("echo BAUD_OK 115200") or \
        "stty 115200" in dut
    assert "stty 115200" in dut


def test_host_restore_failure_is_an_explicit_error(tmp_path):
    clock = Clock()
    local = tmp_path / "blob.bin"
    local.write_bytes(b"C" * 20)
    ch = _push_channel(clock, 20, fail_baud={115200})
    with pytest.raises(st.SerialTransferError) as exc:
        st.push_file(ch, str(local), "/root/blob.bin", baud=921600,
                     console_baud=115200, sleep=clock.sleep, now=clock.now)
    assert "restore to 115200 failed on the Host PC" in str(exc.value)


def test_unconfirmed_dut_restore_is_an_explicit_error(tmp_path):
    clock = Clock()
    local = tmp_path / "blob.bin"
    local.write_bytes(b"D" * 20)
    ch = _push_channel(clock, 20, confirm_restore=False)
    with pytest.raises(st.SerialTransferError) as exc:
        st.push_file(ch, str(local), "/root/blob.bin", baud=921600,
                     console_baud=115200, sleep=clock.sleep, now=clock.now)
    assert "not confirmed" in str(exc.value)


def test_baud_switch_needs_channel_support(tmp_path):
    clock = Clock()
    local = tmp_path / "blob.bin"
    local.write_bytes(b"E" * 20)
    ch = _push_channel(clock, 20)
    ch.set_baudrate = None            # channel without baud control
    with pytest.raises(st.SerialTransferError) as exc:
        st.push_file(ch, str(local), "/root/blob.bin", baud=921600,
                     console_baud=115200, sleep=clock.sleep, now=clock.now)
    assert "does not support baud control" in str(exc.value)


# ---------------------------------------------------------------------------
# §1 estimate + Browse default
# ---------------------------------------------------------------------------
def test_estimate_and_format_duration():
    assert st.estimate_seconds(0, 115200) == 0.0
    assert st.estimate_seconds(115200, 115200) == pytest.approx(13.0)
    assert st.estimate_text(100000, 921600) == "1 s"
    assert st.format_duration(0.4) == "<1 s"
    assert st.format_duration(59) == "59 s"
    assert st.format_duration(320) == "5 min 20 s"
    assert st.format_duration(3900) == "1 h 5 min"


def test_dir_size_counts_a_tree(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.bin").write_bytes(b"1" * 10)
    (tmp_path / "b.bin").write_bytes(b"2" * 5)
    assert st.dir_size(str(tmp_path)) == 15
    assert st.dir_size(str(tmp_path / "b.bin")) == 5
    assert st.dir_size(str(tmp_path / "missing")) == 0


def test_browse_default_prefers_project_assets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "projects" / "P1" / "assets").mkdir(parents=True)
    path, hint = default_assets_dir("P1", "projects")
    assert path == str(Path("projects") / "P1" / "assets")
    assert hint == ""


def test_browse_default_falls_back_to_bundled_template(tmp_path,
                                                       monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "assets").mkdir()
    path, hint = default_assets_dir("P1", "projects")
    assert path == "assets"
    assert "not found" in hint
    assert default_assets_dir("", "projects") == ("assets", "")


def test_browse_default_without_any_template(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path, hint = default_assets_dir("P1", "projects")
    assert "not found" in hint
    assert "choose a folder manually" in hint


# ---------------------------------------------------------------------------
# §2 transport hardening
# ---------------------------------------------------------------------------
class EchoChannel:
    """Simulates a DUT shell: echoed command, output, then the marker."""

    kind = "serial"

    def __init__(self, clock: Clock, *, echo_corrupt: bool = False,
                 clutter: str = "") -> None:
        self.clock = clock
        self.echo_corrupt = echo_corrupt
        self.clutter = clutter
        self.written: list = []
        self._lines: list = []

    def write(self, text: str) -> None:
        self.written.append(text)
        for line in text.splitlines():
            if line.startswith("echo @@MTK_FRAME_"):
                marker = line[len("echo "):]
                # command output first, THEN the marker, then any console
                # chatter that arrived after the frame closed
                self._lines.append("Linux 5.15 fct")
                self._lines.append(marker)
                if self.clutter:
                    self._lines.append(self.clutter)
            elif self.echo_corrupt:
                self._lines.append("##garbled##")
            else:
                self._lines.append(line)

    def read_lines(self, max_lines: int = 200, timeout_s: float = 0.0) -> list:
        out = self._lines[:max_lines]
        del self._lines[:len(out)]
        return out


def test_quiet_window_waits_before_the_first_character():
    clock = Clock()

    class Silent:
        kind = "serial"

        def write(self, _text):
            pass

        def read_lines(self, max_lines=200, timeout_s=0.0):
            return []

    ok = stp.wait_quiet(Silent(), 200, sleep=clock.sleep, now=clock.now)
    assert ok is True
    assert clock.t == pytest.approx(0.2, abs=0.021)


def test_quiet_window_extends_while_the_dut_is_chatty():
    clock = Clock()

    class Chatty:
        kind = "serial"

        def __init__(self):
            self.left = 3

        def write(self, _text):
            pass

        def read_lines(self, max_lines=200, timeout_s=0.0):
            if self.left > 0:
                self.left -= 1
                return ["boot log line"]
            return []

    ok = stp.wait_quiet(Chatty(), 100, sleep=clock.sleep, now=clock.now)
    assert ok is True
    assert clock.t >= 0.14          # every new line re-armed the window


def test_marker_frame_parses_interleaved_output():
    clock = Clock()
    ch = EchoChannel(clock, clutter="kernel: usb 1-1: new device")
    serial = stp.HardenedSerial(ch, quiet_ms=0, char_delay_ms=0,
                                sleep=clock.sleep, now=clock.now)
    out = serial.send("uname -r", timeout_s=0.5)
    assert "Linux 5.15 fct" in out
    # the interleaved line AFTER the frame marker is dropped
    assert "usb 1-1" not in out
    assert "@@MTK_FRAME_" not in out


def test_echo_verify_retries_then_fails_explicitly():
    clock = Clock()
    ch = EchoChannel(clock, echo_corrupt=True)
    serial = stp.HardenedSerial(ch, quiet_ms=0, char_delay_ms=0,
                                max_retries=3, sleep=clock.sleep,
                                now=clock.now)
    with pytest.raises(stp.TransportError) as exc:
        serial.send("uname -r", timeout_s=0.3)
    assert "after 3 attempts" in str(exc.value)
    assert serial.attempts == 3
    assert len([w for w in ch.written if w == "uname -r\n"]) == 3


def test_throttle_writes_one_character_per_delay():
    clock = Clock()
    ch = FakeChannel(clock)
    calls: list = []

    def sleep(sec):
        calls.append(sec)
        clock.sleep(sec)

    stp.write_throttled(ch, "abc", 5, sleep=sleep)
    assert len(ch.written) == 3
    assert calls == pytest.approx([0.005, 0.005, 0.005])


def test_apply_send_hardening_leaves_virtual_channels_alone():
    class Virtual:
        kind = "virtual"

        def __init__(self):
            self.written = []

        def write(self, text):
            self.written.append(text)

        def read_lines(self, max_lines=200, timeout_s=0.0):
            return []

    v = Virtual()
    stp.apply_send_hardening(v, "ls\n")
    assert v.written == ["ls\n"]


def test_apply_send_hardening_waits_and_throttles_real_channels():
    clock = Clock()
    ch = FakeChannel(clock)
    stp.apply_send_hardening(ch, "ls\n", quiet_ms=100, char_delay_ms=5,
                             sleep=clock.sleep, now=clock.now)
    assert clock.t == pytest.approx(0.1 + 3 * 0.005, abs=0.021)
    assert len(ch.written) == 3


# ---------------------------------------------------------------------------
# §1 submenu contract (16 entries, Custom gone) - Qt panel
# ---------------------------------------------------------------------------
def test_operation_submenu_has_sixteen_entries_and_no_custom():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel

    QApplication.instance() or QApplication([])
    panel = FCTTestConfigPanel()
    panel.set_values({})
    texts = list(panel._op_add_actions)
    assert len(texts) == 16
    assert "Operation: Custom" not in texts
    assert STEP_TYPE_SERIAL_PUT in texts
    assert STEP_TYPE_SERIAL_PULL in texts
    assert "Delay — plain wait (ms)" in texts
