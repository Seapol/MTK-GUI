# -*- coding: utf-8 -*-
"""Fine-grained failure taxonomy (P1 Task5).

Replaces the coarse blanket "unexpected error -> freeze" fallback
with six differentiated exception branches, each with its own
handling policy, state-machine target and log tag:

  STEP_FAIL       business step failed (measured out of limit)
  ENGINE_ERROR    engine code error            -> freeze + alarm
  RESOURCE        instrument/resource failure  -> terminate run
  OPERATOR_ABORT  operator stop                -> intercepts all
                                               automatic handling
  FROZEN          engine already frozen        -> no further action
  TIMEOUT         step timed out               -> reset + one retry

Only the safety-net exception handlers consult this module: the
normal FAIL/ERROR step results, the retry core, the state machine
transition table and the layered scheduler architecture are
untouched.  Nested exception chains (__cause__ / __context__) are
unwrapped so the classification reflects the root cause.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FailureKind(str, Enum):
    STEP_FAIL = "STEP_FAIL"
    ENGINE_ERROR = "ENGINE_ERROR"
    RESOURCE = "RESOURCE"
    OPERATOR_ABORT = "OPERATOR_ABORT"
    FROZEN = "FROZEN"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class FailurePolicy:
    """Per-kind handling contract (no one-size-fits-all)."""
    kind: FailureKind
    retry_allowed: bool          # feeds the retry core eligibility
    action: str                  # retry | reset | freeze | abort | none
    state_target: str            # running | frozen | aborted
    tag: str                     # log tag, e.g. "[EXC:RESOURCE]"


_POLICIES: dict[FailureKind, FailurePolicy] = {
    FailureKind.STEP_FAIL: FailurePolicy(
        FailureKind.STEP_FAIL, retry_allowed=True, action="retry",
        state_target="running", tag="[EXC:STEP_FAIL]"),
    FailureKind.ENGINE_ERROR: FailurePolicy(
        FailureKind.ENGINE_ERROR, retry_allowed=False, action="freeze",
        state_target="frozen", tag="[EXC:ENGINE_ERROR]"),
    FailureKind.RESOURCE: FailurePolicy(
        FailureKind.RESOURCE, retry_allowed=False, action="abort",
        state_target="aborted", tag="[EXC:RESOURCE]"),
    FailureKind.OPERATOR_ABORT: FailurePolicy(
        FailureKind.OPERATOR_ABORT, retry_allowed=False, action="none",
        state_target="aborted", tag="[EXC:OPERATOR_ABORT]"),
    FailureKind.FROZEN: FailurePolicy(
        FailureKind.FROZEN, retry_allowed=False, action="none",
        state_target="frozen", tag="[EXC:FROZEN]"),
    FailureKind.TIMEOUT: FailurePolicy(
        FailureKind.TIMEOUT, retry_allowed=True, action="reset",
        state_target="running", tag="[EXC:TIMEOUT]"),
}


def policy_for(kind: FailureKind) -> FailurePolicy:
    return _POLICIES[kind]


@dataclass
class FailureEvent:
    """One classified failure, ready for policy handling + tracing."""
    kind: FailureKind
    policy: FailurePolicy
    message: str
    source: str                  # "runner" | "scheduler" | ...
    chain: list[str]             # nested exception chain (root first)

    @property
    def tag(self) -> str:
        return self.policy.tag

    @property
    def retry_allowed(self) -> bool:
        return self.policy.retry_allowed


def _exception_kind(exc: BaseException) -> FailureKind:
    # local import: instruments does not import this module
    from .instruments import DriverUnavailable
    if isinstance(exc, TimeoutError):
        return FailureKind.TIMEOUT
    if isinstance(exc, (DriverUnavailable, ConnectionError, OSError)):
        return FailureKind.RESOURCE
    return FailureKind.ENGINE_ERROR


def classify_exception(exc: BaseException, *,
                       source: str = "runner") -> FailureEvent:
    """Classify an exception, unwrapping nested chains down to the
    root cause so the branch reflects what actually went wrong."""
    chain: list[str] = []
    seen: set[int] = set()
    root: BaseException = exc
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        chain.append(f"{type(cur).__name__}: {cur}")
        nxt = cur.__cause__ or cur.__context__
        if nxt is not None:
            root = nxt
        cur = nxt
    kind = _exception_kind(root)
    return FailureEvent(kind=kind, policy=policy_for(kind),
                        message=str(root), source=source, chain=chain)


def failure_log_line(event: FailureEvent,
                     action_taken: Optional[str] = None) -> str:
    """Structured per-step failure trace: kind / source / root cause /
    handling action / final state."""
    action = action_taken if action_taken is not None \
        else event.policy.action
    chain_txt = " <- ".join(event.chain) if event.chain else event.message
    return (f"{event.tag} source={event.source} "
            f"root={chain_txt} -> action={action} "
            f"(state_target={event.policy.state_target})")
