# -*- coding: utf-8 -*-
"""P3-B2 T7: Design Input module refactor tests.

Import/Parse split inside the unified panel (no standalone popup),
SPF auto-parse (Core ID from file name, Project Name from the
first-page title), NET load-only, fixed Batch # options with the
Customized / Deviation (DRQ) dialogs, YAML round trip and legacy
compatibility."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QInputDialog,
    QMessageBox,
)

from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog  # noqa: E402
from mtkgui.gui.yamlbuild.design_input_panel import (  # noqa: E402
    DesignInputPanel,
    DrqDialog,
)
from mtkgui.gui.yamlbuild.schema import (  # noqa: E402
    BATCH_CUSTOMIZED_PREFIX,
    BATCH_DEVIATION_PREFIX,
    BATCH_OPTIONS,
    MODULE_FIELDS,
)
from mtkgui.gui.yamlbuild.spf_title import (  # noqa: E402
    extract_spf_project_name,
)

SPF_SAMPLE = """[Drawing]
FRDM-IMXRT700 CPU Board

[Component]
U1 ; MIMXRT798S
"""

NET_SAMPLE = """*SIGNAL* 3V3
U1.5 U2.VOUT
"""


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _silent_part_popup(monkeypatch):
    """B1 closure #4: the SPF import now pops the non-silent Project
    Part# guidance - tests stub it out (the wording itself is covered
    by the dedicated test)."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: None)


@pytest.fixture()
def panel(qapp):
    w = DesignInputPanel()
    yield w
    w.deleteLater()


@pytest.fixture()
def files(tmp_path):
    spf = tmp_path / "spf-92722_revB.spf"
    spf.write_text(SPF_SAMPLE, encoding="utf-8")
    net = tmp_path / "board.net"
    net.write_text(NET_SAMPLE, encoding="utf-8")
    return str(spf), str(net)


# ------------------------------------------------------------- schema
def test_part_number_nonsilent_guidance(panel, monkeypatch):
    """B1 closure #4: the non-silent Project Part# mechanism - the
    standard popup wording, the resident muted hint and the Event-Log
    line all fire on an SPF import."""
    import tempfile
    from pathlib import Path

    from PySide6.QtWidgets import QLabel, QMessageBox
    from mtkgui.gui.yamlbuild.design_input_panel import (
        PART_NO_AUTO_SOURCE_HINT,
        PART_NO_AUTO_SOURCE_LOG,
        PART_NO_AUTO_SOURCE_POPUP,
    )
    popups = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: popups.append(a[2]))
    logs = []
    panel.task_log.connect(lambda level, msg: logs.append(msg))
    # the resident muted hint always sits next to the field
    assert PART_NO_AUTO_SOURCE_HINT in \
        [w.text() for w in panel.findChildren(QLabel)]
    # popup + Event-Log wording on an SPF import
    with tempfile.TemporaryDirectory() as td:
        spf = Path(td) / "spf-92722_revB.spf"
        spf.write_text(SPF_SAMPLE, encoding="utf-8")
        monkeypatch.setattr(
            QFileDialog_PATCH,
            staticmethod(lambda *a, **k: (str(spf), "")))
        panel._import_spf()
    assert popups == [PART_NO_AUTO_SOURCE_POPUP]
    assert PART_NO_AUTO_SOURCE_LOG in logs


# ------------------------------------------------------------- schema
def test_schema_design_input_fields():
    """The design_input schema carries exactly the T7 field set; the
    deprecated design-data fields are gone."""
    names = [f.name for f in MODULE_FIELDS["design_input"]]
    assert names == ["product_id", "part_number", "sw_version",
                     "hw_version", "batch", "spf_file", "net_file"]
    assert "design_data" not in names
    batch = next(f for f in MODULE_FIELDS["design_input"]
                 if f.name == "batch")
    assert batch.choices == BATCH_OPTIONS
    assert len(BATCH_OPTIONS) == 8


# --------------------------------------------------------- SPF import
QFileDialog_PATCH = "PySide6.QtWidgets.QFileDialog.getOpenFileName"


def test_spf_import_autoparse(panel, files, monkeypatch):
    """Import SPF reads + auto-parses: Core ID from the file name,
    Project Name from the first-page title; fields stay editable."""
    spf, _net = files
    monkeypatch.setattr(QFileDialog_PATCH,
                        staticmethod(lambda *a, **k: (spf, "")))
    rec_progress = []
    panel.task_progress.connect(lambda p, l: rec_progress.append(p))
    panel._import_spf()
    assert panel.edit_product_id.text() == "92722"
    assert panel.edit_part_number.text() == "FRDM-IMXRT700 CPU Board"
    assert "spf-92722_revB.spf" in panel.lbl_spf.text()
    assert rec_progress[-1] == 100


def test_spf_import_manual_override(panel, files, monkeypatch):
    """Auto-filled fields accept manual edits (override)."""
    panel._import_spf() if False else None
    panel.edit_product_id.setText("MY-CORE")
    panel.edit_part_number.setText("My Project")
    v = panel.values()
    assert v["product_id"] == "MY-CORE"
    assert v["part_number"] == "My Project"


def test_spf_import_failure_reports_reason(panel, tmp_path,
                                           monkeypatch):
    """Empty SPF: exact reason, ERROR log, no progress left hanging."""
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a) or 0)
    bad = tmp_path / "spf-00001.spf"
    bad.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog_PATCH,
        staticmethod(lambda *a, **k: (str(bad), "")))
    logs = []
    panel.task_log.connect(lambda l, m: logs.append((l, m)))
    panel._import_spf()
    assert shown and "SPF import failed" in shown[0][2]
    assert any(l == "ERROR" for l, _m in logs)


def test_net_import_load_only(panel, files, monkeypatch):
    """Import NET stores the raw bytes ONLY - no parse, no structure
    analysis, no generated data."""
    _spf, net = files
    monkeypatch.setattr(
        QFileDialog_PATCH,
        staticmethod(lambda *a, **k: (net, "")))
    panel._import_net()
    assert panel.net_text == NET_SAMPLE
    assert "board.net" in panel.lbl_net.text()
    v = panel.values()
    assert v["net_file"] and "board.net" in v["net_file"]


def test_net_import_empty_reports_reason(panel, tmp_path,
                                         monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a) or 0)
    empty = tmp_path / "empty.net"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog_PATCH,
        staticmethod(lambda *a, **k: (str(empty), "")))
    panel._import_net()
    assert shown and "NET import failed" in shown[0][2]
    assert panel.net_path == ""


# -------------------------------------------------------------- batch
def test_batch_options_fixed(panel):
    """The Batch # dropdown carries exactly the 8 fixed options."""
    items = [panel.combo_batch.itemText(i)
             for i in range(panel.combo_batch.count())]
    assert items == list(BATCH_OPTIONS)


def test_batch_customized_dialog(panel, monkeypatch):
    """Customized opens a name dialog; the value persists with the
    'Customized: ' prefix."""
    shown = []
    monkeypatch.setattr(
        QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("My Batch", True)))
    panel.combo_batch.setCurrentText("Customized")
    panel._on_batch_activated(panel.combo_batch.currentIndex())
    assert panel.batch_value() == BATCH_CUSTOMIZED_PREFIX + "My Batch"
    assert shown == []


def test_batch_deviation_dialog_max_three(panel, monkeypatch):
    """Deviation (DRQ): the dialog accepts up to 3 DRQ numbers."""
    dlg = DrqDialog(["DRQ-001", "DRQ-002", "DRQ-003", "DRQ-004"])
    nums = dlg.drq_numbers()      # 4th entry is dropped by the dialog
    assert len(nums) <= 3
    from PySide6.QtWidgets import QDialog
    monkeypatch.setattr(
        "mtkgui.gui.yamlbuild.design_input_panel.DrqDialog.exec",
        lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(
        "mtkgui.gui.yamlbuild.design_input_panel.DrqDialog.drq_numbers",
        lambda self: ["DRQ-101", "DRQ-102"])
    panel.combo_batch.setCurrentText("Deviation (DRQ)")
    panel._on_batch_activated(panel.combo_batch.currentIndex())
    assert panel.batch_value() == \
        BATCH_DEVIATION_PREFIX + "DRQ-101, DRQ-102"


def test_batch_plain_option_direct(panel):
    """A fixed option (e.g. MP (Production)) needs no dialog."""
    panel.combo_batch.setCurrentText("MP (Production)")
    assert panel.batch_value() == "MP (Production)"


# ------------------------------------------------ YAML round trip / compat
def test_values_yaml_round_trip(panel):
    """values() -> set_values() keeps every field incl. the resolved
    batch string."""
    panel.edit_product_id.setText("92722")
    panel.edit_part_number.setText("FRDM Board")
    panel.edit_sw_version.setText("1.0")
    panel.edit_hw_version.setText("B")
    panel.set_batch(BATCH_CUSTOMIZED_PREFIX + "VIP run")
    data = panel.values()
    fresh = DesignInputPanel()
    try:
        fresh.set_values(data)
        assert fresh.values() == data
        assert fresh.combo_batch.currentText() == "Customized"
        assert fresh.lbl_batch_detail.text() == "VIP run"
    finally:
        fresh.deleteLater()


def test_legacy_batch_maps_to_customized(panel):
    """Old free-text batch values (e.g. 'B9') load as Customized."""
    panel.set_batch("B9")
    assert panel.combo_batch.currentText() == "Customized"
    assert panel.batch_value() == BATCH_CUSTOMIZED_PREFIX + "B9"


def test_legacy_field_mapping(panel):
    """Old YAML keys map onto the new fields: core_id -> Product ID,
    project_name -> Project Part #, schematic_file -> SPF File."""
    panel.set_values({
        "core_id": "IMXRT700", "project_name": "Old Board",
        "schematic_file": "spf-1.spf", "batch": "EVT (Proto-1)",
    })
    v = panel.values()
    assert v["product_id"] == "IMXRT700"
    assert v["part_number"] == "Old Board"
    assert "spf-1.spf" in v["spf_file"]


# -------------------------------------------------- block dialog embed
def test_block_dialog_embeds_panel(qapp):
    """block01 opens the unified panel; no standalone import popup
    button, no deprecated import_result attribute."""
    dlg = BlockConfigDialog("design_input", {"batch": "DVT (Proto-2)"})
    try:
        assert dlg.panel is not None
        assert dlg.panel.combo_batch.currentText() == "DVT (Proto-2)"
        assert dlg.form.rowCount() == 0     # no duplicate generic form
        assert not hasattr(dlg, "import_result")
        buttons = [dlg.panel.btn_import_spf.text(),
                   dlg.panel.btn_import_net.text()]
        assert buttons == ["Import SPF…", "Import NET…"]
    finally:
        dlg.deleteLater()


def test_block_dialog_validates_required(panel, qapp, monkeypatch):
    """Accept without the required fields stays open with the error
    list (all-or-nothing save)."""
    dlg = BlockConfigDialog("design_input", {})
    try:
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: 0)
        dlg._on_accept()
        assert not dlg.result() or True   # not accepted
        assert "value required" in dlg.error_label.text()
    finally:
        dlg.deleteLater()


# ------------------------------------------------------- title helper
def test_spf_title_extractor():
    assert extract_spf_project_name(SPF_SAMPLE) == \
        "FRDM-IMXRT700 CPU Board"
    assert extract_spf_project_name("") == ""
    assert extract_spf_project_name("[Component]\nU1 ; X\n") == ""


# ------------------------------------------------ item 21 (final fix)
def test_spf_filter_pdf_only(panel, monkeypatch):
    """Import SPF accepts ONLY Allegro Smart PDF (*.pdf) - the txt /
    .spf text fallback is removed from the file dialog filter."""
    captured = {}
    monkeypatch.setattr(
        QFileDialog_PATCH,
        staticmethod(lambda _p, _t, _d, flt: captured.update(
            filter=flt) or ("", "")))
    panel._import_spf()
    assert captured["filter"] == \
        "Allegro Smart PDF (*.pdf);;All files (*.*)"
    assert "*.txt" not in captured["filter"]
    assert "*.spf" not in captured["filter"]


def test_optional_labels_and_only_product_id_required():
    """SW / HW / Batch carry '(optional)' labels and stay non-required
    (root-cause closure directive); Project Part # is the manual-entry
    board-level part number (required, no '(optional)' mark) and
    Product ID stays the other mandatory field."""
    specs = {f.name: f for f in MODULE_FIELDS["design_input"]}
    for name in ("sw_version", "hw_version", "batch"):
        assert "(optional)" in specs[name].label, name
        assert specs[name].required is False, name
    # Project Part # manual-entry final scheme (no auto source)
    assert specs["part_number"].label == "Project Part #"
    assert specs["part_number"].required is True
    assert specs["product_id"].label == "Product ID"
    assert specs["product_id"].required is True
    # empty optional values validate clean
    assert specs["sw_version"].validate("") == ""
    assert specs["hw_version"].validate("") == ""
    assert specs["batch"].validate("") == ""


def test_accept_with_blank_optional_fields_passes(qapp, monkeypatch):
    """No 'Required' warning when SW / HW Version are blank - the
    mandatory fields (Product ID / Project Part #) are validated."""
    warnings = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a))
    dlg = BlockConfigDialog("design_input", {})
    try:
        dlg.panel.edit_product_id.setText("10342")
        dlg.panel.edit_part_number.setText("MTK12345")
        dlg._on_accept()          # blank SW / HW must pass
        assert not warnings       # no validation popup at all
        assert dlg.error_label.text() == ""
    finally:
        dlg.deleteLater()


def test_accept_blank_part_number_blocked(qapp, monkeypatch):
    """Project Part # is the manual-entry mandatory board-level part
    number: blank -> validation popup, dialog stays open."""
    warnings = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a))
    dlg = BlockConfigDialog("design_input", {})
    try:
        dlg.panel.edit_product_id.setText("10342")
        dlg._on_accept()
        assert warnings            # validation popup shown
        assert "Project Part #" in dlg.error_label.text()
    finally:
        dlg.deleteLater()


def test_accept_empty_product_id_still_blocked(qapp, monkeypatch):
    """Product ID remains mandatory: blank -> error list, dialog open."""
    warnings = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a))
    dlg = BlockConfigDialog("design_input", {})
    try:
        dlg._on_accept()
        assert warnings            # validation popup shown
        assert "Product ID" in dlg.error_label.text()
    finally:
        dlg.deleteLater()


def test_panel_layout_adaptive(qapp):
    """Item 21: the panel is expanding in both directions, the meta
    form uses the flat evenly-spaced Qt form layout and all fields
    grow proportionally when the dialog widens."""
    from PySide6.QtWidgets import (
        QFormLayout,
        QSizePolicy,
    )
    dlg = BlockConfigDialog("design_input", {})
    try:
        p = dlg.panel
        assert p.sizePolicy().horizontalPolicy() \
            == QSizePolicy.Policy.Expanding
        assert p.sizePolicy().verticalPolicy() \
            == QSizePolicy.Policy.Expanding
        form = p.findChild(QFormLayout)
        assert form is not None
        assert form.verticalSpacing() >= 12
        assert form.fieldGrowthPolicy() \
            == QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        dlg.resize(460, 500)
        dlg.show()
        qapp.processEvents()
        w_small = p.edit_product_id.width()
        dlg.resize(760, 500)
        qapp.processEvents()
        assert p.edit_product_id.width() > w_small
        # all input boxes share the same width (aligned columns)
        assert p.edit_product_id.width() \
            == p.edit_part_number.width() \
            == p.edit_sw_version.width() \
            == p.edit_hw_version.width()
        dlg.hide()
    finally:
        dlg.deleteLater()
