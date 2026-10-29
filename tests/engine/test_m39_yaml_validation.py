# -*- coding: utf-8 -*-
"""M39: project YAML validation on load (phase 1 - retired flash steps).

The validator is a framework (registered rules) with the first rule
rejecting the M33-retired flash operations with a delete / replace fix
hint.  severity=error blocks the load; warnings only report.
"""
from __future__ import annotations

from mtkgui import project_config
from mtkgui.engine import yaml_validation as yv


def _doc(ict=None, fct=None) -> dict:
    return {"test_workflow": {
        "ict_test_cases": list(ict or []),
        "fct_test_cases": list(fct or []),
    }}


def test_clean_document_passes():
    doc = _doc(ict=[{"name": "Init Instruments", "kind": "op"},
                    {"name": "R-GND - TP_P01", "kind": "R-GND"}],
               fct=[{"name": "Flash_GUI", "kind": "Flash_GUI"},
                    {"name": "MessageGoStop", "kind": "MessageGoStop"}])
    assert yv.validate_project_yaml(doc) == []
    assert yv.validate_project_yaml({}) == []
    assert yv.validate_project_yaml(None) == []


def test_retired_flash_fat_in_ict_is_an_error():
    doc = _doc(ict=[{"name": "Init Instruments", "kind": "op"},
                    {"name": "Flash FAT Firmware", "kind": "op"}])
    issues = yv.validate_project_yaml(doc)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == yv.SEVERITY_ERROR
    assert issue.location == "ict_test_cases[1].name"
    assert "delete the row 'Flash FAT Firmware'" in issue.message
    assert "ict: ict_test_cases" in issue.message
    assert "replace it with a Flash_GUI step" in issue.message


def test_retired_flash_oobe_in_fct_is_an_error():
    doc = _doc(fct=[{"name": "Flash OOBE Firmware", "kind": "op"}])
    issues = yv.validate_project_yaml(doc)
    assert len(issues) == 1
    assert issues[0].severity == yv.SEVERITY_ERROR
    assert issues[0].location == "fct_test_cases[0].name"
    assert "Flash OOBE Firmware" in issues[0].message


def test_retired_rows_in_both_sequences_are_reported():
    doc = _doc(ict=[{"name": "Flash FAT Firmware"}],
               fct=[{"name": "Flash OOBE Firmware"},
                    {"name": "Flash FAT Firmware"}])
    issues = yv.validate_project_yaml(doc)
    assert len(issues) == 3
    assert [i.location for i in issues] == [
        "ict_test_cases[0].name", "fct_test_cases[0].name",
        "fct_test_cases[1].name"]


def test_other_steps_are_unaffected():
    doc = _doc(ict=[{"name": "Fixture Clamp Down", "kind": "op"},
                    {"name": "Power On DUT", "kind": "op"}],
               fct=[{"name": "Flash_GUI", "kind": "Flash_GUI"},
                    {"name": "Delay", "kind": "Delay"}])
    assert yv.validate_project_yaml(doc) == []


def test_blocking_only_errors():
    issues = [yv.YamlIssue(yv.SEVERITY_WARNING, "w", "loc"),
              yv.YamlIssue(yv.SEVERITY_ERROR, "e", "loc")]
    blocking = yv.blocking_issues(issues)
    assert len(blocking) == 1 and blocking[0].severity == yv.SEVERITY_ERROR


def test_warning_rule_reports_without_blocking(monkeypatch):
    def warn_rule(doc):
        return [yv.YamlIssue(yv.SEVERITY_WARNING, "sample warning",
                             "worksheet")]

    monkeypatch.setattr(yv, "_RULES", list(yv._RULES) + [warn_rule])
    issues = yv.validate_project_yaml({})
    assert len(issues) == 1
    assert yv.blocking_issues(issues) == []


def test_format_issues_states_fix_and_suggestion():
    issues = yv.validate_project_yaml(
        _doc(fct=[{"name": "Flash FAT Firmware"}]))
    text = yv.format_issues(issues)
    assert "ERROR fct_test_cases[0].name:" in text
    assert "delete the row 'Flash FAT Firmware'" in text
    assert "Edit the YAML file" in text
    assert "create a new YAML project" in text


def test_load_path_reports_retired_step(tmp_path):
    """The real load sequence (project_config.load_config -> validate)
    reports the retired row before anything is applied."""
    path = tmp_path / "legacy.yaml"
    path.write_text(
        "product: {part_number: TEST-0001}\n"
        "test_workflow:\n"
        "  ict_test_cases: []\n"
        "  fct_test_cases:\n"
        "    - {name: Flash FAT Firmware, kind: op}\n"
        "    - {name: MessageGoStop, kind: MessageGoStop}\n",
        encoding="utf-8")
    doc = project_config.load_config(str(path))
    issues = yv.validate_project_yaml(doc)
    assert len(issues) == 1
    assert issues[0].location == "fct_test_cases[0].name"
    assert yv.blocking_issues(issues)
