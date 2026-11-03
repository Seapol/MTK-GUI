# -*- coding: utf-8 -*-
"""M62: known layout-audit issues (the acceptance baseline).

Every entry is keyed by a widget-path PREFIX and holds the EXACT
signature(s) tolerated below it (``kind|widget class|detail`` - see
:meth:`mtkgui.gui.layout_audit.LayoutIssue.signature`).  A new issue
whose signature is absent here fails ``tests/gui/test_layout_audit.py``
- there is no blanket path-level suppression.

The first-run inventory (reports/m62_layout_audit_report.txt) fixed the
clipped fixed-width control family (two 18px collapse arrows -> 24px,
the M61 Config button) and the oversized Virtual Fault percentage
spinners (200px cap); everything below is either a deliberate design
trade-off or needs a design decision.
"""

#: widget-path prefix -> whitelisted issue signatures (with reasons)
KNOWN_ISSUES: dict[str, list[str]] = {
    # ChannelAllocationPage -------------------------------------------------
    "ChannelAllocationPage": [
        # scrollable tab content may legitimately scroll (design decision)
        "overflow_x|QScrollArea|content sizeHint=442px > viewport=346px "
        "(horizontal scrollbar)",
    ],
    # EquipmentPage ----------------------------------------------------------
    "EquipmentPage": [
        # M61 130px name minimum; long entry labels elide (design decision)
        "clipped|QLabel|width=130px < sizeHint=137px (minimumSizeHint=137px)",
        "clipped|QLabel|width=130px < sizeHint=145px (minimumSizeHint=145px)",
        "clipped|QLabel|width=130px < sizeHint=177px (minimumSizeHint=177px)",
        # M64: the longer "Flash Tool/Programmer" entry label elides too
        "clipped|QLabel|width=130px < sizeHint=159px (minimumSizeHint=159px)",
        # M65: ... like the longer "Wired & Wireless Network" label
        "clipped|QLabel|width=130px < sizeHint=181px (minimumSizeHint=181px)",
        # 240px minimum left column + entry content (design decision);
        # M65: the longer entry labels raise the content hint to 323px
        "overflow_x|QScrollArea|content sizeHint=323px > viewport=226px "
        "(horizontal scrollbar)",
    ],
    # ExportPage -------------------------------------------------------------
    "ExportPage": [
        # scrollable content may legitimately scroll (design decision)
        "overflow_x|QScrollArea|content sizeHint=605px > viewport=533px "
        "(horizontal scrollbar)",
    ],
    # MainWindow -------------------------------------------------------------
    # Run Control is squeezed by the top-row splitter at the 1020px default
    # window width - the group is 190px wide while it needs 370px.  Raising
    # its minimum would force a wider default window (design decision -> M63).
    "MainWindow": [
        "clipped|QDoubleSpinBox|width=33px < minimumSizeHint=98px",
        "clipped|QGroupBox|width=190px < sizeHint=370px (minimumSizeHint=370px)",
        "clipped|QLabel|width=33px < sizeHint=59px (minimumSizeHint=59px)",
        "clipped|QLabel|width=33px < sizeHint=68px (minimumSizeHint=68px)",
        "clipped|QLineEdit|width=0px < minimumSizeHint=16px",
        "clipped|QSpinBox|width=33px < minimumSizeHint=87px",
        "input_narrow|QDoubleSpinBox|width=33px < sizeHint=98px (80%)",
        "input_narrow|QLineEdit|width=0px < sizeHint=106px (80%)",
        "input_narrow|QLineEdit|width=36px < sizeHint=158px (80%)",
        "input_narrow|QSpinBox|width=33px < sizeHint=87px (80%)",
        "overlap|QPushButton/QPushButton|intersection 71x62px",
        # status-bar widgets are placed by hand; cosmetic (design decision)
        "overlap|InstrumentStatusBar/QLabel|intersection 75x21px",
        "overlap|InstrumentStatusBar/SerialStatusBar|intersection 73x21px",
        # status-bar text elides by design
        "clipped|QLabel|width=146px < sizeHint=163px (minimumSizeHint=163px)",
        "clipped|QLabel|width=146px < sizeHint=208px (minimumSizeHint=208px)",
        # the offscreen test screen is 800x800; real monitors are larger.
        # 1322x1030 is the STABLE sizeHint after run_sweep primes one
        # MainWindow (the first-in-process window measures 1322x1024 and
        # every later one 1322x1030 - see layout_audit._prime_layout).
        "undersize|MainWindow|sizeHint 1322x1030px exceeds screen 800x800px",
    ],
    # SharePointSignInDialog ------------------------------------------------
    "SharePointSignInDialog": [
        # the sign-in URL line spans the dialog by design
        "input_oversized|QLineEdit|width=878px sizeHint=158px content-length=0",
    ],
    # SharePointUploadDialog ------------------------------------------------
    "SharePointUploadDialog": [
        # form fields follow the dialog width (QFormLayout stretch); cosmetic
        "input_oversized|QComboBox|width=591px sizeHint=195px content-length=5",
        "input_oversized|QLineEdit|width=545px sizeHint=158px content-length=19",
        "input_oversized|QLineEdit|width=581px sizeHint=158px content-length=0",
    ],
    # YamlBuildPage ---------------------------------------------------------
    "YamlBuildPage": [
        # compact numeric entry; 120px fits the short content (design)
        "input_narrow|QLineEdit|width=120px < sizeHint=158px (80%)",
        # scrollable content may legitimately scroll (design decision)
        "overflow_x|QScrollArea|content sizeHint=896px > viewport=521px "
        "(horizontal scrollbar)",
    ],
    # equipment dialogs ------------------------------------------------------
    "_BlockConfigDialog": [
        # form fields follow the dialog width (QFormLayout stretch); cosmetic
        "input_oversized|QLineEdit|width=505px sizeHint=158px content-length=8",
    ],
    "_GroupConfigDialog": [
        # form fields follow the dialog width (QFormLayout stretch); cosmetic
        "input_oversized|QLineEdit|width=455px sizeHint=158px content-length=7",
    ],
    "_InstrumentDialog": [
        # form fields follow the dialog width (QFormLayout stretch); cosmetic
        "input_oversized|QComboBox|width=774px sizeHint=100px content-length=4",
        "input_oversized|QLineEdit|width=710px sizeHint=158px content-length=3",
        "input_oversized|QLineEdit|width=710px sizeHint=158px content-length=4",
        "input_oversized|QLineEdit|width=774px sizeHint=158px content-length=15",
        "input_oversized|QLineEdit|width=806px sizeHint=158px content-length=4",
    ],
}

#: windows the sweep cannot build with ``None`` service deps (elaborate
#: mocks are forbidden) -> the reason shown in the audit report
SKIPPED_WINDOWS: dict[str, str] = {
    "AuditPage": "needs AccessControl + AuditLog services (no stub)",
    "ClusterPage": "needs a ClusterScheduler service (no stub)",
    "QueuePage": "needs a TaskQueue service (no stub)",
    "UploadPage": "needs a SharePointUploader service (no stub)",
    "ResourcePage": "needs a ResourceManager service (no stub)",
    "FleetPage": "needs a ClusterHub service (no stub)",
}


def is_whitelisted(issue, path=None) -> bool:
    """True only when the EXACT signature is registered below a prefix.

    An absent entry (or a different signature) is NEVER tolerated - a
    new defect must surface in the audit run.
    """
    target = path or issue.widget_path
    for prefix, signatures in KNOWN_ISSUES.items():
        if target.startswith(prefix) and issue.signature() in signatures:
            return True
    return False
