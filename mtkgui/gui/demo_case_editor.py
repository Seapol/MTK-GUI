# -*- coding: utf-8 -*-
"""P2-3 AI-case visual editor demo (headless-safe, rc=0 on success).

Full closed loop offscreen: real casegen draft -> grouped tree list ->
single-case visual edit + validate -> save (snapshot + [CASE] audit) ->
dimension toggles -> version lock intercept -> history traceability.
Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.casegen.generator import CaseGenerator  # noqa: E402
from mtkgui.engine.casegen.netlist import NetlistParser  # noqa: E402
from mtkgui.gui.case_editor import CaseEditorPage  # noqa: E402
from mtkgui.gui.case_store import (LockedCaseError, CaseStore,  # noqa: E402
                                   categorize)

NETLIST = """
# demo netlist (P1-16 text format)
NET 3V3 U1.VDD C2.1
NET 1V8 U1.CORE
RAIL 1V8 FROM 3V3 LDO
SEQ 3V3 1
NET CLK_32K U2.1
NET GPIO1 U1.10 R2.1
"""


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="p2_3_demo_")
    nl_path = os.path.join(tmp, "net.txt")
    with open(nl_path, "w", encoding="utf-8") as fh:
        fh.write(NETLIST)

    # 0. reuse P1-16 casegen untouched to produce the AI draft
    gen = CaseGenerator()
    fragment = gen.generate([nl_path])
    assert NetlistParser is not None
    cfg = dict(fragment)
    names = [c["name"] for c in cfg["ict_test_cases"]]
    assert any(n.startswith("PWR 1V8") for n in names), "power tree"
    assert any(n.startswith("CLK") for n in names), "clock row"
    assert any(n.startswith("SIG") for n in names), "signal row"

    yaml_path = os.path.join(tmp, "project.yaml")
    CaseStore.save(cfg, yaml_path)
    store = CaseStore(snapshot_dir=os.path.join(tmp, "snaps"))

    # 1. store layer: categorize + edit + history + lock
    assert categorize({"name": "PWR 3V3 Voltage"}) == "电源网络"
    assert categorize({"name": "CLK X Frequency"}) == "时钟网络"
    assert categorize({"name": "SIG X Continuity"}) == "信号网络"
    assert categorize({"name": "Fixture Clamp Down", "kind": "op"}) == \
        "操作流程"

    changed = store.apply_case_edit(
        cfg, names[0], {"threshold_min": "0.9", "priority": "2",
                        "retry": "3"})
    assert {c.field for c in changed} == {"threshold_min", "priority",
                                          "retry"}, changed
    assert len(store.history(cfg)) == 1, "history entry recorded"
    try:
        store.apply_case_edit(cfg, names[0], {"wait_ms": "abc"})
        raise SystemExit("illegal value must be rejected")
    except ValueError:
        pass

    store.set_locked(cfg, names[0], True)
    assert store.is_locked(cfg, names[0])
    try:
        store.apply_case_edit(cfg, names[0], {"notes": "x"})
        raise SystemExit("locked case must be immutable")
    except LockedCaseError:
        pass
    store.set_locked(cfg, names[0], False)
    store.apply_case_edit(cfg, names[0], {"notes": "ok"})
    assert store.history(cfg)[-1]["changed"][0]["new"] == "ok"

    # dimension batch toggle skips locked cases
    store.set_locked(cfg, names[0], True)
    lockable = next(c for c in cfg["ict_test_cases"]
                    if c.get("test_dim") in ("impedance", "voltage",
                                             "timing"))
    dim0 = str(lockable["test_dim"])
    touched = store.set_dimension_enabled(cfg, dim0, False)
    assert all(c.case != names[0] for c in touched), "locked skipped"

    # 2. GUI page: tree grouping -> form edit -> save -> lock guard
    page = CaseEditorPage(yaml_path, store=store)
    page.interactive = False
    applied = []
    page.cases_applied.connect(applied.append)

    cats = {page.tree.topLevelItem(i).text(0)
            for i in range(page.tree.topLevelItemCount())}
    assert cats == {"电源网络", "时钟网络", "信号网络",
                    "操作流程"}, cats

    target_name = next(n for n in names if n.startswith("PWR 3V3"))
    item = None
    for i in range(page.tree.topLevelItemCount()):
        group = page.tree.topLevelItem(i)
        for j in range(group.childCount()):
            if group.child(j).text(0) == target_name:
                item = group.child(j)
    assert item is not None, "target case visible in grouped tree"
    page.tree.setCurrentItem(item)
    page.f_prio.setText("5")
    page.f_notes.setPlainText("人工终审微调")
    result = page.on_save()
    assert result is not None, "legal save passes"
    saved_cfg = CaseStore.load(yaml_path)
    saved_case = next(c for c in saved_cfg["ict_test_cases"]
                      if c["name"] == target_name)
    assert saved_case["priority"] == 5, "priority persisted"
    assert saved_case["notes"] == "人工终审微调", "notes persisted"
    assert applied, "cases_applied signal fired"

    # lock via page button -> save intercepted
    page.on_lock_toggle()
    page.f_notes.setPlainText("should not land")
    assert page.on_save() is None, "locked save intercepted"
    page.on_lock_toggle()  # unlock again
    assert not store.is_locked(CaseStore.load(yaml_path), target_name)

    # 3. snapshot round-trip
    snaps = sorted(os.listdir(store.snapshot_dir))
    assert snaps, "snapshots recorded"
    snap_cfg = store.load_snapshot(snaps[-1][:-len(".yaml")])
    assert isinstance(snap_cfg, dict) and snap_cfg

    # 4. traceability panel shows AI gen + manual edits
    page.reload()
    text = page.trace.toPlainText()
    assert "AI生成" in text, "AI provenance shown"
    assert "gui-editor" in text, "manual edit history shown"
    assert "版本锁定" in text, "lock state shown"

    print("[P2-3 case editor demo] visual case editor OK — grouped list, "
          "single-case visual edit, dimension toggles, version lock "
          "interception, snapshots + AI/manual traceability all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
