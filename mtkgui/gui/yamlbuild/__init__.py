# -*- coding: utf-8 -*-
"""Yaml Build subpackage (V4.0 phase B1, interface_spec.md section 31).

Layout: stages (fixed sequence) / schema (per-module field tables) /
model (single source of truth) / sync (validated two-way sync) /
block_flow + preview + blocks (UI) / excel_io / publish / store.
"""

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.stages import (
    STAGE_KEYS,
    STAGE_BY_KEY,
    WORKFLOW_STAGES,
)

__all__ = [
    "STAGE_BY_KEY",
    "STAGE_KEYS",
    "WORKFLOW_STAGES",
    "YamlBuildModel",
]
