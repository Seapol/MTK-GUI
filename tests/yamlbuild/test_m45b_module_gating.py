# -*- coding: utf-8 -*-
"""M45b: module gating 01 -> 03 (sequential unlock + star on validated
+ apply-time yaml validation).  M45c: FCT (module 05) is independent of
the ICT chain and every save path prompts for missing Product
Information.

Owner spec 2026-10-30:
* an ICT module cannot be opened unless its predecessor has been
  validated (star = applied by a valid Apply_Save yaml or by a valid
  project load);
* 01 (design_input) owns SPF / NET / BOM - with ANY of them missing
  only module 01 may be opened; FCT stays openable (FCT-only projects);
* after a load, ICT modules re-validate 01 -> 03 in order, passing
  levels get their star and unlock the next one, the first failure
  stops the chain; fct_build validates independently;
* every apply-save yaml path runs the M39 validation (module schema +
  global rules) BEFORE writing - a blocking issue writes nothing;
* apply-save / save-as-new with a missing Product Information prompt
  the operator (Part Number required; Cancel aborts the save).
"""
from __future__ import annotations

import yaml

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from mtkgui.yaml_build_page import (  # noqa: E402
    GATING_CHAIN,
    YamlBuildPage,
)

DESIGN_PARAMS = {
    "product_id": "MTK-96",
    "part_number": "P-0001",
    "spf_file": "board.spf",
    "net_file": "board.net",
    "bom_file": "board.csv",
}

RETIRED_FCT = yaml.safe_dump({"fct_test_config": {
    "dut_type": "linux",
    "console": {"port": "/dev/cu.test", "test_commands": [
        {"name": "Flash FAT Firmware", "send": "flash", "timeout": 5}]},
}}, sort_keys=False)

#: a minimal VALID FCT-only configuration (one console send row)
FCT_OK = yaml.safe_dump({"fct_test_config": {
    "dut_type": "linux",
    "console": {"port": "/dev/cu.test", "test_commands": [
        {"name": "Ping", "send": "echo ok", "timeout": 5}]},
}}, sort_keys=False)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _quiet_warnings(monkeypatch):
    """Never let the modal boxes block an offscreen run."""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: 0)


@pytest.fixture()
def page(qapp, tmp_path, monkeypatch):
    from mtkgui.gui.yamlbuild import store
    monkeypatch.setattr(store, "STATE_DIR", tmp_path)
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "state.json")
    return YamlBuildPage()


def _seed(page, levels: tuple[str, ...], files: bool = True) -> None:
    """Star the given chain levels (and the 01 files)."""
    if files:
        page.model.set_params("design_input", dict(DESIGN_PARAMS))
    for level in levels:
        page.model.set_mark(level, "star")


def _prompts(monkeypatch) -> list:
    shown: list = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *a, **k: shown.append(a) or 0)
    return shown


# ---------------------------------------------------- sequential unlock
def test_fresh_page_locks_ict_chain_and_fct_stays_open(page, monkeypatch):
    """Nothing validated -> the ICT chain 02 / 03 is locked, 01 stays
    open; M45c: the FCT module opens directly (FCT-only project)."""
    shown = _prompts(monkeypatch)
    opened: list = []

    def fake_open(key, *args, **kwargs):
        opened.append(key)
        return None, None

    monkeypatch.setattr(page.block_flow, "open_dialog", fake_open)
    for key in ("parse_ict", "channel_alloc", "ict_workflow", "fct_build"):
        page._open_block(key)
    assert opened == ["fct_build"]
    assert len(shown) == 3
    assert "module 01" in shown[0][2]


def test_openable_matrix(page):
    """01 starred + files -> 02 open; 02 starred -> 03 open.
    M45c: FCT is openable at every step (independent of the chain)."""
    assert page.module_openable("design_input") is True
    assert page.module_openable("fct_build") is True
    assert page.module_openable("parse_ict") is False
    _seed(page, ("design_input",))
    assert page.module_openable("parse_ict") is True
    assert page.module_openable("channel_alloc") is False
    assert page.module_openable("ict_workflow") is False
    assert page.module_openable("fct_build") is True
    _seed(page, ("design_input", "parse_ict"))
    assert page.module_openable("channel_alloc") is True
    assert page.module_openable("ict_workflow") is True
    assert page.module_openable("fct_build") is True


def test_validated_module_can_be_reopened(page):
    """An already-validated module stays openable (to fix / edit it)."""
    for level in GATING_CHAIN:
        page.model.set_mark(level, "star")
    page.model.set_params("design_input", dict(DESIGN_PARAMS))
    assert all(page.module_openable(level) for level in GATING_CHAIN)


def test_missing_design_file_locks_ict_but_not_fct(page):
    """Owner rule (M45b 4): with ANY of SPF / NET / BOM missing only
    module 01 may be opened in the ICT chain - M45c keeps the FCT
    module openable."""
    for level in GATING_CHAIN:
        page.model.set_mark(level, "star")
    for missing in ("spf_file", "net_file", "bom_file"):
        params = dict(DESIGN_PARAMS)
        params[missing] = ""
        page.model.set_params("design_input", params)
        assert page.module_openable("design_input") is True
        for key in ("parse_ict", "channel_alloc", "ict_workflow"):
            assert page.module_openable(key) is False, missing
        assert page.module_openable("fct_build") is True, missing


# ------------------------------------------- load-time validation stars
def test_load_gating_stars_the_whole_valid_chain(page):
    page.model.set_params("design_input", dict(DESIGN_PARAMS))
    # level 03 completes once the project carries parsed testable nets
    page.model.imported["testable_nets"] = {
        "3V3": {"category": "Power", "members": ["U1.5"]}}
    page.apply_load_gating()
    assert [page.model.marks.get(level) for level in GATING_CHAIN] == \
        ["star"] * len(GATING_CHAIN)


def test_load_gating_stops_at_the_first_failure(page):
    """01 invalid (no Part #) -> the ICT chain stops immediately: no
    star anywhere, so 02 / 03 stay locked."""
    page.model.set_params("design_input", {
        "product_id": "MTK-96", "part_number": "",
        "spf_file": "board.spf", "net_file": "board.net",
        "bom_file": "board.csv"})
    page.apply_load_gating()
    assert [page.model.marks.get(level) for level in GATING_CHAIN] == \
        [None] * len(GATING_CHAIN)
    assert page.module_openable("parse_ict") is False


def test_load_gating_keeps_later_levels_locked(page):
    """01 + 02 valid, 03 incomplete (no parsed nets) -> 03 stays
    locked; M45c: fct_build has no content -> no star but stays
    openable."""
    page.model.set_params("design_input", dict(DESIGN_PARAMS))
    page.model.imported["testable_nets"] = {}
    page.model.channel_allocation = {}
    page.apply_load_gating()
    assert page.model.marks.get("design_input") == "star"
    assert page.model.marks.get("parse_ict") == "star"
    assert page.model.marks.get("ict_workflow") is None
    assert page.model.marks.get("fct_build") is None
    assert page.module_openable("fct_build") is True


# ------------------------------------------- M45c FCT independence
def test_load_gating_stars_fct_without_any_ict_level(page):
    """FCT-only project: no design files, no ICT content - the ICT
    chain stays locked while fct_build stars on its own content."""
    page.model.set_params("fct_build", {"fct_test_config_yaml": FCT_OK})
    page.apply_load_gating()
    assert [page.model.marks.get(level) for level in GATING_CHAIN] == \
        [None] * len(GATING_CHAIN)
    assert page.model.marks.get("fct_build") == "star"
    assert page.module_openable("fct_build") is True


def test_invalid_fct_content_is_not_starred(page):
    """The retired flash step fails the M39 rules -> fct_build gets no
    star (its own validation decides, ICT levels are irrelevant)."""
    page.model.set_params("fct_build", {"fct_test_config_yaml": RETIRED_FCT})
    page.apply_load_gating()
    assert page.model.marks.get("fct_build") is None


# --------------------------------------------- apply-time yaml validation
def test_save_as_new_blocked_by_module_validation(page, monkeypatch):
    """A config page whose values violate its schema never reaches
    Save as new yaml (nothing applied, no signal)."""
    warned: list = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: warned.append(a) or 0)
    emitted: list = []
    page.save_as_yaml_requested.connect(lambda: emitted.append(1))
    page._save_as_new_yaml("design_input", {"product_id": "",
                                            "part_number": ""})
    assert warned and "required" in warned[0][2].lower()
    assert emitted == []


def test_m39_rule_blocks_the_write(window, tmp_path, monkeypatch):
    """M45b 2: the M39 global rules run on every write path - a retired
    flash step blocks the save and nothing is written."""
    warned: list = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: warned.append(a) or 0)
    model = window.yaml_build_page.model
    model.set_params("fct_build", {"fct_test_config_yaml": RETIRED_FCT})
    path = tmp_path / "blocked.yaml"
    assert window._save_yaml_to(str(path)) is False
    assert not path.exists()
    assert warned and "retired flash operation" in warned[0][2]


# ------------------------------------- M45c Product Information prompt
def test_apply_save_prompts_and_writes_product(window, tmp_path,
                                               monkeypatch):
    """Missing Product Information -> modal prompt; OK with a Part
    Number writes ``product:`` and the save proceeds."""
    from mtkgui import main_window as mw
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    asked: list = []

    def fake_ask(parent, product):
        asked.append(dict(product))
        return {"part_number": "P-0001", "core_id": "C-1",
                "batch": "B-0001"}

    monkeypatch.setattr(mw, "ask_product_information", fake_ask)
    path = tmp_path / "product.yaml"
    assert window._save_yaml_to(str(path)) is True
    assert asked, "the Product Information prompt never appeared"
    doc = yaml.safe_load(path.read_text())
    assert doc["product"]["part_number"] == "P-0001"
    assert doc["product"]["core_id"] == "C-1"
    assert doc["product"]["batch"] == "B-0001"


def test_apply_save_cancel_prompt_writes_nothing(window, tmp_path,
                                                 monkeypatch):
    """Cancel on the Product Information prompt aborts the save."""
    from mtkgui import main_window as mw
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(mw, "ask_product_information",
                        lambda parent, product: None)
    path = tmp_path / "cancelled.yaml"
    assert window._save_yaml_to(str(path)) is False
    assert not path.exists()


def test_existing_product_does_not_prompt(window, tmp_path, monkeypatch):
    """A project that already carries a Part Number saves silently."""
    from mtkgui import main_window as mw
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    asked: list = []
    monkeypatch.setattr(mw, "ask_product_information",
                        lambda parent, product: asked.append(product))
    window.workflow_page.part_edit.setText("P-EXISTING")
    path = tmp_path / "existing.yaml"
    assert window._save_yaml_to(str(path)) is True
    assert asked == []


def test_fct_only_project_hits_the_same_product_prompt(window, tmp_path,
                                                       monkeypatch):
    """Product identity is project-level: an FCT-only project (no ICT
    content at all) prompts exactly like an ICT project."""
    from mtkgui import main_window as mw
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.yaml_build_page.model.set_params(
        "fct_build", {"fct_test_config_yaml": FCT_OK})
    prompted: list = []
    monkeypatch.setattr(
        mw, "ask_product_information",
        lambda parent, product: prompted.append(product) or {
            "part_number": "FCT-ONLY", "core_id": "", "batch": ""})
    path = tmp_path / "fct_only.yaml"
    assert window._save_yaml_to(str(path)) is True
    assert prompted
    assert yaml.safe_load(path.read_text())["product"]["part_number"] == \
        "FCT-ONLY"


# ---------------------------------- load / apply-save: one rule set
def test_load_and_apply_save_run_the_same_rule_set(window, tmp_path,
                                                   monkeypatch):
    """M45c 5: load, apply-save and save-as-new share ONE validation
    rule set - the SAME YAML issue blocks both entry points."""
    from mtkgui import main_window as mw
    from mtkgui.engine.yaml_validation import YamlIssue

    issue = YamlIssue(severity="error", message="shared rule failure",
                      location="test_workflow")
    calls: list = []

    def fake_validate(doc):
        calls.append(doc)
        return [issue]

    monkeypatch.setattr(mw, "validate_project_yaml", fake_validate)
    monkeypatch.setattr(
        mw.QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "in.yaml"), "")))
    src = tmp_path / "in.yaml"
    src.write_text(yaml.safe_dump({
        "project": {}, "product": {"part_number": "P-X"},
        "test_workflow": {"fct_test_cases": []}}, sort_keys=False))
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    criticals: list = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: criticals.append(a) or 0)
    warned: list = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.append(a) or 0)
    window.load_yaml()
    assert criticals and "shared rule failure" in criticals[0][2]
    window.workflow_page.part_edit.setText("P-X")
    out = tmp_path / "out.yaml"
    assert window._save_yaml_to(str(out)) is False
    assert warned and "shared rule failure" in warned[0][2]
    assert not out.exists()
    assert len(calls) == 2       # load + save both ran the same validator


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.save_project_state",
        lambda key, state: True)
    from mtkgui.main_window import MainWindow
    MainWindow.__test__ = False
    w = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    yield w
    w.close()
    w.deleteLater()
