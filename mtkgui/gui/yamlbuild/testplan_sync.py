# -*- coding: utf-8 -*-
"""ICT Test Plan <-> project YAML bidirectional sync (M5 PART 2).

The YAML is the PRODUCTION TRUTH (what the Test Work Flow / FCT
consume); the Test Plan workbook is the execution form.  Both
directions share ONE merge contract:

* YAML values always win - a non-empty YAML cell (nominal / tolerance
  / test point / clock frequency / Do-Not-Test) is never overwritten
  by the algorithm;
* a blank YAML cell is filled from the workbook;
* import APPENDS new rails / clocks / control-IO / GND nets the YAML
  does not have and never deletes an existing entry;
* every decision (kept / filled / added) goes to the returned report
  list (the GUI mirrors it into the Event-Log).

The module lives in ``yamlbuild`` because the YAML schema lives here -
the headless ``mtkgui.ict.netparse`` package never imports this.
"""
from __future__ import annotations

from mtkgui.ict.netparse import (NET_TYPE_CLOCK_SINGLE, NET_TYPE_GND_REF,
                                 NET_TYPE_POWER, NET_TYPE_SIGNAL,
                                 ParseNetsResult, ResourceLimits,
                                 NetRecord)
from mtkgui.ict.netparse.capacity import DEFAULT_LIMITS
from mtkgui.ict.netparse.export_testplan import (
    SHEET_CLOCK,
    SHEET_CONTROL_IO,
    SHEET_GND,
    SHEET_OTHERS,
    SHEET_POWER,
    SHEET_SUMMARY,
    export_testplan_markdown,
    export_testplan_xlsx,
)
from mtkgui.gui.yamlbuild.channel_allocation import UNSET
from mtkgui.gui.yamlbuild.model import YamlBuildModel

#: rail colour palette (same one the Test Work Flow page uses)
PALETTE = ("#ef4444", "#22c55e", "#3b82f6", "#f59e0b",
           "#a855f7", "#06b6d4", "#84cc16", "#f97316")

#: YAML section key carrying the imported Test Plan snapshot
SNAPSHOT_KEY = "ict_test_plan"


# ------------------------------------------------------------- xlsx read
def _read_sheets(path: str) -> dict:
    """Read every sheet into ``{sheet: [ {header: value} ... ]}``."""
    from openpyxl import load_workbook

    workbook = load_workbook(path, data_only=True)
    sheets: dict = {}
    for name in workbook.sheetnames:
        sheet = workbook[name]
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            sheets[name] = []
            continue
        if name == SHEET_SUMMARY:
            # the Summary sheet is a label / value list WITHOUT a
            # header row - every row is data
            sheets[name] = [
                {"label": str(row[0]).strip()
                 if row and row[0] is not None else "",
                 "value": row[1] if len(row) > 1 else ""}
                for row in rows
                if row and row[0] not in (None, "")]
            continue
        header = [str(value).strip() if value is not None else ""
                  for value in rows[0]]
        entries = []
        for row in rows[1:]:
            values = list(row)
            if all(v in (None, "") for v in values):
                continue
            entries.append({key: ("" if value is None else value)
                            for key, value in zip(header, values) if key})
        sheets[name] = entries
    return sheets


def _summary_value(rows: list, label: str) -> str:
    for row in rows:
        values = list(row.values())
        if values and str(values[0]).strip() == label:
            return str(values[1] if len(values) > 1 else "").strip()
    return ""


def _tokens(text) -> list[str]:
    return [tok for tok in str(text or "").split() if tok]


def _first_token(text) -> str:
    tokens = _tokens(text)
    return tokens[0] if tokens else ""


def _number(value) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------- model lookup
def _allocation(model: YamlBuildModel, kind: str) -> list[dict]:
    rows = (model.get_channel_allocation() or {}).get(kind) or []
    return [dict(row) for row in rows]


def _store_allocation(model: YamlBuildModel, kind: str,
                      rows: list[dict]) -> None:
    allocation = dict(model.get_channel_allocation() or {})
    allocation[kind] = rows
    model.set_channel_allocation(allocation)


def _rail_entries(model: YamlBuildModel) -> list[dict]:
    seq = dict(model.power_rails_up_sequence or {})
    return [dict(rail) for rail in (seq.get("rails") or [])]


def _store_rails(model: YamlBuildModel, rails: list[dict]) -> None:
    seq = dict(model.power_rails_up_sequence or {})
    seq["rails"] = rails
    model.set_power_rails(seq)


def _param_lines(model: YamlBuildModel, module: str, field: str) -> list[str]:
    raw = model.get_params(module).get(field, "")
    return [line.strip() for line in str(raw or "").splitlines()
            if line.strip()]


def _split_lines(model: YamlBuildModel, module: str, field: str) -> list:
    """``name:freq_hz:tolerance_pct`` -> ``[(name, freq, tol)]``."""
    parsed = []
    for line in _param_lines(model, module, field):
        parts = [part.strip() for part in line.split(":")]
        if not parts or not parts[0]:
            continue
        parsed.append((parts[0],
                       _number(parts[1]) if len(parts) > 1 else None,
                       _number(parts[2]) if len(parts) > 2 else None))
    return parsed


def _testable(model: YamlBuildModel) -> dict:
    return dict(model.imported.get("testable_nets") or {})


def _ensure_testable(model: YamlBuildModel, net: str, category: str,
                     members: list[str], report: list[str]) -> None:
    nets = _testable(model)
    if net in nets:
        report.append(f"kept testable net {net} ({category})")
    else:
        nets[net] = {"category": category,
                     "members": list(members) or [net]}
        report.append(f"added testable net {net} ({category})")
    model.imported["testable_nets"] = nets


# ------------------------------------------------------ xlsx -> YAML
def testplan_to_yaml(model: YamlBuildModel, xlsx_path: str | None = None,
                     md_path: str | None = None,
                     result: ParseNetsResult | None = None,
                     overwrite: bool = False) -> YamlBuildModel:
    """Import the Test Plan workbook into the project YAML (PART 2).

    Merge mode (default): only blank YAML cells are filled and new nets
    are appended - an existing YAML value is never overwritten
    (production truth wins).
    Overwrite mode (``overwrite=True``, File > Import ICT Test from
    Excel to Yaml): the workbook values REPLACE the ICT portion of the
    project YAML (power rails / channel allocation / clocks / control
    IO / DNT); every other YAML section (equipment, workflow, FCT, ...)
    stays untouched - user direction 2026-10-25.
    *result* (when supplied) enriches the stored snapshot with the
    confidence / provenance / sub-class evidence the workbook
    deliberately omits.

    Returns:
        The same *model* (``model.testplan_sync_report`` carries the
        kept / filled / overwritten / added decision list).
    """
    report: list[str] = []
    if not xlsx_path:
        report.append("no Test Plan workbook supplied - YAML unchanged")
        model.testplan_sync_report = report
        return model
    sheets = _read_sheets(xlsx_path)
    project = _summary_value(sheets.get(SHEET_SUMMARY, []), "project_name")

    power_rows = sheets.get(SHEET_POWER, [])
    clock_rows = sheets.get(SHEET_CLOCK, [])
    control_rows = sheets.get(SHEET_CONTROL_IO, [])
    gnd_rows = sheets.get(SHEET_GND, [])
    others_rows = sheets.get(SHEET_OTHERS, [])

    rails = _rail_entries(model)
    rail_by_name = {str(rail.get("name") or ""): rail for rail in rails}
    power_alloc = _allocation(model, "power")
    alloc_by_net = {str(row.get("net") or ""): row for row in power_alloc}
    clocks = list(model.se_clock_allocation or [])
    clock_by_net = {str(row.get("net") or ""): row for row in clocks}
    clock_alloc = _allocation(model, "clock")
    clock_alloc_by_net = {str(row.get("net") or ""): row
                          for row in clock_alloc}
    gpios = list(model.gpio_allocation or [])
    gpio_by_net = {str(row.get("net") or ""): row for row in gpios}
    gpio_alloc = _allocation(model, "gpio")
    gpio_alloc_by_net = {str(row.get("net") or ""): row
                         for row in gpio_alloc}
    dnt = set(_param_lines(model, "parse_ict", "power_dont_test"))

    # --------------------------------------------------------- Power
    for row in power_rows:
        net = str(row.get("Net") or "").strip()
        if not net:
            continue
        nominal = _number(row.get("Nominal (V)"))
        test_point = _first_token(row.get("Test Point(s)"))
        rail = rail_by_name.get(net)
        if rail is None:
            rail = {"name": net,
                    "nominal_v": nominal if nominal is not None else "",
                    "ramp_offset_s": 0.0,
                    "color": PALETTE[len(rails) % len(PALETTE)]}
            rails.append(rail)
            rail_by_name[net] = rail
            report.append(f"added power rail {net}")
        elif overwrite and nominal is not None:
            rail["nominal_v"] = nominal
            report.append(
                f"overwrote power rail {net} nominal_v={nominal:g}")
        elif rail.get("nominal_v") in (None, "", 0) and nominal is not None:
            rail["nominal_v"] = nominal
            report.append(f"filled power rail {net} nominal_v={nominal:g}")
        else:
            report.append(f"kept power rail {net} "
                          f"nominal_v={rail.get('nominal_v')}")
        alloc = alloc_by_net.get(net)
        if alloc is None:
            alloc = {"net": net, "test_point": test_point or UNSET,
                     "impedance": UNSET,
                     "r_gnd_min_ohm": str(row.get(
                         "R-GND Min limit (ohm)") or "") or UNSET,
                     "nominal_v": str(row.get("Nominal (V)") or "")
                     or UNSET,
                     "lower_v": str(row.get("Lower limit (V)") or "")
                     or UNSET,
                     "upper_v": str(row.get("Upper limit (V)") or "")
                     or UNSET,
                     "power_rails": str(row.get("DAQ AI Channel") or "")
                     or UNSET,
                     "voltage": str(row.get("R-V Channel") or "")
                     or UNSET}
            power_alloc.append(alloc)
            alloc_by_net[net] = alloc
            report.append(f"added power channel row {net}")
        elif overwrite:
            for key, column in (
                    ("test_point", "Test Point(s)"),
                    ("r_gnd_min_ohm", "R-GND Min limit (ohm)"),
                    ("nominal_v", "Nominal (V)"),
                    ("lower_v", "Lower limit (V)"),
                    ("upper_v", "Upper limit (V)"),
                    ("voltage", "R-V Channel"),
                    ("power_rails", "DAQ AI Channel")):
                value = str(row.get(column) or "").strip()
                alloc[key] = value or UNSET
            report.append(f"overwrote power channel row {net}")
        else:
            filled = False
            for key, column in (
                    ("test_point", "Test Point(s)"),
                    ("r_gnd_min_ohm", "R-GND Min limit (ohm)"),
                    ("nominal_v", "Nominal (V)"),
                    ("lower_v", "Lower limit (V)"),
                    ("upper_v", "Upper limit (V)"),
                    ("voltage", "R-V Channel"),
                    ("power_rails", "DAQ AI Channel")):
                value = str(row.get(column) or "").strip()
                current = str(alloc.get(key) or "").strip()
                if current in ("", UNSET) and value:
                    alloc[key] = value
                    filled = True
            report.append(f"{'filled' if filled else 'kept'} "
                          f"power channel row {net}")
        _ensure_testable(model, net, "Power",
                         _tokens(row.get("Test Point(s)")), report)

    # --------------------------------------------------------- Clocks
    for row in clock_rows:
        net = str(row.get("Net") or "").strip()
        if not net:
            continue
        khz = _number(row.get("Nominal (kHz)"))
        test_point = _first_token(row.get("Test Point(s)"))
        entry = clock_by_net.get(net)
        if entry is None:
            lower = _number(row.get("Lower limit (kHz)"))
            upper = _number(row.get("Upper limit (kHz)"))
            entry = {"net": net,
                     "freq_hz": (khz * 1000.0) if khz is not None else "",
                     "lower_hz": (lower * 1000.0
                                  if lower is not None else ""),
                     "upper_hz": (upper * 1000.0
                                  if upper is not None else ""),
                     "test_point": test_point}
            clocks.append(entry)
            clock_by_net[net] = entry
            report.append(f"added clock {net}")
        elif overwrite and khz is not None:
            entry["freq_hz"] = khz * 1000.0
            lower = _number(row.get("Lower limit (kHz)"))
            upper = _number(row.get("Upper limit (kHz)"))
            entry["lower_hz"] = (lower * 1000.0
                                 if lower is not None else "")
            entry["upper_hz"] = (upper * 1000.0
                                 if upper is not None else "")
            entry["test_point"] = test_point
            report.append(f"overwrote clock {net} freq_hz={khz * 1000.0:g}")
        elif entry.get("freq_hz") in (None, "", 0) and khz is not None:
            entry["freq_hz"] = khz * 1000.0
            report.append(f"filled clock {net} freq_hz={khz * 1000.0:g}")
        else:
            report.append(f"kept clock {net} "
                          f"freq_hz={entry.get('freq_hz')}")
        alloc = clock_alloc_by_net.get(net)
        if alloc is None:
            alloc = {"net": net, "test_point": test_point or UNSET,
                     "se_clock_hz": str(row.get("FREQ Channel") or "")
                     or UNSET, "band": UNSET}
            nominal_khz = _number(row.get("Nominal (kHz)"))
            lower = _number(row.get("Lower limit (kHz)"))
            upper = _number(row.get("Upper limit (kHz)"))
            if nominal_khz is not None:
                alloc["nominal_khz"] = f"{nominal_khz:.3f}"
            if lower is not None:
                alloc["lower_khz"] = f"{lower:.3f}"
            if upper is not None:
                alloc["upper_khz"] = f"{upper:.3f}"
            clock_alloc.append(alloc)
            clock_alloc_by_net[net] = alloc
            report.append(f"added clock channel row {net}")
        elif overwrite:
            alloc["test_point"] = test_point or UNSET
            alloc["se_clock_hz"] = (str(row.get("FREQ Channel") or "")
                                    or UNSET)
            nominal_khz = _number(row.get("Nominal (kHz)"))
            lower = _number(row.get("Lower limit (kHz)"))
            upper = _number(row.get("Upper limit (kHz)"))
            if nominal_khz is not None:
                alloc["nominal_khz"] = f"{nominal_khz:.3f}"
            if lower is not None:
                alloc["lower_khz"] = f"{lower:.3f}"
            if upper is not None:
                alloc["upper_khz"] = f"{upper:.3f}"
            report.append(f"overwrote clock channel row {net}")
        else:
            report.append(f"kept clock channel row {net}")
        _ensure_testable(model, net, "Clock",
                         _tokens(row.get("Test Point(s)")), report)

    # ----------------------------------------------------- Control IO
    for row in control_rows:
        net = str(row.get("Net") or "").strip()
        if not net:
            continue
        test_point = _first_token(row.get("Test Point(s)"))
        entry = gpio_by_net.get(net)
        if entry is None:
            entry = {"net": net, "test_point": test_point}
            gpios.append(entry)
            gpio_by_net[net] = entry
            report.append(f"added control IO {net}")
        elif overwrite:
            entry["test_point"] = test_point
            report.append(f"overwrote control IO {net}")
        else:
            report.append(f"kept control IO {net}")
        alloc = gpio_alloc_by_net.get(net)
        if alloc is None:
            alloc = {"net": net, "test_point": test_point or UNSET,
                     "dio_channel": UNSET}
            gpio_alloc.append(alloc)
            gpio_alloc_by_net[net] = alloc
            report.append(f"added control IO channel row {net}")
        elif overwrite:
            alloc["test_point"] = test_point or UNSET
            report.append(f"overwrote control IO channel row {net}")
        else:
            report.append(f"kept control IO channel row {net}")
        _ensure_testable(model, net, "GPIO",
                         _tokens(row.get("Test Point(s)")), report)

    # ------------------------------------------------------------- GND
    pcb_gnd = [row for row in gnd_rows
               if str(row.get("sub_class(pcb/chassis/shield)") or "") ==
               "pcb"]
    reference = str((pcb_gnd[0].get("net") if pcb_gnd else "") or "")
    for row in gnd_rows:
        net = str(row.get("net") or "").strip()
        if not net:
            continue
        _ensure_testable(model, net, "GND",
                         [str(row.get("test_point") or "")], report)
        nets = _testable(model)
        info = nets.get(net) or {}
        if net == reference and not info.get("is_reference_gnd"):
            info["is_reference_gnd"] = True
            nets[net] = info
            model.imported["testable_nets"] = nets
            report.append(f"set GND reference {net} (pcb rank 0)")

    # ---------------------------------------------------------- Others
    for row in others_rows:
        net = str(row.get("net") or "").strip()
        if not net:
            continue
        if net in dnt:
            report.append(f"kept Do-Not-Test {net}")
        else:
            dnt.add(net)
            report.append(f"added Do-Not-Test {net}")

    _store_rails(model, rails)
    _store_allocation(model, "power", power_alloc)
    _store_allocation(model, "clock", clock_alloc)
    _store_allocation(model, "gpio", gpio_alloc)
    model.se_clock_allocation = clocks
    model.gpio_allocation = gpios
    model.set_params("parse_ict",
                     {"power_dont_test": "\n".join(sorted(dnt))})
    model.ict_test_plan = _snapshot(project, sheets, result)
    model.testplan_sync_report = report
    model.changed = True
    return model


def _snapshot(project: str, sheets: dict,
              result: ParseNetsResult | None) -> dict:
    """The YAML-stored Test Plan snapshot (evidence survives re-export).

    Categories use the FIXED names this module's rebuild understands
    (``Power`` / ``SE-Clock`` / ``Control IO`` / ``GND`` / ``Others``) -
    never the GUI label constants.
    """
    records: dict = {}
    if result is not None:
        for category, bucket in (("Power", result.power),
                                 ("SE-Clock", result.clock),
                                 ("Control IO", result.control_io),
                                 ("GND", result.gnd),
                                 ("Others", result.others)):
            for rec in bucket:
                records[rec.name] = {
                    "category": category,
                    "confidence": rec.confidence or "",
                    "provenance": rec.provenance or "",
                    "sub_class": rec.sub_class or "",
                    "input_rail": bool(rec.input_rail),
                    "members": list(rec.members),
                }
    return {
        "project_name": project,
        "source": result.source if result is not None else "",
        "format": result.format if result is not None else "",
        "records": records,
        "sheets": {name: rows for name, rows in sheets.items()},
    }


# ------------------------------------------------------ YAML -> output
def _record_of(net: str, info: dict) -> NetRecord:
    """One YAML snapshot entry -> a classified NetRecord."""
    category = str(info.get("category") or "Others")
    if category == "Power":
        net_type = NET_TYPE_POWER
    elif category in ("Clock", "SE-Clock"):
        net_type = NET_TYPE_CLOCK_SINGLE
    elif category == "GND":
        net_type = NET_TYPE_GND_REF
    else:
        net_type = NET_TYPE_SIGNAL
    return NetRecord(name=net,
                     members=list(info.get("members") or [net]),
                     net_type=net_type,
                     sub_class=str(info.get("sub_class") or ""),
                     provenance=str(info.get("provenance") or ""),
                     confidence=str(info.get("confidence") or ""),
                     input_rail=bool(info.get("input_rail")))


def _result_from_snapshot(model: YamlBuildModel) -> ParseNetsResult:
    """Rebuild the parse result from the YAML snapshot (no data loss)."""
    snapshot = dict(model.ict_test_plan or {})
    records = snapshot.get("records") or {}
    result = ParseNetsResult(source=str(snapshot.get("source") or ""),
                             format=str(snapshot.get("format") or ""))
    for net, info in records.items():
        category = str(info.get("category") or "Others")
        rec = _record_of(net, info)
        if category == "Power":
            result.power.append(rec)
        elif category in ("Clock", "SE-Clock"):
            result.clock.append(rec)
        elif category == "GND":
            result.gnd.append(rec)
        elif category == "Control IO":
            result.control_io.append(rec)
        else:
            result.others.append(rec)
    for row in (snapshot.get("sheets") or {}).get(SHEET_OTHERS, []):
        net = str(row.get("net") or "").strip()
        if not net or net in records:
            continue
        result.others.append(NetRecord(
            name=net, members=[net], net_type=NET_TYPE_SIGNAL,
            sub_class=str(row.get("sub_class") or ""),
            provenance=str(row.get("provenance") or "")))
    result.total = len(records)
    return result


def _result_from_model(model: YamlBuildModel) -> ParseNetsResult:
    """Fallback: rebuild from ``imported.testable_nets`` + allocations."""
    nets = _testable(model)
    power = [dict(row) for row in _allocation(model, "power")]
    clocks = [dict(row) for row in _allocation(model, "clock")]
    ctrl = [dict(row) for row in _allocation(model, "gpio")]
    by_net = {str(row.get("net") or ""): row
              for row in power + clocks + ctrl}
    result = ParseNetsResult(
        source=str((model.imported.get("net") or {}).get("file") or ""),
        total=len(nets))
    for net, info in nets.items():
        category = str(info.get("category") or "GPIO")
        row = by_net.get(net) or {}
        override_members = _tokens(row.get("test_point"))
        rec = _record_of(net, {"category": category,
                               "members": info.get("members")
                               or override_members or [net],
                               "provenance": "yaml",
                               "input_rail": False})
        if category == "Power":
            result.power.append(rec)
        elif category == "Clock":
            result.clock.append(rec)
        elif category == "GND":
            result.gnd.append(rec)
        else:
            result.control_io.append(rec)
    for line in _param_lines(model, "parse_ict", "power_dont_test"):
        if line in nets:
            continue
        result.others.append(NetRecord(name=line, members=[line],
                                       net_type=NET_TYPE_SIGNAL,
                                       sub_class="", provenance="yaml:dnt"))
    return result


def _yaml_overrides(model: YamlBuildModel) -> dict:
    """Human YAML values per net (the merge contract's winning side)."""
    overrides: dict = {}

    def slot(net: str) -> dict:
        return overrides.setdefault(net, {})

    for rail in _rail_entries(model):
        net = str(rail.get("name") or "").strip()
        if not net:
            continue
        if rail.get("nominal_v") not in (None, "", 0):
            slot(net)["nominal_v"] = rail.get("nominal_v")
    tolerance = _number(model.get_params("rails")
                        .get("voltage_tolerance_pct", ""))
    for row in _allocation(model, "power"):
        net = str(row.get("net") or "").strip()
        if not net:
            continue
        test_point = str(row.get("test_point") or "").strip()
        if test_point and test_point != UNSET:
            slot(net)["test_point"] = test_point
        if str(row.get("voltage") or "").strip() not in ("", UNSET):
            slot(net)["r_v_channel"] = row.get("voltage")
        if str(row.get("power_rails") or "").strip() not in ("", UNSET):
            slot(net)["daq_ai_channel"] = row.get("power_rails")
    for net, values in overrides.items():
        nominal = _number(values.get("nominal_v"))
        if nominal is None or tolerance is None:
            continue
        values.setdefault("lower_v", nominal * (1 - tolerance / 100.0))
        values.setdefault("upper_v", nominal * (1 + tolerance / 100.0))

    for entry in (model.se_clock_allocation or []):
        net = str(entry.get("net") or "").strip()
        if not net:
            continue
        freq = _number(entry.get("freq_hz"))
        if freq:
            slot(net)["nominal_khz"] = freq / 1000.0
        if str(entry.get("test_point") or "").strip():
            slot(net)["test_point"] = entry.get("test_point")
    for name, freq, tol in _split_lines(model, "clocks", "clocks"):
        if freq:
            slot(name)["nominal_khz"] = freq / 1000.0
            if tol:
                slot(name)["lower_khz"] = freq / 1000.0 * (1 - tol / 100.0)
                slot(name)["upper_khz"] = freq / 1000.0 * (1 + tol / 100.0)
    for row in _allocation(model, "clock"):
        net = str(row.get("net") or "").strip()
        if not net:
            continue
        if str(row.get("test_point") or "").strip() not in ("", UNSET):
            slot(net)["test_point"] = row.get("test_point")
        if str(row.get("se_clock_hz") or "").strip() not in ("", UNSET):
            slot(net)["freq_channel"] = row.get("se_clock_hz")

    for entry in (model.gpio_allocation or []):
        net = str(entry.get("net") or "").strip()
        if net and str(entry.get("test_point") or "").strip():
            slot(net)["test_point"] = entry.get("test_point")
    for row in _allocation(model, "gpio"):
        net = str(row.get("net") or "").strip()
        if net and str(row.get("test_point") or "").strip() not in \
                ("", UNSET):
            slot(net)["test_point"] = row.get("test_point")
    # input-rail evidence travels with the snapshot (the re-export must
    # keep the Power tree flow markers)
    for net, info in ((model.ict_test_plan or {}).get("records")
                      or {}).items():
        if info.get("input_rail"):
            slot(net)["input_rail"] = True
    return overrides


def _wide_limits(result: ParseNetsResult) -> ResourceLimits:
    """Never drop YAML content on re-export (widen past the defaults)."""
    lf = sum(1 for rec in result.clock
             if (rec.priority or {}).get("band") == "LF")
    return ResourceLimits(
        power_pts=max(DEFAULT_LIMITS.power_pts, len(result.power)),
        rails_up=max(DEFAULT_LIMITS.rails_up, len(result.power)),
        clock_lf=max(DEFAULT_LIMITS.clock_lf, lf),
        clock_hf=max(DEFAULT_LIMITS.clock_hf,
                     len(result.clock) - lf),
        ctrl_io=max(DEFAULT_LIMITS.ctrl_io, len(result.control_io)))


def yaml_to_testplan(model: YamlBuildModel, xlsx_path: str,
                     md_path: str) -> None:
    """Re-export the Test Plan files from the YAML (PART 2).

    YAML values are merged ON TOP of the algorithm output (nominal /
    tolerance / test point / clock frequency / channel allocation);
    the worksheet never overwrites a non-empty YAML value.
    """
    report: list[str] = []
    if model.ict_test_plan:
        result = _result_from_snapshot(model)
        report.append("source: YAML test-plan snapshot")
    else:
        result = _result_from_model(model)
        report.append("source: YAML testable nets + channel allocation")
    overrides = _yaml_overrides(model)
    limits = _wide_limits(result)
    project = str(model.get_params("design_input").get("product_id")
                  or "").strip()
    if not project:
        project = str((model.ict_test_plan or {}).get("project_name")
                      or model.project_key())
    rows = export_testplan_xlsx(result, limits, xlsx_path, project,
                                overrides)
    sections = export_testplan_markdown(result, limits, md_path, project,
                                        overrides)
    report.append(f"exported {rows} sheet rows, {sections} evidence "
                  f"net(s)")
    report.append(f"merged {len(overrides)} YAML net value set(s)")
    model.testplan_sync_report = report
    model.changed = True


__all__ = ["SNAPSHOT_KEY", "testplan_to_yaml", "yaml_to_testplan"]
