# -*- coding: utf-8 -*-
"""Design Input panel (P3-B2 T7): the unified file-entry + meta form.

Replaces the deprecated standalone "Design data import" popup: all
file entry lives on this panel only, with three import buttons:

* **Import SPF…** - reads the file bytes AND auto-parses the project
  info: Core ID from the SPF file name, Project Name from the SPF
  first-page title (both editable afterwards);
* **Import NET…** - reads the file bytes ONLY (no parse, no structure
  analysis; the formal net parsing happens in the Parse Nets module);
* **Import BOM…** - optional CSV/XLSX Bill Of Materials; its
  RefDes -> MPN/DNP evidence feeds the Parse Nets classification.
  A BOM failure is a WARNING only (NET-only parsing keeps working).

Meta fields (two-column grid): Product Part # (= Project Name), Core ID
(= Product ID), FSW Revision and 700 HW Revision (both a Rev A..H
dropdown with a Customized entry, manual, report metadata), and the
fixed Batch # dropdown (Customized / Deviation (DRQ) resolve through a
small dialog).  All fields persist to the project YAML via the schema.

M126 layout: Product Information is a two-column grid; Design Files for
ICT (with Route A / B / C) and Pre-Configure for FCT sit side by side,
and a card whose Enable is cleared greys out completely.
"""

from __future__ import annotations

from pathlib import Path

from mtkgui.startup_timing import begin, end

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mtkgui.ict.netparse import read_text_any_encoding
from mtkgui.gui.dialog_sizing import (apply_scroll_to_dialog,
                                      enable_dialog_controls)
from mtkgui.gui.yamlbuild.parser import core_id_from_filename
from mtkgui.gui.yamlbuild.schema import (
    BATCH_CUSTOMIZED_PREFIX,
    BATCH_DEVIATION_PREFIX,
    BATCH_OPTIONS,
)
from mtkgui.gui.yamlbuild.spf_title import extract_spf_project_name

MAX_DRQ_NUMBERS = 3

#: caption under Route C, restored whenever the imports are cleared
MTK_ROUTE_NOTE = ("Nets are parsed on import - node 02 is skipped "
                  "(read-only).")

#: M126: revision dropdown shared by FSW / 700 HW (Rev A..H + custom).
REVISION_CHOICES = tuple(f"Rev {c}" for c in "ABCDEFGH")
#: the dropdown entry that asks for free text (User Guide / legacy YAML)
REVISION_CUSTOMIZED = "Customized ..."

#: FCT test types the Pre-Configure block declares support for.
#: (stored key, UI label).  node 06 may only offer what was ticked here.
FCT_TEST_TYPES = (
    ("console", "Console serial (serial / SSH)"),
    ("serial_transfer", "Serial file transfer"),
    ("sftp", "SSH SFTP"),
    ("message", "Message dialogs"),
    ("wifi", "Wi-Fi (RF)"),
    ("bluetooth", "Bluetooth (RF)"),
)

#: the two groups the list is rendered in ("standard steps" first)
FCT_STANDARD_TESTS = ("console", "serial_transfer", "sftp", "message")
FCT_SPECIFIC_TESTS = ("wifi", "bluetooth")

#: M126: default ticks per DUT board software (Linux = everything).
FCT_DEFAULT_TESTS = {
    "linux": tuple(key for key, _l in FCT_TEST_TYPES),
    "bare_metal": ("console", "message"),
    "slave_daughter": ("message",),
}

#: M126: "disabled" must read as disabled - every glyph greys, not only
#: the controls that refuse clicks.  Widget-level stylesheet wins over
#: the application theme for these selectors.
_GREY_TEXT = "#8b9099"
_GREY_QSS = (
    f"QLabel{{color:{_GREY_TEXT};}}"
    f"QRadioButton{{color:{_GREY_TEXT};}}"
    f"QCheckBox{{color:{_GREY_TEXT};}}"
    f"QPushButton{{color:{_GREY_TEXT};}}"
    f"QComboBox{{color:{_GREY_TEXT};}}"
    f"QLineEdit{{color:{_GREY_TEXT};}}"
    # a widget-level colour rule switches the checkbox to stylesheet
    # rendering, so the theme's accent tick would stay vivid inside a
    # disabled card - grey the indicators here as well (M126)
    f"QCheckBox::indicator:disabled{{border:1px solid #c2c7cf;"
    f"background-color:#f2f3f5;}}"
    f"QCheckBox::indicator:checked:disabled{{background-color:#c2c7cf;"
    f"border:1px solid #c2c7cf;}}")


def _grey_out(widget: QWidget, grey: bool) -> None:
    """M126: one call greys (or restores) a whole sub-tree."""
    widget.setEnabled(not grey)
    widget.setStyleSheet(_GREY_QSS if grey else "")


#: The card frame and its caption must grey with the body - a coloured
#: "Design Files for ICT" above a grey card still reads as enabled.
_GREY_BOX_QSS = (
    f"QGroupBox{{color:{_GREY_TEXT};border-color:{_GREY_TEXT};}}"
    f"QGroupBox::title{{color:{_GREY_TEXT};}}")


def _grey_card(box: QWidget, body: QWidget, grey: bool) -> None:
    """M126: grey the card caption + frame together with the body."""
    _grey_out(body, grey)
    box.setStyleSheet(_GREY_BOX_QSS if grey else "")


class SpfExtractWorker(QThread):
    """Extract the Smart-PDF text OFF the GUI thread (M15, user
    direction 2026-10-25: a frozen main window is not acceptable).

    A 7-10 MB Allegro Smart PDF takes ~1 s to rasterize and extract
    through QtPdf; running it in the GUI thread freezes the dialog
    and the page.  The worker emits the raw text; the panel finishes
    the (cheap) project-info extraction and form fill on the main
    thread via ``done`` / ``failed``.
    """

    done = Signal(str, str)      # (text, path)
    failed = Signal(str)         # human-readable reason

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = str(path)

    def run(self) -> None:
        try:
            from mtkgui.gui.yamlbuild.parser import extract_pdf_text
            text = extract_pdf_text(self._path)
            if not text.strip():
                raise ValueError(
                    "no extractable text in the PDF (scanned or "
                    "vector-only drawing)")
            self.done.emit(text, self._path)
        except Exception as exc:                 # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class DrqDialog(QDialog):
    """Up to 3 DRQ numbers for the Deviation (DRQ) batch option."""

    def __init__(self, values: list[str] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deviation (DRQ) Numbers")
        enable_dialog_controls(self)
        outer = QVBoxLayout(self)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.edits: list[QLineEdit] = []
        values = list(values or [])[:MAX_DRQ_NUMBERS]
        for i in range(MAX_DRQ_NUMBERS):
            edit = QLineEdit(values[i] if i < len(values) else "")
            edit.setPlaceholderText(f"DRQ number #{i + 1} (optional)")
            form.addRow(f"DRQ #{i + 1}:", edit)
            self.edits.append(edit)
        body_lay.addLayout(form)
        # M34: body scrolls, OK / Cancel stays outside (always visible)
        apply_scroll_to_dialog(self, body)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def drq_numbers(self) -> list[str]:
        """The non-empty DRQ numbers in entry order."""
        return [e.text().strip() for e in self.edits if e.text().strip()]


class DesignInputPanel(QWidget):
    """Block 01 Design Input: import buttons + project meta form."""

    #: (level, message) Event-Log mirror (T6 detail, failures included)
    task_log = Signal(str, str)
    #: (percent, label) long-task progress mirror (T6)
    task_progress = Signal(int, str)
    #: emitted after every successful import (file entry changed)
    content_changed = Signal()
    #: M102 Route C: a parsed MTK ICT Excel Sheet (``RouteCResult``)
    mtk_sheet_imported = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spf_path: str = ""      # imported SPF file (bytes + parse)
        self.spf_text: str = ""      # SPF raw text (import step)
        self.net_path: str = ""      # imported NET file (LOAD ONLY)
        self.net_text: str = ""      # NET raw bytes (never parsed here)
        self.bom_path: str = ""      # optional BOM file (CSV / XLSX)
        self.bom_records: int = 0    # parsed BOM record count
        self.bom_dnp: int = 0        # parsed BOM DNP count
        self._ict_excel_path: str = ""  # Route B workbook (LOAD ONLY)
        self._mtk_sheet_path: str = ""  # Route C workbook (parse on import)

        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        #: set while set_values() loads a project (route signals must not
        #: be mistaken for an operator switch - M126)
        self._loading = False

        lay.addWidget(self._build_product_block())
        # M126: ICT and FCT side by side - each block owned one full-width
        # column before, which wasted the dialog's width
        blocks = QHBoxLayout()
        blocks.setSpacing(12)
        blocks.addWidget(self._build_ict_block(), 1)
        blocks.addWidget(self._build_fct_block(), 1)
        lay.addLayout(blocks)
        lay.addStretch(1)
        self._refresh_route_state()
        _grey_card(self._fct_box, self._fct_body,
                   not self.chk_fct.isChecked())

        # M126: the theme QSS adds 14 px of padding to the push buttons
        # AFTER the first layout pass, so a squeezed panel used to let the
        # import buttons overlap their captions.  Polish everything, then
        # pin the minimum to the real hint - a panel that is never given
        # less than it needs cannot overlap its own rows.
        self.ensurePolished()
        for child in self.findChildren(QWidget):
            child.ensurePolished()
        # +16 px width: the QSS padding lands after the first measure, so
        # the layout hint stays a few px short of the painted buttons
        hint = self.sizeHint()
        hint.setWidth(hint.width() + 16)
        self.setMinimumSize(hint)
        self.resize(hint)

        self.btn_import_spf.clicked.connect(self._import_spf)
        self.btn_import_net.clicked.connect(self._import_net)
        self.btn_import_bom.clicked.connect(self._import_bom)
        self._route_group.buttonClicked.connect(self._on_route_changed)

    # --------------------------------------------------------- block 1
    def _build_product_block(self) -> QWidget:
        """Block 1 - Product Information, two fields per row (M126).

        Single-column rows made every input span the whole dialog; two
        columns keep the five metadata fields on three rows instead.
        """
        box = QGroupBox("Product Information")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.edit_part_number = QLineEdit()
        self.edit_part_number.setToolTip(
            "Product Part # - auto-filled from the SPF first-page "
            "drawing title when available, always editable")
        self.edit_part_number.setMaximumWidth(320)
        self.edit_product_id = QLineEdit()
        self.edit_product_id.setToolTip(
            "Core ID - auto-filled with the Core ID extracted from "
            "the SPF file name; manual override allowed")
        self.edit_product_id.setMaximumWidth(320)

        self.combo_sw_revision = self._revision_combo(
            "FSW Revision - the whole test-software package revision")
        self.combo_hw_revision = self._revision_combo(
            "700 HW Revision - board revision used for the report "
            "metadata and the MTK ICT Sheet file name")

        self.combo_batch = QComboBox()
        self.combo_batch.setInsertPolicy(QComboBox.NoInsert)
        self.combo_batch.addItems(list(BATCH_OPTIONS))
        self.combo_batch.setMaximumWidth(260)
        self.combo_batch.setToolTip(
            "Batch # - fixed options; Customized and Deviation (DRQ) "
            "open a small dialog for the details")
        self.combo_batch.activated.connect(self._on_batch_activated)

        grid.addWidget(QLabel("Product Part #:"), 0, 0)
        grid.addWidget(self.edit_part_number, 0, 1)
        grid.addWidget(QLabel("Core ID:"), 0, 2)
        grid.addWidget(self.edit_product_id, 0, 3)

        grid.addWidget(QLabel("FSW Revision:"), 1, 0)
        grid.addWidget(self.combo_sw_revision, 1, 1)
        grid.addWidget(QLabel("700 HW Revision:"), 1, 2)
        grid.addWidget(self.combo_hw_revision, 1, 3)

        grid.addWidget(QLabel("Batch #:"), 2, 0)
        grid.addWidget(self.combo_batch, 2, 1)
        self.lbl_batch_detail = QLabel("")
        self.lbl_batch_detail.setObjectName("muted")
        grid.addWidget(self.lbl_batch_detail, 2, 2, 1, 2)
        return box

    # ------------------------------------------------- revision dropdown
    def _revision_combo(self, tooltip: str) -> QComboBox:
        """Rev A..H + ``Customized ...``; blank until something is picked.

        A legacy value (``1.0.3``, ``Rev C-2``) is added as an item on
        load so the stored string is shown verbatim - never rewritten.
        """
        combo = QComboBox()
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.addItems(REVISION_CHOICES + (REVISION_CUSTOMIZED,))
        combo.setCurrentIndex(-1)
        combo.setMaximumWidth(220)
        combo.setToolTip(tooltip)
        combo.activated.connect(
            lambda _index, c=combo: self._on_revision_activated(c))
        return combo

    def _on_revision_activated(self, combo: QComboBox) -> None:
        """``Customized ...`` asks for free text; anything else is taken."""
        if combo.currentText() != REVISION_CUSTOMIZED:
            combo._last_value = combo.currentText()          # noqa: SLF001
            return
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Customized Revision",
            "User-defined revision:", text=getattr(combo, "_last_value", ""))
        if not ok or not text.strip():
            self._set_revision(combo, getattr(combo, "_last_value", ""))
            return
        self._set_revision(combo, text.strip())
        self.content_changed.emit()

    @staticmethod
    def _set_revision(combo: QComboBox, value: str) -> None:
        """Show ``value`` exactly - adding it as an item when unknown."""
        value = (value or "").strip()
        combo._last_value = value                             # noqa: SLF001
        if not value:
            combo.setCurrentIndex(-1)
            return
        known = [combo.itemText(i) for i in range(combo.count())]
        if value not in known:
            combo.addItem(value)
        combo.setCurrentText(value)

    @staticmethod
    def _revision_value(combo: QComboBox) -> str:
        return combo.currentText().strip()

    # --------------------------------------------------------- block 2
    def _build_ict_block(self) -> QWidget:
        """Block 2 - Design Files for ICT: Enable + three exclusive routes.

        M126: Route A / B / C are spelled out and stacked top to bottom;
        the two routes that are not chosen grey out ENTIRELY (label
        included) and switching route clears the files imported so far.
        """
        box = QGroupBox("Design Files for ICT")
        self._ict_box = box
        lay = QVBoxLayout(box)
        self.chk_ict = QCheckBox("Enable")
        self.chk_ict.setChecked(True)
        lay.addWidget(self.chk_ict)

        # everything under Enable lives in one body so "disable" can
        # grey / freeze it without touching the Enable box itself
        self._ict_body = QWidget()
        body = QVBoxLayout(self._ict_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        lay.addWidget(self._ict_body)

        self._route_group = QButtonGroup(box)
        self.radio_files = QRadioButton("Route A - SPF + NET + BoM")
        self.radio_excel = QRadioButton(
            "Route B - ICT Excel Spreadsheet (Traditional)")
        self.radio_mtk = QRadioButton("Route C - MTK ICT Excel Sheet")
        self.radio_files.setChecked(True)
        for radio in (self.radio_files, self.radio_excel, self.radio_mtk):
            self._route_group.addButton(radio)

        # --- Route A: the three import buttons + captions
        self._files_route = QWidget()
        files_lay = QVBoxLayout(self._files_route)
        files_lay.setContentsMargins(10, 0, 0, 4)
        files_lay.setSpacing(6)
        buttons = QHBoxLayout()
        self.btn_import_spf = QPushButton("Import SPF…")
        self.btn_import_net = QPushButton("Import NET…")
        self.btn_import_bom = QPushButton("Import BOM…")
        buttons.addWidget(self.btn_import_spf)
        buttons.addWidget(self.btn_import_net)
        buttons.addWidget(self.btn_import_bom)
        buttons.addStretch(1)
        files_lay.addLayout(buttons)
        files_lay.addSpacing(4)
        self.lbl_spf = QLabel("SPF: (not imported)")
        self.lbl_net = QLabel("NET: (not imported)")
        self.lbl_bom = QLabel("BOM: (not imported)")
        for label in (self.lbl_spf, self.lbl_net, self.lbl_bom):
            files_lay.addWidget(label)

        # --- Route B: one workbook
        self._excel_route = QWidget()
        excel_lay = QVBoxLayout(self._excel_route)
        excel_lay.setContentsMargins(10, 0, 0, 4)
        excel_row = QHBoxLayout()
        self.btn_import_excel = QPushButton("Import ICT Excel…")
        self.btn_import_excel.clicked.connect(self._import_ict_excel)
        excel_row.addWidget(self.btn_import_excel)
        excel_row.addStretch(1)
        excel_lay.addLayout(excel_row)
        self.lbl_excel = QLabel("Workbook: (not imported)")
        self.lbl_excel.setObjectName("muted")
        self.lbl_excel.setWordWrap(True)
        excel_lay.addWidget(self.lbl_excel)

        # --- Route C: one MTK-authored workbook, parsed on import
        self._mtk_route = QWidget()
        mtk_lay = QVBoxLayout(self._mtk_route)
        mtk_lay.setContentsMargins(10, 0, 0, 4)
        mtk_row = QHBoxLayout()
        self.btn_import_mtk = QPushButton("Import MTK ICT Excel Sheet…")
        self.btn_import_mtk.clicked.connect(self._import_mtk_sheet)
        mtk_row.addWidget(self.btn_import_mtk)
        mtk_row.addStretch(1)
        mtk_lay.addLayout(mtk_row)
        self.lbl_mtk = QLabel("Sheet: (not imported)")
        self.lbl_mtk.setObjectName("muted")
        self.lbl_mtk.setWordWrap(True)
        mtk_lay.addWidget(self.lbl_mtk)
        self.lbl_mtk_note = QLabel(MTK_ROUTE_NOTE)
        self.lbl_mtk_note.setObjectName("muted")
        self.lbl_mtk_note.setWordWrap(True)
        mtk_lay.addWidget(self.lbl_mtk_note)

        # top-to-bottom: the label of each route sits above its own panel
        body.addWidget(self.radio_files)
        body.addWidget(self._files_route)
        body.addWidget(self.radio_excel)
        body.addWidget(self._excel_route)
        body.addWidget(self.radio_mtk)
        body.addWidget(self._mtk_route)
        body.addStretch(1)       # spare height stays at the bottom

        self._route_radios = {"files": self.radio_files,
                              "excel": self.radio_excel,
                              "mtk_sheet": self.radio_mtk}
        self._route_bodies = {"files": self._files_route,
                              "excel": self._excel_route,
                              "mtk_sheet": self._mtk_route}
        self._route_current = "files"

        self.chk_ict.toggled.connect(self._on_ict_toggled)
        self.radio_files.toggled.connect(self._on_route_changed)
        self.radio_excel.toggled.connect(self._on_route_changed)
        self.radio_mtk.toggled.connect(self._on_route_changed)
        return box

    # --------------------------------------------------------- block 3
    def _build_fct_block(self) -> QWidget:
        """Block 3 - Pre-Configure for FCT: Enable + board software +
        supported test types (declare only, never branch).

        M126: the list is split into standard steps and FCT-specific
        steps, offers Select all / Select none (all-off is allowed), and
        follows the board software's default ticks.
        """
        box = QGroupBox("Pre-Configure for FCT")
        self._fct_box = box
        lay = QVBoxLayout(box)
        self.chk_fct = QCheckBox("Enable")
        self.chk_fct.setChecked(True)
        lay.addWidget(self.chk_fct)

        self._fct_body = QWidget()
        body = QVBoxLayout(self._fct_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        lay.addWidget(self._fct_body)

        sw_row = QHBoxLayout()
        sw_row.addWidget(QLabel("DUT Board Software:"))
        self.combo_board_software = QComboBox()
        self.combo_board_software.setInsertPolicy(QComboBox.NoInsert)
        self.combo_board_software.addItems(
            ["linux", "bare_metal", "slave_daughter"])
        self.combo_board_software.setMaximumWidth(200)
        sw_row.addWidget(self.combo_board_software)
        sw_row.addStretch(1)
        body.addLayout(sw_row)

        body.addWidget(QLabel("FCT supported test types:"))
        # the two shortcuts own one right-aligned row: sharing the line
        # with the caption clipped it at the half-width column (M126)
        head = QHBoxLayout()
        head.addStretch(1)
        self.btn_fct_all = QPushButton("Select all")
        self.btn_fct_all.setToolTip("Tick every supported test type")
        self.btn_fct_none = QPushButton("Select none")
        self.btn_fct_none.setToolTip(
            "Untick every test type - an all-off list is allowed")
        for btn in (self.btn_fct_all, self.btn_fct_none):
            # no width cap: the QSS padding makes the button minimum 3 px
            # wider than its size hint, and a cap clipped the label (M126)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            head.addWidget(btn)
        body.addLayout(head)

        # two checks per row: the list must fit the half-width FCT
        # column, not force the dialog wider (M126)
        self._fct_type_checks: dict[str, QCheckBox] = {}
        for title, keys in (("Standard test steps", FCT_STANDARD_TESTS),
                            ("FCT-specific test steps", FCT_SPECIFIC_TESTS)):
            caption = QLabel(title)
            caption.setObjectName("muted")
            body.addWidget(caption)
            grid = QGridLayout()
            grid.setContentsMargins(10, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(4)
            for index, key in enumerate(keys):
                check = QCheckBox(dict(FCT_TEST_TYPES)[key])
                self._fct_type_checks[key] = check
                grid.addWidget(check, index // 2, index % 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            body.addLayout(grid)
        body.addStretch(1)       # spare height stays at the bottom
        self._fct_rows = body

        self.btn_fct_all.clicked.connect(lambda: self._set_all_fct_tests(True))
        self.btn_fct_none.clicked.connect(
            lambda: self._set_all_fct_tests(False))
        self.combo_board_software.activated.connect(
            self._on_board_software_changed)
        self._apply_default_fct_tests()
        self.chk_fct.toggled.connect(self._on_fct_toggled)
        return box

    # ------------------------------------------------------ fct defaults
    def _apply_default_fct_tests(self) -> None:
        """Tick the board software's defaults (Linux = everything)."""
        default = FCT_DEFAULT_TESTS.get(
            self.combo_board_software.currentText()) or ()
        for key, check in self._fct_type_checks.items():
            check.setChecked(key in default)

    def _on_board_software_changed(self, _index: int) -> None:
        """A board-software change resets the ticks to its defaults."""
        self._apply_default_fct_tests()
        self.task_log.emit(
            "info",
            "DUT board software "
            f"{self.combo_board_software.currentText()}: default test "
            "types applied")
        self.content_changed.emit()

    def _set_all_fct_tests(self, checked: bool) -> None:
        """Select all / none (all-off is a legal configuration)."""
        for check in self._fct_type_checks.values():
            check.setChecked(checked)
        self.content_changed.emit()

    # --------------------------------------------------------- route ui
    def _current_route(self) -> str:
        if self.radio_mtk.isChecked():
            return "mtk_sheet"
        if self.radio_excel.isChecked():
            return "excel"
        return "files"

    def _refresh_route_state(self) -> None:
        """Grey every route that is not chosen; disable the whole body
        when the block itself is off (M126)."""
        enabled = self.chk_ict.isChecked()
        chosen = self._current_route()
        _grey_card(self._ict_box, self._ict_body, not enabled)
        if not enabled:
            return
        for key, radio in self._route_radios.items():
            is_chosen = key == chosen
            radio.setStyleSheet("" if is_chosen else _GREY_QSS)
            _grey_out(self._route_bodies[key], not is_chosen)

    def _on_route_changed(self, _button=None) -> None:
        """Switch route: clear what was imported before, re-import needed."""
        if getattr(self, "_loading", False):
            self._refresh_route_state()
            return
        chosen = self._current_route()
        if chosen != self._route_current:
            self._route_current = chosen
            self._clear_imports()
            self.task_log.emit(
                "info",
                "ICT route changed: previously imported files were "
                "cleared - import the files for this route again")
            self.content_changed.emit()
        self._refresh_route_state()

    def _clear_imports(self) -> None:
        """Drop every imported ICT file (route switch = start over)."""
        self.spf_path = self.spf_text = ""
        self.net_path = self.net_text = ""
        self.bom_path = ""
        self.bom_records = self.bom_dnp = 0
        self._ict_excel_path = ""
        self._mtk_sheet_path = ""
        self.lbl_spf.setText("SPF: (not imported)")
        self.lbl_net.setText("NET: (not imported)")
        self.lbl_bom.setText("BOM: (not imported)")
        self.lbl_excel.setText("Workbook: (not imported)")
        self.lbl_mtk.setText("Sheet: (not imported)")
        self.lbl_mtk_note.setText(MTK_ROUTE_NOTE)

    def _on_ict_toggled(self, checked: bool) -> None:
        self._refresh_route_state()

    def _on_fct_toggled(self, checked: bool) -> None:
        _grey_card(self._fct_box, self._fct_body, not checked)

    def _import_ict_excel(self) -> None:
        """Record the ICT Excel workbook (Route B); LOAD ONLY here."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import ICT Excel Spreadsheet", "", "Excel (*.xlsx)")
        if not path:
            return
        self._ict_excel_path = path
        _path_text(self.lbl_excel, "Workbook:", _rel_path(path))
        self.content_changed.emit()

    def _import_mtk_sheet(self) -> None:
        """Import + parse the MTK ICT Excel Sheet (Route C).

        A rejected sheet writes nothing: the path stays empty, the
        caption stays ``Sheet: (not imported)`` and no override is
        offered.
        """
        from PySide6.QtWidgets import QFileDialog

        from mtkgui.ict.netparse.route_c import parse_mtk_sheet

        path, _ = QFileDialog.getOpenFileName(
            self, "Import MTK ICT Excel Sheet", "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            result = parse_mtk_sheet(path)
        except ValueError as exc:
            self._reject_mtk_sheet(str(exc))
            return
        if not result.gate_ok:
            self._reject_mtk_sheet(result.gate_error)
            return
        self._mtk_sheet_path = path
        _path_text(self.lbl_mtk, "Sheet:", _rel_path(path))
        self.lbl_mtk_note.setText(result.summary())
        self.mtk_sheet_imported.emit(result)
        self.content_changed.emit()

    def _reject_mtk_sheet(self, reason: str) -> None:
        """Show the rejection (no override) and keep the model untouched."""
        self.task_log.emit("ERROR", reason)
        box = QMessageBox(self)
        box.setWindowTitle("Cannot import MTK ICT Excel Sheet")
        box.setText(
            f"{reason}\n\nNo data was written. Fix the sheet and import "
            "again.")
        box.exec()

    # ------------------------------------------------------------ import
    def _import_spf(self) -> None:
        """IMPORT + auto-parse an SPF file: bytes in memory, Core ID
        from the file name, Project Name from the first-page title.

        M15: the Smart-PDF text extraction runs in a worker thread so
        a ~1 s extraction never freezes the dialog; the foreground
        progress dialog is driven through ``task_progress`` (0/15/50/
        100).  Non-PDF files are read directly (fast)."""
        from PySide6.QtWidgets import QFileDialog
        # item 21: SPF import accepts ONLY Allegro Smart PDF - the
        # txt / .spf text fallback is removed
        begin("yamlbuild: import SPF pick", category="ui", wait=True)
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import SPF", "",
                "Allegro Smart PDF (*.pdf);;All files (*.*)")
        finally:
            end("yamlbuild: import SPF pick")
        if not path:
            return
        begin("yamlbuild: import SPF")
        self.task_progress.emit(0, "spf import: reading file")
        self.task_log.emit("INFO",
                           f"SPF import started: {Path(path).name}")
        if Path(path).suffix.lower() == ".pdf":
            # heavy extraction off the GUI thread (M15); the
            # completion / failure slots continue on the main thread
            self.btn_import_spf.setEnabled(False)
            self.task_progress.emit(15, "spf import: extracting text")
            self._spf_worker = SpfExtractWorker(path, self)
            self._spf_worker.done.connect(self._on_spf_text)
            self._spf_worker.failed.connect(self._on_spf_failed)
            self._spf_worker.start()
            return
        try:
            text = read_text_any_encoding(path)
            if not text.strip():
                raise ValueError("the file is empty (0 content bytes)")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            self._spf_fail(f"SPF import failed: {exc}")
            return
        self._spf_apply(text, path)

    def _on_spf_text(self, text: str, path: str) -> None:
        """Worker done: finish the (cheap) project-info extraction."""
        self._spf_apply(text, path)

    def _on_spf_failed(self, reason: str) -> None:
        """Worker failed: exact reason, never a silent fail."""
        self._spf_fail(f"SPF import failed: {reason}")

    def _spf_fail(self, reason: str) -> None:
        """Shared failure path (direct read + worker extraction)."""
        end("yamlbuild: import SPF")
        self.btn_import_spf.setEnabled(True)
        self.task_log.emit("ERROR", reason)
        self.task_progress.emit(0, "spf import: idle")
        QMessageBox.critical(self, "SPF Import Failed", reason)

    def _spf_apply(self, text: str, path: str) -> None:
        """Shared success path: fill the meta form from the extracted
        text (main thread; the worker text was already validated)."""
        end("yamlbuild: import SPF")
        self.btn_import_spf.setEnabled(True)
        self.task_progress.emit(50, "spf import: extracting project info")
        core_id = core_id_from_filename(Path(path).name)
        title = ""
        if Path(path).suffix.lower() == ".pdf":
            # Smart-PDF drawing: the board Project Part# lives in the
            # drawing title block (e.g. FRDM-IMXRT700); the Core ID
            # enables the "Part No. <name> + SCH-<core id>" pairing
            # (old drawings list several boards in the title block)
            from mtkgui.gui.yamlbuild.parser import \
                extract_drawing_board_name
            title = extract_drawing_board_name(text, core_id)
        if not title:
            title = extract_spf_project_name(text)
        if not core_id and not title:
            reason = ("SPF import: no Core ID in the file name and no "
                      "first-page title found - fill Product ID / "
                      "Project Part # manually")
            self.task_log.emit("WARNING", reason)
        self.spf_path = path
        self.spf_text = text
        if core_id:
            self.edit_product_id.setText(core_id)
        if title:
            self.edit_part_number.setText(title)
        _path_text(self.lbl_spf, "SPF:", _rel_path(path))
        self.task_progress.emit(100, "spf import: done")
        self.task_log.emit(
            "INFO",
            f"SPF import done: {Path(path).name} "
            f"(Core ID: {core_id or '-'}, Project Name: "
            f"{title or '-'})")
        self.content_changed.emit()
    def _import_net(self) -> None:
        """IMPORT a NET file: LOAD ONLY - raw bytes into memory, no
        parse, no structure analysis, no data generation."""
        from PySide6.QtWidgets import QFileDialog
        begin("yamlbuild: import NET pick", category="ui", wait=True)
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import NET", "", "Netlist (*.net *.net.txt *.txt)")
        finally:
            end("yamlbuild: import NET pick")
        if not path:
            return
        begin("yamlbuild: import NET")
        self.task_progress.emit(0, "net import: reading file")
        self.task_log.emit("INFO",
                           f"NET import started: {Path(path).name}")
        try:
            text = read_text_any_encoding(path)
            if not text.strip():
                raise ValueError("the file is empty (0 content bytes)")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            reason = f"NET import failed: {exc}"
            self.task_log.emit("ERROR", reason)
            self.task_progress.emit(0, "net import: idle")
            QMessageBox.critical(self, "NET Import Failed", reason)
            end("yamlbuild: import NET")
            return
        self.net_path = path
        self.net_text = text            # load only - never parsed here
        _path_text(self.lbl_net, "NET:", _rel_path(path))
        self.task_progress.emit(100, "net import: done")
        self.task_log.emit(
            "INFO",
            f"NET import done: {Path(path).name} "
            "(load only - parsed by the Parse Nets module)")
        self.content_changed.emit()
        end("yamlbuild: import NET")

    def _import_bom(self) -> None:
        """IMPORT an optional BOM (CSV / XLSX).

        The BOM is parsed immediately for the status label, but a
        failure is a WARNING only - it never blocks NET-only parsing
        (M1 "GUI optional BOM, non-blocking" contract)."""
        from PySide6.QtWidgets import QFileDialog
        from mtkgui.ict.netparse.bom import parse_bom
        begin("yamlbuild: import BOM pick", category="ui", wait=True)
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import BOM", "", "BOM (*.csv *.xlsx)")
        finally:
            end("yamlbuild: import BOM pick")
        if not path:
            return
        begin("yamlbuild: import BOM")
        self.task_log.emit("INFO", f"BOM import started: {Path(path).name}")
        try:
            bom = parse_bom(path)
        except (OSError, ValueError) as exc:
            self.bom_path = ""
            self.bom_records = self.bom_dnp = 0
            self.lbl_bom.setText("BOM: (not imported)")
            reason = f"BOM import failed: {exc}"
            self.task_log.emit("WARNING", reason)
            end("yamlbuild: import BOM")
            return
        self.bom_path = path
        self.bom_records = len(bom.records)
        self.bom_dnp = sum(1 for rec in bom.records if rec.dnp)
        _path_text(self.lbl_bom, "BOM:", _rel_path(path),
                   f" - imported ({self.bom_records} records, "
                   f"{self.bom_dnp} DNP)")
        self.task_log.emit(
            "INFO",
            f"BOM import done: {Path(path).name} "
            f"({self.bom_records} records, {self.bom_dnp} DNP)")
        self.content_changed.emit()
        end("yamlbuild: import BOM")

    # ------------------------------------------------------------- batch
    def _on_batch_activated(self, index: int) -> None:
        """Customized / Deviation (DRQ) resolve through small dialogs;
        every other option is taken as-is."""
        option = self.combo_batch.itemText(index)
        if option == "Customized":
            from PySide6.QtWidgets import QInputDialog
            old = self._customized_value()
            name, ok = QInputDialog.getText(
                self, "Customized Batch",
                "User-defined batch name:", text=old)
            if not ok or not name.strip():
                # restore the persisted value / fall back to plain
                self._reload_batch(self.batch_value() or option)
                return
            self.set_batch(BATCH_CUSTOMIZED_PREFIX + name.strip())
            self.content_changed.emit()
        elif option == "Deviation (DRQ)":
            dlg = DrqDialog(self._drq_values(), self)
            if dlg.exec() != QDialog.DialogCode.Accepted \
                    or not dlg.drq_numbers():
                self._reload_batch(self.batch_value() or option)
                return
            self.set_batch(BATCH_DEVIATION_PREFIX
                           + ", ".join(dlg.drq_numbers()))
            self.content_changed.emit()
        else:
            self.lbl_batch_detail.setText("")
            self.content_changed.emit()

    # ------------------------------------------------------ batch values
    def batch_value(self) -> str:
        """The persisted batch string (dialog options resolved)."""
        option = self.combo_batch.currentText()
        if option == "Customized":
            return BATCH_CUSTOMIZED_PREFIX + self._customized_value()
        if option == "Deviation (DRQ)":
            return (BATCH_DEVIATION_PREFIX
                    + ", ".join(self._drq_values()))
        return option

    def set_batch(self, value: str) -> None:
        """Load a persisted batch string (backward compatible: legacy
        free-text batches map to Customized)."""
        text = (value or "").strip()
        if text.startswith(BATCH_CUSTOMIZED_PREFIX):
            self.combo_batch.setCurrentText("Customized")
            self.lbl_batch_detail.setText(
                text[len(BATCH_CUSTOMIZED_PREFIX):])
        elif text.startswith(BATCH_DEVIATION_PREFIX):
            self.combo_batch.setCurrentText("Deviation (DRQ)")
            self.lbl_batch_detail.setText(
                text[len(BATCH_DEVIATION_PREFIX):])
        elif text in BATCH_OPTIONS:
            self.combo_batch.setCurrentText(text)
            self.lbl_batch_detail.setText("")
        elif text:
            # legacy free-text batch: keep visible as Customized
            self.combo_batch.setCurrentText("Customized")
            self.lbl_batch_detail.setText(text)
        else:
            self.combo_batch.setCurrentIndex(0)
            self.lbl_batch_detail.setText("")

    def _customized_value(self) -> str:
        """The user-defined batch name (empty unless Customized)."""
        if self.combo_batch.currentText() != "Customized":
            return ""
        return self.lbl_batch_detail.text().strip()

    def _drq_values(self) -> list[str]:
        """The stored DRQ numbers (empty unless Deviation (DRQ))."""
        if self.combo_batch.currentText() != "Deviation (DRQ)":
            return []
        return [p.strip() for p in self.lbl_batch_detail.text().split(",")
                if p.strip()]

    def _reload_batch(self, value: str) -> None:
        self.set_batch(value)

    # ------------------------------------------------------ values in/out
    def values(self) -> dict:
        """The schema-shaped parameter dict (all values strings)."""
        fct_tests = "\n".join(key for key, check in self._fct_type_checks.items()
                              if check.isChecked())
        return {
            "part_number": self.edit_part_number.text().strip(),
            "product_id": self.edit_product_id.text().strip(),
            "sw_version": self._revision_value(self.combo_sw_revision),
            "hw_version": self._revision_value(self.combo_hw_revision),
            "batch": self.batch_value(),
            "ict_block_enabled": _bool_text(self.chk_ict.isChecked()),
            "ict_route": ("mtk_sheet" if self.radio_mtk.isChecked()
                          else ("excel" if self.radio_excel.isChecked()
                                else "files")),
            "ict_excel_file": _stored_path(self._ict_excel_path),
            "ict_mtk_sheet_file": _stored_path(self._mtk_sheet_path),
            "fct_block_enabled": _bool_text(self.chk_fct.isChecked()),
            "dut_board_software": self.combo_board_software.currentText(),
            "fct_supported_tests": fct_tests,
            "spf_file": _rel_path(self.spf_path) if self.spf_path else "",
            "net_file": _rel_path(self.net_path) if self.net_path else "",
            "bom_file": _stored_path(self.bom_path),
        }

    def set_values(self, params: dict) -> None:
        """Load persisted values (backward compatible with old YAML:
        legacy core_id / project_name / schematic_file keys map onto
        the new fields; legacy free-text batch maps to Customized).

        M126: the load runs with ``_loading`` set - a loaded route must
        not look like an operator switch (that would clear the files
        the project just brought in).
        """
        params = params or {}
        self._loading = True
        try:
            self._set_values(params)
        finally:
            self._loading = False
        self._route_current = self._current_route()
        self._refresh_route_state()
        _grey_card(self._fct_box, self._fct_body,
                   not self.chk_fct.isChecked())

    def _set_values(self, params: dict) -> None:
        self.edit_part_number.setText(
            str(params.get("part_number")
                or params.get("project_name") or ""))
        self.edit_product_id.setText(
            str(params.get("product_id")
                or params.get("core_id") or ""))
        self._set_revision(self.combo_sw_revision,
                           str(params.get("sw_version") or ""))
        self._set_revision(self.combo_hw_revision,
                           str(params.get("hw_version") or ""))
        self.set_batch(str(params.get("batch") or ""))
        self.chk_ict.setChecked(_true_text(params.get("ict_block_enabled")))
        route = str(params.get("ict_route") or "files")
        if route not in ("files", "excel", "mtk_sheet"):
            route = "files"          # unknown value: old YAML keeps loading
        self.radio_mtk.setChecked(route == "mtk_sheet")
        self.radio_excel.setChecked(route == "excel")
        self.radio_files.setChecked(route == "files")
        self._ict_excel_path = str(params.get("ict_excel_file") or "")
        if self._ict_excel_path:
            _path_text(self.lbl_excel, "Workbook:", self._ict_excel_path)
        else:
            self.lbl_excel.setText("Workbook: (not imported)")
        self._mtk_sheet_path = str(params.get("ict_mtk_sheet_file") or "")
        if self._mtk_sheet_path:
            _path_text(self.lbl_mtk, "Sheet:", self._mtk_sheet_path)
        else:
            self.lbl_mtk.setText("Sheet: (not imported)")
        self.chk_fct.setChecked(_true_text(params.get("fct_block_enabled")))
        sw = str(params.get("dut_board_software") or "linux")
        if sw in ("linux", "bare_metal", "slave_daughter"):
            self.combo_board_software.setCurrentText(sw)
        if "fct_supported_tests" in params:
            # an explicit (possibly EMPTY) list is the project's choice -
            # "all off" is legal (M126) and must not become defaults
            supported = {
                ln.strip() for ln in
                str(params.get("fct_supported_tests") or "").splitlines()
                if ln.strip()}
        else:
            supported = set(FCT_DEFAULT_TESTS.get(sw) or ())
        for key, check in self._fct_type_checks.items():
            check.setChecked(key in supported)
        self.spf_path = str(params.get("spf_file")
                            or params.get("schematic_file") or "")
        if self.spf_path:
            _path_text(self.lbl_spf, "SPF:", self.spf_path)
        else:
            self.lbl_spf.setText("SPF: (not imported)")
        self.net_path = str(params.get("net_file") or "")
        if self.net_path:
            _path_text(self.lbl_net, "NET:", self.net_path)
        else:
            self.lbl_net.setText("NET: (not imported)")
        self.bom_path = str(params.get("bom_file") or "")
        self._reload_bom_label()

    # ---------------------------------------------------------- validation
    def validate(self) -> tuple[bool, str]:
        """Node 01 gate: both blocks off is forbidden; the five Product
        Information fields and the chosen route's files must be present.

        Returns ``(ok, message)`` — ``message`` becomes the ``[Next >]``
        tooltip when ``ok`` is False.
        """
        if not self.chk_ict.isChecked() and not self.chk_fct.isChecked():
            return False, "At least one of ICT / FCT must be enabled"
        for key, label in (("part_number", "Product Part #"),
                           ("product_id", "Core ID"),
                           ("sw_version", "FSW Revision"),
                           ("hw_version", "700 HW Revision")):
            if not self.values()[key].strip():
                return False, f"{label} is required"
        if not self.batch_value().strip():
            return False, "Batch # is required"
        if self.chk_ict.isChecked():
            if self.radio_mtk.isChecked():
                if not self._mtk_sheet_path.strip():
                    return False, "MTK ICT Excel Sheet is required"
            elif self.radio_excel.isChecked():
                if not self._ict_excel_path.strip():
                    return False, "ICT Excel Spreadsheet is required"
            else:
                if not (self.spf_path.strip() and self.net_path.strip()
                        and self.bom_path.strip()):
                    return False, "SPF, NET and BoM are all required"
        return True, ""

    def _reload_bom_label(self) -> None:
        """Restore the BOM caption after a project load: parse the
        stored path for the record / DNP counts; a missing or broken
        file shows the path only (never blocks the load)."""
        if not self.bom_path:
            self.bom_records = self.bom_dnp = 0
            self.lbl_bom.setText("BOM: (not imported)")
            return
        try:
            from mtkgui.ict.netparse.bom import parse_bom
            bom = parse_bom(self.bom_path)
        except (OSError, ValueError):
            self.bom_records = self.bom_dnp = 0
            _path_text(self.lbl_bom, "BOM:", self.bom_path,
                       " (not readable)")
            return
        self.bom_records = len(bom.records)
        self.bom_dnp = sum(1 for rec in bom.records if rec.dnp)
        _path_text(self.lbl_bom, "BOM:", _rel_path(self.bom_path),
                   f" - imported ({self.bom_records} records, "
                   f"{self.bom_dnp} DNP)")


def _path_text(label, prefix: str, path: str, tail: str = "") -> None:
    """M124: bound a path label so an import never widens the dialog.

    A plain ``QLabel`` grew with the whole path and pushed the dialog
    past the screen edge (user report 2026-11-25: "import 文件后，路径
    长度会改变窗体宽度").  A long path is shown as its file name, the
    full path stays in the tooltip, and the label wraps inside a fixed
    width.
    """
    path = str(path or "")
    shown = Path(path).name if len(path) > 48 else path
    label.setText(f"{prefix} {shown}{tail}")
    label.setToolTip(f"{prefix} {path}" if path else prefix)
    label.setWordWrap(True)
    label.setMaximumWidth(520)


def _rel_path(path: str) -> str:
    """Relative path + file name when inside the repo, else the full
    path (the caption never loses the file name)."""
    if not path:
        return ""
    p = Path(path)
    try:
        rel = p.relative_to(Path.cwd())
        return f"{rel.as_posix()} ({p.name})"
    except ValueError:
        return str(p)


def _stored_path(path: str) -> str:
    """Persistable path: repo-relative when inside the working tree,
    absolute otherwise (the display caption is NOT reusable)."""
    if not path:
        return ""
    p = Path(path)
    try:
        return p.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(p.resolve())


def _bool_text(value: bool) -> str:
    """``"true"`` / ``"false"`` for the schema's T_BOOL fields."""
    return "true" if value else "false"


def _true_text(value) -> bool:
    """Tolerant bool read-back for a stored T_BOOL string."""
    return str(value or "").strip().lower() not in ("", "false", "0", "no")
