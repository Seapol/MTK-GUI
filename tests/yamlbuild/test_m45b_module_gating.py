# -*- coding: utf-8 -*-
"""M45b: module gating 01 -> 04 (sequential unlock + star on validated
+ apply-time yaml validation).

Owner spec 2026-10-30:
* a module cannot be opened unless its predecessor has been validated
  (star = applied by a valid Apply_Save yaml or by a valid project
  load);
* 01 (design_input) owns SPF / NET / BOM - with ANY of them missing
  only module 01 may be opened;
* after a load, modules re-validate 01 -> 04 in order, passing levels
  get their star and unlock the next one, the first failure stops the
  chain;
* every apply-save yaml path runs the M39 validation (module schema +
  global rules) BEFORE writing - a blocking issue writes nothing.
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
def test_fresh_page_locks_02_03_04(page, monkeypatch):
    """Nothing validated -> 02 / 03 / 04 are locked, 01 stays open."""
    shown = _prompts(monkeypatch)
    opened: list = []
    monkeypatch.setattr(page.block_flow, "open_dialog",
                        lambda key, *a, **k: opened.append(key))
    for key in ("parse_ict", "channel_alloc", "ict_workflow", "fct_build"):
        page._open_block(key)
    assert opened == []
    assert len(shown) == 4
    assert "module 01" in shown[0][2]


def test_openable_matrix(page, monkeypatch):
    """01 starred + files -> 02 open; 02 starred -> 03 open;
    03 starred -> 04 open."""
    assert page.module_openable("design_input") is True
    assert page.module_openable("parse_ict") is False
    _seed(page, ("design_input",))
    assert page.module_openable("parse_ict") is True
    assert page.module_openable("channel_alloc") is False
    assert page.module_openable("ict_workflow") is False
    _seed(page, ("design_input", "parse_ict"))
    assert page.module_openable("channel_alloc") is True
    assert page.module_openable("ict_workflow") is True
    assert page.module_openable("fct_build") is False
    _seed(page, ("design_input", "parse_ict", "ict_workflow"))
    assert page.module_openable("fct_build") is True


def test_validated_module_can_be_reopened(page):
    """An already-validated module stays openable (to fix / edit it)."""
    for level in GATING_CHAIN:
        page.model.set_mark(level, "star")
    page.model.set_params("design_input", dict(DESIGN_PARAMS))
    assert all(page.module_openable(level) for level in GATING_CHAIN)


def test_missing_design_file_locks_02_plus(page):
    """Owner rule (M45b 4): with ANY of SPF / NET / BOM missing only
    module 01 may be opened - even when everything is starred."""
    for level in GATING_CHAIN:
        page.model.set_mark(level, "star")
    for missing in ("spf_file", "net_file", "bom_file"):
        params = dict(DESIGN_PARAMS)
        params[missing] = ""
        page.model.set_params("design_input", params)
        assert page.module_openable("design_input") is True
        for key in ("parse_ict", "channel_alloc", "ict_workflow",
                    "fct_build"):
            assert page.module_openable(key) is False, missing


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
    """01 invalid (no Part #) -> the chain stops immediately: no star
    anywhere, so 02 / 03 / 04 stay locked."""
    page.model.set_params("design_input", {
        "product_id": "MTK-96", "part_number": "",
        "spf_file": "board.spf", "net_file": "board.net",
        "bom_file": "board.csv"})
    page.apply_load_gating()
    assert [page.model.marks.get(level) for level in GATING_CHAIN] == \
        [None] * len(GATING_CHAIN)
    assert page.module_openable("parse_ict") is False


def test_load_gating_keeps_later_levels_locked(page):
    """01 + 02 valid, 03 incomplete (no parsed nets) -> 04 stays locked."""
    page.model.set_params("design_input", dict(DESIGN_PARAMS))
    page.model.imported["testable_nets"] = {}
    page.model.channel_allocation = {}
    page.apply_load_gating()
    assert page.model.marks.get("design_input") == "star"
    assert page.model.marks.get("parse_ict") == "star"
    assert page.model.marks.get("ict_workflow") is None
    assert page.model.marks.get("fct_build") is None
    assert page.module_openable("fct_build") is False


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
