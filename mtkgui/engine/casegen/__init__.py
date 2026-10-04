# -*- coding: utf-8 -*-
"""P1-16 closed-loop case generation package (pure incremental).

Pipeline: netlist / schematic / ICT excel  --AI rules-->  YAML draft
          --export--> review Excel --human edits-- --import+sync-->
          production YAML (audited, traceable).

Public API:
    CaseGenerator().generate(paths)          -> YAML fragment
    export_review_excel(config, path)        -> row count
    import_review_excel(path)                -> ImportResult
    diff_rows / apply_diff / sync_review_excel
"""
from .generator import AI_GEN_VERSION, CaseGenerator
from .excel_io import (COLUMNS, ImportResult, export_review_excel,
                       import_review_excel)
from .netlist import NetlistParser, rail_depth
from .sync import apply_diff, diff_rows, sync_review_excel

__all__ = [
    "AI_GEN_VERSION", "CaseGenerator", "NetlistParser", "rail_depth",
    "COLUMNS", "ImportResult", "export_review_excel",
    "import_review_excel", "diff_rows", "apply_diff",
    "sync_review_excel",
]
