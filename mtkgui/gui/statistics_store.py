# -*- coding: utf-8 -*-
"""Statistics data model (M10-FIX4 F1).

One :class:`RunRecord` per counted unit; the append-only history lives
in ``work/statistics/<PROJECT>/<YYYY-MM>.jsonl`` (one JSON object per
line, one shard per month).  The module is pure data (no Qt) so both the
run-end hook and the statistics dialog share one source of truth, and
the numbers stay testable without a GUI.
"""
from __future__ import annotations

import json
import os
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from mtkgui import report_paths

#: pre-M87 history (module config dir, a JSON array) - migrated once
LEGACY_HISTORY_PATH = (Path(__file__).resolve().parents[1] / "config"
                       / "statistics" / "runs.json")

_MIGRATED = False

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"


def _as_float(value) -> float | None:
    """Parse a numeric table cell; None for empties / non-numeric."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


@dataclass
class RunRecord:
    """One finished unit (the statistics single source of truth)."""

    timestamp: str
    serial: str
    verdict: str                       # PASS | FAIL
    cycle_time_s: float
    passed: int
    failed: int
    failed_steps: list[str] = field(default_factory=list)
    #: ICT numeric test name -> (measured, lower limit, upper limit)
    measurements: dict[str, tuple[float, float, float]] = field(
        default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-safe representation (measurement tuples -> arrays)."""
        return {
            "timestamp": self.timestamp,
            "serial": self.serial,
            "verdict": self.verdict,
            "cycle_time_s": float(self.cycle_time_s),
            "passed": int(self.passed),
            "failed": int(self.failed),
            "failed_steps": list(self.failed_steps),
            "measurements": {
                str(k): [float(v[0]), float(v[1]), float(v[2])]
                for k, v in self.measurements.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunRecord":
        """Rebuild a record; tolerates missing optional fields."""
        if not isinstance(data, dict):
            raise TypeError("run record must be a JSON object")
        measurements = {}
        for name, vals in (data.get("measurements") or {}).items():
            try:
                measurements[str(name)] = (
                    float(vals[0]), float(vals[1]), float(vals[2]))
            except (TypeError, ValueError, IndexError):
                continue
        return cls(
            timestamp=str(data.get("timestamp") or ""),
            serial=str(data.get("serial") or ""),
            verdict=str(data.get("verdict") or VERDICT_PASS),
            cycle_time_s=float(data.get("cycle_time_s") or 0.0),
            passed=int(data.get("passed") or 0),
            failed=int(data.get("failed") or 0),
            failed_steps=[str(s) for s in (data.get("failed_steps") or [])],
            measurements=measurements,
        )


# ---------------------------------------------------------------- history
def runs_dir() -> Path:
    """``<work>/statistics/<PROJECT>/`` - survives a package upgrade."""
    return report_paths.work_dir() / "statistics" / report_paths.project_key()


def runs_path(month: str | None = None) -> Path:
    """The month shard: ``runs_dir()/<YYYY-MM>.jsonl``."""
    name = month or datetime.now().strftime("%Y-%m")
    return runs_dir() / f"{name}.jsonl"


def _read_shard(target: Path) -> tuple[list[RunRecord], int]:
    """``(records, corrupt_line_count)`` for one JSON Lines shard."""
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], 0
    records: list[RunRecord] = []
    corrupt = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError:
            corrupt += 1
            continue
        try:
            records.append(RunRecord.from_dict(data))
        except (TypeError, ValueError):
            corrupt += 1
    return records, corrupt


def load_runs(path=None) -> tuple[list[RunRecord], str]:
    """Read the history (JSON Lines).

    With *path* read that one shard, otherwise every ``*.jsonl`` shard
    in :func:`runs_dir` in name order.  Returns ``(records, warning)``;
    a missing file/directory is normal (no warning), a corrupt line is
    skipped with a warning, an unreadable file reports the reason -
    never an exception."""
    if path is not None:
        targets = [Path(path)]
    else:
        try:
            targets = sorted(p for p in runs_dir().glob("*.jsonl")
                             if p.is_file())
        except OSError as exc:
            return [], f"statistics history unreadable: {exc}"
        if not targets:
            return [], ""
    records: list[RunRecord] = []
    corrupt = 0
    for target in targets:
        try:
            shard_records, shard_corrupt = _read_shard(target)
        except OSError as exc:
            return records, f"statistics history unreadable: {exc}"
        records.extend(shard_records)
        corrupt += shard_corrupt
    warning = (f"statistics history has {corrupt} corrupt line(s), skipped"
               if corrupt else "")
    return records, warning


def append_run(record: RunRecord, path=None) -> Path | None:
    """Append one JSON line to the month shard (never rewrite it).

    Returns the written path, or None when the write failed - the run
    itself must never be blocked by statistics."""
    global _MIGRATED
    if path is None and not _MIGRATED:
        _MIGRATED = True
        migrate_legacy_history()
    target = Path(path) if path is not None else runs_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    except OSError:
        return None
    return target


def _month_of(record: RunRecord) -> str:
    """The shard month of one record (current month when unparsable)."""
    month = record.timestamp[:7]
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        return datetime.now().strftime("%Y-%m")
    return month


def migrate_legacy_history() -> int:
    """Move the pre-M87 package history into the monthly shards once.

    A missing / unreadable / corrupt legacy file returns ``0`` and is
    left untouched; a migrated file is renamed to ``runs.json.migrated``
    next to itself, so a second call migrates nothing."""
    legacy = Path(LEGACY_HISTORY_PATH)
    try:
        raw = legacy.read_text(encoding="utf-8")
    except OSError:
        return 0
    try:
        data = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(data, list):
        return 0
    migrated = 0
    for item in data:
        try:
            record = RunRecord.from_dict(item)
        except (TypeError, ValueError):
            continue
        target = runs_path(_month_of(record))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            continue
        migrated += 1
    try:
        os.replace(legacy, legacy.with_name(legacy.name + ".migrated"))
    except OSError:
        pass
    return migrated


# ------------------------------------------------------------ page facts
def _row_text(table, row: int, column: int) -> str:
    item = table.item(row, column)
    return item.text().strip() if item is not None else ""


def _is_failure(text: str) -> bool:
    upper = text.upper()
    return "FAIL" in upper or upper == "ERROR"


def record_from_page(page, timestamp: str | None = None) -> RunRecord:
    """Build the record of the just-finished unit from the page state.

    Measurements only include ICT numeric tests that stored a measured
    value AND both limits; failed steps cover ICT and FCT rows."""
    info = page.product_info() if hasattr(page, "product_info") else {}
    cycle = float(page.cycle_times[-1]) if getattr(
        page, "cycle_times", None) else 0.0
    try:
        verdict = VERDICT_FAIL if page._judge_verdict() == "FAIL" \
            else VERDICT_PASS
    except Exception:                       # noqa: BLE001 (defensive)
        verdict = VERDICT_PASS

    failed_steps: list[str] = []
    measurements: dict[str, tuple[float, float, float]] = {}

    ict = getattr(page, "ict", None)
    steps = getattr(page, "ict_steps", []) or []
    if ict is not None:
        for row in range(ict.rowCount()):
            name = (steps[row][1] if row < len(steps)
                    else _row_text(ict, row, 1))
            status = _row_text(ict, row, 7)
            if _is_failure(status):
                failed_steps.append(name)
            if row < len(steps) and steps[row][0] == "test":
                measured = _as_float(_row_text(ict, row, 4))
                lower = _as_float(_row_text(ict, row, 5))
                upper = _as_float(_row_text(ict, row, 6))
                if measured is not None and lower is not None \
                        and upper is not None:
                    measurements[name] = (measured, lower, upper)
    fct = getattr(page, "fct", None)
    if fct is not None:
        for row in range(fct.rowCount()):
            if _is_failure(_row_text(fct, row, 4)):
                failed_steps.append(_row_text(fct, row, 1))

    return RunRecord(
        timestamp=timestamp or datetime.now().isoformat(timespec="seconds"),
        serial=str(info.get("serial") or ""),
        verdict=verdict,
        cycle_time_s=cycle,
        passed=1 if verdict == VERDICT_PASS else 0,
        failed=1 if verdict == VERDICT_FAIL else 0,
        failed_steps=failed_steps,
        measurements=measurements,
    )


def session_records(page) -> list[RunRecord]:
    """Session source: the page counters + the current per-row results.

    The counters give the total passed / failed units; the current
    cycle's row detail (measurements for CpK, failed step names)
    enriches the newest record.  A stopped / never-counted run with
    visible results still yields one record instead of an empty view."""
    if page is None:
        return []
    passed = int(getattr(page, "products_passed", 0) or 0)
    failed = int(getattr(page, "products_failed", 0) or 0)
    cycles = [float(c) for c in (getattr(page, "cycle_times", None) or [])]
    detail = record_from_page(page)
    has_rows = bool(detail.measurements or detail.failed_steps)
    total = passed + failed
    if total <= 0:
        if not cycles and not has_rows:
            return []
        return [detail]
    mean_cycle = (sum(cycles) / len(cycles) if cycles else
                  detail.cycle_time_s)
    detail_passed = 1 if detail.verdict == VERDICT_PASS else 0
    other_passed = max(0, passed - detail_passed)
    other_failed = max(0, failed - (1 - detail_passed))

    def _plain(verdict: str, cycle: float) -> RunRecord:
        return RunRecord(
            timestamp=detail.timestamp, serial=detail.serial,
            verdict=verdict, cycle_time_s=cycle,
            passed=1 if verdict == VERDICT_PASS else 0,
            failed=1 if verdict == VERDICT_FAIL else 0)

    records: list[RunRecord] = []
    index = 0
    for _ in range(other_passed):
        cycle = cycles[index] if index < len(cycles) else mean_cycle
        records.append(_plain(VERDICT_PASS, cycle))
        index += 1
    for _ in range(other_failed):
        cycle = cycles[index] if index < len(cycles) else mean_cycle
        records.append(_plain(VERDICT_FAIL, cycle))
        index += 1
    records.append(detail)
    return records


# ------------------------------------------------------------------ CpK
def cpk_rows(records: list[RunRecord]) -> list[dict]:
    """Group measurements by test name and compute Cp / CpK.

    ``Cp = (USL-LSL)/(6 sigma)`` and
    ``CpK = min((USL-mean)/(3 sigma), (mean-LSL)/(3 sigma))`` with
    sigma = sample standard deviation (n-1).  ``cp`` / ``cpk`` are
    None when undefined (n == 1 or sigma == 0); ``indicative`` marks
    2..4 samples."""
    grouped: dict[str, list[tuple[float, float, float]]] = {}
    for record in records:
        for name, values in record.measurements.items():
            grouped.setdefault(name, []).append(tuple(values))
    rows: list[dict] = []
    for name in sorted(grouped):
        values = grouped[name]
        measured = [v[0] for v in values]
        n = len(measured)
        lower, upper = values[-1][1], values[-1][2]
        mean = sum(measured) / n
        sigma = statistics.stdev(measured) if n >= 2 else 0.0
        cp = cpk = None
        if n >= 2 and sigma > 0:
            half = (upper - lower) / (6.0 * sigma)
            cp = half
            cpk = min((upper - mean) / (3.0 * sigma),
                      (mean - lower) / (3.0 * sigma))
        rows.append({
            "test": name,
            "samples": n,
            "mean": mean,
            "sigma": sigma,
            "lsl": lower,
            "usl": upper,
            "cp": cp,
            "cpk": cpk,
            "indicative": 2 <= n < 5,
        })
    return rows


# -------------------------------------------------------------- overview
def overview(records: list[RunRecord]) -> dict:
    """Overview card numbers for one data source."""
    total = len(records)
    passed = sum(1 for r in records if r.verdict == VERDICT_PASS)
    failed = sum(1 for r in records if r.verdict == VERDICT_FAIL)
    cycles = [r.cycle_time_s for r in records if r.cycle_time_s > 0]
    avg = sum(cycles) / len(cycles) if cycles else 0.0
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "yield_pct": (passed / total * 100.0) if total else 0.0,
        "avg_cycle_s": avg,
        "uph": (3600.0 / avg) if avg > 0 else 0.0,
    }
