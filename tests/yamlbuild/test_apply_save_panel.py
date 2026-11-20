# -*- coding: utf-8 -*-
"""v2-17: node 07 Apply & Save Yaml panel tests."""

from __future__ import annotations

import yaml

from mtkgui.gui.yamlbuild.apply_save_panel import (
    NO_TARGET,
    ApplySavePanel,
    save_as,
)
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.publish import (
    archive_copy,
    build_plan_document,
    plan_filename,
)

#: every required field of the modules that validate_all() checks
_REQUIRED = {
    "design_input": {
        "product_id": "P001", "part_number": "MTK12345",
        "sw_version": "1.2.3", "hw_version": "A",
        "batch": "MP (Production)",
    },
    "instruments": {
        "psu_visa": "TCPIP0::192.168.1.20::inst0",
        "daq_visa": "GPIB0::9::INSTR", "dmm_visa": "",
        "self_test": "true",
    },
    "parse_ict": {"netlist_file": "design.net"},
    "fct_build": {"flow_steps": "step1\nstep2",
                  "yield_threshold_pct": "98.0",
                  "exception_branch": "stop", "case_link": ""},
}


def valid_model() -> YamlBuildModel:
    model = YamlBuildModel()
    model.enable_all()
    for key, params in _REQUIRED.items():
        model.set_params(key, {**model.get_params(key), **params})
    return model


def test_panel_reuses_the_publish_helpers():
    model = valid_model()
    panel = ApplySavePanel()
    panel.set_values(model)
    assert panel.edit_target.text() == plan_filename(model, "draft")
    assert panel.validation_errors() == []
    assert panel.btn_apply.isEnabled()
    assert panel.btn_save_as.isEnabled()
    assert panel.values() == {}


def test_preview_is_the_read_only_safe_dump_of_the_draft():
    model = valid_model()
    panel = ApplySavePanel()
    panel.set_values(model)
    assert panel.preview.isReadOnly()
    assert panel.yaml_text().startswith("yaml_build:")
    preview = yaml.safe_load(panel.yaml_text())
    expected = build_plan_document(model, "draft")
    # created_at is a timestamp - compare everything else verbatim
    preview["plan"].pop("created_at", None)
    expected["plan"].pop("created_at", None)
    assert preview == expected
    assert preview["plan"]["kind"] == "draft"


def test_invalid_model_disables_both_save_buttons():
    model = YamlBuildModel()
    panel = ApplySavePanel()
    panel.set_values(model)
    assert panel.lbl_status.text().startswith("Validation:")
    assert "error(s)" in panel.lbl_status.text()
    assert not panel.btn_apply.isEnabled()
    assert not panel.btn_save_as.isEnabled()
    assert panel.edit_target.text() == NO_TARGET
    assert panel.lbl_errors.text()


def test_apply_and_save_writes_the_draft_and_an_archive_copy(
        monkeypatch, tmp_path):
    monkeypatch.setattr("mtkgui.app_paths.work_dir", lambda: tmp_path)
    model = valid_model()
    panel = ApplySavePanel()
    panel.set_values(model)
    panel.btn_apply.click()
    draft = tmp_path / "P001" / plan_filename(model, "draft")
    assert draft.is_file()
    archived = list((tmp_path / "archive" / "yamlbuild").rglob("*.yaml"))
    assert len(archived) == 1
    assert panel.lbl_saved.text().startswith("Saved:")
    document = yaml.safe_load(draft.read_text(encoding="utf-8"))
    assert document["plan"]["kind"] == "draft"


def test_save_as_writes_the_chosen_path(monkeypatch, tmp_path):
    monkeypatch.setattr("mtkgui.app_paths.work_dir", lambda: tmp_path)
    model = valid_model()
    chosen = tmp_path / "picked" / "my_plan.yaml"
    monkeypatch.setattr(
        "mtkgui.gui.yamlbuild.apply_save_panel.QFileDialog.getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(chosen), "YAML (*.yaml)")))
    panel = ApplySavePanel()
    panel.set_values(model)
    panel.btn_save_as.click()
    assert chosen.is_file()
    assert yaml.safe_load(chosen.read_text(encoding="utf-8"))["plan"] \
        ["kind"] == "draft"
    assert list((tmp_path / "archive" / "yamlbuild").rglob("*.yaml"))
    assert panel.lbl_saved.text().startswith("Saved:")


def test_save_as_helper_appends_the_yaml_suffix(monkeypatch, tmp_path):
    monkeypatch.setattr("mtkgui.app_paths.work_dir", lambda: tmp_path)
    model = valid_model()
    path, archive = save_as(model, tmp_path / "no_suffix")
    assert path.name == "no_suffix.yaml"
    assert path.is_file()
    assert archive.is_file()


def test_archive_copy_is_the_same_helper_as_publish():
    # the panel must archive through publish.archive_copy, not a copy
    import mtkgui.gui.yamlbuild.apply_save_panel as panel_module

    assert panel_module.archive_copy is archive_copy


def test_wizard_mounts_the_real_panel():
    from mtkgui.gui.yamlbuild import steps_v2 as sv
    from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard

    model = valid_model()
    wizard = YamlBuildWizard(model=model)
    assert isinstance(wizard._panels.get("apply_save"), ApplySavePanel)
    assert sv.PLACEHOLDER_STEPS == frozenset()
    assert sv.STEP_BY_KEY["apply_save"].kind == "panel"
    panel = wizard._panels["apply_save"]
    assert panel.edit_target.text() == plan_filename(model, "draft")
