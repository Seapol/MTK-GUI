# -*- coding: utf-8 -*-
"""v2 Yaml Build — the seven-step wizard, its routing and its files.

Qt-free on purpose: the routing, the project-tree creator and the draft
hook are all testable without a GUI.  The page (``mtkgui/yaml_build_page.py``)
only re-parents existing panels into these steps.

Topology (owner flow diagram ``01 → (02 ∥ 03) → 04 → (05 ∥ 06) → 07``):

    design_input → parse_ict  → firmware   → equipment → build_ict → build_fct → apply_save

The bar linearises the two parallel pairs.  ``group`` decides greying:
``ict`` steps are greyed when the ICT block is off, ``fct`` steps when the
FCT block is off, ``both`` never.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: steps whose body is a single sentence, not a real panel.  v2-5 flipped
#: ``firmware``; node 07 later flips ``apply_save``.
PLACEHOLDER_STEPS: frozenset[str] = frozenset({"apply_save"})

PLACEHOLDER_TEXT = "This node is not built yet — scheduled for its own commit."


@dataclass(frozen=True)
class Step:
    """One step of the seven-step Yaml Build wizard.

    Attributes:
        key:    Stable module identifier.
        title:  UI label.
        group:  ``"both"`` / ``"ict"`` / ``"fct"`` (greying family).
        kind:   ``"panel"`` / ``"launcher"`` / ``"placeholder"``.
    """

    key: str
    title: str
    group: str
    kind: str


#: The fixed seven steps — one source of truth for the step bar, the
#: routing and the greying.  DO NOT REORDER.
YAML_STEPS: tuple[Step, ...] = (
    Step("design_input", "Design Input",            group="both", kind="panel"),
    Step("parse_ict",    "Parse nets for ICT",      group="ict",  kind="panel"),
    Step("firmware",     "Firmware Config",         group="fct",  kind="panel"),
    Step("equipment",    "Equipment Config",        group="both", kind="panel"),
    Step("build_ict",    "Build ICT Test Sequence", group="ict",  kind="panel"),
    Step("build_fct",    "Build FCT Test Sequence", group="fct",  kind="panel"),
    Step("apply_save",   "Apply & Save Yaml",       group="both", kind="placeholder"),
)

STEP_KEYS: tuple[str, ...] = tuple(s.key for s in YAML_STEPS)
STEP_BY_KEY: dict[str, Step] = {s.key: s for s in YAML_STEPS}


def step_number(key: str) -> int:
    """1-based position in the step bar (``01``..``07``)."""
    return STEP_KEYS.index(key) + 1


def step_label(key: str) -> str:
    """The numbered bar label, e.g. ``03 · Firmware Config``."""
    return f"{step_number(key):02d} · {STEP_BY_KEY[key].title}"


def is_step_enabled(key: str, ict_on: bool, fct_on: bool) -> bool:
    """True when *key* is reachable for the given block combination."""
    step = STEP_BY_KEY[key]
    if step.group == "ict" and not ict_on:
        return False
    if step.group == "fct" and not fct_on:
        return False
    return True


def enabled_step_keys(ict_on: bool, fct_on: bool) -> tuple[str, ...]:
    """The reachable step keys in order, for the given combination.

    Both blocks off is forbidden at the validate level and yields no
    route here (``next_key`` returns ``None`` on every step).
    """
    if not ict_on and not fct_on:
        return ()
    return tuple(s.key for s in YAML_STEPS
                 if is_step_enabled(s.key, ict_on, fct_on))


def next_key(key: str, ict_on: bool, fct_on: bool) -> str | None:
    """The next reachable step key, or ``None`` on the last step."""
    keys = enabled_step_keys(ict_on, fct_on)
    if key not in keys:
        return None
    index = keys.index(key)
    return keys[index + 1] if index + 1 < len(keys) else None


def prev_key(key: str, ict_on: bool, fct_on: bool) -> str | None:
    """The previous reachable step key, or ``None`` on the first step."""
    keys = enabled_step_keys(ict_on, fct_on)
    if key not in keys:
        return None
    index = keys.index(key)
    return keys[index - 1] if index > 0 else None


def next_label(key: str, ict_on: bool, fct_on: bool) -> str:
    """The ``[Next >]`` caption: the real target number, or ``Next: >``."""
    target = next_key(key, ict_on, fct_on)
    if target is None:
        return "Next: >"
    return f"Next: {step_number(target):02d} >"


# ------------------------------------------------------------ project tree
def ensure_project_tree(core_id: str) -> Path:
    """Create (idempotently) the project folder under the work dir.

    ``<work>/<Core ID>/`` with ``sources/``, ``rules/`` and ``DUT Report/``.
    ``assets/`` and ``exports/`` are NOT created here (first use owns
    them).  Calling it twice must not fail and must not delete an
    existing ``rules/project_rules.json``.
    """
    from mtkgui.app_paths import work_dir

    base = work_dir() / str(core_id or "").strip()
    for name in ("sources", "rules", "DUT Report"):
        (base / name).mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------- draft hook
def save_draft(model) -> Path:
    """Write the current draft; never raise out of ``plan_filename``.

    Destination, in order of preference:

    1. ``<work>/<Core ID>/<plan file name>`` when the project tree exists;
    2. ``<work>/drafts/<plan file name>`` when Core ID + Product Part # are
       both present but the tree does not exist yet;
    3. ``<work>/drafts/draft_<yyyyMMddTHHmmss>.yaml`` otherwise.

    No project folder is ever created here.
    """
    import yaml

    from mtkgui.app_paths import timestamp, work_dir
    from mtkgui.gui.yamlbuild.publish import build_plan_document, plan_filename

    design = model.get_params("design_input") or {}
    core = str(design.get("product_id") or "").strip()
    part = str(design.get("part_number") or "").strip()

    drafts = work_dir() / "drafts"

    def _write(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        document = build_plan_document(model, "draft")
        path.write_text(
            yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
            encoding="utf-8")
        return path

    tree = (work_dir() / core) if core else None
    if tree is not None and tree.is_dir():
        try:
            return _write(tree / plan_filename(model, "draft"))
        except ValueError:
            # a tree exists but a name component is still empty — fall
            # through to the timestamped form, never raise
            pass
    if core and part:
        try:
            return _write(drafts / plan_filename(model, "draft"))
        except ValueError:
            pass
    return _write(drafts / f"draft_{timestamp()}.yaml")
