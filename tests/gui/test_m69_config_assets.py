# -*- coding: utf-8 -*-
"""M69: Tools > Config assets for projects... (project-bound assets).

Built-in assets stay READ-ONLY; each project owns
``projects/<Project>/assets_<Project>``; the choice is a shared
parameter (``assets_dir``) - no FCT sequence row is ever injected.
"""
from __future__ import annotations

import os
import shutil

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QMessageBox,
)

from mtkgui.engine import assets_config as assets  # noqa: E402
from mtkgui.engine.fct_test_config import default_assets_dir  # noqa: E402
from mtkgui.gui.assets_config_dialog import (  # noqa: E402
    AssetsConfigDialog,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
BUILTIN = os.path.join(REPO_ROOT, "assets")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def tenant(tmp_path):
    base = tmp_path / "projects"
    base.mkdir()
    (base / "29420").mkdir()
    (base / "94923").mkdir()
    (base / "95100").mkdir()
    (base / "95100" / "assets").mkdir()
    (base / "demo").mkdir()
    (base / ".DS_Store").write_text("junk")
    return str(base)


def _dialog(tenant, captured=None, opener=None):
    calls = captured if captured is not None else []

    def bind(project, path):
        calls.append((project, path))

    dlg = AssetsConfigDialog(
        None, tenant_base=tenant, bind_callback=bind,
        builtin_source=BUILTIN, folder_opener=opener)
    dlg.show()
    QApplication.processEvents()
    return dlg, calls


# ------------------------------------------------------------- menu entry
def test_tools_menu_has_the_action_after_perf_log(qapp):
    from mtkgui.main_window import MainWindow
    w = MainWindow(role="SUPERVISOR", mode="Virtual")
    try:
        tools_action = [a for a in w.menuBar().actions()
                        if a.text() == "Tools"][0]
        tools = tools_action.menu()
        actions = tools.actions()
        labels = [a.text() for a in actions if not a.isSeparator()]
        assert "Config assets for projects…" in labels
        perf = labels.index("Performance Timing Log")
        new = labels.index("Config assets for projects…")
        assert new == perf + 1
        # a separator sits between the two entries
        perf_action = [a for a in actions
                       if a.text() == "Performance Timing Log"][0]
        idx = actions.index(perf_action)
        assert actions[idx + 1].isSeparator()
        assert actions[idx + 2] is w.act_assets_config
        # lazy + reused
        assert w._assets_dialog is None
    finally:
        w.close()
        w.deleteLater()


# ------------------------------------------------------------- project list
def test_dialog_lists_projects_with_status(qapp, tenant):
    dlg, _calls = _dialog(tenant)
    try:
        texts = [dlg.list_widget.item(i).text()
                 for i in range(dlg.list_widget.count())]
        assert texts == [
            "29420  (no assets yet)",
            "94923  (no assets yet)",
            "95100  (built-in fallback)"]
        # demo / hidden entries are skipped
        assert all("demo" not in t and "DS_Store" not in t for t in texts)
        dlg.list_widget.setCurrentRow(2)
        QApplication.processEvents()
        assert dlg.project() == "95100"
        # legacy folder -> Create still available
        assert dlg.btn_create.isEnabled()
        assert not dlg.btn_open.isEnabled()
        assert dlg.path_label.text().endswith(
            os.path.join("95100", "assets_95100"))
    finally:
        dlg.deleteLater()


# ------------------------------------------------------------- operations
def test_create_copies_the_whole_tree_and_binds(qapp, tenant):
    dlg, calls = _dialog(tenant)
    try:
        dlg.list_widget.setCurrentRow(0)      # 29420
        dlg._create()
        target = os.path.join(tenant, "29420", "assets_29420")
        assert os.path.isdir(target)
        expected = sorted(assets.list_asset_files(BUILTIN))
        assert assets.list_asset_files(target) == expected
        assert calls == [("29420", os.path.normpath(target))]
        assert dlg.project() == "29420"
        assert "assets ready" in dlg.list_widget.currentItem().text()
        assert dlg.btn_create.isEnabled() is False
        assert dlg.btn_recreate.isEnabled() and dlg.btn_delete.isEnabled()
        # the built-in template itself is untouched
        assert assets.list_asset_files(BUILTIN) == expected
    finally:
        dlg.deleteLater()


def test_recreate_overwrites_custom_edits(qapp, tenant, monkeypatch):
    dlg, calls = _dialog(tenant)
    monkeypatch.setattr(
        "mtkgui.gui.assets_config_dialog.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        dlg.list_widget.setCurrentRow(0)
        dlg._create()
        target = os.path.join(tenant, "29420", "assets_29420")
        readme = os.path.join(target, "README.md")
        assets.write_asset_text(readme, "custom edit")
        dlg._recreate()
        text, is_text = assets.read_asset_text(readme)
        assert is_text and text != "custom edit"
        assert calls[-1] == ("29420", os.path.normpath(target))
    finally:
        dlg.deleteLater()


def test_delete_removes_only_the_custom_folder(qapp, tenant, monkeypatch):
    dlg, calls = _dialog(tenant)
    monkeypatch.setattr(
        "mtkgui.gui.assets_config_dialog.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        dlg.list_widget.setCurrentRow(1)      # 94923
        dlg._create()
        target = os.path.join(tenant, "94923", "assets_94923")
        assert os.path.isdir(target)
        dlg._delete()
        assert not os.path.exists(target)
        assert os.path.isdir(os.path.join(tenant, "94923"))   # kept
        assert calls[-1] == ("94923", "")     # fall back to built-in
        assert "(no assets yet)" in dlg.list_widget.currentItem().text()
    finally:
        dlg.deleteLater()


def test_delete_refuses_a_legacy_assets_folder(tenant):
    """remove_custom_assets only touches assets_<Project>."""
    legacy = os.path.join(tenant, "95100", "assets")
    assert assets.remove_custom_assets("95100", tenant) is False
    assert os.path.isdir(legacy)


# ---------------------------------------------------------------- editor
def test_edit_file_saves_utf8(qapp, tenant):
    dlg, _calls = _dialog(tenant)
    try:
        dlg.list_widget.setCurrentRow(0)
        dlg._create()
        dlg._toggle_editor()
        names = [dlg.file_list.item(i).text()
                 for i in range(dlg.file_list.count())]
        assert "README.md" in names
        dlg.file_list.setCurrentRow(names.index("README.md"))
        QApplication.processEvents()
        dlg.editor.setPlainText("# edited — ünïcode\n")
        dlg._save_file()
        text, is_text = assets.read_asset_text(
            os.path.join(dlg.custom_path(), "README.md"))
        assert is_text and text == "# edited — ünïcode\n"
        assert "Saved README.md" in dlg.editor_hint.text()
    finally:
        dlg.deleteLater()


def test_binary_file_is_read_only_with_hint(qapp, tenant):
    dlg, _calls = _dialog(tenant)
    try:
        dlg.list_widget.setCurrentRow(0)
        dlg._create()
        binary = os.path.join(dlg.custom_path(), "firmware.bin")
        with open(binary, "wb") as handle:
            handle.write(b"\x00\x01\x02")
        dlg._toggle_editor()
        dlg.file_list.setCurrentRow(
            [dlg.file_list.item(i).text()
             for i in range(dlg.file_list.count())].index("firmware.bin"))
        QApplication.processEvents()
        assert dlg.editor.isReadOnly()
        assert not dlg.btn_save.isEnabled()
        assert "binary file" in dlg.editor_hint.text()
        assert "external editor" in dlg.editor_hint.text()
    finally:
        dlg.deleteLater()


# ------------------------------------------------- default_assets_dir priority
def test_default_assets_dir_priority(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    (base / "P1").mkdir(parents=True)
    (base / "P1" / "assets_P1").mkdir()
    (base / "P2").mkdir()
    (base / "P2" / "assets").mkdir()
    (base / "P3").mkdir()
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.chdir(tmp_path.parent)
    path, hint = default_assets_dir("P1", str(base), str(bundled))
    assert os.path.basename(path) == "assets_P1" and hint == ""
    path, hint = default_assets_dir("P2", str(base), str(bundled))
    assert os.path.basename(path) == "assets" and hint == ""
    path, hint = default_assets_dir("P3", str(base), str(bundled))
    assert path == os.path.normpath(str(bundled)) and hint
    # no project name -> bundled template
    path, hint = default_assets_dir("", str(base), str(bundled))
    assert path == os.path.normpath(str(bundled)) and hint == ""


# ------------------------------------------------------------ YAML binding
def test_binding_writes_shared_params_without_steps(qapp, tmp_path):
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import \
        FCTTestConfigPanel
    from mtkgui.main_window import MainWindow
    w = MainWindow(role="SUPERVISOR", mode="Virtual")
    try:
        before = w.workflow_page.fct.rowCount()
        bound = tmp_path / "assets_29420"
        bound.mkdir()
        w._bind_project_assets("29420", str(bound))
        params = w.yaml_build_page.model.get_params("fct_build")
        assert params["assets_dir"] == os.path.normpath(str(bound))
        assert params["project_name"] == "29420"
        # no sequence row injected / removed by the assets binding
        assert w.workflow_page.fct.rowCount() == before
        # the next FCT panel load reads the bound folder as the push
        # source (bound value wins over the bundled template)
        panel = FCTTestConfigPanel()
        try:
            panel.set_values(dict(params))
            path, hint = panel._default_assets_dir()
            assert path == os.path.normpath(str(bound)) and hint == ""
        finally:
            panel.deleteLater()
    finally:
        w.close()
        w.deleteLater()
