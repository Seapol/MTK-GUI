# -*- coding: utf-8 -*-
"""Flash flow fault tolerance (P1 Task8).

Industrial hardening around the flash driver call, purely additive:
the happy path is unchanged, only exceptions branch differently.

  * segmented timeouts - connect / write / verify phases get their
    own budget; overruns are logged (a blocking driver call cannot
    be interrupted, so the watchdog records and reports overruns)
  * transient-disconnect auto retry - ConnectionError/OSError during
    the write phase are retried within the driver retry budget
    (flash_params.retries); exhaustion propagates as ConnectionError
    so the RESOURCE branch of the failure taxonomy terminates the run
  * safe rollback - a write or verify failure marks the slot dirty in
    the image registry (no half-written firmware is ever treated as
    flashed; the next flash re-writes unconditionally)
  * dual verification - write verify flag plus a post-write device
    verify (when the driver exposes verify_firmware)
  * forced resource release - the driver handle is closed in a
    finally block; a failed close is logged, never raised
  * [FLASH_FT] structured lines for every phase / retry / rollback
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

DEFAULT_CONNECT_TIMEOUT_S = 10.0
DEFAULT_WRITE_TIMEOUT_S = 120.0
DEFAULT_VERIFY_TIMEOUT_S = 30.0

TRANSIENT_EXCEPTIONS = (ConnectionError, OSError, TimeoutError)


@dataclass
class PhaseOutcome:
    """One guarded flash phase."""
    phase: str                # connect | write | verify
    ok: bool
    detail: str = ""
    duration_s: float = 0.0
    timed_out: bool = False
    attempt: int = 1


class FlashTolerance:
    """Segmented-timeout, retrying, rollback-aware flash executor."""

    def __init__(self,
                 retries: int = 0,
                 connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
                 write_timeout_s: float = DEFAULT_WRITE_TIMEOUT_S,
                 verify_timeout_s: float = DEFAULT_VERIFY_TIMEOUT_S,
                 log_fn: Optional[Callable[[str], None]] = None):
        self.retries = max(0, int(retries))
        self.timeouts = {"connect": connect_timeout_s,
                         "write": write_timeout_s,
                         "verify": verify_timeout_s}
        self._log = log_fn or (lambda line: print(line))
        self.phases: list[PhaseOutcome] = []

    # ------------------------------------------------------------- log
    def _ft(self, line: str) -> None:
        self._log(f"[FLASH_FT] {line}")

    # ---------------------------------------------------------- phases
    def _guarded(self, phase: str, fn: Callable[[], object],
                 attempt: int = 1) -> PhaseOutcome:
        t0 = time.monotonic()
        try:
            result = fn()
            dt = time.monotonic() - t0
            out = PhaseOutcome(phase, ok=True, detail=str(result),
                               duration_s=dt, attempt=attempt)
        except Exception as exc:
            dt = time.monotonic() - t0
            out = PhaseOutcome(
                phase, ok=False, detail=f"{type(exc).__name__}: {exc}",
                duration_s=dt, attempt=attempt)
        out.timed_out = out.duration_s > self.timeouts[phase]
        if out.timed_out:
            self._ft(f"{phase} phase exceeded its timeout budget "
                     f"({out.duration_s:.1f}s > "
                     f"{self.timeouts[phase]:.0f}s) - flagged for "
                     f"review")
        self.phases.append(out)
        return out

    # ---------------------------------------------------------- flash
    def execute_write(self, write_fn: Callable[[], object],
                      registry, slot: str) -> PhaseOutcome:
        """Write phase with transient-disconnect retry and rollback.

        Retry budget comes from the flash parameter layer (P1 Task6:
        0..5).  A non-transient failure or exhausted retries rolls
        the slot back to dirty and re-raises for the taxonomy."""
        attempt = 0
        while True:
            attempt += 1
            out = self._guarded("write", write_fn, attempt)
            if out.ok:
                self._ft(f"write ok (attempt {attempt}): {out.detail}")
                return out
            transient = isinstance_exception(out.detail)
            if transient and attempt <= self.retries + 1:
                self._ft(f"transient disconnect during write "
                         f"(attempt {attempt}) -> auto retry "
                         f"({self.retries + 2 - attempt} left)")
                continue
            if transient:
                self._ft(f"retry budget exhausted after {attempt} "
                         f"attempts -> terminating")
            else:
                self._ft(f"write failed permanently: {out.detail}")
            self._rollback(registry, slot, out)
            if transient:
                raise ConnectionError(
                    f"flash write failed after {attempt} attempt(s): "
                    f"{out.detail}")
            raise FlashWriteFailed(out)

    def execute_verify(self, verify_fn: Callable[[], object],
                       registry, slot: str) -> PhaseOutcome:
        """Post-write on-device verification (landing check)."""
        if verify_fn is None:
            self._ft("verify phase: driver has no verify_firmware -> "
                     "skipped (write verify flag still applies)")
            return PhaseOutcome("verify", ok=True, detail="skipped")
        out = self._guarded("verify", verify_fn)
        if out.ok:
            self._ft(f"landing verification passed: {out.detail}")
            return out
        self._rollback(registry, slot, out)
        raise FlashVerifyFailed(out)

    def _rollback(self, registry, slot: str, out: PhaseOutcome) -> None:
        self._ft(f"rollback: slot '{slot}' marked dirty "
                 f"(half-written firmware will not be treated as "
                 f"flashed)")
        registry.mark_dirty(slot)

    def release(self, drv) -> None:
        """Forced resource release - never raises."""
        close = getattr(drv, "close", None)
        if close is None:
            return
        try:
            close()
            self._ft("driver handle closed (resource released)")
        except Exception as exc:
            self._ft(f"driver close failed (logged, not raised): "
                     f"{exc!r}")


class FlashWriteFailed(RuntimeError):
    def __init__(self, out: PhaseOutcome):
        super().__init__(f"flash write failed: {out.detail}")


class FlashVerifyFailed(RuntimeError):
    def __init__(self, out: PhaseOutcome):
        super().__init__(f"flash landing verification failed: "
                         f"{out.detail}")


def isinstance_exception(detail: str) -> bool:
    """The phase outcome only carries a stringified exception; the
    transient classes all stringify with these names."""
    return any(name in detail for name in
               ("ConnectionError", "OSError", "TimeoutError"))
