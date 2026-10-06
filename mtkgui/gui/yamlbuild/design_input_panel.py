# -*- coding: utf-8 -*-
"""Design Input panel (P3-B2 T7): the unified file-entry + meta form.

Replaces the deprecated standalone "Design data import" popup: all
file entry lives on this panel only, with exactly two import buttons:

* **Import SPF…** - reads the file bytes AND auto-parses the project
  info: Core ID from the SPF file name, Project Name from the SPF
  first-page title (both editable afterwards);
* **Import NET…** - reads the file bytes ONLY (no parse, no structure
  analysis; the formal net parsing happens in the Parse Nets module).

Meta fields: Product ID (= Core ID), Project Part # (= Project Name),
SW / HW Version (manual, report metadata only) and the fixed Batch #
dropdown (Customized / Deviation (DRQ) resolve through a small
dialog).  All fields persist to the project YAML via the schema.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.parser import (
    core_id_from_filename,
    read_text_any_encoding,
)
from mtkgui.gui.yamlbuild.schema import (
    BATCH_CUSTOMIZED_PREFIX,
    BATCH_DEVIATION_PREFIX,
    BATCH_OPTIONS,
)
from mtkgui.gui.yamlbuild.spf_title import extract_spf_project_name

MAX_DRQ_NUMBERS = 3


class DrqDialog(QDialog):
    """Up to 3 DRQ numbers for the Deviation (DRQ) batch option."""

    def __init__(self, values: list[str] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deviation (DRQ) Numbers")
        form = QFormLayout(self)
        self.edits: list[QLineEdit] = []
        values = list(values or [])[:MAX_DRQ_NUMBERS]
        for i in range(MAX_DRQ_NUMBERS):
            edit = QLineEdit(values[i] if i < len(values) else "")
            edit.setPlaceholderText(f"DRQ number #{i + 1} (optional)")
            form.addRow(f"DRQ #{i + 1}:", edit)
            self.edits.append(edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spf_path: str = ""      # imported SPF file (bytes + parse)
        self.spf_text: str = ""      # SPF raw text (import step)
        self.net_path: str = ""      # imported NET file (LOAD ONLY)
        self.net_text: str = ""      # NET raw bytes (never parsed here)

        # item 21: adaptive flat layout - the panel grows with the
        # dialog in both directions, fields stretch proportionally
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # ------------------------------------------ import button rows
        buttons = QHBoxLayout()
        self.btn_import_spf = QPushButton("Import SPF…")
        self.btn_import_spf.setToolTip(
            "Import an Allegro Smart PDF (*.pdf only): the file is "
            "read and the project info (Core ID from the file name, "
            "Project Name from the first-page title) is auto-filled - "
            "both stay editable")
        self.btn_import_net = QPushButton("Import NET…")
        self.btn_import_net.setToolTip(
            "Import an Allegro netlist: LOAD ONLY (raw bytes, no "
            "parse).  The formal net parsing runs in the Parse Nets "
            "for ICT module.")
        buttons.addWidget(self.btn_import_spf)
        buttons.addWidget(self.btn_import_net)
        buttons.addStretch(1)
        lay.addLayout(buttons)

        # file captions: relative path + file name
        self.lbl_spf = QLabel("SPF: (not imported)")
        self.lbl_net = QLabel("NET: (not imported)")
        lay.addWidget(self.lbl_spf)
        lay.addWidget(self.lbl_net)

        # --------------------------------------------------- meta form
        # item 21: flat, evenly spaced Qt form layout - uniform row
        # spacing, all input boxes aligned to the same (growing) width
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(14)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.edit_product_id = QLineEdit()
        self.edit_product_id.setToolTip(
            "Product ID - auto-filled with the Core ID extracted from "
            "the SPF file name; manual override allowed")
        form.addRow("Product ID:", self.edit_product_id)
        self.edit_part_number = QLineEdit()
        self.edit_part_number.setToolTip(
            "Project Part # - auto-filled with the Project Name from "
            "the SPF first-page title; manual override allowed")
        form.addRow("Project Part #:", self.edit_part_number)
        self.edit_sw_version = QLineEdit()
        self.edit_sw_version.setToolTip(
            "SW Version - manual fill only, report metadata purpose")
        form.addRow("SW Version:", self.edit_sw_version)
        self.edit_hw_version = QLineEdit()
        self.edit_hw_version.setToolTip(
            "HW Version - manual fill only, report metadata purpose")
        form.addRow("HW Version:", self.edit_hw_version)
        self.combo_batch = QComboBox()
        self.combo_batch.addItems(list(BATCH_OPTIONS))
        self.combo_batch.setToolTip(
            "Batch # - fixed options; Customized and Deviation (DRQ) "
            "open a small dialog for the details")
        self.combo_batch.activated.connect(self._on_batch_activated)
        form.addRow("Batch #:", self.combo_batch)
        self.lbl_batch_detail = QLabel("")
        self.lbl_batch_detail.setObjectName("muted")
        form.addRow("", self.lbl_batch_detail)
        lay.addLayout(form)
        lay.addStretch(1)   # balanced free space (flat, uncrowded)

        self.btn_import_spf.clicked.connect(self._import_spf)
        self.btn_import_net.clicked.connect(self._import_net)

    # ------------------------------------------------------------ import
    def _import_spf(self) -> None:
        """IMPORT + auto-parse an SPF file: bytes in memory, Core ID
        from the file name, Project Name from the first-page title.
        No silent fail - every error reports the exact reason."""
        from PySide6.QtWidgets import QFileDialog
        # item 21: SPF import accepts ONLY Allegro Smart PDF - the
        # txt / .spf text fallback is removed
        path, _ = QFileDialog.getOpenFileName(
            self, "Import SPF", "",
            "Allegro Smart PDF (*.pdf);;All files (*.*)")
        if not path:
            return
        self.task_progress.emit(0, "spf import: reading file")
        self.task_log.emit("INFO",
                           f"SPF import started: {Path(path).name}")
        try:
            text = read_text_any_encoding(path)
            if not text.strip():
                raise ValueError("the file is empty (0 content bytes)")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            reason = f"SPF import failed: {exc}"
            self.task_log.emit("ERROR", reason)
            self.task_progress.emit(0, "spf import: idle")
            QMessageBox.critical(self, "SPF Import Failed", reason)
            return
        self.task_progress.emit(50, "spf import: extracting project info")
        core_id = core_id_from_filename(Path(path).name)
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
        self.lbl_spf.setText(f"SPF: {_rel_path(path)}")
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
        path, _ = QFileDialog.getOpenFileName(
            self, "Import NET", "", "Netlist (*.net *.net.txt *.txt)")
        if not path:
            return
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
            return
        self.net_path = path
        self.net_text = text            # load only - never parsed here
        self.lbl_net.setText(f"NET: {_rel_path(path)}")
        self.task_progress.emit(100, "net import: done")
        self.task_log.emit(
            "INFO",
            f"NET import done: {Path(path).name} "
            "(load only - parsed by the Parse Nets module)")
        self.content_changed.emit()

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
        return {
            "product_id": self.edit_product_id.text().strip(),
            "part_number": self.edit_part_number.text().strip(),
            "sw_version": self.edit_sw_version.text().strip(),
            "hw_version": self.edit_hw_version.text().strip(),
            "batch": self.batch_value(),
            "spf_file": _rel_path(self.spf_path) if self.spf_path else "",
            "net_file": _rel_path(self.net_path) if self.net_path else "",
        }

    def set_values(self, params: dict) -> None:
        """Load persisted values (backward compatible with old YAML:
        legacy core_id / project_name / schematic_file keys map onto
        the new fields; legacy free-text batch maps to Customized)."""
        params = params or {}
        self.edit_product_id.setText(
            str(params.get("product_id")
                or params.get("core_id") or ""))
        self.edit_part_number.setText(
            str(params.get("part_number")
                or params.get("project_name") or ""))
        self.edit_sw_version.setText(
            str(params.get("sw_version") or ""))
        self.edit_hw_version.setText(
            str(params.get("hw_version") or ""))
        self.set_batch(str(params.get("batch") or ""))
        self.spf_path = str(params.get("spf_file")
                            or params.get("schematic_file") or "")
        self.lbl_spf.setText(
            f"SPF: {self.spf_path}" if self.spf_path
            else "SPF: (not imported)")
        self.net_path = str(params.get("net_file") or "")
        self.lbl_net.setText(
            f"NET: {self.net_path}" if self.net_path
            else "NET: (not imported)")


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
