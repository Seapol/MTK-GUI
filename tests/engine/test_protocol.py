# -*- coding: utf-8 -*-
"""Instrument protocol layer (P1 Task9): tolerant parsing, precise
rejection, timeout tiers, version compatibility, gateway pre-check."""
from __future__ import annotations

import pytest

from mtkgui.engine.instruments import RealGateway
from mtkgui.engine.protocol import (CommandValidator, ProtocolAdapter,
                                    ProtocolError, ReplyParser,
                                    TimeoutPolicy)
from tests.engine.conftest import scripted_drivers  # noqa: F401


# ---------------------------------------------------------------- parsing
class TestReplyParsing:
    def test_v2_standard_reply(self):
        r = ReplyParser("v2").parse("OK 17 3.3")
        assert r.ok and r.seq == 17 and r.value == 3.3
        assert r.deviations == []

    def test_tolerant_case_and_whitespace(self):
        r = ReplyParser().parse("  ok   \r\n 12.5  ")
        assert r.ok and r.value == 12.5
        assert "status case normalised" in r.deviations

    def test_v1_reply_without_seq(self):
        r = ReplyParser("v1").parse("OK 3.3")
        assert r.seq is None and r.value == 3.3

    def test_v2_missing_seq_tolerated_with_deviation(self):
        r = ReplyParser("v2").parse("OK 3.3")
        assert r.value == 3.3
        assert "missing sequence field (v2)" in r.deviations

    def test_error_statuses_parse_ok_false(self):
        for raw in ("ERR 1 overflow", "FAIL", "ERROR 2 -1"):
            assert ReplyParser().parse(raw).ok is False

    def test_empty_frame_rejected_precisely(self):
        with pytest.raises(ProtocolError) as ei:
            ReplyParser().parse("   \r\n")
        assert ei.value.kind == "frame" and "empty" in ei.value.reason

    def test_unknown_status_rejected(self):
        with pytest.raises(ProtocolError) as ei:
            ReplyParser().parse("MAYBE 1 2")
        assert "unknown reply status" in ei.value.reason

    def test_non_numeric_payload_rejected(self):
        with pytest.raises(ProtocolError) as ei:
            ReplyParser().parse("OK abc")
        assert "non-numeric payload 'abc'" in ei.value.reason

    def test_unknown_version_rejected(self):
        with pytest.raises(ProtocolError):
            ReplyParser("v3")

    def test_extreme_long_reply_parses(self):
        r = ReplyParser().parse("OK 1 " + "9" * 300)
        assert r.value == float("9" * 300)


# ------------------------------------------------------------- validation
class TestCommandValidation:
    def _v(self):
        return CommandValidator({"POWER_ON", "RESET", "MEASURE"},
                                restricted={"FACTORY_RESET"})

    def test_known_command_passes(self):
        assert self._v().validate(" power_on ") == "POWER_ON"

    def test_unknown_command_rejected(self):
        with pytest.raises(ProtocolError) as ei:
            self._v().validate("SELF_DESTRUCT")
        assert ei.value.kind == "command"

    def test_over_permission_rejected(self):
        with pytest.raises(ProtocolError) as ei:
            self._v().validate("FACTORY_RESET")
        assert ei.value.kind == "permission"


# ---------------------------------------------------------------- timing
class TestTimeoutTiers:
    def test_three_tiers_independent(self):
        p = TimeoutPolicy(connect_s=1, reply_s=0.5, execute_s=10)
        assert p.budget("reply") == 0.5 and p.budget("connect") == 1.0

    def test_exchange_logs_duration_and_overrun(self):
        lines: list[str] = []
        pa = ProtocolAdapter(
            policy=TimeoutPolicy(reply_s=0.0000001),
            log_fn=lines.append)
        r = pa.exchange("MEASURE", lambda: "OK 1 3.3")
        assert r.ok
        text = "\n".join(lines)
        assert "TIMEOUT-OVERRUN" in text and "cmd=MEASURE" in text

    def test_transport_error_logged_and_raised(self):
        lines: list[str] = []
        pa = ProtocolAdapter(log_fn=lines.append)

        def boom():
            raise IOError("port vanished")
        with pytest.raises(IOError):
            pa.exchange("MEASURE", boom)
        assert "TRANSPORT-ERROR" in "\n".join(lines)

    def test_rejected_frame_logged(self):
        lines: list[str] = []
        pa = ProtocolAdapter(log_fn=lines.append)
        with pytest.raises(ProtocolError):
            pa.exchange("MEASURE", lambda: "")
        assert "REJECTED" in "\n".join(lines)


# ------------------------------------------------------------ gateway link
class TestGatewayPreValidation:
    def test_unknown_op_type_rejected_before_instruments(self):
        gw = RealGateway({"psu": {"fields": {"Address": "/dev/x"}}})
        out = gw.execute_op("Bad Step", {"type": "hypersonic"})
        assert out.verdict == "Error"
        assert "illegal command" in " ".join(out.lines)
        assert gw._drivers == {}                 # nothing was opened

    def test_known_op_carries_proto_audit_line(self, tmp_path,
                                                monkeypatch,
                                                scripted_drivers):
        gw = RealGateway({"psu": {"fields": {"Address": "/dev/x"}}})
        out = gw.execute_op("Power On", {"type": "power",
                                         "state": "on", "voltage": 5.0})
        assert out.verdict == "Done"
        assert out.lines[-1].startswith("[INSTR_PROTO] op=power")
        assert "verdict=Done" in out.lines[-1]
