# -*- coding: utf-8 -*-
"""Project configuration stored as a YAML file.

One YAML file per product / project, named

    ProductPartNumber_CoreID_Batch_rev1.0.yaml
    e.g. MTK-DEMO-A1_10342_proto_rev1.0.yaml

It stores:
  * product information (part number, core ID, batch - the serial number
    is per-unit and therefore intentionally NOT stored)
  * the verified equipment configuration (every block of the Equipment
    page, with its connection / status information)
  * the Test Work Flow: overall flow, ICT test cases (including the
    editable per-step wait times), the power-rails up-sequence capture
    setup and the FCT message-test cases.
  * the console channels (serial / SSH) of the Test Work Flow page,
    together with their connection parameters
"""

import re
from datetime import datetime

import yaml

from .test_workflow_page import DURATION_S, RAILS, SAMPLE_HZ

REVISION = "1.1"
SOFTWARE = "mtk-gui v2.0.0"


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
def build_config(workflow_page, equipment_page):
    """Collect the current project configuration from the pages."""
    product = workflow_page.product_info()
    return {
        "project": {
            "software": SOFTWARE,
            "revision": REVISION,
            "created": datetime.now().isoformat(timespec="seconds"),
        },
        "product": {
            "part_number": product["part"],
            "core_id": product["core_id"],
            "batch": product["batch"],
            # serial number is per-unit -> excluded on purpose
        },
        "equipment": _equipment_to_yaml(equipment_page.configs),
        "console": workflow_page.multi_console.yaml_channels(),
        "test_workflow": _workflow_to_yaml(workflow_page),
    }


def _equipment_to_yaml(configs):
    """Equipment page configs -> plain YAML-safe structure."""
    data = {}
    for key, cfg in configs.items():
        entry = {"title": cfg["title"]}
        if "fields" in cfg:
            entry["fields"] = {label: value for label, value in cfg["fields"]}
        if "table" in cfg:
            entry["table"] = [
                {"item": item, "role": role, "status": status}
                for item, role, status in cfg["table"]
            ]
        data[key] = entry
    return data


def _workflow_to_yaml(page):
    overall_flow = []
    for r in range(page.overall.rowCount()):
        stage_item = page.overall.item(r, 1)
        overall_flow.append({
            "stage": stage_item.text(),
            "description": stage_item.toolTip(),
        })

    ict_cases = []
    for (kind, name, unit, _measured, lo, hi), enable, wait, timeout in zip(
            page.ict_steps, page.ict_enables, page.ict_waits,
            page.ict_timeouts):
        ict_cases.append({
            "name": name,
            "kind": kind,          # "op" -> Done/Error, "test" -> PASS/FAIL
            "enable": enable,
            "wait_ms": wait,
            "timeout_ms": timeout,
            "unit": unit,
            "threshold_min": lo,
            "threshold_max": hi,
        })

    rails = {
        "instrument": "Keysight U2355A analog input",
        "channels": len(RAILS),
        "duration_s": DURATION_S,
        "sample_rate_hz": SAMPLE_HZ,
        "judgment": "record only - no pass/fail",
        "rails": [
            {"name": name, "nominal_v": vnom,
             "ramp_offset_s": ramp_off, "color": color}
            for name, color, vnom, ramp_off in RAILS
        ],
    }

    fct_cases = []
    for name, enable, wait, timeout in zip(
            page.fct_rows, page.fct_enables, page.fct_waits,
            page.fct_timeouts):
        fct_cases.append({
            "name": name,
            "enable": enable,
            "wait_ms": wait,
            "timeout_ms": timeout,
        })

    return {
        "overall_flow": overall_flow,
        "stop_if_failure": page.stop_if_fail_cb.isChecked(),
        "stop_if_any_short": page.stop_if_short_cb.isChecked(),
        "ict_test_cases": ict_cases,
        "power_rails_up_sequence": rails,
        "fct_test_cases": fct_cases,
    }


# --------------------------------------------------------------------------
# file name
# --------------------------------------------------------------------------
def _clean(text, fallback):
    """Make one filename component filesystem-safe."""
    text = re.sub(r'[\\/:*?"<>|\s]+', "-", (text or "").strip())
    return text.strip("-.") or fallback


def default_filename(config):
    """ProductPartNumber_CoreID_Batch_rev1.0.yaml"""
    product = config.get("product", {})
    part = _clean(product.get("part_number"), "PROJECT")
    core = _clean(product.get("core_id"), "00000")
    batch = _clean(product.get("batch"), "freebatch")
    return f"{part}_{core}_{batch}_rev{REVISION}.yaml"


# --------------------------------------------------------------------------
# save / load
# --------------------------------------------------------------------------
def save_config(config, path):
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, sort_keys=False, allow_unicode=True,
                  default_flow_style=False, width=120)


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def apply_config(config, workflow_page, equipment_page):
    """Restore a loaded configuration into the pages.

    The serial number is not part of the file (per-unit input), so the
    product fields are restored without touching it."""
    product = config.get("product", {})
    if product.get("part_number") is not None:
        workflow_page.part_edit.setText(str(product["part_number"]))
    if product.get("core_id") is not None:
        workflow_page.core_edit.setText(str(product["core_id"]))
    if product.get("batch") is not None:
        batch = str(product["batch"])
        workflow_page.batch_edit.setText("" if batch == "freebatch" else batch)

    # Overall Flow stop policies (defaults: stop on failure = False,
    # stop on any short = True)
    tw = config.get("test_workflow", {})
    if "stop_if_failure" in tw:
        workflow_page.stop_if_fail_cb.setChecked(
            bool(tw["stop_if_failure"]))
    if "stop_if_any_short" in tw:
        workflow_page.stop_if_short_cb.setChecked(
            bool(tw["stop_if_any_short"]))

    # per-step enable / wait / timeout for ICT. The step list itself
    # (name / kind / unit / thresholds) is rebuilt from the YAML so a
    # project file can expand aggregate tests into individual nets.
    cases = config.get("test_workflow", {}).get("ict_test_cases", [])
    if cases:
        try:
            workflow_page.ict_steps = [
                (str(c.get("kind", "test")),
                 str(c.get("name", "")),
                 str(c.get("unit", "—")),
                 "—",
                 str(c.get("threshold_min", "—")),
                 str(c.get("threshold_max", "—")))
                for c in cases
            ]
            workflow_page.ict.setRowCount(len(workflow_page.ict_steps))
            workflow_page.ict_enables = [
                bool(c.get("enable", True)) for c in cases]
            workflow_page.ict_waits = [
                max(100, min(9999, int(c.get("wait_ms", 100))))
                for c in cases]
            workflow_page.ict_timeouts = [
                max(1000, min(99999, int(c.get("timeout_ms", 5000))))
                for c in cases]
        except (TypeError, ValueError):
            pass
        else:
            workflow_page._fill_ict(placeholder=True)

    # per-step enable / wait / timeout for FCT. The row list (name /
    # justification) is rebuilt from the YAML so a project file can
    # carry different FCT test cases than the hard-coded defaults.
    fct_cases = config.get("test_workflow", {}).get("fct_test_cases", [])
    if fct_cases:
        try:
            workflow_page.fct_rows = [
                str(c.get("name", "")) for c in fct_cases]
            workflow_page.fct.setRowCount(len(workflow_page.fct_rows))
            workflow_page.fct_enables = [
                bool(c.get("enable", True)) for c in fct_cases]
            workflow_page.fct_waits = [
                max(100, min(9999, int(c.get("wait_ms", 100))))
                for c in fct_cases]
            workflow_page.fct_timeouts = [
                max(1000, min(99999, int(c.get("timeout_ms", 5000))))
                for c in fct_cases]
        except (TypeError, ValueError):
            pass
        else:
            workflow_page._fill_fct_all()

    equipment = config.get("equipment")
    if equipment:
        equipment_page.configs = _equipment_from_yaml(equipment)

    # console channels defined by the project (older files have no
    # 'console' section -> nothing to restore)
    channels = config.get("console") or []
    if channels:
        workflow_page.multi_console.apply_yaml_channels(channels)


def _equipment_from_yaml(data):
    """YAML structure -> the dict shape the Equipment page expects."""
    configs = {}
    for key, entry in data.items():
        cfg = {"title": entry.get("title", key)}
        if entry.get("fields"):
            cfg["fields"] = [(label, value)
                             for label, value in entry["fields"].items()]
        if entry.get("table"):
            cfg["table"] = [(row["item"], row["role"], row["status"])
                            for row in entry["table"]]
        configs[key] = cfg
    return configs
