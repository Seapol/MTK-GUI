# -*- coding: utf-8 -*-
"""Design-Input subsystem (B1-01, spec .trae/specs/B1-DesignInput).

Layered as:

* parsing kernel (no GUI):  sources / spf_parser / pdf_schematic /
  components / netlist / testpoints / power_tree_draft
* data model (draft vs committed isolation):  model (T1)
* GUI pages:  page / editors / canvas (T2-T5)

Every automatic output is DRAFT state; nothing flows downstream until
the user runs Final Review & Commit.
"""
