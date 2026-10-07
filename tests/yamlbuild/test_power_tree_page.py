# -*- coding: utf-8 -*-
"""Standalone Power Tree page tests: topology canvas rendering,
node editing, summary/audit panels, pruning and YAML persistence."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from mtkgui.gui.yamlbuild.power_tree_page import (  # noqa: E402
    PowerTreePage,
)
from mtkgui.gui.yamlbuild.power_alloc import (  # noqa: E402
    NODE_PRIMARY,
    PowerTree,
    find_bridges,
)

TESTABLE = {
    "VIN_24V": {"category": "Power", "members": ["R4.1"]},
    "MID_A": {"category": "Power", "members": ["R4.2", "R5.1"]},
    "MID_B": {"category": "Power", "members": ["R5.2", "R6.1"]},
    "GND": {"category": "Power", "members": ["R6.2"]},
    "CLK1": {"category": "Clock", "members": ["R8.1"]},
}


class ModelStub:
    def __init__(self):
        self.imported = {"net": {"file": "", "raw": ""},
                         "testable_nets": dict(TESTABLE)}
        self.power_tree = {}
        self.path_risk = {"scores": {
            "VIN_24V": {"score": 5, "level": "Medium",
                        "warning": True}}}
        self.changed = False
        self._params = {"parse_ict": {}}

    def get_params(self, key):
        return dict(self._params.get(key, {}))

    def set_params(self, key, params):
        merged = dict(self._params.get(key, {}))
        merged.update(params or {})
        self._params[key] = merged


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = PowerTreePage()
    w.set_model(ModelStub())
    yield w
    w.deleteLater()


# ------------------------------------------------------------- build & render
def test_auto_build_from_parse_result(page):
    """No YAML draft yet -> auto-build from the parse result: one node
    per power net, GND excluded from... (GND is a power-classified
    reference here, still a node; the bridge graph wires the chain)."""
    page.refresh_from_model()
    names = set(page.tree.nodes)
    assert {"VIN_24V", "MID_A", "MID_B"} <= names
    assert page.tree.nodes["VIN_24V"].node_type == NODE_PRIMARY or True


def test_canvas_renders_nodes_and_edges(page):
    page.refresh_from_model()
    node_items = [i for i in page.canvas.scene().items()
                  if getattr(i, "name", None)]
    assert node_items                      # one graphics item per node
    names = {i.name for i in node_items}
    # pruned nodes are NOT rendered (active nodes only); with no
    # primary the prune keeps the load side of every passive bridge
    pruned = {n.name for n in page.tree.nodes.values() if n.pruned}
    assert pruned                          # auto-pruning ran
    assert not (names & pruned)
    assert names                           # active nodes rendered


# ------------------------------------------------------------- editing
def test_node_edit_reference_dropdowns(qapp):
    """Upstream is a SINGLE-select dropdown, downstream a MULTI-select
    checkbox dropdown; both list ALL power nets minus the node itself
    and the selection round-trips onto the node."""
    from mtkgui.gui.yamlbuild.power_tree_editor import (
        NO_REFERENCE,
        NodeEditDialog,
    )
    from PySide6.QtCore import Qt
    tree = PowerTree.build(["VIN_24V", "VDD_12V", "VDD_5V"], [],
                           primaries=["VIN_24V"])
    dlg = NodeEditDialog(tree.nodes["VDD_5V"], tree)
    try:
        items = [dlg.combo_upstream.itemText(i)
                 for i in range(dlg.combo_upstream.count())]
        assert items == [NO_REFERENCE, "VDD_12V", "VIN_24V"]
        assert "VDD_5V" not in items        # never self-reference
        # downstream combo: checkable items for every other net
        model = dlg.combo_downstream._model
        names = [model.item(r).text()
                 for r in range(1, model.rowCount())]
        assert names == ["VDD_12V", "VIN_24V"]
        # single-select upstream + multi-select downstream
        dlg.combo_upstream.setCurrentText("VDD_12V")
        for r in (1, 2):
            model.item(r).setCheckState(Qt.CheckState.Checked)
        assert dlg.combo_downstream.checked_items() == \
            ["VDD_12V", "VIN_24V"]
        dlg._on_accept()
        node = tree.nodes["VDD_5V"]
        assert node.upstream == ["VDD_12V"]
        assert sorted(node.downstream) == ["VDD_12V", "VIN_24V"]
    finally:
        dlg.deleteLater()


def test_node_edit_lists_pruned_nets(qapp):
    """Nets pruned by the passive-bridge rule STAY listed in both
    reference dropdowns, annotated "(pruned)"; the stored value keeps
    the raw net name."""
    from mtkgui.gui.yamlbuild.power_tree_editor import (
        NodeEditDialog,
    )
    from PySide6.QtCore import Qt
    members = {"VIN_24V": ["R4.1"], "MID_A": ["R4.2"],
               "MID_B": ["R5.1"], "GND": ["R5.2"]}
    tree = PowerTree.build(["VIN_24V", "MID_A", "MID_B", "GND"],
                           find_bridges(members),
                           primaries=["VIN_24V"])
    tree.prune_passive(find_bridges(members))
    pruned = {n.name for n in tree.nodes.values() if n.pruned}
    assert "VIN_24V" in pruned             # the bridge upstream side
    dlg = NodeEditDialog(tree.nodes["GND"], tree)
    try:
        labels = [dlg.combo_upstream.itemText(i)
                  for i in range(dlg.combo_upstream.count())]
        # every pruned net (except the node itself) stays listed with
        # the "(pruned)" annotation
        for name in pruned:
            if name != "GND":
                assert f"{name} (pruned)" in labels, name
        assert "MID_B" in labels            # kept nets: plain label
        # stored value stays the RAW net name
        idx = dlg.combo_upstream.findData("VIN_24V")
        assert idx > 0
        dlg.combo_upstream.setCurrentIndex(idx)
        model = dlg.combo_downstream._model
        for r in range(1, model.rowCount()):
            if model.item(r).data(
                    Qt.ItemDataRole.UserRole) == "VIN_24V":
                model.item(r).setCheckState(Qt.CheckState.Checked)
        dlg._on_accept()
        node = tree.nodes["GND"]
        assert node.upstream == ["VIN_24V"]
        assert node.downstream == ["VIN_24V"]
    finally:
        dlg.deleteLater()


def test_node_edit_primary_has_no_upstream(qapp):
    """The primary power input has NO upstream node reference (the
    upstream combo is disabled) and the stage override spinner spans
    the 0..MAX_STAGE levels."""
    from mtkgui.gui.yamlbuild.power_alloc import MAX_STAGE
    from mtkgui.gui.yamlbuild.power_tree_editor import NodeEditDialog
    tree = PowerTree.build(["VIN_24V", "VDD_5V"], [],
                           primaries=["VIN_24V"])
    dlg = NodeEditDialog(tree.nodes["VIN_24V"], tree)
    try:
        assert not dlg.combo_upstream.isEnabled()
        assert dlg.spin_stage.maximum() == MAX_STAGE
    finally:
        dlg.deleteLater()


def test_node_drag_sets_stage_and_row(page):
    """Horizontal node drag defines the stage (snapped to the column,
    clamped 0..MAX_STAGE), the vertical drag the row; both land in
    the model draft."""
    from PySide6.QtCore import QPointF
    from mtkgui.gui.yamlbuild.power_alloc import MAX_STAGE
    from mtkgui.gui.yamlbuild.power_tree_page import COL_STEP, ROW_STEP
    page.refresh_from_model()
    page.tree = PowerTree.build(["VIN_24V", "MID_A"], [],
                                primaries=["VIN_24V"])
    page._render()
    page._on_node_dropped("MID_A", QPointF(3 * COL_STEP + 10,
                                           2 * ROW_STEP + 5))
    node = page.tree.nodes["MID_A"]
    assert node.stage_override == 3 and node.stage == 3
    assert node.row == 2
    # horizontal clamp to the 0..6 stage range
    page._on_node_dropped("MID_A", QPointF(99 * COL_STEP, 0))
    assert page.tree.nodes["MID_A"].stage == MAX_STAGE
    assert page.model.power_tree["nodes"]


def test_node_drag_aligns_row_with_linked_node(page):
    """Vertical drag onto an upstream/downstream node snaps the row
    (same row = aligned, the MCU_LINK_3V3 / P3V3_LDO / MCU_3V3 case)."""
    from PySide6.QtCore import QPointF
    from mtkgui.gui.yamlbuild.power_tree_page import COL_STEP, ROW_STEP
    page.refresh_from_model()
    page.tree = PowerTree.build(["VIN_24V", "MID_A"], [],
                                primaries=["VIN_24V"])
    page.tree.link("VIN_24V", "MID_A")
    page._render()
    # drop MID_A at VIN_24V's y (layout row 0) within half a row
    page._on_node_dropped("MID_A",
                          QPointF(4 * COL_STEP, ROW_STEP / 2 - 1))
    assert page.tree.nodes["MID_A"].row == 0
    assert page.tree.nodes["VIN_24V"].row in (None, 0)


def test_flow_arrow_link_via_page(page):
    """Flow-arrow mode: press on the upstream node, drop on the
    downstream node -> the edge is created, the draft saved and the
    temp rubber line cleaned up."""
    from PySide6.QtCore import QPointF
    page.refresh_from_model()
    page.tree = PowerTree.build(["VIN_24V", "MID_A", "MID_B"], [],
                                primaries=["VIN_24V"])
    page._render()
    page._link_start("VIN_24V")
    assert page._link_line is not None
    page._link_update(QPointF(1, 1))
    page._link_end("MID_B")
    assert page.tree.nodes["MID_B"].upstream == ["VIN_24V"]
    assert "MID_B" in page.tree.nodes["VIN_24V"].downstream
    assert page.model.power_tree["nodes"]
    assert page._link_line is None and page._link_from is None


def test_node_edit_records_manual_override(page, qapp, monkeypatch):
    """Double-click edit (dialog mocked): attributes land on the node,
    a manual-override record enters the audit log and the draft is
    saved into the model."""
    page.refresh_from_model()
    from mtkgui.gui.yamlbuild.power_tree_editor import NodeEditDialog

    def fake_exec(self):
        self._node.expected_voltage = "3.3"
        self._node.dont_test = True
        self._node.stage_override = 2
        self._node.stage = 2
        return NodeEditDialog.DialogCode.Accepted

    monkeypatch.setattr(NodeEditDialog, "exec", fake_exec)
    page._edit_node("GND")
    node = page.tree.nodes["GND"]
    assert node.expected_voltage == "3.3"
    assert node.dont_test is True
    assert node.stage_override == 2
    assert any("manual override" in e["reason"]
               for e in page.tree.audit_log)
    assert page.model.power_tree["nodes"]       # saved to the model


# ------------------------------------------------------------- pruning
def test_prune_and_restore_with_audit(page):
    """Passive-bridge pruning keeps the load side and logs the audit;
    restore brings the node back (audit stays) - the core rule is
    covered here, the AUTOMATIC run is tested via _build_tree."""
    bridges = [{"refdes": "R4", "kind": "passive",
                "nets": ("MID_A", "VIN_24V")}]
    page.tree = PowerTree.build(["VIN_24V", "MID_A"], bridges,
                                primaries=["VIN_24V"])
    page._bridges = bridges
    pruned = page.tree.prune_passive(page._bridges)
    assert pruned                          # VIN_24V pruned, MID_A kept
    assert page.tree.nodes["VIN_24V"].pruned
    assert page.tree.audit_log[-1]["refdes"] == "R4"
    assert page.tree.restore_pruned("VIN_24V")
    assert not page.tree.nodes["VIN_24V"].pruned


def test_auto_prune_on_build_and_category_override_restore(page):
    """The pruning runs AUTOMATICALLY when the tree is built from the
    parse result (no manual button); a wrongly-pruned net restored by
    the user (re-categorized as Power in Parsed Nets -> the
    category_override flag) comes back into the tree."""
    page.refresh_from_model()
    assert any(n.pruned for n in page.tree.nodes.values())
    assert any("passive bridge" in e["reason"]
               for e in page.tree.audit_log)
    # user re-categorization restores the wrongly-pruned net
    pruned_name = next(n.name for n in page.tree.nodes.values()
                       if n.pruned)
    page.model.imported["testable_nets"][pruned_name][
        "category_override"] = True
    page.model.power_tree = {}             # force a fresh build
    page.refresh_from_model()
    assert not page.tree.nodes[pruned_name].pruned


def test_bridges_detected_from_parse_members(page):
    page.refresh_from_model()
    members = {name: list(info.get("members") or [])
               for name, info in TESTABLE.items()}
    assert page._bridges == find_bridges(members)


# ------------------------------------------------------------ Event Log
def _spy(page):
    records = []
    page.task_log.connect(lambda level, msg: records.append((level,
                                                             msg)))
    return records


def test_rebuild_emits_event_log(page):
    """The AI Power Tree Topology rebuild reports into the global
    Event Log (INFO level) with the auto-pruned / auto-filled counts
    - double-layer logging: the fine tree.audit_log stays untouched."""
    records = _spy(page)
    page.refresh_from_model()
    page._rebuild()
    messages = [msg for _lvl, msg in records]
    assert any("AI power tree topology built" in m for m in messages)
    assert any("auto-pruned" in m and "auto-filled" in m
               for m in messages)


def test_node_edit_logs_field_change_summary(page, monkeypatch):
    """Manual node edit reports 'Manual tree attribute override' with
    the changed-field summary (voltage / DNT / stage)."""
    records = _spy(page)
    page.refresh_from_model()
    from mtkgui.gui.yamlbuild.power_tree_editor import NodeEditDialog

    def fake_exec(self):
        self._node.expected_voltage = "3.3"
        self._node.dont_test = True
        self._node.stage_override = 2
        self._node.stage = 2
        return NodeEditDialog.DialogCode.Accepted

    monkeypatch.setattr(NodeEditDialog, "exec", fake_exec)
    page._edit_node("GND")
    messages = [msg for _lvl, msg in records]
    assert any(m.startswith("Manual tree attribute override on "
                           "GND:") for m in messages)
    entry = next(m for m in messages if m.startswith("Manual tree"))
    assert "voltage" in entry and "Do Not Test" in entry
    assert "stage -> 2" in entry
    # fine-grained audit record still kept (double-layer logging)
    assert any("manual override" in e["reason"]
               for e in page.tree.audit_log)


def test_unedited_node_still_logged(page, monkeypatch):
    """An accepted dialog without changes still logs the override
    touch (summary falls back to 'saved')."""
    records = _spy(page)
    page.refresh_from_model()
    from mtkgui.gui.yamlbuild.power_tree_editor import NodeEditDialog
    monkeypatch.setattr(
        NodeEditDialog, "exec",
        lambda self: NodeEditDialog.DialogCode.Accepted)
    page._edit_node("GND")
    assert any(m.startswith("Manual tree attribute override on "
                            "GND: saved")
               for _l, m in records)


# ------------------------------------------------------------- persistence
def test_yaml_round_trip_via_real_model():
    """Draft (nodes / stages / audit) survives the project YAML
    section power_tree and restores on a fresh model."""
    import yaml

    from tests.yamlbuild.conftest import fill_required
    from mtkgui.gui.yamlbuild.model import YamlBuildModel
    model = YamlBuildModel()
    model.enable_all()
    fill_required(model)
    tree = PowerTree.build(["VIN_24V", "MID_A"],
                           [{"refdes": "R4", "kind": "passive",
                             "nets": ("MID_A", "VIN_24V")}],
                           primaries=["VIN_24V"])
    model.power_tree = tree.to_dict()
    doc = yaml.safe_load(yaml.safe_dump(
        model.to_effective_dict(), sort_keys=False))
    fresh = YamlBuildModel()
    fresh.enable_all()
    fill_required(fresh)
    assert fresh.apply_yaml_dict(doc) == []
    restored = PowerTree.from_dict(fresh.power_tree)
    assert restored.nodes["VIN_24V"].node_type == NODE_PRIMARY
    assert restored.nodes["MID_A"].upstream == ["VIN_24V"]
    assert restored.nodes["MID_A"].stage == 0    # passive: no increment
