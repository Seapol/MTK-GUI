# -*- coding: utf-8 -*-
"""Load current yaml (user direction 2026-10-13).

The "Load current yaml" button derives the ICT / FCT sequences from
the CURRENT Yaml Build model and pushes them into the Test Work Flow
page.  Readiness gate: without a usable ICT configuration (parsed +
fully allocated nets, rails/clocks/gpios enabled) or FCT
configuration (configured fct_test_config) a warning is shown and
NOTHING is executed."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from mtkgui.main_window import MainWindow  # noqa: E402

MainWindow.__test__ = False


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _sandbox_cwd(tmp_path, monkeypatch):
    """Load current yaml auto-saves the project under ./projects/ -
    redirect the cwd so tests never write into the repository."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def window(qapp):
    w = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    yield w
    w.close()
    w.deleteLater()


def _make_ict_ready(window):
    """Parsed nets + full channel allocation + enabled build modules
    (the blocks 01-04 readiness state)."""
    model = window.yaml_build_page.model
    model.imported["testable_nets"] = {
        "3V3": {"category": "Power", "members": ["U1.5"]},
        "CLK_24M": {"category": "Clock", "members": ["U1.10"]},
    }
    model.set_channel_allocation({
        "power": [{"net": "3V3", "impedance": "DAQM908A #1 CH101",
                   "power_rails": "U2355A AI01",
                   "voltage": "DAQM908A #1 CH101"}],
        "clock": [{"net": "CLK_24M", "se_clock_hz": "DAQM907A TOT"}],
        "gpio": [],
    })
    window.yaml_build_page.channel_alloc.refresh_from_model()


def test_load_blocked_without_configuration(window, monkeypatch):
    """Fresh model: nothing usable -> the warning box shows, nothing
    is loaded (empty ICT table, no 'Current yaml loaded' log line)."""
    warnings = []
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.warning",
        lambda *a, **k: warnings.append(k[1] if len(k) > 1 else a[1]))
    window._load_current_yaml()
    assert warnings == ["Load current yaml"]
    # nothing generated: no ICT test rows (the placeholder op row of
    # a fresh page is fine)
    steps = window.workflow_page.ict_steps
    assert not any("Impedance" in s[1] or "Clock Hz" in s[1]
                   for s in steps)
    logged = window.event_log.toPlainText()
    assert "Current yaml loaded" not in logged


def test_load_pushes_ict_sequence_and_jumps(window):
    """With blocks 01-04 ready the ICT sequence (tests + standard
    operations) lands in the ICT table and the GUI jumps to the Test
    Work Flow tab."""
    _make_ict_ready(window)
    window._load_current_yaml()
    assert window.tabs.currentWidget() is window.workflow_page
    ict_steps = window.workflow_page.ict_steps
    names = [s[1] for s in ict_steps]
    # standard operations around the generated tests
    assert "Init Instruments" in names
    assert any(n.startswith("Static Impedance") for n in names)
    assert any(n.startswith("Power Voltage") for n in names)
    assert any(n.startswith("Clock Hz") for n in names)
    # the derived limits: P3V3-style net name absent, but the power
    # rails channel rows carry the sequence; row count = 4 ops before
    # + 2 tests + 1 op mid + 1 DAQ AI capture + 1 test + 4 ops after
    assert len(ict_steps) == 13
    # user direction 2026-10-14: the DAQ AI power-rails capture sits
    # right AFTER Power On DUT and BEFORE the Power Voltage tests
    daq_idx = next(i for i, s in enumerate(ict_steps)
                   if s[0] == "DAQ AI")
    on_idx = ict_steps.index(next(s for s in ict_steps
                                  if s[1] == "Power On DUT"))
    volt_idx = next(i for i, s in enumerate(ict_steps)
                    if s[1].startswith("Power Voltage"))
    assert on_idx < daq_idx < volt_idx
    # the DAQ AI Net cell is the read-only rail count (channel
    # allocation here holds exactly one U2355A AI power rail)
    assert ict_steps[daq_idx][1] == "1 Power rails assigned on DAQ channels"


def test_load_current_yaml_button_wired(window, monkeypatch):
    """The page "Load current yaml" button routes into the main
    window slot (the same behavior as the File-menu style slot)."""
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.warning",
        lambda *a, **k: None)      # the fresh-model gate warns (mocked)
    clicked = []
    window.yaml_build_page.load_yaml_requested.connect(
        lambda: clicked.append(True))
    window.yaml_build_page.btn_load_yaml.click()
    assert clicked == [True]


def test_load_merges_manually_filled_limits(window):
    """Re-running Load current yaml keeps manually edited limits:
    Auto re-derives what it can, filled Expected / Min / Max cells
    win (user direction 2026-10-14)."""
    _make_ict_ready(window)
    window._load_current_yaml()
    steps = window.workflow_page.ict_steps
    clock = next(s for s in steps if s[1].startswith("Clock Hz"))
    edited = ("test", clock[1], clock[2], clock[3],
              "23880000.0", "24120000.0")
    window.workflow_page.ict_steps = [
        edited if s is clock else s for s in steps]
    window._load_current_yaml()
    clock2 = next(s for s in window.workflow_page.ict_steps
                  if s[1] == clock[1])
    assert (clock2[4], clock2[5]) == ("23880000.0", "24120000.0")


def test_load_autosaves_project_file(window):
    """A Load with no project file loaded auto-saves the project under
    ./projects/ (standard naming) so the Run gate ("No YAML file is
    loaded") cannot hit right after a Load."""
    _make_ict_ready(window)
    window.yaml_build_page.model.set_params("design_input", {
        "product_id": "29420", "part_number": "MTK12345",
        "batch": "EVT (Proto-1)"})
    assert window._project_path is None
    window._load_current_yaml()
    assert window._project_path is not None
    path = Path(window._project_path)
    assert path.exists()
    assert path.parent.name == "projects"
    assert path.name == "MTK12345_29420_EVT-(Proto-1)" \
        "_rev_1.0.0_Draft.yaml"
    # the Overall Flow Project File label follows the auto-save
    assert window.workflow_page.project_path == str(path)


def test_load_syncs_product_information(window):
    """The Design Input identity lands in Product Information on Load
    (previously the group stayed empty); the serial number stays
    manual.  Core ID keeps the parser's 4..10-digit domain."""
    _make_ict_ready(window)
    window.yaml_build_page.model.set_params("design_input", {
        "product_id": "29420", "part_number": "MTK12345",
        "batch": "EVT (Proto-1)"})
    window.workflow_page.serial_edit.setText("SN01")
    window._load_current_yaml()
    page = window.workflow_page
    assert page.part_edit.text() == "MTK12345"
    assert page.core_edit.text() == "29420"
    assert page.batch_edit.text() == "EVT (Proto-1)"
    assert page.serial_edit.text() == "SN01"
    # a 10-digit core id survives (the old 6-digit limit truncated it)
    window.yaml_build_page.model.set_params(
        "design_input", {"product_id": "1234567890"})
    window._load_current_yaml()
    assert page.core_edit.text() == "1234567890"


def test_zero_test_items_block_run(window, monkeypatch):
    """User direction 2026-10-14: each stage may legally run empty,
    but a run with NO test items at all (ICT and FCT both empty) is
    blocked with a warning.  Placeholder / op-only rows never count."""
    page = window.workflow_page
    assert page.test_item_counts() == (0, 0)   # fresh placeholders
    page.project_path = "dummy.yaml"           # pass the project gate
    warnings, logs = [], []
    monkeypatch.setattr(
        "mtkgui.test_workflow_page.QMessageBox.warning",
        lambda *a, **k: warnings.append(k[0] if len(k) > 0 else a[1]))
    page.log_line.connect(logs.append)
    page.start_run()
    assert warnings == ["No Test Items"]
    assert page.run_state != "running"
    assert any("no test items" in ln for ln in logs)

    # with a real test item the gate passes (no zero-item warning;
    # the runner itself is mocked out - this test checks the gate)
    page.ict_steps = [("test", "Static Impedance - 3V3", "Ω",
                       "—", "30", "—")]
    warnings.clear()
    monkeypatch.setattr(page._runner, "start", lambda *a, **k: None)
    monkeypatch.setattr(
        "mtkgui.test_workflow_page.TestWorkFlowPage._pretest",
        lambda self: True)
    page.start_run()
    assert warnings == []


def test_save_without_test_items_asks(window, monkeypatch, tmp_path):
    """Saving a YAML with no usable test items asks for confirmation:
    No cancels the save, Yes checkpoints the working file."""
    page = window.workflow_page
    assert page.test_item_counts() == (0, 0)
    out = tmp_path / "empty.yaml"
    answers = iter([QMessageBox.StandardButton.No])
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.question",
        lambda *a, **k: next(answers))
    window._save_yaml_to(str(out))
    assert not out.exists()
    assert window._project_path is None
    answers = iter([QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.question",
        lambda *a, **k: next(answers))
    window._save_yaml_to(str(out))
    assert out.exists()
    assert window._project_path == str(out)


def test_close_clears_run_state(window, monkeypatch):
    """Close Yaml resets the last RUN state: Overall Flow statuses /
    durations back to Pending / --, the verdict to '-' and the
    per-product statistics to zero - with the session Event Log kept
    (user direction 2026-10-14, stale Virtual PASS panel screenshot)."""
    page = window.workflow_page
    # fabricate the finished-run state of the user screenshot
    page.products_passed = 3
    page.products_failed = 0
    page.cycle_times = [9.42]
    for r, (status, dur) in enumerate((("PASS", "6.84"),
                                       ("PASS", "2.26"))):
        page.overall.item(r, 3).setText(status)
        page.overall.item(r, 4).setText(dur)
    page._update_result()
    window._append_event_log("pre-close entry")

    window.close_yaml()

    for r in range(2):
        assert page.overall.item(r, 3).text() == "Pending"
        assert page.overall.item(r, 4).text() == "--"
    assert page.result_label.text() == "—"
    stats = page.result_stats.text()
    assert "Passed: 0 | Failed: 0" in stats
    assert "Yield: —" in stats
    assert "Cycle Time (avg): —" in stats
    # the session log history survives the reset
    logged = window.event_log.toPlainText()
    assert "pre-close entry" in logged
    assert "Yaml closed" in logged


def test_yaml_load_updates_product_information(window, monkeypatch):
    """File > Load Yaml fills Product Information from the loaded
    file's product section (round trip: Load current yaml auto-save ->
    Close -> Load)."""
    _make_ict_ready(window)
    window.yaml_build_page.model.set_params("design_input", {
        "product_id": "29420", "part_number": "MTK12345",
        "batch": "EVT (Proto-1)"})
    window._load_current_yaml()          # auto-saves with product info
    saved = window._project_path
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.close_yaml()                  # Product Information blanked
    assert window.workflow_page.part_edit.text() == ""

    monkeypatch.setattr(
        "mtkgui.main_window.QFileDialog.getOpenFileName",
        lambda *a, **k: (saved, ""))
    window.load_yaml()
    page = window.workflow_page
    assert page.part_edit.text() == "MTK12345"
    assert page.core_edit.text() == "29420"
    assert page.batch_edit.text() == "EVT (Proto-1)"
    assert page.project_path == saved


def test_plan_yaml_load_updates_product_information(window,
                                                    monkeypatch,
                                                    tmp_path):
    """File > Load Yaml of a published PLAN file fills Product
    Information from the plan's design_input section (user direction
    2026-10-14: the plan branch previously left the group empty)."""
    import yaml as _yaml
    plan = {
        "plan": {"kind": "draft", "plan_version": "1.0.0"},
        "yaml_build": {
            "plan_version": "1.0.0",
            "modules": {"design_input": {
                "part_number": "MTK12345", "product_id": "29420",
                "batch": "EVT (Proto-1)"}},
        },
    }
    path = tmp_path / "plan.yaml"
    path.write_text(_yaml.safe_dump(plan), encoding="utf-8")
    monkeypatch.setattr(
        "mtkgui.main_window.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(path), ""))
    window.load_yaml()
    page = window.workflow_page
    assert page.part_edit.text() == "MTK12345"
    assert page.core_edit.text() == "29420"
    assert page.batch_edit.text() == "EVT (Proto-1)"
    assert "Plan yaml loaded" in window.event_log.toPlainText()
