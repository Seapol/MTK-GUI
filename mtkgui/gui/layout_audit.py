# -*- coding: utf-8 -*-
"""M62: automated GUI layout audit (read-only, no app singletons).

The audit walks a widget tree after it has been shown (so geometry is
real) and reports the layout defects the user keeps hitting by hand:

* ``clipped``        - a control squeezed below its minimum / size hint
                        (fixed-width buttons clipped by the QSS padding);
* ``input_overflow`` - an input sticking out of its form container;
* ``input_oversized``- a short-content field stretched far too wide;
* ``input_narrow``   - an input squeezed below its content (early warning);
* ``overlap``        - sibling widgets whose visible rects intersect;
* ``overflow_x``     - an unintended horizontal scrollbar in a scroll area;
* ``undersize``      - a top-level window smaller than its layout minimum
                        (or than the screen available geometry).

Everything is read-only: no widget is mutated, and each widget is audited
inside a guard so an exotic widget cannot abort the sweep.

CLI: ``python -m mtkgui.gui.layout_audit`` builds an offscreen app, runs
:data:`WINDOW_FACTORIES`, prints a markdown report and exits 1 when any
issue is NOT in the known-issues whitelist
(:mod:`mtkgui.gui.layout_audit_known_issues`).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Iterable

from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFontComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QRadioButton,
    QScrollArea,
    QScrollBar,
    QSizeGrip,
    QSlider,
    QSpinBox,
    QToolButton,
    QWidget,
)

#: controls audited by the hard clipped rule (§1.1)
_CLIP_CONTROLS = (
    QAbstractButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox,
    QDateTimeEdit, QFontComboBox, QCheckBox, QRadioButton, QToolButton,
    QSlider,
)
#: editable inputs audited by the input-sizing rules (§1.2)
_INPUT_CONTROLS = (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
                   QDateTimeEdit, QFontComboBox)


@dataclass(frozen=True)
class LayoutIssue:
    """One audit finding (str-friendly / markdown-friendly)."""

    kind: str            # clipped | input_* | overlap | overflow_x |
    severity: str        # high | low
    widget_path: str     # "EquipmentPage / QPushButton#Config"
    widget_type: str     # class name
    detail: str

    def signature(self) -> str:
        """Stable whitelist key: kind + widget class + detail."""
        return f"{self.kind}|{self.widget_type}|{self.detail}"

    def __str__(self) -> str:
        return (f"[{self.severity}] {self.kind}: {self.widget_path} - "
                f"{self.detail}")

    def to_markdown(self) -> str:
        return (f"- **{self.kind}** ({self.severity}) "
                f"`{self.widget_path}` - {self.detail}")


# --------------------------------------------------------------- helpers
def _name(widget: QWidget) -> str:
    name = type(widget).__name__
    obj = widget.objectName()
    return f"{name}#{obj}" if obj else name


def widget_path(root: QWidget, widget: QWidget) -> str:
    """Root-relative path ("Root / ... / QPushButton#Config")."""
    chain = []
    cur = widget
    while cur is not None:
        chain.append(_name(cur))
        if cur is root:
            break
        cur = cur.parentWidget()
    return " / ".join(reversed(chain))


def _inside_item_view(widget: QWidget) -> bool:
    cur = widget.parentWidget()
    while cur is not None:
        if isinstance(cur, QAbstractItemView):
            return True
        cur = cur.parentWidget()
    return False


def _content_length(widget: QWidget) -> int:
    if isinstance(widget, QLineEdit):
        return len(widget.text())
    if isinstance(widget, QComboBox):
        return len(widget.currentText())
    if isinstance(widget, QSpinBox):
        return len(str(widget.value()))
    if isinstance(widget, QDoubleSpinBox):
        return len(f"{widget.value():g}")
    if isinstance(widget, QDateTimeEdit):
        return len(widget.text())
    if isinstance(widget, QFontComboBox):
        return len(widget.currentText())
    return 0


def _fixed_width(widget: QWidget) -> bool:
    return (widget.minimumWidth() == widget.maximumWidth()
            and widget.minimumWidth() > 0)


def _visible_to_root(widget: QWidget, root: QWidget) -> bool:
    try:
        return widget.isVisibleTo(root)
    except RuntimeError:                        # deleted C++ object
        return False


# --------------------------------------------------------------- engine
def _audit_one(root: QWidget, w: QWidget, tol: int) -> list[LayoutIssue]:
    """Rules §1.1 / §1.2 / §1.4 / §1.5 for one widget."""
    issues: list[LayoutIssue] = []
    path = widget_path(root, w)
    cls = type(w).__name__

    def add(kind: str, severity: str, detail: str) -> None:
        issues.append(LayoutIssue(kind, severity, path, cls, detail))

    # 1. clipped controls (hard: below the minimum size hint)
    if isinstance(w, _CLIP_CONTROLS):
        need = w.minimumSizeHint().width()
        if need and w.width() < need - tol:
            detail = f"width={w.width()}px < minimumSizeHint={need}px"
            hint = w.sizeHint().width()
            if _fixed_width(w) and hint > w.width():
                detail += (f" (fixed width {w.width()}px < sizeHint={hint}px"
                           ", QSS padding 7px 16px)")
            add("clipped", "high", detail)

    # 1b. labels / group boxes (soft: below their content hint)
    if isinstance(w, (QLabel, QGroupBox)):
        wrap = bool(w.wordWrap()) if isinstance(w, QLabel) else False
        if (not wrap and not _inside_item_view(w)
                and not isinstance(w.parentWidget(), QAbstractItemView)):
            hint = w.sizeHint().width()
            need = w.minimumSizeHint().width()
            if (need > 0 and hint > 0
                    and w.width() < hint * 0.95
                    and w.width() < need - tol):
                add("clipped", "low",
                    f"width={w.width()}px < sizeHint={hint}px "
                    f"(minimumSizeHint={need}px)")

    # 2. input sizing
    if isinstance(w, _INPUT_CONTROLS):
        parent = w.parentWidget()
        if parent is not None:
            right = parent.contentsRect().right()
            if w.geometry().right() > right + tol:
                add("input_overflow", "high",
                    f"right edge={w.geometry().right()}px > container "
                    f"right={right}px")
        hint = w.sizeHint().width()
        if hint >= 40:
            if w.width() > hint * 2.5 + 50:
                add("input_oversized", "low",
                    f"width={w.width()}px sizeHint={hint}px "
                    f"content-length={_content_length(w)}")
            elif w.width() < hint * 0.8:
                add("input_narrow", "low",
                    f"width={w.width()}px < sizeHint={hint}px (80%)")

    # 4. horizontal overflow in scroll areas
    if isinstance(w, QAbstractScrollArea):
        try:
            bar = w.horizontalScrollBar()
            if bar is not None and bar.isVisible():
                content = w.widget() if isinstance(w, QScrollArea) else None
                hint = (content.sizeHint().width() if content is not None
                        else w.sizeHint().width())
                if hint > w.viewport().width() + tol:
                    add("overflow_x", "low",
                        f"content sizeHint={hint}px > viewport="
                        f"{w.viewport().width()}px (horizontal scrollbar)")
        except RuntimeError:
            pass

    # 5. undersized top-level windows
    if w.isWindow():
        minimum = w.minimumSizeHint()
        if (minimum.width() > w.width() + tol
                or minimum.height() > w.height() + tol):
            add("undersize", "high",
                f"window {w.width()}x{w.height()}px < layout minimum "
                f"{minimum.width()}x{minimum.height()}px")
        screen = w.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            hint = w.sizeHint()
            if hint.width() > avail.width() or hint.height() > avail.height():
                add("undersize", "high",
                    f"sizeHint {hint.width()}x{hint.height()}px exceeds "
                    f"screen {avail.width()}x{avail.height()}px")
    return issues


def _audit_overlaps(root: QWidget, widgets: list[QWidget],
                    min_overlap_px: int) -> list[LayoutIssue]:
    """Rule §1.3: sibling overlap (same parent) for visible widgets."""
    issues: list[LayoutIssue] = []
    grouped: dict[int, list[QWidget]] = {}
    for w in widgets:
        if isinstance(w, (QScrollBar, QSizeGrip)):
            continue
        if w.width() < 4 or w.height() < 4:
            continue
        parent = w.parentWidget()
        if parent is None:
            continue
        grouped.setdefault(id(parent), []).append(w)
    area_min = min_overlap_px * min_overlap_px
    for siblings in grouped.values():
        for i, a in enumerate(siblings):
            for b in siblings[i + 1:]:
                try:
                    geo_a, geo_b = a.geometry(), b.geometry()
                except RuntimeError:
                    continue
                if not geo_a.intersects(geo_b):
                    continue
                inter = geo_a.intersected(geo_b)
                if inter.width() * inter.height() < area_min:
                    continue
                issues.append(LayoutIssue(
                    "overlap", "high",
                    widget_path(root, a) + " <> " +
                    widget_path(root, b),
                    f"{type(a).__name__}/{type(b).__name__}",
                    f"intersection {inter.width()}x{inter.height()}px"))
    return issues


def audit_widget(root: QWidget, tol_px: int = 2,
                 min_overlap_px: int = 4) -> list[LayoutIssue]:
    """Recursively audit *root* and every VISIBLE descendant."""
    issues: list[LayoutIssue] = []
    widgets: list[QWidget] = []
    try:
        candidates = [root] + root.findChildren(QWidget)
    except RuntimeError:                          # pragma: no cover
        return issues
    for w in candidates:
        if not _visible_to_root(w, root):
            continue
        widgets.append(w)
        try:
            issues.extend(_audit_one(root, w, tol_px))
        except Exception:                         # noqa: BLE001 - exotic
            continue                              # widget never aborts the sweep
    try:
        issues.extend(_audit_overlaps(root, widgets, min_overlap_px))
    except Exception:                             # noqa: BLE001
        pass
    return issues


def audit_widgets(roots: Iterable[QWidget], **kw) -> list[LayoutIssue]:
    """Audit several roots (each independently) in one flat list."""
    issues: list[LayoutIssue] = []
    for root in roots:
        issues.extend(audit_widget(root, **kw))
    return issues


def audit_top_levels(app: QApplication, **kw) -> list[LayoutIssue]:
    """Audit every visible top-level widget of the running app."""
    return audit_widgets(app.topLevelWidgets(), **kw)


# ------------------------------------------------------------ the sweep
def _factory_equipment():
    from mtkgui.equipment_page import EquipmentPage
    return EquipmentPage()


def _factory_yaml_build():
    from mtkgui.yaml_build_page import YamlBuildPage
    return YamlBuildPage()


def _factory_fct_panel():
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel
    return FCTTestConfigPanel()


def _factory_design_input():
    from mtkgui.gui.yamlbuild.design_input_panel import DesignInputPanel
    return DesignInputPanel()


def _factory_instruments():
    from mtkgui.gui.yamlbuild.instruments_panel import InstrumentsPanel
    return InstrumentsPanel()


def _factory_channel_alloc():
    from mtkgui.gui.yamlbuild.channel_allocation import ChannelAllocationPage
    return ChannelAllocationPage()


def _factory_preview():
    from mtkgui.gui.yamlbuild.preview import YamlPreviewWidget
    return YamlPreviewWidget()


def _factory_block_flow():
    from mtkgui.gui.yamlbuild.block_flow import BlockFlowWidget
    return BlockFlowWidget()


def _factory_audit_page():
    from mtkgui.gui.audit_page import AuditPage
    return AuditPage(None, None)


def _factory_cluster_page():
    from mtkgui.gui.cluster_page import ClusterPage
    return ClusterPage(None)


def _factory_pipeline_page():
    from mtkgui.gui.pipeline_page import PipelinePage
    return PipelinePage(None)


def _factory_queue_page():
    from mtkgui.gui.queue_page import QueuePage
    return QueuePage(None)


def _factory_upload_page():
    from mtkgui.gui.upload_page import UploadPage
    return UploadPage(None)


def _factory_export_page():
    from mtkgui.gui.export_page import ExportPage
    return ExportPage(None)


def _factory_resource_page():
    from mtkgui.gui.resource_page import ResourcePage
    return ResourcePage(None)


def _factory_fleet_page():
    from mtkgui.gui.fleet_page import FleetPage
    return FleetPage(None)


def _factory_steps_editor():
    from mtkgui.gui.steps_editor import StepsEditorDialog
    return StepsEditorDialog("ict", [], [], [], [])


def _factory_group_config():
    from mtkgui.equipment_page import _GroupConfigDialog
    return _GroupConfigDialog(
        None, "SSH Login", [("ip", "IP address", "")], {"ip": "1.2.3.4"})


def _factory_block_config():
    from mtkgui.equipment_page import _BlockConfigDialog
    return _BlockConfigDialog(
        None, "Router", [("IP address", "10.1.2.3")], "")


def _factory_instrument_dialog():
    from mtkgui.equipment_page import _InstrumentDialog
    return _InstrumentDialog(
        None, "DAQ973A", [("Port", "USB0")], "daq973a", True)


def _factory_sharepoint_signin():
    from PySide6.QtWidgets import QLabel
    from mtkgui.gui.sharepoint_upload_dialog import SharePointSignInDialog
    # never spin a real QtWebEngine browser up for the audit
    return SharePointSignInDialog(view_factory=lambda: QLabel("stub view"))


def _factory_import_browser_session():
    from mtkgui.gui.sharepoint_upload_dialog import (
        ImportBrowserSessionDialog)
    return ImportBrowserSessionDialog()


def _factory_sharepoint_upload():
    from mtkgui.gui.sharepoint_upload_dialog import SharePointUploadDialog
    return SharePointUploadDialog(virtual=True)


def _factory_virtual_fault():
    from mtkgui.virtual_mode import VirtualFaultDialog
    return VirtualFaultDialog({})


def _factory_tone_slider():
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import _ToneRangeSlider
    return _ToneRangeSlider()


def _factory_net_table():
    from mtkgui.gui.yamlbuild.channel_allocation import (
        POWER_COLUMNS,
        _NetTable,
    )
    return _NetTable("power", POWER_COLUMNS, lambda _net: [])


#: (window label, factory) pairs audited by both the CLI and the pytest
#: sweep; a factory that cannot run with minimal args raises and the
#: sweep records it in the "skipped" bucket (never an elaborate mock)
WINDOW_FACTORIES: list[tuple[str, Callable[[], QWidget]]] = [
    ("EquipmentPage", _factory_equipment),
    ("YamlBuildPage", _factory_yaml_build),
    ("FCTTestConfigPanel", _factory_fct_panel),
    ("DesignInputPanel", _factory_design_input),
    ("InstrumentsPanel", _factory_instruments),
    ("ChannelAllocationPage", _factory_channel_alloc),
    ("YamlPreviewWidget", _factory_preview),
    ("BlockFlowWidget", _factory_block_flow),
    ("AuditPage", _factory_audit_page),
    ("ClusterPage", _factory_cluster_page),
    ("PipelinePage", _factory_pipeline_page),
    ("QueuePage", _factory_queue_page),
    ("UploadPage", _factory_upload_page),
    ("ExportPage", _factory_export_page),
    ("ResourcePage", _factory_resource_page),
    ("FleetPage", _factory_fleet_page),
    ("StepsEditorDialog", _factory_steps_editor),
    ("_GroupConfigDialog", _factory_group_config),
    ("_BlockConfigDialog", _factory_block_config),
    ("_InstrumentDialog", _factory_instrument_dialog),
    ("SharePointSignInDialog", _factory_sharepoint_signin),
    ("ImportBrowserSessionDialog", _factory_import_browser_session),
    ("SharePointUploadDialog", _factory_sharepoint_upload),
    ("VirtualFaultDialog", _factory_virtual_fault),
    ("_ToneRangeSlider", _factory_tone_slider),
    ("_NetTable", _factory_net_table),
]


def main_window(app: QApplication):
    """Build the sweep MainWindow (Virtual mode, supervisor, ATE)."""
    from mtkgui.main_window import MainWindow
    from mtkgui.permissions import FIXTURE_ATE, ROLE_SUPERVISOR
    return MainWindow(role=ROLE_SUPERVISOR, mode="Virtual", fixture=FIXTURE_ATE)


def main_window_pages(window) -> list[QWidget]:
    """The tab pages of the MainWindow (lazy secondary pages included)."""
    pages: list[QWidget] = []
    ensure = getattr(window, "_ensure_secondary_ui", None)
    if ensure is not None:
        ensure()
    tabs = getattr(window, "tabs", None)
    if tabs is not None:
        for idx in range(tabs.count()):
            pages.append(tabs.widget(idx))
    return pages


def audit_main_window(app: QApplication) -> dict[str, list[LayoutIssue]]:
    """Audit the MainWindow plus each tab page (after selecting it)."""
    results: dict[str, list[LayoutIssue]] = {}
    window = main_window(app)
    try:
        window.show()
        app.processEvents()
        results["MainWindow"] = audit_widget(window)
        tabs = getattr(window, "tabs", None)
        for page in main_window_pages(window):
            if tabs is not None:
                tabs.setCurrentWidget(page)
            page.show()
            app.processEvents()
            results[f"MainWindow/{_name(page)}"] = audit_widget(page)
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
    return results


def run_sweep(app: QApplication, factories=None
              ) -> tuple[dict[str, list[LayoutIssue]], dict[str, str]]:
    """Run every factory: show + audit; report factory crashes as skipped."""
    results: dict[str, list[LayoutIssue]] = {}
    skipped: dict[str, str] = {}
    factories = WINDOW_FACTORIES if factories is None else factories
    results.update(audit_main_window(app))
    for label, factory in factories:
        try:
            widget = factory()
        except Exception as exc:                  # noqa: BLE001
            skipped[label] = f"{type(exc).__name__}: {exc}"
            continue
        try:
            widget.show()
            app.processEvents()
            results[label] = audit_widget(widget)
        except Exception as exc:                  # noqa: BLE001
            skipped[label] = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                widget.close()
                widget.deleteLater()
                app.processEvents()
            except Exception:                     # noqa: BLE001
                pass
    return results, skipped


# ---------------------------------------------------------------- report
def format_report(results: dict[str, list[LayoutIssue]],
                  skipped: dict[str, str] | None = None) -> str:
    """Markdown report grouped by window."""
    from mtkgui.gui.layout_audit_known_issues import is_whitelisted

    lines = ["# M62 layout audit report", ""]
    total = 0
    new_count = 0
    for label, issues in results.items():
        total += len(issues)
        new = [i for i in issues if not is_whitelisted(i)]
        new_count += len(new)
        lines.append(f"## {label} - {len(issues)} issue(s)")
        if not issues:
            lines.append("")
            continue
        lines.append("")
        for issue in issues:
            mark = "" if not is_whitelisted(issue) else " _(known)_"
            lines.append(issue.to_markdown() + mark)
        lines.append("")
    for label, reason in (skipped or {}).items():
        lines.append(f"## {label} - SKIPPED ({reason})")
        lines.append("")
    high = sum(1 for issues in results.values() for i in issues
               if i.severity == "high")
    low = total - high
    lines.append(f"TOTAL {total} issues ({high} high / {low} low), "
                 f"{new_count} not whitelisted")
    return "\n".join(lines)


def main(argv=None) -> int:
    """CLI entry: exit 0 only when every issue is whitelisted."""
    argv = sys.argv[1:] if argv is None else argv
    app = QApplication.instance() or QApplication([])
    results, skipped = run_sweep(app)
    text = format_report(results, skipped)
    print(text)
    new = [i for issues in results.values() for i in issues
           if not _whitelisted(i)]
    return 1 if new else 0


def _whitelisted(issue: LayoutIssue) -> bool:
    from mtkgui.gui.layout_audit_known_issues import is_whitelisted
    return is_whitelisted(issue)


if __name__ == "__main__":                        # pragma: no cover
    raise SystemExit(main())
