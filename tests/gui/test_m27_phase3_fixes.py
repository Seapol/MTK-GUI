# -*- coding: utf-8 -*-
"""M27 Phase-3 dogfooding fixes (P1..P10).

Each problem in m27 got a targeted fix; these tests lock the regressions
out.  They are plain headless GUI/unit tests (offscreen platform) and do
NOT depend on the published FRDM-IMX93 project files - every fixture is
built inline so the assertions stay stable when the example data changes.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import yaml  # noqa: E402

from mtkgui.main_window import MainWindow  # noqa: E402

from mtkgui.gui.yamlbuild.publish import plan_filename  # noqa: E402
from mtkgui import project_config  # noqa: E402

MainWindow.__test__ = False


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _sandbox_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.save_project_state",
        lambda key, state: True)


@pytest.fixture()
def window(qapp):
    w = MainWindow(role="Supervisor", mode="Virtual", fixture="ATE")
    yield w
    w.close()
    w.deleteLater()


def _load(window, qapp, doc, tmp_path):
    """Write `doc` to a temp yaml and load it through the real path."""
    path = tmp_path / "proj.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    window._begin_yaml_load(str(path))
    while getattr(window, "_yaml_loading", False):
        qapp.processEvents()
    return window.workflow_page


def _legacy_wait_pair(name, wait_pattern, send):
    """The legacy 2-row shape: one '(wait)' case + one main case, both
    carrying an ``op_params.fct_step`` marker."""
    return [
        {"name": f"{name} (wait): 'done' (expected)",
         "kind": "CapturefromConsole",
         "op_params": {"fct_step": {
             "name": f"{name} (wait)", "step_type": "MESSAGE_CHECK",
             "channel": "ser1", "timeout_s": 10.0,
             "params": {"fct_console": True, "kind": "wait",
                        "expect_pass_re": wait_pattern}}}},
        {"name": f"{name}: 'done' (expected)",
         "kind": "CapturefromConsole",
         "op_params": {"fct_step": {
             "name": name, "step_type": "MESSAGE_CHECK",
             "channel": "ser1", "timeout_s": 5.0,
             "params": {"fct_console": True, "kind": "send",
                        "send": send}}}},
    ]


# ------------------------------------------------------------- P1
def test_p1_plain_load_normalizes_legacy_rows(window, qapp, tmp_path):
    """File > Load Yaml merges a legacy '(wait)' pre-step into its main
    step so the Test Work Flow FCT table shows ONE row per step (no
    'X (wait)' rows), not the legacy 2-row expansion."""
    cases = (_legacy_wait_pair("Console login", "imx93frdm login:", "root")
             + _legacy_wait_pair("Load RF drivers", "root@", "sh load.sh")
             + [{"name": "FCT done.", "kind": "MessageOK",
                 "op_params": None}])
    page = _load(window, qapp, {
        "product": {"part_number": "MTK1", "core_id": "1"},
        "test_workflow": {"fct_test_cases": cases},
    }, tmp_path)

    names = [page.fct_rows[r] for r in range(len(page.fct_rows))]
    assert "Console login" in names
    assert "Load RF drivers" in names
    assert "FCT done." in names
    # the '(wait)' expansion is gone (one row per FCT step)
    assert not any(" (wait)" in n for n in names)
    assert len(names) == 3
    # the merged step keeps the WaitFor stage in its marker
    login = next(c for c in cases if c["name"].startswith("Console login:"))
    _ = login
    marker = next(
        (page.fct_op_params[r] or {}).get("fct_step") for r in range(3)
        if page.fct_rows[r] == "Console login")
    assert marker["params"]["wait_pattern"] == "imx93frdm login:"
    assert marker["params"]["send"] == "root"


# ------------------------------------------------------------- P3
def test_p3_plan_version_field_edits_and_validates(window):
    """The Yaml Build header exposes an editable plan-version field
    (1.x.y).  A valid value drives the model; an invalid one is
    rejected (field snaps back, model unchanged)."""
    yb = window.yaml_build_page
    edit = yb.plan_version_edit
    assert edit is not None
    assert edit.text() == yb.model.plan_version

    edit.setText("1.1.0")
    yb._on_plan_version_edited()
    assert yb.model.plan_version == "1.1.0"

    # invalid values are rejected
    for bad in ("2.0", "abc", "1.2", "1.2.3.4", ""):
        edit.setText(bad)
        yb._on_plan_version_edited()
        assert yb.model.plan_version == "1.1.0", bad
        assert edit.text() == "1.1.0", bad


def test_p3_plan_version_drives_filename_and_revision(window):
    """The edited plan version lands in the published file name
    (rev_<version>) and in project.revision on save."""
    yb = window.yaml_build_page
    yb.model.set_params("design_input", {
        "product_id": "29420", "part_number": "MTK12345",
        "batch": "EVT (Proto-1)"})
    yb.plan_version_edit.setText("1.2.3")
    yb._on_plan_version_edited()
    assert yb.model.plan_version == "1.2.3"

    # project.revision derives from the yaml_build_state.plan_version
    config = project_config.build_config(
        window.workflow_page, window.equipment_page,
        yaml_build_state={"plan_version": yb.model.plan_version})
    assert config["project"]["revision"] == "1.2.3"

    # the publish file name carries rev_<version>
    name = plan_filename(yb.model, "draft")
    assert "rev_1.2.3" in name