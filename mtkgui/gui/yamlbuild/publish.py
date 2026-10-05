# -*- coding: utf-8 -*-
"""Draft / Final YAML publishing with fixed naming, version compare
and archiving (V4.0 rule 5.4).

Fixed naming (100% compliant):

    Draft: Plan_[Core ID]_[Project Part#]_build_draft_v.1.0.0.yaml
    Final: Plan_[Core ID]_[Project Part#]_build_final_v.1.0.0.yaml

The dynamic build version (interface_spec.md section 33) is embedded
in the YAML header (``built_with``) and in the archive copy file
names, keeping the canonical file names exactly compliant.
"""

from __future__ import annotations

import difflib
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.version_info import get_version_info

ARCHIVE_DIR = "archive/yamlbuild"

_FILENAME_RE = re.compile(
    r"^Plan_(?P<core>[^_]+)_(?P<part>.+)_build_"
    r"(?P<kind>draft|final)_v\.(?P<version>\d+\.\d+\.\d+)\.yaml$")


def plan_filename(model: YamlBuildModel, kind: str) -> str:
    """Build the compliant Draft/Final file name.

    Args:
        model: The data model (Core ID / Part # come from the Design
               Input module).
        kind:  ``"draft"`` or ``"final"``.

    Returns:
        e.g. ``Plan_IMXRT700_MTK12345_build_draft_v.1.0.0.yaml``.

    Raises:
        ValueError: kind is invalid or Design Input is missing.
    """
    if kind not in ("draft", "final"):
        raise ValueError(f"kind must be draft|final, got {kind!r}")
    design = model.get_params("design_input")
    core = str(design.get("core_id", "") or "").strip()
    part = str(design.get("part_number", "") or "").strip()
    if not core or not part:
        raise ValueError(
            "Design Input must provide Core ID and Project Part # "
            "before building a plan file")
    safe = lambda text: re.sub(r"[^A-Za-z0-9._-]", "_", text)  # noqa: E731
    return (f"Plan_{safe(core)}_{safe(part)}_"
            f"build_{kind}_v.{model.plan_version}.yaml")


def build_plan_document(model: YamlBuildModel, kind: str) -> dict:
    """Compose the full plan document (header + effective modules).

    Args:
        model: The data model.
        kind:  ``"draft"`` or ``"final"``.

    Returns:
        Dict with a ``plan`` header (kind, plan_version, core/part,
        created_at, built_with dynamic version) plus the effective
        ``yaml_build`` section (enabled modules only).
    """
    document = model.to_effective_dict()
    design = model.get_params("design_input")
    document["plan"] = {
        "kind": kind,
        "plan_version": model.plan_version,
        "core_id": str(design.get("core_id", "") or "").strip(),
        "part_number": str(design.get("part_number", "") or "").strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "built_with": get_version_info().suffix(),
        "locked": kind == "final",
    }
    return document


def publish(model: YamlBuildModel, kind: str, out_dir: str | Path) -> Path:
    """Generate and write one plan file (Draft or Final).

    Args:
        model:   The data model (must be valid; the page validates
                 before calling).
        kind:    ``"draft"`` or ``"final"``.
        out_dir: Target directory (created when missing).

    Returns:
        The written file path.

    Raises:
        ValueError: Design Input incomplete or invalid kind.
        OSError:    The file could not be written.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / plan_filename(model, kind)
    document = build_plan_document(model, kind)
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    return path


def archive_copy(path: str | Path, archive_root: str | Path) -> Path:
    """Copy a published plan into the archive, suffixed with the
    dynamic build version and a timestamp (audit trail).

    Args:
        path:        Published plan file.
        archive_root: Archive base directory (created when missing).

    Returns:
        The archive copy path.
    """
    src = Path(path)
    dest_dir = Path(archive_root) / ARCHIVE_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"{src.stem}_{stamp}_{get_version_info().suffix()}"
    dest = dest.with_suffix(".yaml")
    shutil.copy2(src, dest)
    return dest


def compare_plans(left_path: str | Path, right_path: str | Path) -> str:
    """Unified diff of two plan files (version compare).

    Args:
        left_path:  Baseline plan file.
        right_path: Candidate plan file.

    Returns:
        Unified diff text (empty when identical).
    """
    left = Path(left_path).read_text(encoding="utf-8").splitlines()
    right = Path(right_path).read_text(encoding="utf-8").splitlines()
    return "\n".join(difflib.unified_diff(
        left, right,
        fromfile=Path(left_path).name, tofile=Path(right_path).name,
        lineterm=""))


def parse_plan_name(name: str) -> dict | None:
    """Parse a compliant plan file name into its parts.

    Args:
        name: File name (with or without directories).

    Returns:
        Dict with core / part / kind / version keys, or ``None`` when
        the name is not compliant.
    """
    match = _FILENAME_RE.match(Path(name).name)
    if match is None:
        return None
    return match.groupdict()
