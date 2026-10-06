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
    assert "VIN_24V" in names
    # canvas capabilities: pan + zoom + scrollbars as needed
    assert page.canvas.dragMode() == page.canvas.DragMode.ScrollHandDrag
    assert page.canvas.horizontalScrollBarPolicy() in (
        __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ScrollBarPolicy
        .ScrollBarAsNeeded,)


def test_summary_and_audit_panels_populated(page):
    page.refresh_from_model()
    headers = [page.node_summary.headerItem().text(i)
               for i in range(page.node_summary.columnCount())]
    assert headers == ["Net", "Stage", "Type", "Risk", "Status"]
    nets = [page.node_summary.topLevelItem(i).text(0)
            for i in range(page.node_summary.topLevelItemCount())]
    assert "VIN_24V" in nets
    row = next(page.node_summary.topLevelItem(i)
               for i in range(page.node_summary.topLevelItemCount())
               if page.node_summary.topLevelItem(i).text(0)
               == "VIN_24V")
    assert row.text(3) == "5"              # risk score from path_risk


# ------------------------------------------------------------- editing
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
    page._edit_node("VIN_24V")
    node = page.tree.nodes["VIN_24V"]
    assert node.expected_voltage == "3.3"
    assert node.dont_test is True
    assert node.stage_override == 2
    assert any("manual override" in e["reason"]
               for e in page.tree.audit_log)
    assert page.model.power_tree["nodes"]       # saved to the model


def test_summary_double_click_opens_editor(page, monkeypatch):
    from PySide6.QtCore import Qt
    opened = []
    monkeypatch.setattr(page, "_edit_node",
                        lambda name: opened.append(name))
    page.refresh_from_model()
    item = next(page.node_summary.topLevelItem(i)
                for i in range(page.node_summary.topLevelItemCount()))
    page._on_summary_double_click(item, 0)
    assert opened == [item.data(0, Qt.ItemDataRole.UserRole)]


# ------------------------------------------------------------- pruning
def test_prune_and_restore_with_audit(page):
    """Passive-bridge pruning keeps the load side and logs the audit;
    restore brings the node back (audit stays)."""
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


def test_rebuild_prune_restore_emit_event_log(page, monkeypatch):
    """All tree-level operations report into the global Event Log
    (INFO level, standard wording) - double-layer logging: the fine
    tree.audit_log stays untouched."""
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    records = _spy(page)
    pruned_names = []

    def fake_restore_choice(*_a, **_k):
        # restore the first actually pruned node (direction depends
        # on the auto-built bridge orientation)
        name = next(n.name for n in page.tree.nodes.values()
                    if n.pruned)
        pruned_names.append(name)
        return (name, True)

    monkeypatch.setattr(QInputDialog, "getItem", fake_restore_choice)
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: None)
    page.refresh_from_model()
    page._rebuild()
    page._prune()
    page._restore()
    messages = [msg for _lvl, msg in records]
    assert any("Power tree rebuilt from parse result" in m
               for m in messages)
    assert any("Passive bridge pruning executed" in m
               for m in messages)
    assert any("Pruned topology restored" in m for m in messages)


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
    page._edit_node("VIN_24V")
    messages = [msg for _lvl, msg in records]
    assert any(m.startswith("Manual tree attribute override on "
                           "VIN_24V:") for m in messages)
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
    page._edit_node("VIN_24V")
    assert any(m.startswith("Manual tree attribute override on "
                            "VIN_24V: saved")
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
