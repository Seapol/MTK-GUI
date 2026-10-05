# -*- coding: utf-8 -*-
"""Bidirectional diagram <-> YAML synchronization with live
validation (interface_spec.md section 31, V4.0 rule 5.2-3).

Anti-loop architecture: the :class:`YamlBuildModel` is the single
source of truth.  Views push into the model; the model is the only
component that broadcasts refreshes.  No view ever copies data to
another view, so a feedback loop is structurally impossible.

Validation layers on a hand-edited YAML text:

* syntax  - YAML parse errors with line/column,
* sequence - enabled modules must follow the fixed workflow order,
* parameters - every field against its schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.stages import STAGE_KEYS


@dataclass
class ValidationResult:
    """Outcome of validating one hand-edited YAML text.

    Attributes:
        ok:         True when the text parses and passes all checks.
        errors:     List of (message, line) tuples; line is 1-based
                    (0 when not attributable to a line).
        data:       Parsed dict (None when syntax validation failed).
    """

    ok: bool
    errors: list[tuple[str, int]] = field(default_factory=list)
    data: dict | None = None

    def error_lines(self) -> set[int]:
        """Return the 1-based line numbers to mark red.

        Returns:
            Set of line numbers (0-line errors are ignored).
        """
        return {line for _, line in self.errors if line > 0}


def validate_yaml_text(text: str, model: YamlBuildModel) -> ValidationResult:
    """Validate a hand-edited YAML document against the model schema.

    Args:
        text:  Raw YAML text from the preview editor.
        model: The data model (provides parameter schemas).

    Returns:
        :class:`ValidationResult`; ``data`` is set only when the text
        parses (the caller applies it to the model only when
        ``ok`` is True - invalid edits never enter the model).
    """
    try:
        data = yaml.safe_load(text or "")
    except yaml.YAMLError as exc:
        line = 0
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            line = mark.line + 1
        return ValidationResult(
            ok=False, errors=[(f"YAML syntax error: {exc}", line)])
    if data is None:
        return ValidationResult(ok=False, errors=[("empty document", 0)])
    if not isinstance(data, dict) or "yaml_build" not in data:
        return ValidationResult(
            ok=False,
            errors=[("missing 'yaml_build' section", 1)])
    # parameter + sequence validation via the model (dry check: parse
    # into a THROWAWAY copy so an invalid edit never touches state)
    trial = YamlBuildModel()
    trial.apply_state(model.to_dict())
    errors = trial.apply_yaml_dict(data)
    if errors:
        # locate the first offending module line for the red marker
        first_line = _find_module_line(text, errors)
        return ValidationResult(
            ok=False, errors=[(e, first_line) for e in errors],
            data=data)
    return ValidationResult(ok=True, data=data)


def _find_module_line(text: str, errors: list[str]) -> int:
    """Find the 1-based line of the first module mentioned in errors.

    Args:
        text:   YAML text.
        errors: Error messages, e.g. ``"module clocks: ..."``.

    Returns:
        Line number, or 0 when nothing matches.
    """
    for error in errors:
        for token in error.split():
            if token in STAGE_KEYS:
                for i, line in enumerate(text.splitlines(), start=1):
                    if token in line:
                        return i
    return 0


def sync_preview_to_model(model: YamlBuildModel, text: str) -> ValidationResult:
    """Apply a hand-edited YAML text into the model (YAML -> diagram).

    Invalid edits are rejected without touching the model; the caller
    refreshes the preview from the model afterwards either way, which
    keeps the diagram and preview converging on model state.

    Args:
        model: The data model.
        text:  Raw YAML text from the preview editor.

    Returns:
        The :class:`ValidationResult` of the edit.
    """
    result = validate_yaml_text(text, model)
    if result.ok and result.data is not None:
        model.apply_yaml_dict(result.data)
    return result


def sync_model_to_yaml(model: YamlBuildModel) -> str:
    """Render the model's effective state as YAML (diagram -> YAML).

    Args:
        model: The data model.

    Returns:
        YAML text of the effective (enabled-only) configuration.
    """
    return model.to_effective_yaml()
