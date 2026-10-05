# -*- coding: utf-8 -*-
"""Design-Input page: file loading & project meta info (B1-01-00).

Spec items implemented here:

* Schematic / Net file browse buttons with load-state captions
  (``Schematic: ✔ Loaded`` / ``Net: ✔ Loaded``, plus the Smart-PDF
  review marker);
* scanned-image PDF interception with the spec-fixed wording;
* ``Parse nets for ICT`` disabled until BOTH inputs are loaded;
* project_name / core_id auto-fill with the ``⚠ Manually entered``
  distinction;
* dut_board_type combo (4 fixed enums + auto inference) and the
  DUT power-up procedure text (archive-only note).

The page owns the :class:`DesignDataModel`; every action is mirrored
to the ``event_log`` signal (level, message) so the main window can
append timestamped Event-Log lines.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.designinput.components import build_library
from mtkgui.gui.designinput.model import (
    BOARD_TYPES,
    DesignDataModel,
)
from mtkgui.gui.designinput.netlist import classify_nets, \
    parse_netlist_file
from mtkgui.gui.designinput.pdf_schematic import parse_pdf_schematic
from mtkgui.gui.designinput.power_tree_draft import \
    derive_candidate_tree
from mtkgui.gui.designinput.sources import (
    SCANNED_PDF_NOTICE,
    SOURCE_SMART_PDF_SPF,
    ScannedPdfError,
    detect_schematic_source,
)
from mtkgui.gui.designinput.spf_parser import SpfParseError, parse_spf
from mtkgui.gui.designinput.testpoints import select_test_points
from mtkgui.gui.yamlbuild.parser import extract_pdf_text

SMART_PDF_MARKER = "(Smart-PDF source, review component library!)"
MANUAL_MARKER = "⚠ Manually entered"

BOARD_LABELS = {
    "FULL_SYSTEM_BOARD": "FULL_SYSTEM_BOARD 完整系统板",
    "MAIN_CONTROLLER_BOARD": "MAIN_CONTROLLER_BOARD 主控板",
    "NO_MCU_INTERFACE_SUB_BOARD": "NO_MCU_INTERFACE_SUB_BOARD 无主芯片接口基板",
    "DAUGHTER_MODULE_CARD": "DAUGHTER_MODULE_CARD 子卡模组",
}


class DesignInputPage(QWidget):
    """B1-01 Design-Input: load -> parse -> meta editing."""

    #: (level, message) Event-Log mirror for the main window
    event_log = Signal(str, str)

    def __init__(self, parent=None) -> None:
        """Build the page (model + load row + meta form)."""
        super().__init__(parent)
        self.model = DesignDataModel()
        self._schematic_loaded = False
        self._net_loaded = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # ------------------------------------------- file loading group
        load_group = QGroupBox("Design Input Files")
        load_form = QFormLayout(load_group)

        schem_row = QHBoxLayout()
        self.btn_schematic = QPushButton("Schematic File [Browse]")
        self.lbl_schematic_status = QLabel("Schematic: -")
        schem_row.addWidget(self.btn_schematic, 0)
        schem_row.addWidget(self.lbl_schematic_status, 1)
        load_form.addRow(schem_row)

        net_row = QHBoxLayout()
        self.btn_net = QPushButton("Net File [Browse]")
        self.lbl_net_status = QLabel("Net: -")
        net_row.addWidget(self.btn_net, 0)
        net_row.addWidget(self.lbl_net_status, 1)
        load_form.addRow(net_row)

        self.btn_parse = QPushButton("Parse nets for ICT")
        self.btn_parse.setEnabled(False)      # until BOTH files loaded
        load_form.addRow(self.btn_parse)
        root.addWidget(load_group)

        # ------------------------------------------------- meta group
        meta_group = QGroupBox("Project Meta Information")
        meta_form = QFormLayout(meta_group)

        name_row = QHBoxLayout()
        self.edit_project_name = QLineEdit()
        self.lbl_name_marker = QLabel("")
        self.lbl_name_marker.setObjectName("muted")
        name_row.addWidget(self.edit_project_name, 1)
        name_row.addWidget(self.lbl_name_marker, 0)
        meta_form.addRow("Project Name:", name_row)

        self.edit_core_id = QLineEdit()
        self.lbl_core_marker = QLabel("")
        self.lbl_core_marker.setObjectName("muted")
        core_row = QHBoxLayout()
        core_row.addWidget(self.edit_core_id, 1)
        core_row.addWidget(self.lbl_core_marker, 0)
        meta_form.addRow("Core ID:", core_row)

        self.combo_board_type = QComboBox()
        for value in BOARD_TYPES:
            self.combo_board_type.addItem(BOARD_LABELS[value], value)
        meta_form.addRow("DUT Board Type:", self.combo_board_type)

        self.edit_powerup = QPlainTextEdit()
        self.edit_powerup.setPlaceholderText(
            "DUT power-up procedure (archive note text ...)")
        self.edit_powerup.setFixedHeight(72)
        meta_form.addRow("Power-up Procedure:", self.edit_powerup)
        root.addWidget(meta_group)
        root.addStretch(1)

        # ---------------------------------------------------- wiring
        self.btn_schematic.clicked.connect(self._browse_schematic)
        self.btn_net.clicked.connect(self._browse_net)
        self.btn_parse.clicked.connect(self._parse_nets)
        # user edits mark the field as manually entered
        self.edit_project_name.textEdited.connect(
            lambda: self.lbl_name_marker.setText(MANUAL_MARKER))
        self.edit_core_id.textEdited.connect(
            lambda: self.lbl_core_marker.setText(MANUAL_MARKER))

    # ------------------------------------------------------------ browse
    def _browse_schematic(self) -> None:
        """Pick + validate the schematic (SPF/txt or Smart-PDF)."""
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select Schematic", "",
            "Schematic (*.spf *.txt *.pdf)")
        if not path:
            return
        try:
            source = detect_schematic_source(path, extract_pdf_text)
        except ScannedPdfError:
            self._log("ERROR", SCANNED_PDF_NOTICE)
            QMessageBox.warning(self, "Unsupported Schematic",
                                SCANNED_PDF_NOTICE)
            return
        except ValueError as exc:
            self._log("ERROR", f"schematic rejected: {exc}")
            QMessageBox.warning(self, "Unsupported Schematic", str(exc))
            return

        try:
            self._load_schematic(path, source)
        except SpfParseError as exc:
            self._log("ERROR", f"SPF parse failed: {exc}")
            QMessageBox.critical(self, "Schematic Parse Error", str(exc))
            return
        self._schematic_loaded = True
        marker = f" {SMART_PDF_MARKER}" \
            if source == SOURCE_SMART_PDF_SPF else ""
        self.lbl_schematic_status.setText(f"Schematic: ✔ Loaded{marker}")
        self._log("INFO", f"Schematic loaded: {Path(path).name} "
                          f"(source={source})")
        if source == SOURCE_SMART_PDF_SPF:
            self._log(
                "WARNING",
                "INFO: Schematic source is Smart-PDF, not native "
                "text-SPF. Component/net parsing may have deviation, "
                "please double-check component_library.")
        self._sync_parse_button()

    def _load_schematic(self, path: str, source: str) -> None:
        """Parse the schematic into the model (both source branches)."""
        self.model.source_type = source
        if source == SOURCE_SMART_PDF_SPF:
            text = extract_pdf_text(path, 5)
            meta_title = _pdf_meta_title(path)
            pdf_data = parse_pdf_schematic(text, meta_title)
            # spec priority: PDF metadata Title > PDF file name
            self.model.project_info["project_name"] = (
                pdf_data.meta_title or Path(path).stem)
            self.model.component_library = build_library(
                pdf_data.components)
            self._auto_fill_name(self.model.project_info["project_name"])
        else:
            spf = parse_spf(_read_text(path))
            self.model.project_info["project_name"] = (
                spf.drawing_title or Path(path).stem)
            self.model.component_library = build_library(spf.components)
            self._auto_fill_name(self.model.project_info["project_name"])

    def _browse_net(self) -> None:
        """Pick + parse the Allegro netlist file."""
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select Netlist", "", "Netlist (*.net *.net.txt)")
        if not path:
            return
        netlist, _text = parse_netlist_file(path)
        if not netlist.nets:
            self._log("ERROR", f"netlist has no nets: {path}")
            QMessageBox.critical(
                self, "Netlist Error",
                "The netlist file contains no nets.")
            return
        self._net_data = netlist
        self._net_loaded = True
        self.lbl_net_status.setText("Net: ✔ Loaded")
        self._log("INFO", f"Netlist loaded: {Path(path).name} "
                          f"({len(netlist.nets)} nets)")
        self._sync_parse_button()

    # ------------------------------------------------------------- parse
    def _sync_parse_button(self) -> None:
        """``Parse nets for ICT`` needs BOTH inputs loaded."""
        self.btn_parse.setEnabled(
            self._schematic_loaded and self._net_loaded)

    def _parse_nets(self) -> None:
        """Run the parsing kernel -> draft results (never committed)."""
        netlist = getattr(self, "_net_data", None)
        if netlist is None or not self._schematic_loaded:
            return
        self.model.net_collection = classify_nets(netlist)
        assignments = select_test_points(self.model.net_collection)
        for rec in self.model.net_collection.nets:
            assign = assignments.get(rec.name)
            if assign is None:
                continue
            rec.is_alternative_testpoint = assign.is_alternative_testpoint
            if rec.net_type == "gnd_ref":
                # reference grounds default ON (user can untoggle)
                rec.is_reference_gnd = True
        # main chips from the library + board-type inference
        mains = [r.refdes for r in self.model.component_library.mains()]
        self.model.set_main_chips(mains)
        if not mains:
            self._log("WARNING", "no main_mcu device identified - "
                                 "check the main-chip list")
        if not self.lbl_core_marker.text():
            self._auto_fill_core(self.model.core_id_suggestion())
        self.model.candidate_power_tree = derive_candidate_tree(
            self.model.component_library, self.model.net_collection)
        if self.model.source_type == SOURCE_SMART_PDF_SPF:
            self._log("WARNING",
                      "Smart-PDF source: power-tree derivation error "
                      "probability is higher, review source/children "
                      "links on the canvas")
        self.combo_board_type.setCurrentIndex(
            BOARD_TYPES.index(self.model.infer_board_type()))
        for rec in self.model.net_collection.nets:
            self._log("INFO", f"net {rec.name}: {rec.net_type}")
        self._log("INFO",
                  f"parse done: {len(self.model.net_collection.nets)} "
                  "nets (DRAFT state - downstream stays disabled)")

    # ------------------------------------------------------------ helpers
    def _auto_fill_name(self, value: str) -> None:
        """Auto-fill project_name (marker stays empty; user edits set
        the manual marker through textEdited)."""
        self.edit_project_name.setText(value or "")
        self.lbl_name_marker.setText("")

    def _auto_fill_core(self, value: str) -> None:
        """Auto-fill the core id from main_mcu part numbers."""
        self.edit_core_id.setText(value or "")
        self.lbl_core_marker.setText("")

    def _log(self, level: str, message: str) -> None:
        """Mirror a line to the Event-Log signal."""
        self.event_log.emit(level, message)


def _read_text(path: str) -> str:
    """Read a text file with the tolerant decode chain."""
    from mtkgui.gui.yamlbuild.parser import read_text_any_encoding
    return read_text_any_encoding(path)


def _pdf_meta_title(path: str) -> str:
    """PDF document metadata Title ("" when unavailable)."""
    try:
        from PySide6.QtPdf import QPdfDocument
        doc = QPdfDocument()
        error = doc.load(path)
        if getattr(error, "value", error) != 0:
            return ""
        meta = doc.metaData(QPdfDocument.MetaDataField.Title)
        return str(meta) if meta else ""
    except Exception:      # noqa: BLE001 - metadata is best-effort
        return ""
