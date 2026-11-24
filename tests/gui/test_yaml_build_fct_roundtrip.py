# -*- coding: utf-8 -*-
"""m118 §1: the stored FCT list survives a project load.

The shipped project files store their FCT rows in
``test_workflow.fct_test_cases`` (45 rows on FRDM-IMX93) while their
``yaml_build_state`` section stores an EMPTY list - the old load path
restored that empty state and every Yaml Build emit rebuilt only 38
rows from the legacy config.  These tests pin the m114 fix: the stored
list is restored on load, emitted verbatim, and wins over the rebuild.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

import yaml

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.project_config import apply_config
from mtkgui.test_workflow_page import TestWorkFlowPage
from mtkgui.yaml_build_page import YamlBuildPage

ROOT = Path(__file__).resolve().parents[2]
PROJECT_YAML = (ROOT / "projects" / "FRDM-IMX93" /
                "FRDM-IMX93_i.MX93_EVT-(Proto-1)_rev_1.3.1_Draft.yaml")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def project_doc():
    """The shipped project YAML (read-only - never written back)."""
    if not PROJECT_YAML.is_file():
        pytest.skip(f"shipped project file not present: {PROJECT_YAML}")
    return yaml.safe_load(PROJECT_YAML.read_text(encoding="utf-8"))


@pytest.fixture
def loaded(qapp, project_doc):
    """(Test Work Flow page, Yaml Build page) after a real project load."""
    workflow = TestWorkFlowPage()
    equipment = type("Equipment", (), {"configs": {}})()
    page = YamlBuildPage()
    # YamlBuildPage restores the machine-local persisted state on
    # construction - blank the FCT list first so the emit below proves
    # the LOAD path seeded it (the project state itself stores []).
    page.model.set_fct_test_cases([])
    try:
        apply_config(project_doc, workflow, equipment, page.model)
        yield workflow, page
    finally:
        workflow.deleteLater()
        page.deleteLater()


def test_project_yaml_restores_all_45_fct_rows(qapp, project_doc, caplog):
    """The load path seeds the model with the stored 45 rows (m114)."""
    workflow = TestWorkFlowPage()
    equipment = type("Equipment", (), {"configs": {}})()
    model = YamlBuildModel()
    try:
        with caplog.at_level("INFO", logger="mtkgui.project_config"):
            apply_config(project_doc, workflow, equipment, model)
        assert len(model.get_fct_test_cases()) == 45
        assert "FCT sequence restored: 45 cases" in caplog.text
    finally:
        workflow.deleteLater()


def test_roundtrip_keeps_row_order_and_names(loaded, project_doc):
    """An emit after the load returns the stored rows verbatim."""
    _workflow, page = loaded
    stored = project_doc["test_workflow"]["fct_test_cases"]
    cases, errors = page._emit_fct_sequence(
        page.model.get_params("fct_build") or {})
    assert errors == []
    assert [c["name"] for c in cases] == [c["name"] for c in stored]
    assert [c.get("kind") for c in cases] == [
        c.get("kind") for c in stored]
    assert cases[0]["name"] == "Power On DUT"
    assert cases[-1]["name"] == "Power Off DUT"


def test_stored_list_wins_over_derivable_config(loaded):
    """The legacy config derives 38 rows - the stored 45 still win, and
    exactly one WARNING reports the drift."""
    _workflow, page = loaded
    logs = []
    page.task_log.connect(
        lambda level, message: logs.append((level, message)))
    cases, errors = page._emit_fct_sequence(
        page.model.get_params("fct_build") or {})
    assert errors == []
    assert len(cases) == 45
    warnings = [message for level, message in logs
                if level == "WARNING"]
    assert warnings == ["stored FCT list has 45 rows, config yields 38 "
                        "rows - stored list wins"]
