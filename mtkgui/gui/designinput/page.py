# -*- coding: utf-8 -*-
"""Design-Input page: file loading & project meta info (B1-01-00).

Spec items implemented here:

* Schematic / Net file browse buttons with load-state captions
  (``Schematic: ✔ Imported`` / ``Net: ✔ Imported`` at IMPORT; the
  explicit PARSE step flips them to ``✔ Parsed``, plus the Smart-PDF
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
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
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
    #: (percent 0-100, label) parse-step progress for the global
    #: status bar (T6); 0 = start/failed reset, 100 = done
    parse_progress = Signal(int, str)

    def __init__(self, parent=None) -> None:
        """Build the page (model + load row + meta form)."""
        super().__init__(parent)
        self.model = DesignDataModel()
        # IMPORT / PARSE split: the browse buttons only read the file
        # bytes into memory (fast, no structure resolution); the
        # "Parse nets for ICT" button runs the explicit parse step
        self._schematic_loaded = False
        self._net_loaded = False
        self._schematic_path: str | None = None
        self._schematic_text: str | None = None
        self._schematic_source: str | None = None
        self._net_path: str | None = None
        self._parsed = False

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
        self.btn_parse.setEnabled(False)      # until BOTH files imported
        load_form.addRow(self.btn_parse)

        # real-time parse progress (IMPORT / PARSE split): stepped
        # 0 -> 100 % while the explicit parse stage runs
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setObjectName("parse_progress")
        self.progress.setFormat("parse: idle")
        load_form.addRow(self.progress)
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

    # ------------------------------------------------------------ import
    def _browse_schematic(self) -> None:
        """IMPORT step (file load only): pick the schematic and read
        its bytes into memory.  No structure resolution happens here -
        the explicit parse step does that (see _parse_nets)."""
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select Schematic", "",
            "Schematic (*.spf *.txt *.pdf)")
        if not path:
            return
        try:
            size = Path(path).stat().st_size
        except OSError as exc:
            reason = f"schematic import failed: {exc}"
            self._log("ERROR", reason)
            QMessageBox.critical(self, "Import Failed", reason)
            return
        text = None
        if Path(path).suffix.lower() in (".spf", ".txt"):
            # text sources: read + decode now (tolerant decode chain);
            # decode problems surface here, with the file name + reason
            try:
                text = _read_text(path)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                reason = (f"schematic import failed: cannot decode "
                          f"{Path(path).name}: {exc}")
                self._log("ERROR", reason)
                QMessageBox.critical(self, "Import Failed", reason)
                return
        self._schematic_path = path
        self._schematic_text = text
        self._schematic_source = None
        self._schematic_loaded = True
        self._parsed = False
        self.lbl_schematic_status.setText("Schematic: ✔ Imported")
        self._log("INFO", f"Schematic imported: {Path(path).name} "
                          f"({size} bytes) - not parsed yet, click "
                          "'Parse nets for ICT'")
        self._sync_parse_button()

    def _browse_net(self) -> None:
        """IMPORT step (file load only): pick the netlist and read its
        bytes into memory (structure resolve happens in _parse_nets)."""
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select Netlist", "", "Netlist (*.net *.net.txt)")
        if not path:
            return
        try:
            text = _read_text(path)
            size = Path(path).stat().st_size
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            reason = f"netlist import failed: {exc}"
            self._log("ERROR", reason)
            QMessageBox.critical(self, "Import Failed", reason)
            return
        if not text.strip():
            reason = (f"netlist import failed: {Path(path).name} "
                      "is empty (0 content bytes)")
            self._log("ERROR", reason)
            QMessageBox.critical(self, "Import Failed", reason)
            return
        self._net_path = path
        self._net_loaded = True
        self._parsed = False
        self.lbl_net_status.setText("Net: ✔ Imported")
        self._log("INFO", f"Netlist imported: {Path(path).name} "
                          f"({size} bytes) - not parsed yet, click "
                          "'Parse nets for ICT'")
        self._sync_parse_button()

    # ------------------------------------------------------------- parse
    def _sync_parse_button(self) -> None:
        """``Parse nets for ICT`` needs BOTH inputs imported."""
        self.btn_parse.setEnabled(
            self._schematic_loaded and self._net_loaded)

    def _parse_progress(self, percent: int, label: str) -> None:
        """Real-time progress update + step detail in the Event-Log."""
        self.progress.setValue(percent)
        self.progress.setFormat(f"parse: {label}")
        self.parse_progress.emit(percent, f"parse: {label}")
        QApplication.processEvents()   # keep the bar live during parse

    def _parse_failed(self, stage: str, exc: Exception) -> None:
        """NO silent fail: log the exact stage + reason and show it."""
        reason = f"{stage} failed: {exc}"
        self._log("ERROR", reason)
        self._parse_progress(0, "failed")
        QMessageBox.critical(self, "Parse Error", reason)

    def _parse_nets(self) -> None:
        """Explicit PARSE step (structure resolve) with per-stage
        progress + Event-Log detail.  Any parse error aborts with the
        clear reason (no silent fail) and leaves the model untouched."""
        if not (self._schematic_loaded and self._net_loaded):
            return
        self._parse_progress(5, "schematic structure")
        self._log("INFO", "parse step 1/4: schematic structure resolve")
        try:
            self._parse_schematic_structure()
        except ScannedPdfError:
            # spec-fixed wording popup (verbatim, spec B1-01-00)
            self._log("ERROR", SCANNED_PDF_NOTICE)
            self._parse_progress(0, "failed")
            QMessageBox.warning(self, "Unsupported Schematic",
                                SCANNED_PDF_NOTICE)
            return
        except (SpfParseError, OSError, ValueError) as exc:
            self._parse_failed("schematic parse", exc)
            return
        self._parse_progress(30, "netlist structure")
        self._log("INFO", "parse step 2/4: netlist structure resolve")
        try:
            netlist, _text = parse_netlist_file(self._net_path)
        except (OSError, ValueError) as exc:
            self._parse_failed("netlist parse", exc)
            return
        if not netlist.nets:
            self._parse_failed(
                "netlist parse",
                ValueError(f"{Path(self._net_path).name} contains "
                           "no nets (*SIGNAL* blocks)"))
            return
        self._log("INFO", f"netlist resolved: {len(netlist.nets)} nets")
        self._parse_progress(55, "net classification")
        self._log("INFO", "parse step 3/4: net classification + "
                          "test-point selection")
        try:
            self.model.net_collection = classify_nets(netlist)
            assignments = select_test_points(self.model.net_collection)
        except (KeyError, TypeError, ValueError) as exc:
            self._parse_failed("net classification", exc)
            return
        for rec in self.model.net_collection.nets:
            assign = assignments.get(rec.name)
            if assign is None:
                continue
            rec.is_alternative_testpoint = assign.is_alternative_testpoint
            if rec.net_type == "gnd_ref":
                # reference grounds default ON (user can untoggle)
                rec.is_reference_gnd = True
        type_counts = {}
        for rec in self.model.net_collection.nets:
            type_counts[rec.net_type] = \
                type_counts.get(rec.net_type, 0) + 1
        summary = ", ".join(f"{t}={n}"
                            for t, n in sorted(type_counts.items()))
        self._log("INFO", f"nets classified: {summary}")
        self._parse_progress(80, "power tree / board type")
        self._log("INFO", "parse step 4/4: main chips + power tree + "
                          "board type")
        # main chips from the library + board-type inference
        mains = [r.refdes for r in self.model.component_library.mains()]
        self.model.set_main_chips(mains)
        if not mains:
            self._log("WARNING", "no main_mcu device identified - "
                                 "check the main-chip list")
        if not self.lbl_core_marker.text():
            self._auto_fill_core(self.model.core_id_suggestion())
        try:
            self.model.candidate_power_tree = derive_candidate_tree(
                self.model.component_library,
                self.model.net_collection)
        except (KeyError, TypeError, ValueError) as exc:
            self._parse_failed("power tree derivation", exc)
            return
        if self.model.source_type == SOURCE_SMART_PDF_SPF:
            self._log("WARNING",
                      "Smart-PDF source: power-tree derivation error "
                      "probability is higher, review source/children "
                      "links on the canvas")
        self.combo_board_type.setCurrentIndex(
            BOARD_TYPES.index(self.model.infer_board_type()))
        for rec in self.model.net_collection.nets:
            self._log("INFO", f"net {rec.name}: {rec.net_type}")
        self._parsed = True
        marker = (f" {SMART_PDF_MARKER}"
                  if self._schematic_source == SOURCE_SMART_PDF_SPF
                  else "")
        self.lbl_schematic_status.setText(
            f"Schematic: ✔ Parsed{marker}")
        self.lbl_net_status.setText("Net: ✔ Parsed")
        self._parse_progress(100, "done")
        self._log("INFO",
                  f"parse done: {len(self.model.net_collection.nets)} "
                  "nets (DRAFT state - downstream stays disabled)")

    def _parse_schematic_structure(self) -> None:
        """PARSE stage 1: schematic structure resolve (SPF text or
        Smart-PDF text layer -> component library + project name)."""
        source = detect_schematic_source(self._schematic_path,
                                         extract_pdf_text)
        self._schematic_source = source
        self.model.source_type = source
        if source == SOURCE_SMART_PDF_SPF:
            text = extract_pdf_text(self._schematic_path, 5)
            meta_title = _pdf_meta_title(self._schematic_path)
            pdf_data = parse_pdf_schematic(text, meta_title)
            # spec priority: PDF metadata Title > PDF file name
            self.model.project_info["project_name"] = (
                pdf_data.meta_title or Path(self._schematic_path).stem)
            self.model.component_library = build_library(
                pdf_data.components)
        else:
            spf = parse_spf(self._schematic_text
                            if self._schematic_text is not None
                            else _read_text(self._schematic_path))
            self.model.project_info["project_name"] = (
                spf.drawing_title or Path(self._schematic_path).stem)
            self.model.component_library = build_library(spf.components)
        n_comp = len(self.model.component_library.records)
        self._log("INFO", f"schematic resolved (source={source}): "
                          f"{n_comp} components")
        self._auto_fill_name(self.model.project_info["project_name"])

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
