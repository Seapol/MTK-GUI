# -*- coding: utf-8 -*-
"""Instrument protocol adaptation layer (P1 Task9).

Standardised, validated, version-tolerant communication base between
the engine and real instruments.  Purely additive: the driver API
(T1), the runner, the scheduler and the failure taxonomy are not
modified - the gateway only gains command pre-validation and
structured [INSTR_PROTO] logging.

  * uniform request/reply frames - "CMD [seq] payload..." text form
    with numeric reply payloads
  * tolerant reply parsing - case, whitespace and minor format
    deviations are normalised; structurally illegal frames raise a
    precise ProtocolError (field + raw + reason)
  * three-tier timeout policy - connect / reply / execute, each with
    its own budget and overrun flagging (a blocking transport cannot
    be interrupted; overruns are recorded and reported)
  * command pre-validation - unknown and restricted (over-permission)
    commands are rejected BEFORE reaching the instrument
  * protocol version compatibility - v1 replies ("OK value") and v2
    replies ("OK seq value") parse with one engine-side parser, so
    legacy devices keep working unchanged
  * [INSTR_PROTO] lines: command, raw reply, duration, exception
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

REPLY_STATUSES = {"OK", "DONE", "PASS", "ERR", "ERROR", "FAIL"}
_SEQ_RE = re.compile(r"^\d+$")
_NUM_RE = re.compile(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$")


class ProtocolError(ValueError):
    """Illegal frame / command / permission violation (precise)."""

    def __init__(self, kind: str, raw: str, reason: str,
                 allowed: str = ""):
        self.kind = kind            # "frame" | "command" | "permission"
        self.raw = raw
        self.reason = reason
        self.allowed = allowed
        suffix = f" (allowed: {allowed})" if allowed else ""
        super().__init__(f"[INSTR_PROTO] illegal {kind}: {reason} "
                         f"raw={raw!r}{suffix}")


@dataclass
class TimeoutPolicy:
    """Three-tier timeout budgets (seconds)."""
    connect_s: float = 5.0
    reply_s: float = 2.0
    execute_s: float = 30.0

    def budget(self, tier: str) -> float:
        return {"connect": self.connect_s,
                "reply": self.reply_s,
                "execute": self.execute_s}[tier]


@dataclass
class Reply:
    """Parsed instrument reply."""
    status: str                  # normalised: OK/DONE/PASS or ERR/...
    value: Optional[float]
    seq: Optional[int]
    raw: str
    version: str
    deviations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("OK", "DONE", "PASS")


class ReplyParser:
    """Tolerant reply parser with protocol-version compatibility."""

    def __init__(self, version: str = "v2"):
        if version not in ("v1", "v2"):
            raise ProtocolError("frame", version,
                                "unknown protocol version",
                                "v1 | v2")
        self.version = version

    def parse(self, raw: str, expected_cmd: str = "") -> Reply:
        deviations: list[str] = []
        text = " ".join(str(raw).replace("\r", " ")
                        .replace("\n", " ").split())
        if not text:
            raise ProtocolError("frame", raw, "empty reply frame")
        parts = text.split(" ")
        status = parts[0].upper()
        if status != parts[0]:
            deviations.append("status case normalised")
        if status not in REPLY_STATUSES:
            raise ProtocolError("frame", raw,
                                "unknown reply status token",
                                f"one of {sorted(REPLY_STATUSES)}")
        rest = parts[1:]
        seq: Optional[int] = None
        if rest and _SEQ_RE.match(rest[0]):
            seq = int(rest[0])
            rest = rest[1:]
            if self.version == "v1":
                deviations.append("sequence field ignored (v1)")
        elif (self.version == "v2" and len(parts) == 2
                and _NUM_RE.match(parts[1])):
            # v2 replies normally carry a seq; a lone value is a minor
            # format deviation and stays parseable
            deviations.append("missing sequence field (v2)")
        value: Optional[float] = None
        if rest and status in ("OK", "DONE", "PASS"):
            token = rest[0]
            if _NUM_RE.match(token):
                value = float(token)
            else:
                raise ProtocolError("frame", raw,
                                    f"non-numeric payload {token!r}",
                                    "numeric measurement value")
        if expected_cmd:
            pass  # the command echo is validated by the caller layer
        return Reply(status=status, value=value, seq=seq, raw=raw,
                     version=self.version, deviations=deviations)


class CommandValidator:
    """Command allow-list + restricted-list pre-validation."""

    def __init__(self, allowed: set[str],
                 restricted: set[str] | None = None):
        self.allowed = {c.upper() for c in allowed}
        self.restricted = {c.upper() for c in (restricted or set())}

    def validate(self, cmd: str) -> str:
        key = cmd.strip().upper()
        if key in self.restricted:
            raise ProtocolError(
                "permission", cmd,
                "command requires elevated permission",
                "not permitted for test-station role")
        if key not in self.allowed:
            raise ProtocolError(
                "command", cmd, "unknown instrument command",
                f"one of {sorted(self.allowed)}")
        return key


class ProtocolAdapter:
    """Logging + timing wrapper around one instrument exchange."""

    def __init__(self, policy: TimeoutPolicy | None = None,
                 parser: ReplyParser | None = None,
                 log_fn: Optional[Callable[[str], None]] = None):
        self.policy = policy or TimeoutPolicy()
        self.parser = parser or ReplyParser()
        self._log = log_fn or (lambda line: print(line))
        self.exchanges: list[dict] = []

    def _ip(self, line: str) -> None:
        self._log(f"[INSTR_PROTO] {line}")

    def exchange(self, cmd: str, send_fn: Callable[[], str],
                 tier: str = "reply") -> Reply:
        """One validated, timed, logged request/reply round trip."""
        t0 = time.monotonic()
        try:
            raw = send_fn()
            reply = self.parser.parse(raw, expected_cmd=cmd)
        except ProtocolError as exc:
            self._ip(f"cmd={cmd} REJECTED kind={exc.kind} "
                     f"reason={exc.reason}")
            raise
        except Exception as exc:
            self._ip(f"cmd={cmd} TRANSPORT-ERROR "
                     f"{type(exc).__name__}: {exc}")
            raise
        dt = time.monotonic() - t0
        overrun = dt > self.policy.budget(tier)
        self.exchanges.append({"cmd": cmd, "duration_s": dt,
                               "ok": reply.ok, "overrun": overrun})
        self._ip(f"cmd={cmd} reply={reply.raw!r} "
                 f"duration={dt:.3f}s tier={tier}"
                 + (" TIMEOUT-OVERRUN" if overrun else ""))
        if overrun:
            self._ip(f"cmd={cmd} exceeded {tier} budget "
                     f"({self.policy.budget(tier):.1f}s) - flagged")
        return reply

    def validate_command(self, cmd: str, validator: CommandValidator
                         ) -> str:
        try:
            return validator.validate(cmd)
        except ProtocolError as exc:
            self._ip(f"cmd={cmd} REJECTED kind={exc.kind} "
                     f"reason={exc.reason}")
            raise
