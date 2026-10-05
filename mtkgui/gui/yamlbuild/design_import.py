# -*- coding: utf-8 -*-
"""Design Input dedicated import dialog (V4.0 acceptance 3.1.1).

Opened from the Design Input block config dialog:

* **Import Schematic PDF**  - reads the drawing (QtPdf, zero new
  dependencies), auto-detects the Core ID from the standard file
  name (``spf-92722_revB.pdf`` -> ``92722``) and extracts the project
  name from the title block text,
* **Import Netlist**        - parses the raw netlist, extracting
  every net name and its test-point members,
* **TP resolution table**   - nets without a TP field are listed;
  the operator assigns a pin substitute (``net=pin``) or marks the
  point "not tested" (``net=skip``); resolutions are saved with the
  project state (traceable).

Everything is validated and merged back into the config dialog's
edited values on accept.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from mtkgui.gui.yamlbuild.parser import (
    core_id_from_filename,
    extract_pdf_text,
    extract_project_name,
    parse_netlist,
    read_text_any_encoding,
)


class DesignImportDialog(QDialog):
    """Schematic / netlist import with TP tolerance resolution."""

    def __init__(self, parent=None) -> None:
        """Create the import dialog."""
        super().__init__(parent)
        self.setWindowTitle("Design Input - Import & Parse")
        self.setMinimumWidth(640)
        self.schematic_meta: dict = {}
        self.netlist_file: str = ""
        self.netlist_data = None
        self.tp_resolutions: dict[str, str] = {}

        lay = QVBoxLayout(self)
        buttons = QHBoxLayout()
        self.btn_schematic = QPushButton("Import Schematic PDF…")
        self.btn_schematic.setToolTip("导入原理图PDF抓取CoreID，"
                                      "并提取图纸项目名称")
        self.btn_netlist = QPushButton("Import Netlist…")
        self.btn_netlist.setToolTip("导入网表解析点位信息，"
                                    "自动提取net name与TP测试点")
        buttons.addWidget(self.btn_schematic)
        buttons.addWidget(self.btn_netlist)
        buttons.addStretch(1)
        lay.addLayout(buttons)

        self.info_label = QLabel(
            "Schematic: none imported\nNetlist: none imported")
        self.info_label.setWordWrap(True)
        lay.addWidget(self.info_label)

        lay.addWidget(QLabel(
            "Nets without a TP (test point) - assign a pin substitute "
            "or mark the point as not tested:"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["Net", "Members", "Resolution (pin or skip)"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(200)
        lay.addWidget(self.table, 1)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

        self.btn_schematic.clicked.connect(self._import_schematic)
        self.btn_netlist.clicked.connect(self._import_netlist)

    # ------------------------------------------------------- schematic
    def _import_schematic(self) -> None:
        """Import a schematic PDF: filename -> Core ID, text ->
        project name."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Schematic PDF", "", "PDF files (*.pdf)")
        if not path:
            return
        text = extract_pdf_text(path)
        if not text:
            QMessageBox.warning(
                self, "Schematic Import",
                "The PDF could not be read as text (scanned drawing?). "
                "Core ID is still detected from the file name.")
        base = path.replace("\\", "/").rsplit("/", 1)[-1]
        core_id = core_id_from_filename(base)
        project_name = extract_project_name(text)
        self.schematic_meta = {
            "file": path,
            "core_id": core_id,
            "project_name": project_name,
        }
        self._refresh_info()

    # --------------------------------------------------------- netlist
    def _import_netlist(self) -> None:
        """Import a netlist and populate the TP resolution table."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Netlist", "",
            "Netlist files (*.net *.txt *.csv);;All files (*)")
        if not path:
            return
        text = read_text_any_encoding(path)
        self.netlist_data = parse_netlist(text)
        self.netlist_file = path
        self.tp_resolutions = {
            net: self.tp_resolutions.get(net, "")
            for net in self.netlist_data.missing_tp
        }
        self._refresh_info()
        self._fill_resolution_table()

    def _fill_resolution_table(self) -> None:
        """List the nets without TP with editable resolutions."""
        missing = self.netlist_data.missing_tp if self.netlist_data \
            else []
        self.table.setRowCount(len(missing))
        for row, net in enumerate(missing):
            members = ", ".join(
                self.netlist_data.nets.get(net, [])[:6])
            self.table.setItem(row, 0, QTableWidgetItem(net))
            self.table.setItem(row, 1, QTableWidgetItem(members))
            edit = QTableWidgetItem(
                self.tp_resolutions.get(net, ""))
            edit.setFlags(edit.flags() | Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 2, edit)

    # ----------------------------------------------------------- accept
    def _on_accept(self) -> None:
        """Validate the resolution entries and accept.

        A resolution must be ``skip`` or one of the net's member pins
        - anything else keeps the dialog open with a message.
        """
        for row in range(self.table.rowCount()):
            net = self.table.item(row, 0).text() \
                if self.table.item(row, 0) else ""
            value = self.table.item(row, 2).text().strip() \
                if self.table.item(row, 2) else ""
            if not value:
                continue
            value_low = value.lower()
            members = self.netlist_data.nets.get(net, []) \
                if self.netlist_data else []
            if value_low == "skip" or value in members:
                self.tp_resolutions[net] = value \
                    if value_low != "skip" else "skip"
            else:
                QMessageBox.warning(
                    self, "Invalid Resolution",
                    f"Net {net!r}: {value!r} is not a member pin - "
                    f"pick one of: {', '.join(members)} or type "
                    f"'skip'.")
                return
        self.accept()
