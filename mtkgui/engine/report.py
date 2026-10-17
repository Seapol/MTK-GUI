# -*- coding: utf-8 -*-
"""Manufacturing report generator (B4 design §8, Module B): DUT detail
report + batch summary, CSV (MES-importable) + in-app preview data.

Pure stdlib.  The generator NEVER re-judges: it reads the Test Work
Flow session state (the same cells the Overall Result renders) and
formats it.  Categories follow the directive: ICT / Flash / FCT / RF.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

#: CSV column header (DUT detail rows, MES-importable flat shape)
CSV_HEADER = ("serial_no", "station_id", "user", "timestamp",
              "test_name", "category", "channel", "duration", "low",
              "high", "unit", "result")

#: item categories (directive §B1)
CAT_ICT = "ICT"
CAT_FLASH = "Flash"
CAT_FCT = "FCT"
CAT_RF = "RF"


def _clean(value) -> str:
    """Table cell -> flat CSV-safe string."""
    text = "" if value is None else str(value)
    return text.strip()


@dataclass
class ReportItem:
    """One judged test row in the DUT report."""
    test_name: str
    category: str
    channel: str = ""
    measured: str = ""
    # test execution time (seconds, formatted by the caller).  FCT rows
    # carry it; ICT rows keep their measured value instead.
    duration: str = ""
    low: str = ""
    high: str = ""
    unit: str = ""
    result: str = ""
    # ICT sub-classification from the Test Method ("Static Impedance" /
    # "Power Voltage" / "Clock Hz" / "DAQ AI"; "" = generic) - the
    # certificate report splits the ICT detail into per-method tables
    method: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def csv_row(self, dut: "DutReport") -> list:
        """Flat MES row (the DUT header fields repeated per item)."""
        return [dut.serial_no, dut.station_id, dut.user, dut.timestamp,
                self.test_name, self.category, self.channel,
                self.duration or self.measured, self.low, self.high,
                self.unit, self.result]


@dataclass
class DutReport:
    """One tested unit: serial + station identity + all judged items."""
    serial_no: str
    station_id: str
    user: str
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    overall_result: str = ""
    items: list = field(default_factory=list)      # list[ReportItem]
    # full DUT console transcript (raw, ANSI codes included) — the PDF
    # exporter strips the escapes before dumping it after the test table
    console_log: str = ""
    # power-rails capture (DAQ AI): entries (label, color, y_max,
    # samples-as-fractions-of-nominal) + the capture time window — the
    # certificate report draws the sequence chart + per-rail analysis
    rails: list = field(default_factory=list)
    rail_duration: float = 0.0
    rail_t_start: float = 0.0

    # ------------------------------------------------------------- build
    @classmethod
    def from_session(cls, page, serial_no: str = "") -> "DutReport":
        """Read the Test Work Flow session state (B4 §8.1: never
        re-judge — the cells ARE the verdicts)."""
        station_id, user = "", ""
        try:
            from ..gui import identity
            station_id, user = (identity.get_station_id(),
                                identity.get_user())
        except Exception:                # noqa: BLE001 - headless tests
            pass
        report = cls(serial_no=serial_no or _clean(
            getattr(page, "serial_edit", None).text()
            if hasattr(page, "serial_edit") else ""),
            station_id=station_id, user=user)
        report.overall_result = _clean(
            page.result_label.text()) if hasattr(
            page, "result_label") else ""

        def _cell(table, r, c):
            item = table.item(r, c)
            return _clean(item.text()) if item is not None else ""

        # ICT rows (kind op = standard operations; flash ops = Flash).
        # kind IS the Test Method ("Static Impedance"/"Power Voltage"/
        # "Clock Hz"/"DAQ AI"); a generic "test" falls back to its unit
        # (Ω / V / Hz) the same way the virtual hardware guesses.
        for r, step in enumerate(getattr(page, "ict_steps", [])):
            kind, name = step[0], step[1]
            result = _cell(page.ict, r, 7)
            if not result or result in ("Pending", "--"):
                continue
            category = CAT_ICT
            if kind == "op":
                category = CAT_FLASH if "Flash" in name else CAT_ICT
            unit = _clean(step[2]) if len(step) > 2 else ""
            if kind == "op":
                method = ""
            elif kind in ("Static Impedance", "Power Voltage",
                          "Clock Hz", "DAQ AI"):
                method = kind
            else:
                method = {"Ω": "Static Impedance", "V": "Power Voltage",
                          "Hz": "Clock Hz"}.get(unit, "")
            report.items.append(ReportItem(
                test_name=name, category=category,
                channel="fixture",
                measured=_cell(page.ict, r, 4),
                low=_cell(page.ict, r, 5), high=_cell(page.ict, r, 6),
                unit=unit, result=result, method=method))
        # FCT rows (RF kinds -> RF category); the FCT table col 3 is the
        # per-row Duration (s) cell
        for r, name in enumerate(getattr(page, "fct_rows", [])):
            result = _cell(page.fct, r, 4)
            if not result or result in ("Pending", "--"):
                continue
            kind = (page.fct_kinds[r]
                    if r < len(page.fct_kinds) else "")
            category = (CAT_RF if kind in ("WIFI", "Bluetooth")
                        else CAT_FCT)
            dur = _cell(page.fct, r, 3)
            report.items.append(ReportItem(
                test_name=name, category=category, channel="console",
                duration="" if dur == "--" else dur, result=result))

        # power-rails capture (DAQ AI): clone the live waveform data so
        # the report draws the sequence chart + per-rail analysis
        rw = getattr(page, "rail_widget", None)
        rails = getattr(rw, "data", None) or []
        if rails:
            report.rails = list(rails)
            report.rail_duration = float(
                getattr(rw, "duration", 0.0) or 0.0)
            report.rail_t_start = float(
                getattr(rw, "t_start", 0.0) or 0.0)

        # full console transcript dump (per channel RX buffer) for the
        # PDF appendix; headless / fake pages have no multi_console
        mc = getattr(page, "multi_console", None)
        channels = getattr(mc, "channels", None) or {}
        dumps = []
        for key in channels:
            try:
                raw = mc.get_read_buffer(key)
            except Exception:            # noqa: BLE001 - never re-judge
                continue
            if raw:
                dumps.append(f"===== {key} =====\n"
                             + raw.decode("utf-8", "replace"))
        report.console_log = "\n".join(dumps)
        return report

    # ------------------------------------------------------------- output
    def csv_rows(self) -> list:
        """Flat rows for the DUT detail CSV (header first)."""
        return [list(CSV_HEADER)] + [item.csv_row(self)
                                     for item in self.items]

    def to_html(self) -> str:
        """Print-view HTML (in-app QTextBrowser render)."""
        rows = "".join(
            f"<tr><td>{i.test_name}</td><td>{i.category}</td>"
            f"<td>{i.duration or i.measured}</td><td>{i.low}</td>"
            f"<td>{i.high}</td><td>{i.unit}</td><td>{i.result}</td></tr>"
            for i in self.items)
        color = "#1d7a3c" if "PASS" in self.overall_result else "#b02a2a"
        return (
            f"<h2>DUT Report — {self.serial_no}</h2>"
            f"<p>Station: {self.station_id} · Operator: {self.user} · "
            f"{self.timestamp}</p>"
            f"<p><b style='color:{color}'>Overall: "
            f"{self.overall_result}</b></p>"
            f"<table border='1' cellspacing='0' cellpadding='4'>"
            f"<tr><th>Test</th><th>Category</th><th>Measured</th>"
            f"<th>Low</th><th>High</th><th>Unit</th><th>Result</th></tr>"
            f"{rows}</table>")


@dataclass
class BatchSummary:
    """N DUTs: counts + yield + failures-by-item ranking (B4 §8.2)."""
    reports: list = field(default_factory=list)    # list[DutReport]

    @property
    def n_total(self) -> int:
        return len(self.reports)

    @property
    def n_pass(self) -> int:
        return sum(1 for r in self.reports if "PASS" in r.overall_result)

    @property
    def n_fail(self) -> int:
        return self.n_total - self.n_pass

    @property
    def yield_pct(self) -> float:
        return round(100.0 * self.n_pass / self.n_total, 1) \
            if self.n_total else 0.0

    def failures_by_item(self) -> list:
        """[(test_name, fail_count)] sorted by count desc.  Only real
        failures count (FAIL/TIMEOUT/ERROR) — fat.py Summary INFO/WARN/
        SKIP rows carry their status but are not failures."""
        counts: dict = {}
        for report in self.reports:
            for item in report.items:
                up = item.result.upper()
                if any(k in up for k in ("FAIL", "TIMEOUT", "ERROR")):
                    counts[item.test_name] = \
                        counts.get(item.test_name, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def csv_rows(self) -> list:
        """Batch summary CSV: one row per DUT + a statistics block."""
        rows = [["serial_no", "station_id", "user", "timestamp",
                 "overall_result"]]
        rows += [[r.serial_no, r.station_id, r.user, r.timestamp,
                  r.overall_result] for r in self.reports]
        rows.append([])
        rows.append(["n_total", self.n_total])
        rows.append(["n_pass", self.n_pass])
        rows.append(["n_fail", self.n_fail])
        rows.append(["yield_pct", self.yield_pct])
        rows.append([])
        rows.append(["failed_item", "fail_count"])
        rows += [[name, count] for name, count in self.failures_by_item()]
        return rows

    def to_html(self) -> str:
        rank = "".join(
            f"<tr><td>{name}</td><td>{count}</td></tr>"
            for name, count in self.failures_by_item())
        return (f"<h2>Batch Summary</h2>"
                f"<p>Total: {self.n_total} · PASS: {self.n_pass} · "
                f"FAIL: {self.n_fail} · Yield: {self.yield_pct}%</p>"
                f"<table border='1' cellspacing='0' cellpadding='4'>"
                f"<tr><th>Failed item</th><th>Count</th></tr>{rank}"
                f"</table>")


# ------------------------------------------------------------------ output
def _clean_name(value) -> str:
    """File-name safe fragment (Windows-forbidden chars + spaces)."""
    text = "" if value is None else str(value)
    for ch in '/\\:*?"<>| ':
        text = text.replace(ch, "-")
    return text.strip("-") or "NA"


def save_dut_csv(report: DutReport, out_dir: Path, batch: str = "",
                 core_id: str = "", part: str = "") -> Path:
    """Write the DUT detail CSV straight into ``out_dir`` - the per-DUT
    IDENTITY folder under the DUT Report root (2026-10-17: no date
    subfolder any more; folder AND file name carry Part# / Core ID /
    Batch# / Serial# / timestamp)."""
    stamp = datetime.now().strftime("%H%M%S")
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    name = "DUT_detail_" + "_".join(
        _clean_name(v) for v in (report.serial_no or "DUT",
                                 core_id or "NA", part or "NA",
                                 batch or "NA")) + f"_{stamp}.csv"
    path = target / name
    with open(path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(report.csv_rows())
    return path


def save_batch_csv(summary: BatchSummary, out_dir: Path,
                   batch: str = "") -> Path:
    """Write the batch summary CSV: <batch_>summary_<ts>.csv."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{batch}_" if batch else ""
    target = Path(out_dir) / datetime.now().strftime("%Y-%m-%d")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{prefix}summary_{stamp}.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(summary.csv_rows())
    return path
