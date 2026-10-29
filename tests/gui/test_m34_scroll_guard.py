# -*- coding: utf-8 -*-
"""M34 global scroll-guard regressions (offscreen Qt).

Every main page / config dialog must put its body inside a
``QScrollArea`` on a small window (900x520) while keeping the bottom
OK / Cancel row outside the scroll area.  The tests also prove that no
VISIBLE sibling widgets intersect after the layout settles, and that
the Wi-Fi / Bluetooth tab scroll areas from M31 / M32 are untouched.

Dialogs that only exist inside a modal event flow (``exec()``) are
driven here with ``QDialog.exec`` stubbed out; the truly
non-instantiable ones are listed in :data:`UNCOVERED_DIALOGS`.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizeGrip,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.dialog_sizing import (  # noqa: E402
    apply_scroll_to_dialog,
    wrap_page,
    wrap_scrollable,
)

#: 900x520 - the small-window floor named by the M34 acceptance rule.
SMALL_W, SMALL_H = 900, 520

#: dialogs that cannot be constructed offscreen without driving the
#: owning page's live event flow / OS integration.  They are still
#: scroll-wrapped in code, but have no direct geometry test here.
UNCOVERED_DIALOGS = (
    "mtkgui.gui.progress_dialog.ProgressDialog "
    "(long-task modal, driven by QThread signals)",
    "QMessageBox / QFileDialog / native OS dialogs "
    "(system-owned geometry)",
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------
def _show(widget: QWidget, width: int = SMALL_W,
          height: int = SMALL_H) -> QWidget:
    """Show at the small acceptance size and flush the layout."""
    widget.resize(width, height)
    widget.show()
    QApplication.processEvents()
    lay = widget.layout()
    if lay is not None:
        lay.activate()
    QApplication.processEvents()
    return widget


def _scroll_areas_with_marked_content(widget: QWidget) -> list[QScrollArea]:
    out = []
    for scroll in widget.findChildren(QScrollArea):
        body = scroll.widget()
        if body is None:
            continue
        if isinstance(body, QWidget) and bool(
                body.property("_m34_scrolled")):
            out.append(scroll)
    return out


def _outer_scroll(widget: QWidget) -> QScrollArea | None:
    """The scroll area installed directly in ``widget``'s own layout."""
    lay = widget.layout()
    if lay is None:
        return None
    for index in range(lay.count()):
        item = lay.itemAt(index)
        if item is not None and isinstance(item.widget(), QScrollArea):
            return item.widget()
    return None


def _inside_scroll(widget: QWidget) -> bool:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            return True
        parent = parent.parentWidget()
    return False


def _assert_page_wrapped(page: QWidget, label: str) -> QScrollArea:
    scroll = _outer_scroll(page)
    assert isinstance(scroll, QScrollArea), (
        f"{label}: the page layout has no QScrollArea")
    body = scroll.widget()
    assert body is not None, f"{label}: the scroll area is empty"
    assert bool(body.property("_m34_scrolled")), (
        f"{label}: the scroll content is not marked _m34_scrolled")
    return scroll


def _bottom_button_row(dlg: QDialog) -> QWidget:
    """The always-visible bottom button row (button box first)."""
    boxes = [box for box in dlg.findChildren(QDialogButtonBox)
             if box.isVisible() and not _inside_scroll(box)]
    if boxes:
        return boxes[0]
    buttons = [btn for btn in dlg.findChildren(QPushButton)
               if btn.isVisible() and not _inside_scroll(btn)]
    assert buttons, "dialog has no visible button row outside the scroll"
    return max(buttons, key=lambda b: b.mapTo(dlg, QPoint(0, 0)).y())


def _assert_dialog_wrapped(dlg: QDialog, label: str) -> QScrollArea:
    scrolls = _scroll_areas_with_marked_content(dlg)
    assert scrolls, f"{label}: dialog body is not inside a QScrollArea"
    return scrolls[0]


def _assert_button_row_visible(dlg: QDialog, label: str) -> None:
    row = _bottom_button_row(dlg)
    assert row.isVisible(), f"{label}: bottom button row is not visible"
    pos = row.mapTo(dlg, QPoint(0, 0))
    assert pos.y() >= 0, f"{label}: bottom button row starts above the dialog"
    assert pos.y() + row.height() <= dlg.height() + 1, (
        f"{label}: bottom button row falls below the dialog "
        f"(row_bottom={pos.y() + row.height()}, dialog_h={dlg.height()})")


def _visible_children(parent: QWidget) -> list[QWidget]:
    children = []
    for child in parent.findChildren(
            QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
        if not child.isVisible():
            continue                      # hidden / non-current stack page
        if isinstance(child, (QScrollBar, QSizeGrip)):
            continue          # scroll bars / resize grips are decorations
        children.append(child)
    if isinstance(parent, QStackedWidget):
        current = parent.currentWidget()
        children = [current] if current is not None else []
    return children


def _assert_no_overlap(root: QWidget, label: str) -> None:
    """Recursively: visible sibling widgets never intersect (M34).

    Scroll bars, hidden widgets and non-current ``QStackedWidget`` pages
    are skipped (Qt keeps them alive but not laid out).  A 1 px
    tolerance absorbs style-margin rounding.
    """
    stack = [root]
    while stack:
        parent = stack.pop()
        kids = _visible_children(parent)
        for i, first in enumerate(kids):
            rect_a = first.geometry()
            for second in kids[i + 1:]:
                rect_b = second.geometry()
                inter = rect_a.intersected(rect_b)
                assert inter.width() <= 1 or inter.height() <= 1, (
                    f"{label}: visible siblings overlap - "
                    f"{type(first).__name__}({rect_a.getRect()}) / "
                    f"{type(second).__name__}({rect_b.getRect()})")
        stack.extend(kids)


def _check(widget: QWidget, label: str) -> None:
    _show(widget)
    _assert_no_overlap(widget, label)


# ---------------------------------------------------------------------------
# helper idempotency
# ---------------------------------------------------------------------------
def test_wrap_scrollable_is_idempotent(qapp):
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.addWidget(QLabel("field"))
    scroll = wrap_scrollable(content)
    assert isinstance(scroll, QScrollArea)
    assert scroll.widget() is content
    assert bool(content.property("_m34_scrolled"))
    assert wrap_scrollable(content) is scroll       # never a second scroll


def test_apply_scroll_to_dialog_keeps_buttons_outside(qapp):
    dlg = QDialog()
    outer = QVBoxLayout(dlg)
    body = QWidget()
    body_lay = QVBoxLayout(body)
    body_lay.addWidget(QPushButton("field"))
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
    outer.addWidget(body)
    outer.addWidget(buttons)

    apply_scroll_to_dialog(dlg, body)
    scroll = _outer_scroll(dlg)
    assert isinstance(scroll, QScrollArea)
    assert scroll.widget() is body
    assert not _inside_scroll(buttons), "button row must stay outside"
    assert buttons.parentWidget() is dlg
    # repeated call is a no-op
    before = dlg.findChildren(QScrollArea)
    apply_scroll_to_dialog(dlg, body)
    assert dlg.findChildren(QScrollArea) == before


def test_wrap_page_is_idempotent(qapp):
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.addWidget(QPushButton("content"))
    wrap_page(page)
    scroll = _outer_scroll(page)
    assert isinstance(scroll, QScrollArea)
    assert bool(page.property("_m34_page_scrolled"))
    wrap_page(page)
    assert _outer_scroll(page) is scroll


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------
def test_main_pages_scroll_guard(qapp, tmp_path, monkeypatch):
    from mtkgui.gui.yamlbuild import store
    monkeypatch.setattr(store, "STATE_DIR", tmp_path)
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "state.json")

    from mtkgui.equipment_page import EquipmentPage
    from mtkgui.test_workflow_page import TestWorkFlowPage
    from mtkgui.yaml_build_page import YamlBuildPage

    pages = [
        ("TestWorkFlowPage", TestWorkFlowPage()),
        ("EquipmentPage", EquipmentPage()),
        ("YamlBuildPage", YamlBuildPage()),
    ]
    for label, page in pages:
        _check(page, label)
        _assert_page_wrapped(page, label)
        page.close()
        page.deleteLater()


def _write_yaml(path, data) -> str:
    import yaml
    path.write_text(yaml.safe_dump(data, sort_keys=False),
                    encoding="utf-8")
    return str(path)


def _middle_page_factories():
    from mtkgui.engine.api_server import ApiServer, MesAdapter
    from mtkgui.engine.audit_hub import AuditHub
    from mtkgui.engine.auth_audit import AccessControl, AuditLog
    from mtkgui.engine.batch_pipeline import BatchPipeline
    from mtkgui.engine.cluster_hub import ClusterHub
    from mtkgui.engine.cluster_scheduler import ClusterScheduler
    from mtkgui.engine.metrics import MetricsEngine
    from mtkgui.engine.rbac_hub import RbacHub
    from mtkgui.engine.resource_hub import ResourceManager, PathHub
    from mtkgui.engine.task_queue import TaskQueue
    from mtkgui.engine.uploader import FakeSharePoint, SharePointUploader
    from mtkgui.gui.api_page import ApiPage
    from mtkgui.gui.audit_page import AuditPage
    from mtkgui.gui.case_editor import CaseEditorPage
    from mtkgui.gui.case_store import CaseStore
    from mtkgui.gui.cluster_page import ClusterPage
    from mtkgui.gui.compliance_page import CompliancePage
    from mtkgui.gui.config_page import ConfigPage
    from mtkgui.gui.config_store import ConfigStore
    from mtkgui.gui.export_page import ExportPage
    from mtkgui.gui.fleet_page import FleetPage
    from mtkgui.gui.pipeline_page import PipelinePage
    from mtkgui.gui.queue_page import QueuePage
    from mtkgui.gui.rbac_page import RbacPage
    from mtkgui.gui.resource_page import ResourcePage
    from mtkgui.gui.upload_page import UploadPage

    def audit_page(tmp):
        audit = AuditLog(tmp / "audit.jsonl")
        access = AccessControl(tmp / "accounts.json", audit=audit)
        access.ensure_default_accounts()
        return AuditPage(access, audit)

    def case_editor(tmp):
        path = _write_yaml(tmp / "cases.yaml", {
            "project": {"revision": "1.0"}, "ict_test_cases": []})
        return CaseEditorPage(path, store=CaseStore(
            snapshot_dir=str(tmp / "case_snaps")))

    def config_page(tmp):
        path = _write_yaml(tmp / "project.yaml", {
            "project": {"software": "mtk-gui", "revision": "1.0"},
            "product": {"part_number": "X"},
            "test_workflow": {"retry": 0}})
        return ConfigPage(path, store=ConfigStore(
            snapshot_dir=str(tmp / "config_snaps")))

    def upload_page(tmp):
        outbox = tmp / "outbox"
        outbox.mkdir(exist_ok=True)
        (outbox / "a.zip").write_bytes(b"PK-a")
        mgr = SharePointUploader(
            outbox, state_dir=tmp / "upload_state",
            transport=FakeSharePoint(), sleep=lambda s: 0)
        return UploadPage(mgr)

    def export_page(tmp):
        return ExportPage(MetricsEngine(), out_dir=str(tmp / "export"))

    def compliance_page(tmp):
        return CompliancePage(AuditHub(AuditLog(tmp / "audit.jsonl")))

    return [
        ("api_page", lambda tmp: ApiPage(
            ApiServer(), MesAdapter(enqueue=lambda body: None))),
        ("audit_page", audit_page),
        ("case_editor", case_editor),
        ("cluster_page", lambda tmp: ClusterPage(
            ClusterScheduler(log_fn=lambda line: None))),
        ("compliance_page", compliance_page),
        ("config_page", config_page),
        ("export_page", export_page),
        ("fleet_page", lambda tmp: FleetPage(ClusterHub(),
                                             ClusterScheduler())),
        ("pipeline_page", lambda tmp: PipelinePage(BatchPipeline())),
        ("queue_page", lambda tmp: QueuePage(TaskQueue())),
        ("rbac_page", lambda tmp: RbacPage(RbacHub())),
        ("resource_page", lambda tmp: ResourcePage(ResourceManager(),
                                                   PathHub())),
        ("upload_page", upload_page),
    ]


MIDDLE_PAGE_FACTORIES = _middle_page_factories()


@pytest.mark.parametrize(
    "label,factory", MIDDLE_PAGE_FACTORIES,
    ids=[item[0] for item in MIDDLE_PAGE_FACTORIES])
def test_middle_platform_pages_scroll_guard(qapp, tmp_path, label, factory):
    page = factory(tmp_path)
    page.interactive = False
    _check(page, label)
    _assert_page_wrapped(page, label)
    page.close()
    page.deleteLater()


# ---------------------------------------------------------------------------
# FCT panel tabs (Wi-Fi / BT must keep their M31 / M32 scroll areas)
# ---------------------------------------------------------------------------
def test_fct_panel_tabs_scroll_guard(qapp):
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel

    panel = FCTTestConfigPanel()
    labels = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    for name in ("Console", "Sequence", "Wi-Fi", "Bluetooth"):
        body = panel.tabs.widget(labels.index(name))
        assert isinstance(body, QScrollArea), (
            f"FCT {name} tab body must be a QScrollArea")
    # Wi-Fi / Bluetooth keep their original scroll widgets
    assert isinstance(panel.wifi_tab, QScrollArea)
    assert isinstance(panel.bt_tab, QScrollArea)

    _check(panel, "FCTTestConfigPanel")
    # all four tabs are already scroll-wrapped (no double wrap)
    for name in ("Console", "Sequence", "Wi-Fi", "Bluetooth"):
        scroll = panel.tabs.widget(labels.index(name))
        assert len(scroll.findChildren(QScrollArea)) == 0
    panel.close()
    panel.deleteLater()


# ---------------------------------------------------------------------------
# directly constructible dialogs
# ---------------------------------------------------------------------------
def _dialog_factories(tmp_path):
    from mtkgui.gui.sharepoint_upload_dialog import (
        ImportBrowserSessionDialog,
        SharePointSignInDialog,
        SharePointUploadDialog,
    )
    from mtkgui.gui.statistics_dialog import StatisticsDialog
    from mtkgui.gui.steps_editor import StepsEditorDialog
    from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
    from mtkgui.gui.yamlbuild.design_input_panel import DrqDialog
    from mtkgui.gui.yamlbuild.ict_sequence import IctWorkFlowSequenceDialog
    from mtkgui.gui.yamlbuild.net_rules import NetRulesEditorDialog

    fct_values = {"fct_test_config_yaml": (
        "fct_test_config:\n  dut_type: linux\n  console:\n"
        "    enabled: true\n    test_commands:\n"
        "      - {name: Kernel check, send: \"uname -a\", "
        "expect_pass: Linux}\n  wifi: {enabled: false}\n"
        "  bluetooth: {enabled: false}\n")}

    return [
        ("block_parse_ict", lambda: BlockConfigDialog("parse_ict", {})),
        ("block_design_input", lambda: BlockConfigDialog("design_input", {})),
        ("block_fct_build", lambda: BlockConfigDialog(
            "fct_build", fct_values, apply_save_cb=lambda v: None)),
        ("net_rules_editor", lambda: NetRulesEditorDialog({})),
        ("statistics", lambda: StatisticsDialog(
            None, runs_path=str(tmp_path / "runs.json"))),
        ("drq", lambda: DrqDialog(["DRQ1"])),
        ("steps_editor", lambda: StepsEditorDialog("ict", [], [], [], [])),
        ("ict_sequence", lambda: IctWorkFlowSequenceDialog(lambda: {})),
        ("sharepoint_signin", lambda: SharePointSignInDialog(
            view_factory=lambda: QLabel("stub web view"))),
        ("sharepoint_import", lambda: ImportBrowserSessionDialog()),
        ("sharepoint_upload", lambda: SharePointUploadDialog(
            None, virtual=True, config_path=tmp_path / "sp.json",
            state_dir=tmp_path / "sp_state")),
    ]


def test_dialogs_scroll_guard(qapp, tmp_path):
    for label, factory in _dialog_factories(tmp_path):
        dlg = factory()
        _show(dlg)
        _assert_dialog_wrapped(dlg, label)
        _assert_button_row_visible(dlg, label)
        _assert_no_overlap(dlg, label)
        if label == "block_fct_build":
            # m28: the fct_build dialog keeps its >= 1100 px minimum width
            assert dlg.minimumSizeHint().width() >= 1100
        dlg.close()
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# FCT inline QDialogs (six per-row editors, exec() stubbed)
# ---------------------------------------------------------------------------
def test_fct_inline_dialogs_scroll_guard(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog as QtDialog
    from mtkgui.engine.fct_test_config import ConsoleCommand
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel

    monkeypatch.setattr(QtDialog, "exec", lambda self: 0)
    panel = FCTTestConfigPanel()
    seen = set(panel.findChildren(QtDialog))

    class _TransportStub:
        def currentText(self) -> str:
            return "serial"

    monkeypatch.setattr(panel.cmd_table, "cellWidget",
                        lambda row, col: _TransportStub())

    calls = [
        ("fct_console_editor", lambda: panel._edit_console_row(0)),
        ("fct_flash_gui_editor", lambda: panel._edit_flash_gui_row(0)),
        ("fct_message_editor", lambda: panel._edit_message_cell(0)),
        ("fct_regex_editor",
         lambda: panel._edit_regex_cell(0, 3, "WaitFor")),
        ("fct_host_cmd_editor",
         lambda: panel._edit_host_cmd_cell(0, ConsoleCommand())),
        ("fct_sendto_editor", lambda: panel._edit_sendto_cell(0, 3)),
    ]
    for label, call in calls:
        call()
        created = [d for d in panel.findChildren(QtDialog)
                   if d not in seen]
        assert len(created) == 1, f"{label}: expected one dialog"
        dlg = created[0]
        seen.add(dlg)
        _show(dlg)
        _assert_dialog_wrapped(dlg, label)
        _assert_button_row_visible(dlg, label)
        _assert_no_overlap(dlg, label)
        dlg.close()
        dlg.deleteLater()
    panel.close()
    panel.deleteLater()


# ---------------------------------------------------------------------------
# StepsEditorDialog inline QDialogs (three per-row editors, exec() stubbed)
# ---------------------------------------------------------------------------
def test_steps_editor_inline_dialogs_scroll_guard(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog as QtDialog
    from mtkgui.gui.steps_editor import StepsEditorDialog

    monkeypatch.setattr(QtDialog, "exec", lambda self: 0)
    ict_steps = [
        ("R-GND", "3V3", "Ω", "—", "30", "—"),
        ("op", "U2355A DIO Read", "—", "—", "—", "—", {"type": "dio_read"}),
    ]
    editor = StepsEditorDialog("ict", ict_steps, [True, True], [100, 100],
                               [5000, 5000])
    editor.net_catalog_provider = None
    seen = set(editor.findChildren(QtDialog))
    for label, call in (
            ("steps_ict_step_editor", lambda: editor._edit_ict_step(0)),
            ("steps_op_step_editor", lambda: editor._edit_ict_step(1))):
        call()
        created = [d for d in editor.findChildren(QtDialog) if d not in seen]
        assert len(created) == 1, f"{label}: expected one dialog"
        dlg = created[0]
        seen.add(dlg)
        _show(dlg)
        _assert_dialog_wrapped(dlg, label)
        _assert_button_row_visible(dlg, label)
        _assert_no_overlap(dlg, label)
        dlg.close()
        dlg.deleteLater()
    editor.close()
    editor.deleteLater()

    fct = StepsEditorDialog("fct", ["MessageOK: All Done"], [True], [100],
                            [5000], kinds=["MessageOK"], op_params=[None])
    seen_fct = set(fct.findChildren(QtDialog))
    fct._edit_fct_step(0)
    created = [d for d in fct.findChildren(QtDialog) if d not in seen_fct]
    assert len(created) == 1, "steps_fct_step_editor: expected one dialog"
    dlg = created[0]
    _show(dlg)
    _assert_dialog_wrapped(dlg, "steps_fct_step_editor")
    _assert_button_row_visible(dlg, "steps_fct_step_editor")
    _assert_no_overlap(dlg, "steps_fct_step_editor")
    dlg.close()
    dlg.deleteLater()
    fct.close()
    fct.deleteLater()


# ---------------------------------------------------------------------------
# report page detail dialog (interactive modal, exec() stubbed)
# ---------------------------------------------------------------------------
def test_report_detail_dialog_scroll_guard(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog as QtDialog
    from mtkgui.gui.report_page import ReportPage

    monkeypatch.setattr(QtDialog, "exec", lambda self: 0)
    page = ReportPage()
    page.show_detail()
    dialogs = page.findChildren(QtDialog)
    assert dialogs, "report detail dialog was not created"
    _show(dialogs[-1])
    _assert_dialog_wrapped(dialogs[-1], "report_detail")
    page.close()
    page.deleteLater()


# ---------------------------------------------------------------------------
# instrument "Configuration" sub-windows (equipment page)
# ---------------------------------------------------------------------------
def test_equipment_instrument_dialogs_scroll_guard(qapp):
    from mtkgui.equipment_page import (EquipmentPage, _DeviceEditDialog,
                                       _DeviceTableDialog, _InstrumentDialog,
                                       _form_dialog)

    page = EquipmentPage()
    daq = page.configs["daq973a"]
    probes = page.configs["probes"]
    host = page.configs["host"]

    specs = [
        ("instrument_daq973a", lambda: _InstrumentDialog(
            page, daq["title"], daq["fields"], "daq973a", True, config=daq)),
        ("instrument_form_host", lambda: _form_dialog(
            page, host["title"], host["fields"], "note")),
        ("instrument_table_probes", lambda: _DeviceTableDialog(
            page, probes["title"], probes["table"], note="",
            block_key="probes", config=None)),
        ("instrument_device_notice", lambda: _DeviceEditDialog(
            page, "J-Link", None, info=[("Interface", "USB")])),
    ]
    for label, factory in specs:
        dlg = factory()
        _show(dlg)
        _assert_dialog_wrapped(dlg, label)
        _assert_button_row_visible(dlg, label)
        _assert_no_overlap(dlg, label)
        dlg.close()
        dlg.deleteLater()
    page.close()
    page.deleteLater()
